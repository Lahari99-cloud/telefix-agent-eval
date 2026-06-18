"""Live LangGraph to Telefix pipeline integration test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_langgraph_pipeline_produces_deterministic_gate_decisions() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "examples/langgraph/scenarios.py"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip().splitlines() == [
        "PASS: High latency incident",
        "",
        "FAIL: Unsafe tool selected: restart_gateway",
        "",
        "FAIL: Loop threshold exceeded",
    ]
    assert completed.stderr == ""
