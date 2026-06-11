"""LangGraph broadband troubleshooting workflow and evaluation logic."""

from collections.abc import Callable
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.rag import Retriever
from src.schemas import (
    Citation,
    DiagnoseRequest,
    DiagnoseResponse,
    EvaluationMetrics,
    ServiceStatus,
    TelemetrySnapshot,
    WorkflowStatus,
)
from src.tools import MockRFResetTool, MockTelemetryTool


class AgentState(TypedDict):
    request: DiagnoseRequest
    citations: list[Citation]
    telemetry_before: TelemetrySnapshot
    telemetry_after: NotRequired[TelemetrySnapshot]
    selected_tools: list[str]
    trace: list[str]
    reset_performed: bool
    workflow_status: WorkflowStatus
    summary: str
    recommended_action: str
    evaluation: EvaluationMetrics


class BroadbandTroubleshootingAgent:
    """Deterministic agent whose decisions are inspectable and regression-testable."""

    def __init__(
        self,
        settings: Settings,
        retriever: Retriever,
        telemetry_tool: MockTelemetryTool | None = None,
        reset_tool: MockRFResetTool | None = None,
    ):
        self._settings = settings
        self._retriever = retriever
        self._telemetry = telemetry_tool or MockTelemetryTool()
        self._reset = reset_tool or MockRFResetTool()
        self.graph = self._build_graph()

    async def diagnose(self, request: DiagnoseRequest) -> DiagnoseResponse:
        result = await self.graph.ainvoke(
            {
                "request": request,
                "citations": [],
                "selected_tools": [],
                "trace": ["workflow_started"],
                "reset_performed": False,
            }
        )
        return DiagnoseResponse(
            account_id=request.account_id,
            workflow_status=result["workflow_status"],
            summary=result["summary"],
            recommended_action=result["recommended_action"],
            reset_performed=result["reset_performed"],
            telemetry_before=result["telemetry_before"],
            telemetry_after=result.get("telemetry_after"),
            citations=result["citations"],
            evaluation=result["evaluation"],
            trace=result["trace"],
        )

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("retrieve_guidance", self._retrieve_guidance)
        graph.add_node("inspect_telemetry", self._inspect_telemetry)
        graph.add_node("perform_reset", self._perform_reset)
        graph.add_node("verify_telemetry", self._verify_telemetry)
        graph.add_node("compose_response", self._compose_response)
        graph.add_node("evaluate", self._evaluate)

        graph.add_edge(START, "retrieve_guidance")
        graph.add_edge("retrieve_guidance", "inspect_telemetry")
        graph.add_conditional_edges(
            "inspect_telemetry",
            self._route_after_inspection,
            {
                "reset": "perform_reset",
                "respond": "compose_response",
            },
        )
        graph.add_edge("perform_reset", "verify_telemetry")
        graph.add_edge("verify_telemetry", "compose_response")
        graph.add_edge("compose_response", "evaluate")
        graph.add_edge("evaluate", END)
        return graph.compile()

    def _retrieve_guidance(self, state: AgentState) -> dict:
        symptoms = state["request"].symptoms
        citations = self._retriever.search(symptoms, limit=self._settings.rag_top_k)
        return {
            "citations": citations,
            "trace": [*state["trace"], f"retrieved_{len(citations)}_documents"],
        }

    def _inspect_telemetry(self, state: AgentState) -> dict:
        request = state["request"]
        snapshot = self._telemetry.invoke(request.account_id, request.symptoms)
        return {
            "telemetry_before": snapshot,
            "selected_tools": [*state["selected_tools"], self._telemetry.name],
            "trace": [*state["trace"], f"telemetry_status_{snapshot.status.value}"],
        }

    @staticmethod
    def _route_after_inspection(state: AgentState) -> str:
        telemetry = state["telemetry_before"]
        if telemetry.status == ServiceStatus.DEGRADED and state["request"].consent_to_reset:
            return "reset"
        return "respond"

    def _perform_reset(self, state: AgentState) -> dict:
        telemetry = state["telemetry_before"]
        message = self._reset.invoke(
            telemetry.modem_id,
            consent=state["request"].consent_to_reset,
        )
        return {
            "reset_performed": True,
            "selected_tools": [*state["selected_tools"], self._reset.name],
            "trace": [*state["trace"], message],
        }

    def _verify_telemetry(self, state: AgentState) -> dict:
        request = state["request"]
        snapshot = self._telemetry.invoke(
            request.account_id,
            request.symptoms,
            reset_applied=True,
        )
        return {
            "telemetry_after": snapshot,
            "selected_tools": [*state["selected_tools"], self._telemetry.name],
            "trace": [*state["trace"], f"verification_status_{snapshot.status.value}"],
        }

    def _compose_response(self, state: AgentState) -> dict:
        before = state["telemetry_before"]
        after = state.get("telemetry_after")

        if after and after.status == ServiceStatus.ONLINE:
            status = WorkflowStatus.RESOLVED
            summary = (
                "The synthetic modem showed degraded RF telemetry before the mock reset. "
                "Post-reset telemetry returned to the healthy reference range."
            )
            action = "Monitor service; escalate if intermittent symptoms return."
        elif before.status == ServiceStatus.OFFLINE:
            status = WorkflowStatus.ESCALATE
            summary = (
                "The synthetic modem is offline and has not reported recent usable telemetry. "
                "A remote resolution cannot be confirmed."
            )
            action = "Confirm power and coax connections, then escalate for line investigation."
        elif before.status == ServiceStatus.DEGRADED:
            status = WorkflowStatus.ESCALATE
            summary = (
                "The synthetic modem telemetry indicates degraded RF health. "
                "No reset was performed because explicit consent was not provided."
            )
            action = "Obtain reset consent or escalate for RF and connector inspection."
        else:
            status = WorkflowStatus.NO_ACTION
            summary = (
                "The synthetic modem telemetry is within the healthy reference range. "
                "The available evidence does not establish an RF impairment."
            )
            action = "Continue symptom isolation without changing network settings."

        return {
            "workflow_status": status,
            "summary": summary,
            "recommended_action": action,
            "trace": [*state["trace"], f"workflow_status_{status.value}"],
        }

    def _evaluate(self, state: AgentState) -> dict:
        expected_tools = [self._telemetry.name]
        if (
            state["telemetry_before"].status == ServiceStatus.DEGRADED
            and state["request"].consent_to_reset
        ):
            expected_tools.extend([self._reset.name, self._telemetry.name])

        selected = state["selected_tools"]
        matched = sum(
            1 for index, tool_name in enumerate(expected_tools)
            if index < len(selected) and selected[index] == tool_name
        )
        tool_selection = matched / max(len(expected_tools), len(selected), 1)

        has_sources = bool(state["citations"])
        evidence_terms = (
            "synthetic",
            "telemetry",
            "reset",
            "offline",
            "rf",
            "healthy",
            "consent",
            "escalate",
        )
        response_text = f"{state['summary']} {state['recommended_action']}".lower()
        unsupported_claims = []
        if not has_sources:
            unsupported_claims.append("No retrieved manual supports the recommendation.")
        if not any(term in response_text for term in evidence_terms):
            unsupported_claims.append("Response lacks explicit evidence-linked terminology.")

        groundedness = (
            1.0 if has_sources and not unsupported_claims else 0.5 if has_sources else 0.0
        )
        hallucination_risk = round(1.0 - groundedness, 3)
        workflow_completion = float(
            bool(state["summary"])
            and bool(state["recommended_action"])
            and state["workflow_status"] in WorkflowStatus
        )
        metrics = EvaluationMetrics(
            tool_selection=round(tool_selection, 3),
            groundedness=groundedness,
            hallucination_risk=hallucination_risk,
            workflow_completion=workflow_completion,
            selected_tools=selected,
            expected_tools=expected_tools,
            unsupported_claims=unsupported_claims,
        )
        return {
            "evaluation": metrics,
            "trace": [*state["trace"], "evaluation_completed"],
        }


AgentFactory = Callable[[], BroadbandTroubleshootingAgent]
