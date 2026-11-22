import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .interpreters import FixtureInterpreter, Interpreter, InterpreterUnavailable, OllamaInterpreter
from .models import Actor, Draft, Publication, ReportInput, Task
from .workflow import ReportError, ReportWorkflow


DemoActor = Annotated[Actor, Header(alias="X-Demo-User")]


def create_app(database: Path, interpreter: Interpreter | None = None) -> FastAPI:
    workflow = ReportWorkflow(database, interpreter or FixtureInterpreter())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        workflow.initialize()
        yield

    app = FastAPI(title="Workhub Portfolio Demo", lifespan=lifespan)

    @app.exception_handler(ReportError)
    async def report_error(request: Request, exc: ReportError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(InterpreterUnavailable)
    async def interpreter_unavailable(request: Request, exc: InterpreterUnavailable):
        return JSONResponse(status_code=502, content={"detail": "로컬 모델의 응답을 해석할 수 없습니다."})

    @app.get("/tasks")
    def list_tasks(actor: DemoActor) -> list[Task]:
        return workflow.tasks(actor)

    @app.post("/reports", status_code=201)
    def receive_report(report: ReportInput, actor: DemoActor) -> Draft:
        return workflow.create_draft(actor, report.text)

    @app.post("/reports/{draft_id}/confirm")
    def confirm_report(draft_id: str, actor: DemoActor) -> Publication:
        return workflow.confirm(actor, draft_id)

    @app.get("/channel")
    def read_demo_channel(actor: DemoActor) -> list[Publication]:
        return workflow.publications(actor)

    return app


model = os.environ.get("WORKHUB_OLLAMA_MODEL")
app = create_app(
    Path(os.environ.get("WORKHUB_DEMO_DB", "workhub-demo.sqlite3")),
    OllamaInterpreter(model) if model else None,
)
