import queue
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..db.engine import SessionLocal, engine
from ..db.models import Base
from ..executor.runner import Executor
from ..planner.llm import LLMPlanner
from ..policy.engine import PolicyEngine
from ..worker.loop import WorkerLoop
from .routes import approvals as approvals_router
from .routes import tasks as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap DB schema
    Base.metadata.create_all(bind=engine)

    # Shared state between API routes and worker thread
    task_queue: queue.Queue = queue.Queue()
    approval_events: dict = {}

    app.state.task_queue = task_queue
    app.state.approval_events = approval_events
    app.state.session_factory = SessionLocal

    # Build core components
    executor = Executor(
        workspace_dir=settings.workspace_dir.resolve(),
        timeout_seconds=settings.step_timeout_seconds,
    )
    planner = LLMPlanner(
        host=settings.ollama_host,
        model=settings.ollama_model,
        max_retries=settings.llm_max_retries,
    )

    worker = WorkerLoop(
        session_factory=SessionLocal,
        executor=executor,
        planner=planner,
        policy_engine=PolicyEngine(),
        task_queue=task_queue,
        approval_events=approval_events,
        approval_timeout_seconds=settings.approval_timeout_seconds,
        max_steps_per_task=settings.max_steps_per_task,
        step_retry_limit=settings.step_retry_limit,
    )

    thread = threading.Thread(target=worker.run, daemon=True, name="llmos-worker")
    thread.start()

    yield
    # Worker is a daemon thread — dies with the process on shutdown


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic LLM OS",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tasks_router.router, prefix="/tasks", tags=["tasks"])
    app.include_router(approvals_router.router, prefix="/tasks", tags=["approvals"])

    return app


app = create_app()


def start_daemon():
    import uvicorn
    uvicorn.run(
        "llmos.api.app:app",
        host=settings.daemon_host,
        port=settings.daemon_port,
        reload=False,
    )
