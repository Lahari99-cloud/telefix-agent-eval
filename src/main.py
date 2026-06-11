"""FastAPI entrypoint for the Telefix Agent Evaluation demo."""

from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from src.agent import BroadbandTroubleshootingAgent
from src.config import get_settings
from src.eval_worker import EventProcessingResult, OfflineEvaluationWorker
from src.evaluation import EvaluationRunner, EvaluationRunResult
from src.event_stream import EvaluationEvent, InMemoryEventStream, new_event
from src.experiments import ABTestResult, ExperimentRunner
from src.rag import build_retriever
from src.review_queue import ReviewItem, ReviewQueue
from src.schemas import DiagnoseRequest, DiagnoseResponse
from src.state_store import DiagnosticSession, build_state_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.agent = BroadbandTroubleshootingAgent(
        settings=settings,
        retriever=build_retriever(settings),
    )
    app.state.review_queue = ReviewQueue()
    app.state.state_store = build_state_store(settings)
    app.state.event_stream = InMemoryEventStream()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Interview-ready synthetic broadband troubleshooting workflow with built-in evaluation."
    ),
    lifespan=lifespan,
)


@app.get("/healthz", tags=["operations"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.post(
    "/api/v1/diagnose",
    response_model=DiagnoseResponse,
    tags=["diagnostics"],
)
async def diagnose(
    payload: DiagnoseRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> Any:
    state_store = request.app.state.state_store
    if payload.session_id:
        existing = await state_store.get(payload.session_id)
        if existing:
            existing.resume_count += 1
            await state_store.save(existing)
            return existing.response

    session_id = payload.session_id or str(uuid4())
    agent: BroadbandTroubleshootingAgent = request.app.state.agent
    started = perf_counter()
    response = await agent.diagnose(payload)
    response.session_id = session_id
    latency_ms = (perf_counter() - started) * 1000
    await state_store.save(
        DiagnosticSession(
            session_id=session_id,
            request=payload.model_copy(update={"session_id": session_id}),
            response=response,
        )
    )
    event = new_event(
        event_id=str(uuid4()),
        session_id=session_id,
        user_prompt=payload.symptoms,
        retrieved_context=[citation.document_id for citation in response.citations],
        agent_response=f"{response.summary} {response.recommended_action}",
        tools_triggered=response.evaluation.selected_tools,
        latency_ms=latency_ms,
        workflow_status=response.workflow_status.value,
    )
    background_tasks.add_task(request.app.state.event_stream.publish, event)
    return response


@app.get(
    "/api/v1/sessions/{session_id}",
    response_model=DiagnosticSession,
    tags=["diagnostics"],
)
async def get_session(session_id: str, request: Request) -> DiagnosticSession:
    session = await request.app.state.state_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Diagnostic session not found.")
    return session


@app.get(
    "/api/v1/events",
    response_model=list[EvaluationEvent],
    tags=["evaluations"],
)
async def get_events(request: Request) -> list[EvaluationEvent]:
    return await request.app.state.event_stream.list_events()


@app.post(
    "/api/v1/evaluations/run",
    response_model=EvaluationRunResult,
    tags=["evaluations"],
)
async def run_evaluations(request: Request) -> EvaluationRunResult:
    runner = EvaluationRunner(
        request.app.state.agent,
        request.app.state.review_queue,
    )
    return await runner.run()


@app.post(
    "/api/v1/evaluations/process-events",
    response_model=EventProcessingResult,
    tags=["evaluations"],
)
async def process_events(request: Request) -> EventProcessingResult:
    worker = OfflineEvaluationWorker(
        request.app.state.event_stream,
        request.app.state.review_queue,
    )
    return await worker.process_pending()


@app.get(
    "/api/v1/review-queue",
    response_model=list[ReviewItem],
    tags=["evaluations"],
)
async def get_review_queue(request: Request) -> list[ReviewItem]:
    review_queue: ReviewQueue = request.app.state.review_queue
    return review_queue.list_items()


@app.post(
    "/api/v1/experiments/ab-test",
    response_model=ABTestResult,
    tags=["experiments"],
)
async def run_ab_test(request: Request) -> ABTestResult:
    runner = ExperimentRunner(
        request.app.state.agent,
        request.app.state.review_queue,
    )
    return await runner.run_ab_test()
