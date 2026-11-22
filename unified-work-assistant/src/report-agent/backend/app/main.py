from contextlib import asynccontextmanager

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .auth import DemoIdentity, get_identity, require_manager, require_owner_or_manager
from .database import Base, SessionLocal, engine, get_db
from .llm import get_provider, get_provider_status
from .models import Employee, Project
from .schemas import ChatRequest, ChatResponse, ParseResult, ReportConfirm, ReportCreate, ReportDetail, ReportResult, ReportUpdate
from .seed import seed_database
from .services import (
    DuplicateReportError, answer_chat, get_dashboard, get_report_detail,
    list_reports, parse_report_preview, save_confirmed_report, update_report,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.get("/api/system/llm")
async def llm_status() -> dict[str, str | bool]:
    return await get_provider_status()


@app.get("/api/auth/session")
def auth_session(identity: DemoIdentity = Depends(get_identity)) -> dict:
    return {"mode": settings.auth_mode, "role": identity.role, "employee_id": identity.employee_id}


@app.get("/api/employees")
def list_employees(db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> list[dict]:
    stmt = select(Employee).order_by(Employee.name)
    if not identity.is_manager:
        stmt = stmt.where(Employee.id == identity.employee_id)
    return [
        {"id": employee.id, "name": employee.name, "team": employee.team}
        for employee in db.scalars(stmt)
    ]


@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "expected_progress": project.expected_progress,
        }
        for project in db.scalars(select(Project).order_by(Project.id))
    ]


@app.post("/api/reports/parse", response_model=ParseResult)
async def parse_report(payload: ReportCreate, db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> ParseResult:
    require_owner_or_manager(identity, payload.employee_id)
    try:
        parsed, provider, fallback_used, elapsed_ms = await parse_report_preview(db, payload, get_provider())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"업무보고 구조화에 실패했습니다: {exc}") from exc
    return ParseResult(parsed=parsed, provider=provider, fallback_used=fallback_used, elapsed_ms=elapsed_ms)


@app.post("/api/reports", response_model=ReportResult, status_code=201)
def submit_report(payload: ReportConfirm, db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> ReportResult:
    require_owner_or_manager(identity, payload.employee_id)
    try:
        report, parsed = save_confirmed_report(db, payload)
    except DuplicateReportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"업무보고 저장에 실패했습니다: {exc}") from exc
    return ReportResult(
        id=report.id,
        parsed=parsed,
        created_at=report.created_at,
    )


@app.get("/api/reports")
def report_history(
    employee_id: int | None = None,
    project_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    identity: DemoIdentity = Depends(get_identity),
) -> dict:
    if not identity.is_manager:
        employee_id = identity.employee_id
    return list_reports(db, employee_id, project_id, date_from, date_to, search)


@app.get("/api/reports/{report_id}", response_model=ReportDetail)
def report_detail(report_id: int, db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> dict:
    try:
        result = get_report_detail(db, report_id)
        require_owner_or_manager(identity, result["employee_id"])
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/reports/{report_id}", response_model=ReportDetail)
def edit_report(report_id: int, payload: ReportUpdate, db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> dict:
    try:
        current = get_report_detail(db, report_id)
        require_owner_or_manager(identity, current["employee_id"])
        return update_report(db, report_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> dict:
    require_manager(identity)
    return get_dashboard(db)


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), identity: DemoIdentity = Depends(get_identity)) -> ChatResponse:
    require_manager(identity)
    answer, sources = answer_chat(db, payload.message)
    return ChatResponse(answer=answer, sources=sources)
