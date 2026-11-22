import json
import hashlib
import time as time_module
from collections import Counter
from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

from .logic import (
    aggregate_project_progress,
    calculate_duration,
    calculate_progress_from_text,
    extract_time_range,
    infer_task_from_text,
    is_delayed,
    normalize_next_action,
)
from .config import get_settings
from .llm.base import LLMProvider
from .llm.local import LocalLLMError
from .llm.mock import MockProvider
from .models import ChatDraft, ChatDraftItem, Employee, Project, Report, ReportRevision, Task
from .schemas import ParsedWorkReport, ReportConfirm, ReportCreate, ReportUpdate


class DuplicateReportError(RuntimeError):
    pass


def day_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    selected = day or date.today()
    return datetime.combine(selected, time.min), datetime.combine(selected, time.max)


def normalize_parsed(parsed: ParsedWorkReport, raw_message: str, employee_name: str, project_name: str) -> ParsedWorkReport:
    parsed = parsed.model_copy(deep=True)
    deterministic_progress = calculate_progress_from_text(raw_message)
    # An unknown/ambiguous report must not retain an ungrounded model guess.
    parsed.progress = deterministic_progress
    start_time, end_time = extract_time_range(raw_message)
    if start_time and end_time:
        parsed.start_time = start_time
        parsed.end_time = end_time
        parsed.duration_hours = calculate_duration(start_time, end_time)
    if parsed.task.strip() in {project_name, f"{project_name} 업무", "업무"}:
        parsed.task = infer_task_from_text(raw_message, project_name)
    parsed.next_action = normalize_next_action(parsed.next_action)
    parsed.employee = employee_name
    return parsed


async def parse_report_preview(
    db: Session, payload: ReportCreate, provider: LLMProvider
) -> tuple[ParsedWorkReport, str, bool, int]:
    employee = db.get(Employee, payload.employee_id)
    project = db.get(Project, payload.project_id)
    if not employee or not project:
        raise LookupError("직원 또는 프로젝트를 찾을 수 없습니다.")

    started = time_module.perf_counter()
    provider_name = get_settings().llm_provider.lower()
    fallback_used = False
    try:
        parsed = await provider.parse_report(payload.raw_message, employee.name, project.name)
    except LocalLLMError:
        if not get_settings().local_llm_fallback_to_mock:
            raise
        parsed = await MockProvider().parse_report(payload.raw_message, employee.name, project.name)
        provider_name = "mock"
        fallback_used = True
    elapsed_ms = round((time_module.perf_counter() - started) * 1000)
    return normalize_parsed(parsed, payload.raw_message, employee.name, project.name), provider_name, fallback_used, elapsed_ms


def report_fingerprint(employee_id: int, project_id: int, raw_message: str, day: date | None = None) -> str:
    normalized = " ".join(raw_message.lower().split())
    source = f"{employee_id}:{project_id}:{day or date.today()}:{normalized}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def save_confirmed_report(db: Session, payload: ReportConfirm) -> tuple[Report, ParsedWorkReport]:
    employee = db.get(Employee, payload.employee_id)
    project = db.get(Project, payload.project_id)
    if not employee or not project:
        raise LookupError("직원 또는 프로젝트를 찾을 수 없습니다.")
    # 확정 단계에서는 직원이 Preview에서 고친 값을 최우선으로 보존한다.
    parsed = payload.parsed.model_copy(deep=True)
    parsed.employee = employee.name
    parsed.next_action = normalize_next_action(parsed.next_action)
    fingerprint = report_fingerprint(employee.id, project.id, payload.raw_message)
    if db.scalar(select(Report.id).where(Report.fingerprint == fingerprint)):
        raise DuplicateReportError("같은 직원·프로젝트·원문으로 오늘 이미 저장된 보고가 있습니다.")

    task = db.scalar(
        select(Task)
        .where(Task.employee_id == employee.id, Task.project_id == project.id)
        .order_by(Task.id.desc())
    )
    if task is None:
        task = Task(
            employee=employee,
            project=project,
            title=parsed.task,
            status=parsed.status,
            progress=parsed.progress or 0,
            expected_progress=project.expected_progress,
            started_at=date.today(),
        )
        db.add(task)
        db.flush()
    else:
        task.title = parsed.task
        task.status = parsed.status
        if parsed.progress is not None:
            task.progress = parsed.progress

    report = Report(
        employee=employee,
        task=task,
        raw_message=payload.raw_message,
        structured_summary=parsed.model_dump_json(),
        duration_hours=parsed.duration_hours,
        progress=parsed.progress,
        issue=parsed.issue,
        next_action=parsed.next_action,
        fingerprint=fingerprint,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateReportError("동일한 업무보고가 이미 저장되어 있습니다.") from exc
    db.refresh(report)
    return report, parsed


def parsed_from_report(report: Report) -> ParsedWorkReport:
    data = json.loads(report.structured_summary)
    data.setdefault("employee", report.employee.name)
    data.setdefault("task", report.task.title)
    data.setdefault("status", report.task.status)
    data.setdefault("progress", report.progress)
    data.setdefault("duration_hours", report.duration_hours)
    data.setdefault("issue", report.issue)
    data.setdefault("next_action", report.next_action)
    data.setdefault("confidence", 1.0)
    return ParsedWorkReport.model_validate(data)


def report_list_item(report: Report) -> dict:
    parsed = parsed_from_report(report)
    return {
        "id": report.id,
        "employee_id": report.employee_id,
        "employee": report.employee.name,
        "project_id": report.task.project_id,
        "project": report.task.project.name,
        "task": parsed.task,
        "progress": report.progress,
        "status": parsed.status,
        "next_action": report.next_action,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def list_reports(
    db: Session, employee_id: int | None = None, project_id: int | None = None,
    date_from: date | None = None, date_to: date | None = None, search: str | None = None,
) -> dict:
    stmt = select(Report).options(
        joinedload(Report.employee), joinedload(Report.task).joinedload(Task.project)
    )
    if employee_id:
        stmt = stmt.where(Report.employee_id == employee_id)
    if project_id:
        stmt = stmt.join(Report.task).where(Task.project_id == project_id)
    if date_from:
        stmt = stmt.where(Report.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(Report.created_at <= datetime.combine(date_to, time.max))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(or_(Report.raw_message.ilike(term), Report.structured_summary.ilike(term)))
    rows = db.scalars(stmt.order_by(Report.created_at.desc()).limit(200)).unique().all()
    return {"items": [report_list_item(item) for item in rows], "total": len(rows)}


def get_report_detail(db: Session, report_id: int) -> dict:
    report = db.scalar(
        select(Report).options(
            joinedload(Report.employee), joinedload(Report.task).joinedload(Task.project), joinedload(Report.revisions)
        ).where(Report.id == report_id)
    )
    if not report:
        raise LookupError("업무보고를 찾을 수 없습니다.")
    result = report_list_item(report)
    chat_mapping = db.scalar(select(ChatDraftItem).where(ChatDraftItem.report_id == report.id))
    if chat_mapping:
        source = db.get(ChatDraft, chat_mapping.draft_id)
        result["source_url"] = f"http://127.0.0.1:3000/group/poc-reports?msg={source.message_id}"
        result["review_url"] = f"http://127.0.0.1:8003/#{source.id}"
    result.update({
        "raw_message": report.raw_message,
        "parsed": parsed_from_report(report),
        "duration_hours": report.duration_hours,
        "issue": report.issue,
        "revisions": [{
            "id": rev.id, "changed_by": rev.changed_by, "before": json.loads(rev.before_data),
            "after": json.loads(rev.after_data), "reason": rev.reason, "created_at": rev.created_at,
        } for rev in report.revisions],
    })
    return result


def update_report(db: Session, report_id: int, payload: ReportUpdate) -> dict:
    if db.scalar(select(ChatDraftItem).where(ChatDraftItem.report_id == report_id)):
        raise HTTPException(409, "로켓챗 보고는 작성자 인증이 필요한 수정·확정 화면에서 변경하세요.")
    report = db.scalar(select(Report).options(joinedload(Report.employee), joinedload(Report.task).joinedload(Task.project)).where(Report.id == report_id))
    if not report:
        raise LookupError("업무보고를 찾을 수 없습니다.")
    parsed = parsed_from_report(report)
    before = parsed.model_dump(mode="json")
    parsed.task = payload.task
    parsed.status = payload.status
    parsed.progress = payload.progress
    parsed.duration_hours = payload.duration_hours
    parsed.issue = payload.issue
    parsed.next_action = normalize_next_action(payload.next_action)
    after = parsed.model_dump(mode="json")
    if before != after:
        db.add(ReportRevision(
            report=report, changed_by=report.employee.name,
            before_data=json.dumps(before, ensure_ascii=False), after_data=json.dumps(after, ensure_ascii=False),
            reason=payload.edit_reason,
        ))
        report.structured_summary = parsed.model_dump_json()
        report.duration_hours = parsed.duration_hours
        report.progress = parsed.progress
        report.issue = parsed.issue
        report.next_action = parsed.next_action
        report.updated_at = datetime.now()
        report.task.title = parsed.task
        report.task.status = parsed.status
        if parsed.progress is not None:
            report.task.progress = parsed.progress
        db.commit()
    return get_report_detail(db, report_id)


def get_dashboard(db: Session) -> dict:
    start, end = day_bounds()
    employees = db.scalars(select(Employee).order_by(Employee.id)).all()
    projects = db.scalars(select(Project).options(joinedload(Project.tasks)).order_by(Project.id)).unique().all()
    tasks = db.scalars(select(Task).options(joinedload(Task.employee), joinedload(Task.project))).all()
    today_reports = db.scalars(
        select(Report)
        .options(joinedload(Report.employee), joinedload(Report.task).joinedload(Task.project))
        .where(Report.created_at.between(start, end))
        .order_by(Report.id.desc())
    ).unique().all()

    reported_ids = {report.employee_id for report in today_reports}
    project_rows = []
    for project in projects:
        progress = aggregate_project_progress(item.progress for item in project.tasks)
        if project.tasks and all(item.progress is None for item in project.tasks):
            progress = None
        delayed = any(is_delayed(item.progress, item.expected_progress, item.status) for item in project.tasks)
        project_rows.append(
            {
                "id": project.id,
                "name": project.name,
                "progress": progress,
                "expected_progress": project.expected_progress,
                "status": "DELAYED" if delayed else ("DONE" if progress == 100 else "IN_PROGRESS"),
            }
        )

    latest_by_employee: dict[int, Report] = {}
    for report in today_reports:
        latest_by_employee.setdefault(report.employee_id, report)

    employee_rows = []
    for item in employees:
        latest = latest_by_employee.get(item.id)
        duration = sum((r.duration_hours or 0) for r in today_reports if r.employee_id == item.id)
        fallback_task = next((task for task in tasks if task.employee_id == item.id), None)
        selected_task = latest.task if latest else fallback_task
        employee_rows.append(
            {
                "id": item.id,
                "name": item.name,
                "team": item.team,
                "task": selected_task.title if selected_task else "업무 미배정",
                "project": selected_task.project.name if selected_task else "-",
                "progress": selected_task.progress if selected_task else 0,
                "duration_hours": round(duration, 1),
                "next_action": latest.next_action if latest and latest.next_action else "확인 필요",
                "status": selected_task.status if selected_task else "NOT_STARTED",
                "reported": item.id in reported_ids,
            }
        )

    delayed_tasks = [task for task in tasks if is_delayed(task.progress, task.expected_progress, task.status)]
    repeated_issues = Counter(report.issue for report in today_reports if report.issue)
    risks = []
    for task in delayed_tasks:
        latest_issue = next((report.issue for report in today_reports if report.task_id == task.id and report.issue), None)
        reasons = []
        if latest_issue:
            reasons.append(latest_issue)
            if repeated_issues[latest_issue] >= 2:
                reasons.append("동일 이슈가 오늘 2회 이상 보고됨")
        if task.progress is not None and task.progress < task.expected_progress:
            reasons.append(f"계획 {task.expected_progress}% 대비 {task.progress}% 진행")
        risks.append(
            {
                "task_id": task.id,
                "project": task.project.name,
                "task": task.title,
                "owner": task.employee.name,
                "severity": "HIGH" if task.status == "DELAYED" else "MEDIUM",
                "reasons": reasons,
            }
        )

    known_progress = [task.progress for task in tasks if task.progress is not None]
    average = round(sum(known_progress) / len(known_progress)) if known_progress else 0
    on_track = sum(1 for task in tasks if (task.progress is not None and task.progress >= task.expected_progress) or task.status == "DONE")
    completion_rate = round(on_track / len(tasks) * 100) if tasks else 0
    delayed_names = ", ".join(dict.fromkeys(risk["project"] for risk in risks)) or "없음"
    summary = (
        f"오늘 총 {len(reported_ids)}명이 업무를 보고했습니다. 전체 업무 평균 진행률은 {average}%입니다. "
        f"현재 확인이 필요한 지연 후보는 {len(delayed_tasks)}건이며, 주요 프로젝트는 {delayed_names}입니다."
    )
    all_reports = db.scalars(select(Report).where(Report.progress.is_not(None)).order_by(Report.created_at)).all()
    daily: dict[date, list[int]] = {}
    for report in all_reports:
        daily.setdefault(report.created_at.date(), []).append(report.progress or 0)
    trend = [
        {"date": day.isoformat(), "average_progress": round(sum(values) / len(values)), "report_count": len(values)}
        for day, values in sorted(daily.items())[-7:]
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "kpis": {
            "reported_today": len(reported_ids),
            "total_employees": len(employees),
            "average_progress": average,
            "delayed_count": len(delayed_tasks),
            "expected_completion_rate": completion_rate,
        },
        "projects": project_rows,
        "employees": employee_rows,
        "summary": summary,
        "risks": risks,
        "trend": trend,
    }


def answer_chat(db: Session, message: str) -> tuple[str, list[str]]:
    dashboard = get_dashboard(db)
    normalized = message.replace(" ", "")
    sources: list[str] = []

    if "지연" in normalized or "확인" in normalized:
        risks = dashboard["risks"]
        if not risks:
            return "현재 규칙상 지연으로 분류된 업무는 없습니다.", ["tasks"]
        lines = [
            f"{idx + 1}. {risk['project']} · {risk['task']} ({risk['owner']}) — {'; '.join(risk['reasons'])}"
            for idx, risk in enumerate(risks[:4])
        ]
        return "오늘 우선 확인할 지연 업무입니다.\n" + "\n".join(lines), ["tasks", "reports"]

    employee = next((row for row in dashboard["employees"] if row["name"] in message), None)
    if employee:
        progress_text = "확인 필요" if employee["progress"] is None else f"{employee['progress']}%"
        answer = (
            f"{employee['name']}님은 오늘 {employee['task']} 업무를 진행했고, "
            f"현재 진행률은 {progress_text}, 투입시간은 {employee['duration_hours']}시간입니다. "
            f"다음 작업은 {employee['next_action']}입니다."
        )
        return answer, [f"employees:{employee['id']}", "reports:today"]

    project = next((row for row in dashboard["projects"] if row["name"] in message), None)
    if project:
        state = "지연" if project["status"] == "DELAYED" else "진행 중"
        progress_text = "확인 필요" if project["progress"] is None else f"{project['progress']}%"
        return (
            f"{project['name']} 프로젝트는 현재 진행률 {progress_text}, 상태는 {state}입니다. "
            f"기준 진행률은 {project['expected_progress']}%입니다.",
            [f"projects:{project['id']}", "tasks"],
        )

    return dashboard["summary"], ["reports:today", "tasks", "projects"]
