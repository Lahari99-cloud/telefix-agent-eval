"""Streamlit dashboard for Telefix agent evaluation operations."""

import os
from typing import Any

import altair as alt
import pandas as pd
import requests
import streamlit as st

from dashboard.client import (
    DashboardSnapshot,
    TelefixApiClient,
    ab_metric_rows,
    case_rows,
    failure_analysis_rows,
    quality_gate_status,
)

API_URL = os.getenv("TELEFIX_API_URL", "http://127.0.0.1:8000")


st.set_page_config(
    page_title="Telefix Evaluation Command Center",
    page_icon="T",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background:
          radial-gradient(circle at 8% 5%, rgba(43, 127, 255, 0.13), transparent 25rem),
          #07111f;
        color: #e8f0fa;
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] {
        background: #0b1828;
        border-right: 1px solid #1d344c;
    }
    [data-testid="stSidebar"] * { color: #d8e6f3; }
    [data-testid="stSidebar"] code {
        color: #d8e6f3;
        background: #0f2135;
    }
    .block-container { padding-top: 2rem; max-width: 1450px; }
    .hero {
        border: 1px solid #21415f;
        border-radius: 18px;
        padding: 1.6rem 1.8rem;
        margin-bottom: 1.2rem;
        background: linear-gradient(120deg, rgba(12, 31, 51, .96), rgba(17, 46, 74, .86));
        box-shadow: 0 18px 50px rgba(0, 0, 0, .22);
    }
    .eyebrow {
        color: #56c8ff;
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .16em;
        text-transform: uppercase;
    }
    .hero h1 { margin: .35rem 0 .4rem; font-size: 2.35rem; color: #f6fbff; }
    .hero p { margin: 0; color: #a9bed1; max-width: 850px; }
    [data-testid="stMetric"] {
        background: rgba(12, 29, 47, .92);
        border: 1px solid #1e3a55;
        border-radius: 14px;
        padding: 1rem;
    }
    [data-testid="stMetricValue"] { color: #f5fbff; }
    [data-testid="stMetricLabel"] { color: #9fb6ca; }
    [data-testid="stMetricDelta"] { color: #8098ad; }
    button[data-baseweb="tab"] p { color: #8fa7bb; }
    button[data-baseweb="tab"][aria-selected="true"] p { color: #56c8ff; }
    div[data-testid="stDataFrame"] {
        border: 1px solid #1e3a55;
        border-radius: 12px;
        overflow: hidden;
    }
    .gate-pass {
        display: inline-block;
        color: #6ef1b2;
        background: rgba(31, 184, 119, .12);
        border: 1px solid rgba(64, 221, 153, .4);
        border-radius: 999px;
        padding: .4rem .75rem;
        font-weight: 800;
        letter-spacing: .08em;
    }
    .section-note { color: #8fa7bb; font-size: .92rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=45, show_spinner=False)
def load_snapshot(api_url: str) -> DashboardSnapshot:
    return TelefixApiClient(api_url, requests.Session()).load_snapshot()


def percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_header(aggregate: dict[str, Any]) -> None:
    gate, detail = quality_gate_status(aggregate)
    st.markdown(
        f"""
        <div class="hero">
          <div class="eyebrow">Agent Evaluation Platform</div>
          <h1>Telefix Evaluation Command Center</h1>
          <p>Golden-set quality, hallucination safety, tool orchestration, human review,
          and prompt experiments for a synthetic broadband support agent.</p>
          <div style="margin-top: 1rem;">
            <span class="gate-pass">RELEASE GATE: {gate}</span>
            <span style="color:#8fa7bb; margin-left:.7rem;">{detail}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_cards(aggregate: dict[str, Any]) -> None:
    columns = st.columns(5)
    columns[0].metric("Tool accuracy", percentage(aggregate["tool_selection_accuracy"]))
    columns[1].metric("Workflow completion", percentage(aggregate["workflow_completion_rate"]))
    columns[2].metric("Groundedness", percentage(aggregate["groundedness_score"]))
    columns[3].metric(
        "Hallucination risk",
        percentage(aggregate["hallucination_risk"]),
        delta="lower is better",
        delta_color="off",
    )
    columns[4].metric("Average latency", f"{aggregate['average_latency_ms']:.1f} ms")


def render_overview(snapshot: DashboardSnapshot, cases: pd.DataFrame) -> None:
    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Golden dataset quality")
        quality = pd.DataFrame(
            {
                "Metric": ["Tool accuracy", "Completion", "Groundedness"],
                "Score": [
                    snapshot.evaluation["aggregate"]["tool_selection_accuracy"],
                    snapshot.evaluation["aggregate"]["workflow_completion_rate"],
                    snapshot.evaluation["aggregate"]["groundedness_score"],
                ],
            }
        )
        chart = (
            alt.Chart(quality)
            .mark_bar(cornerRadiusEnd=7, color="#37bdf8")
            .encode(
                x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
                y=alt.Y("Metric:N", sort=None, title=None),
                tooltip=["Metric", alt.Tooltip("Score:Q", format=".1%")],
            )
            .properties(height=235)
            .configure(
                background="transparent",
            )
            .configure_axis(
                labelColor="#a9bed1",
                titleColor="#a9bed1",
                gridColor="#1e3a55",
                domainColor="#29445d",
            )
        )
        st.altair_chart(chart, use_container_width=True)

    with right:
        st.subheader("Resolution mix")
        resolution = cases.groupby("resolution", as_index=False).size()
        donut = (
            alt.Chart(resolution)
            .mark_arc(innerRadius=62, outerRadius=100)
            .encode(
                theta="size:Q",
                color=alt.Color(
                    "resolution:N",
                    scale=alt.Scale(
                        domain=["resolved", "escalate", "no_action"],
                        range=["#43d9a3", "#ffb454", "#56a8ff"],
                    ),
                    title=None,
                ),
                tooltip=["resolution", "size"],
            )
            .properties(height=235)
            .configure(background="transparent")
            .configure_legend(labelColor="#a9bed1", titleColor="#a9bed1")
        )
        st.altair_chart(donut, use_container_width=True)

    st.subheader("Hallucination trend by golden case")
    trend = (
        alt.Chart(cases.reset_index())
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=65), color="#ff758f", strokeWidth=3)
        .encode(
            x=alt.X("case:N", sort=None, axis=alt.Axis(labelAngle=-35), title=None),
            y=alt.Y(
                "hallucination_risk:Q",
                scale=alt.Scale(domain=[0, max(0.4, cases["hallucination_risk"].max())]),
                axis=alt.Axis(format="%"),
                title="Risk",
            ),
            tooltip=[
                "case",
                "severity",
                alt.Tooltip("hallucination_risk:Q", format=".1%"),
            ],
        )
        .properties(height=260)
    )
    threshold = alt.Chart(pd.DataFrame({"threshold": [0.35]})).mark_rule(
        color="#ffb454", strokeDash=[6, 5]
    ).encode(y="threshold:Q")
    trend_chart = (
        (trend + threshold)
        .configure(background="transparent")
        .configure_axis(
            labelColor="#a9bed1",
            titleColor="#a9bed1",
            gridColor="#1e3a55",
            domainColor="#29445d",
        )
    )
    st.altair_chart(trend_chart, use_container_width=True)


def render_golden_cases(cases: pd.DataFrame) -> None:
    st.subheader("Golden dataset performance")
    st.markdown(
        '<div class="section-note">Every row is synthetic. Scores are generated by the '
        "same evaluation contract enforced in CI.</div>",
        unsafe_allow_html=True,
    )
    display = cases.copy()
    for column in ("tool_accuracy", "groundedness", "hallucination_risk"):
        display[column] = display[column].map(lambda value: f"{value:.1%}")
    display["latency_ms"] = display["latency_ms"].map(lambda value: f"{value:.1f}")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "case": "Golden case",
            "tool_accuracy": "Tool accuracy",
            "groundedness": "Groundedness",
            "hallucination_risk": "Hallucination risk",
            "latency_ms": "Latency (ms)",
        },
    )


def render_review_queue(snapshot: DashboardSnapshot) -> None:
    queued = snapshot.review_queue
    event_count = len(snapshot.events)
    left, middle, right = st.columns(3)
    left.metric("Cases awaiting review", len(queued))
    middle.metric("Evaluation events", event_count)
    right.metric(
        "Processed events",
        sum(bool(event.get("processed")) for event in snapshot.events),
    )
    if queued:
        st.dataframe(pd.DataFrame(queued), use_container_width=True, hide_index=True)
    else:
        st.success("No cases currently breach the human-review confidence thresholds.")


def render_failure_analysis(snapshot: DashboardSnapshot) -> None:
    st.subheader("Failure Analysis")
    st.markdown(
        '<div class="section-note">Prioritized diagnostic view of weak grounding, '
        "hallucination exposure, tool mismatches, incomplete workflows, and latency "
        "outliers.</div>",
        unsafe_allow_html=True,
    )
    failures = pd.DataFrame(failure_analysis_rows(snapshot.evaluation))
    affected = failures[failures["failure_modes"] != "Healthy"]
    highest_risk = failures.iloc[0]

    left, middle, right, fourth = st.columns(4)
    left.metric("Cases with signals", len(affected))
    middle.metric("Highest failure score", percentage(highest_risk["failure_score"]))
    right.metric("Top-case severity", highest_risk["severity"].upper())
    fourth.metric(
        "Review threshold breaches",
        snapshot.evaluation["aggregate"]["review_queue_count"],
    )
    st.caption(f"Highest-ranked case: `{highest_risk['case']}`")

    chart = (
        alt.Chart(failures)
        .mark_circle(opacity=0.88, stroke="#d9e8f5", strokeWidth=0.8)
        .encode(
            x=alt.X(
                "groundedness:Q",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%"),
                title="Groundedness",
            ),
            y=alt.Y(
                "hallucination_risk:Q",
                scale=alt.Scale(domain=[0, max(0.4, failures["hallucination_risk"].max())]),
                axis=alt.Axis(format="%"),
                title="Hallucination risk",
            ),
            size=alt.Size(
                "failure_score:Q",
                scale=alt.Scale(range=[90, 850]),
                title="Failure score",
            ),
            color=alt.Color(
                "severity:N",
                scale=alt.Scale(
                    domain=["low", "medium", "high", "critical"],
                    range=["#56a8ff", "#43d9a3", "#ffb454", "#ff758f"],
                ),
                title="Severity",
            ),
            tooltip=[
                "case",
                "severity",
                "failure_modes",
                alt.Tooltip("groundedness:Q", format=".1%"),
                alt.Tooltip("hallucination_risk:Q", format=".1%"),
                alt.Tooltip("failure_score:Q", format=".1%"),
            ],
        )
        .properties(height=330)
        .configure(background="transparent")
        .configure_axis(
            labelColor="#a9bed1",
            titleColor="#a9bed1",
            gridColor="#1e3a55",
            domainColor="#29445d",
        )
        .configure_legend(labelColor="#a9bed1", titleColor="#a9bed1")
    )
    st.altair_chart(chart, use_container_width=True)

    st.subheader("Prioritized findings")
    display = failures[
        [
            "case",
            "severity",
            "failure_score",
            "failure_modes",
            "groundedness",
            "hallucination_risk",
            "latency_ms",
            "recommendation",
        ]
    ].copy()
    for column in ("failure_score", "groundedness", "hallucination_risk"):
        display[column] = display[column].map(lambda value: f"{value:.1%}")
    display["latency_ms"] = display["latency_ms"].map(lambda value: f"{value:.1f}")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "case": "Golden case",
            "failure_score": "Failure score",
            "failure_modes": "Detected signals",
            "groundedness": "Groundedness",
            "hallucination_risk": "Hallucination risk",
            "latency_ms": "Latency (ms)",
            "recommendation": "Recommended action",
        },
    )


def render_ab_test(snapshot: DashboardSnapshot) -> None:
    st.subheader("Baseline vs. strict-grounded prompt strategy")
    rows = pd.DataFrame(ab_metric_rows(snapshot.experiment))
    chart = (
        alt.Chart(rows)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
        .encode(
            x=alt.X("metric:N", title=None),
            xOffset="strategy:N",
            y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            color=alt.Color(
                "strategy:N",
                scale=alt.Scale(
                    domain=["Baseline", "Strict grounded"],
                    range=["#37bdf8", "#9d8cff"],
                ),
                title=None,
            ),
            tooltip=["metric", "strategy", alt.Tooltip("score:Q", format=".1%")],
        )
        .properties(height=320)
        .configure(background="transparent")
        .configure_axis(
            labelColor="#a9bed1",
            titleColor="#a9bed1",
            gridColor="#1e3a55",
            domainColor="#29445d",
        )
        .configure_legend(labelColor="#a9bed1", titleColor="#a9bed1")
    )
    st.altair_chart(chart, use_container_width=True)

    comparison = snapshot.experiment["comparison"]
    baseline_latency = comparison["average_latency_ms"]["baseline"]
    strict_latency = comparison["average_latency_ms"]["strict_grounded"]
    left, right = st.columns(2)
    left.metric("Baseline latency", f"{baseline_latency:.1f} ms")
    right.metric(
        "Strict-grounded latency",
        f"{strict_latency:.1f} ms",
        delta=f"{strict_latency - baseline_latency:+.1f} ms",
        delta_color="inverse",
    )


with st.sidebar:
    st.markdown("### Telefix")
    st.caption("Synthetic Agent Evaluation")
    api_url = st.text_input("FastAPI base URL", value=API_URL)
    if st.button("Refresh metrics", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Data sources")
    st.code(
        "POST /evaluations/run\n"
        "POST /experiments/ab-test\n"
        "GET  /review-queue\n"
        "GET  /events",
        language=None,
    )

try:
    snapshot = load_snapshot(api_url)
except requests.RequestException as exc:
    st.error(f"Could not reach the Telefix API at {api_url}: {exc}")
    st.info("Start the backend with: uvicorn src.main:app --reload")
    st.stop()

aggregate = snapshot.evaluation["aggregate"]
cases = pd.DataFrame(case_rows(snapshot.evaluation))
render_header(aggregate)
render_metric_cards(aggregate)

overview_tab, cases_tab, failure_tab, review_tab, experiment_tab = st.tabs(
    [
        "Executive overview",
        "Golden dataset",
        "Failure Analysis",
        "Review operations",
        "A/B experiments",
    ]
)
with overview_tab:
    render_overview(snapshot, cases)
with cases_tab:
    render_golden_cases(cases)
with failure_tab:
    render_failure_analysis(snapshot)
with review_tab:
    render_review_queue(snapshot)
with experiment_tab:
    render_ab_test(snapshot)

st.caption(
    "Synthetic broadband data only. No proprietary customer, network, or Comcast data is used."
)
