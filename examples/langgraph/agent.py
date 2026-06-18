"""Live LangGraph incident-response workflow with OpenTelemetry spans."""

from __future__ import annotations

import json
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from opentelemetry import trace

try:
    from .otel import set_common_span_attributes, tracer
    from .tools import check_router_logs, create_ticket, query_prometheus, restart_gateway
except ImportError:  # pragma: no cover - supports direct script execution
    from otel import set_common_span_attributes, tracer

    from tools import check_router_logs, create_ticket, query_prometheus, restart_gateway


class IncidentState(TypedDict):
    scenario: dict[str, Any]
    trace: list[str]
    metrics: NotRequired[dict[str, Any]]
    logs: NotRequired[dict[str, Any]]
    diagnosis: NotRequired[str]
    action: NotRequired[str]
    loop_count: int
    tool_results: list[dict[str, Any]]


class LangGraphIncidentAgent:
    def __init__(self) -> None:
        self.graph = self._build_graph()

    def run(self, scenario: dict[str, Any]) -> IncidentState:
        return self.graph.invoke(
            {
                "scenario": scenario,
                "trace": [],
                "loop_count": 0,
                "tool_results": [],
            }
        )

    def _build_graph(self):
        graph = StateGraph(IncidentState)
        graph.add_node("ingest_alert", self._ingest_alert)
        graph.add_node("query_metrics", self._query_metrics)
        graph.add_node("check_logs", self._check_logs)
        graph.add_node("diagnose", self._diagnose)
        graph.add_node("choose_action", self._choose_action)
        graph.add_node("execute_tool", self._execute_tool)
        graph.add_node("escalate", self._escalate)

        graph.add_edge(START, "ingest_alert")
        graph.add_edge("ingest_alert", "query_metrics")
        graph.add_edge("query_metrics", "check_logs")
        graph.add_edge("check_logs", "diagnose")
        graph.add_edge("diagnose", "choose_action")
        graph.add_conditional_edges(
            "choose_action",
            self._route_action,
            {
                "execute_tool": "execute_tool",
                "retry_metrics": "query_metrics",
                "escalate": "escalate",
            },
        )
        graph.add_edge("execute_tool", END)
        graph.add_edge("escalate", END)
        return graph.compile()

    def _ingest_alert(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("ingest_alert"):
            set_common_span_attributes(
                node_name="ingest_alert",
                span_type="system",
                scenario=scenario,
            )
            trace.get_current_span().set_attribute(
                "agent.input",
                json.dumps({"alert": scenario["alert"], "severity": scenario["severity"]}),
            )
            return {"trace": [*state["trace"], "ingest_alert"]}

    def _query_metrics(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("query_metrics"):
            set_common_span_attributes(
                node_name="query_metrics",
                span_type="tool",
                scenario=scenario,
            )
            result = _record_tool_call(
                "query_prometheus",
                query_prometheus,
                scenario,
                destructive=False,
                allowed=True,
                risk_level="low",
            )
            return {
                "metrics": result,
                "trace": [*state["trace"], "query_metrics"],
                "tool_results": [*state["tool_results"], result],
            }

    def _check_logs(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("check_logs"):
            set_common_span_attributes(
                node_name="check_logs",
                span_type="tool",
                scenario=scenario,
            )
            result = _record_tool_call(
                "check_router_logs",
                check_router_logs,
                scenario,
                destructive=False,
                allowed=True,
                risk_level="low",
            )
            return {
                "logs": result,
                "trace": [*state["trace"], "check_logs"],
                "tool_results": [*state["tool_results"], result],
            }

    def _diagnose(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("diagnose"):
            set_common_span_attributes(
                node_name="diagnose",
                span_type="llm",
                scenario=scenario,
                prompt_tokens=180,
                completion_tokens=60,
            )
            metrics = state.get("metrics", {})
            logs = state.get("logs", {})
            diagnosis = _diagnose_from_context(metrics, logs)
            span = trace.get_current_span()
            span.set_attribute("agent.input", json.dumps({"metrics": metrics, "logs": logs}))
            span.set_attribute("agent.output", json.dumps({"diagnosis": diagnosis}))
            return {"diagnosis": diagnosis, "trace": [*state["trace"], "diagnose"]}

    def _choose_action(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("choose_action"):
            set_common_span_attributes(
                node_name="choose_action",
                span_type="llm",
                scenario=scenario,
                prompt_tokens=120,
                completion_tokens=40,
            )
            loop_count = state["loop_count"]
            if scenario["behavior"] == "loop" and loop_count < scenario["max_retries"]:
                action = "retry_metrics"
                next_loop_count = loop_count + 1
            else:
                action = scenario["action"]
                next_loop_count = loop_count
            trace.get_current_span().set_attribute(
                "agent.output",
                json.dumps({"action": action, "loop_count": next_loop_count}),
            )
            return {
                "action": action,
                "loop_count": next_loop_count,
                "trace": [*state["trace"], f"choose_{action}"],
            }

    def _execute_tool(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        action = state["action"]
        with tracer().start_as_current_span("execute_tool"):
            set_common_span_attributes(
                node_name="execute_tool",
                span_type="chain",
                scenario=scenario,
            )
            if action == "restart_gateway":
                result = _record_tool_call(
                    "restart_gateway",
                    restart_gateway,
                    scenario,
                    destructive=True,
                    allowed=bool(scenario.get("restart_allowed", False)),
                    risk_level="high",
                )
            else:
                result = _record_tool_call(
                    "create_ticket",
                    create_ticket,
                    scenario,
                    destructive=False,
                    allowed=True,
                    risk_level="low",
                )
            return {
                "tool_results": [*state["tool_results"], result],
                "trace": [*state["trace"], f"execute_{action}"],
            }

    def _escalate(self, state: IncidentState) -> dict[str, Any]:
        scenario = state["scenario"]
        with tracer().start_as_current_span("escalate"):
            set_common_span_attributes(
                node_name="escalate",
                span_type="human",
                scenario=scenario,
            )
            return {"trace": [*state["trace"], "escalate"]}

    @staticmethod
    def _route_action(state: IncidentState) -> str:
        action = state["action"]
        if action == "retry_metrics":
            return "retry_metrics"
        if action == "escalate":
            return "escalate"
        return "execute_tool"


def _record_tool_call(
    tool_name: str,
    fn,
    scenario: dict[str, Any],
    *,
    destructive: bool,
    allowed: bool,
    risk_level: str,
) -> dict[str, Any]:
    with tracer().start_as_current_span(tool_name):
        result = fn(scenario)
        span = trace.get_current_span()
        set_common_span_attributes(
            node_name=tool_name,
            span_type="tool",
            scenario=scenario,
        )
        tool_input = _tool_input_for_scenario(scenario)
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.input", json.dumps(tool_input))
        span.set_attribute("tool.output", json.dumps(result))
        span.set_attribute("tool.status", "success" if allowed else "blocked")
        span.set_attribute("tool.is_destructive", destructive)
        span.set_attribute("tool.is_allowed", allowed)
        span.set_attribute("tool.risk_level", risk_level)
        span.set_attribute("agent.input", json.dumps(tool_input))
        span.set_attribute("agent.output", json.dumps(result))
        return result


def _tool_input_for_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "gateway": scenario["gateway"],
        "incident": {"severity": scenario["severity"]},
        "network": {"packet_loss_pct": scenario["packet_loss_pct"]},
        "human_approval": bool(scenario.get("human_approval", False)),
    }


def _diagnose_from_context(metrics: dict[str, Any], logs: dict[str, Any]) -> str:
    if metrics.get("packet_loss_pct", 0) >= 95:
        return "severe_packet_loss"
    if metrics.get("p95_latency_ms", 0) >= 180:
        return "high_latency"
    if logs.get("recent_errors"):
        return "router_log_errors"
    return "unknown"
