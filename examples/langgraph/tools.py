"""Mock telecom infrastructure tools for the LangGraph integration example."""

from __future__ import annotations

from typing import Any


def query_prometheus(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_loss_pct": scenario["packet_loss_pct"],
        "p95_latency_ms": scenario["p95_latency_ms"],
        "gateway": scenario["gateway"],
    }


def check_router_logs(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "gateway": scenario["gateway"],
        "recent_errors": scenario["router_errors"],
        "last_config_change": scenario.get("last_config_change", "none"),
    }


def restart_gateway(scenario: dict[str, Any]) -> dict[str, Any]:
    approved = bool(scenario.get("human_approval", False))
    return {
        "gateway": scenario["gateway"],
        "status": "queued" if approved else "blocked_by_policy",
        "human_approval": approved,
    }


def create_ticket(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket_id": f"INC-{scenario['name'].upper().replace('_', '-')}",
        "severity": scenario["severity"],
        "status": "created",
    }
