"""Manager-only read models over confirmed Rocket.Chat report drafts."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatDraft
from .draft import safe_text
from .manager_query import ManagerQuery
from .workspace import PROJECTS, source_url

STATUS_LABELS = {
    "DONE": "완료",
    "IN_PROGRESS": "진행 중",
    "NOT_STARTED": "예정",
    "DELAYED": "지연",
    "UNKNOWN": "확인 필요",
}


def _items(draft: ChatDraft) -> list[dict]:
    try:
        value = json.loads(draft.current_data)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _source(draft: ChatDraft) -> dict:
    return {
        "draft_id": draft.id,
        "source_url": source_url(draft.room_id, draft.message_id),
        "review_url": f"http://127.0.0.1:8003/#{draft.id}",
        "reported_at": draft.submitted_at.isoformat(),
    }


def manager_query_context(db: Session) -> list[str]:
    return sorted(set(db.scalars(select(ChatDraft.author_username).where(
        ChatDraft.state == "CONFIRMED")).all()))


def _compact(value: str) -> str:
    return "".join(value.lower().replace("_", "-").split())


def _person_key(value: str) -> str:
    compact = _compact(value)
    for suffix in ("사원", "직원", "대리", "과장", "차장", "부장", "팀장", "님"):
        compact = compact.removesuffix(suffix)
    return compact


def _resolve_employee(requested: str | None, employees: list[str]) -> str | None:
    if not requested:
        return None
    key = _person_key(requested)
    exact = next((name for name in employees if _person_key(name) == key), None)
    if exact:
        return exact
    return next((name for name in employees
                 if _person_key(name) in key or key in _person_key(name)), None)


def _resolve_project(requested: str | None) -> str | None:
    if not requested:
        return None
    normalized = _compact(requested)
    if requested in PROJECTS:
        return requested
    for key, name in PROJECTS.items():
        if _compact(name) in normalized or normalized in _compact(name):
            return key
    if "업무비서" in normalized:
        return "ai-assistant"
    if "공간정보" in normalized:
        return "spatial-agent"
    return None


def _query_reports(db: Session, query: ManagerQuery) -> tuple[list[tuple[ChatDraft, list[dict]]], str | None, str | None]:
    rows = db.scalars(select(ChatDraft).where(ChatDraft.state == "CONFIRMED").order_by(
        ChatDraft.submitted_at.desc(), ChatDraft.id.desc())).all()
    employees = sorted({row.author_username for row in rows})
    employee = _resolve_employee(query.employee, employees)
    project = _resolve_project(query.project)
    if query.target_date:
        start = datetime.combine(query.target_date, time.min)
        end = start + timedelta(days=1)
        rows = [row for row in rows if start <= row.submitted_at < end]
    if employee:
        rows = [row for row in rows if row.author_username == employee]

    selected: list[tuple[ChatDraft, list[dict]]] = []
    seen_authors: set[str] = set()
    for row in rows:
        items = _items(row)
        if project:
            items = [item for item in items if item.get("project") == project]
        if not items:
            continue
        if query.period == "LATEST":
            if employee and selected:
                break
            if project and row.author_username in seen_authors:
                continue
            seen_authors.add(row.author_username)
        selected.append((row, items))
        if query.period == "RECENT" and len(selected) >= 10:
            break
    return selected, employee, project


def _status_text(item: dict) -> str:
    status = item.get("status") or "UNKNOWN"
    progress = item.get("progress")
    suffix = f" {progress}%" if status == "IN_PROGRESS" and progress is not None else ""
    return f"{STATUS_LABELS.get(status, '확인 필요')}{suffix}"


def _manager_text(value: str) -> str:
    """Avoid bracket escapes confusing Rocket.Chat's Markdown link parser."""
    return safe_text(value).replace("\\[", "［").replace("\\]", "］")


def answer_structured_manager_query(db: Session, query: ManagerQuery, today: date | None = None) -> tuple[str, list[str]]:
    if query.intent == "UNSUPPORTED":
        return ("업무보고 관련 질문을 입력해 주세요. 예: `오늘 poc-employee 사원 보고 보여줘`, "
                "`오늘 업무비서 프로젝트 보고 다 보여줘`, `공간정보 프로젝트 진행사항 알려줘`"), []
    if query.intent in {"OVERVIEW", "RISKS"}:
        question = "확인할 리스크" if query.intent == "RISKS" else "업무 현황"
        return answer_manager_question(get_manager_dashboard(db, today), question)

    reports, employee, project = _query_reports(db, query)
    if query.intent == "EMPLOYEE_REPORTS" and not query.employee:
        return "조회할 직원 이름을 함께 입력해 주세요.", []
    if query.intent == "EMPLOYEE_REPORTS" and not employee:
        return f"`{safe_text(query.employee or '')}`에 해당하는 직원의 확정 보고를 찾지 못했습니다.", []
    if query.intent in {"PROJECT_REPORTS", "PROJECT_STATUS"} and not query.project:
        return "조회할 프로젝트 이름을 함께 입력해 주세요.", []
    if query.intent in {"PROJECT_REPORTS", "PROJECT_STATUS"} and not project:
        return f"`{safe_text(query.project or '')}`에 해당하는 프로젝트를 찾지 못했습니다.", []

    subject = employee if query.intent == "EMPLOYEE_REPORTS" else PROJECTS[project]
    period = query.target_date.isoformat() if query.target_date else (
        "최근" if query.period == "RECENT" else "최신")
    if not reports:
        return f"{period} 기준 {safe_text(subject)}의 확정 보고가 없습니다.", []

    sources = list(dict.fromkeys(source_url(row.room_id, row.message_id) for row, _ in reports))
    all_items = [(row, item) for row, items in reports for item in items]
    if query.intent == "PROJECT_STATUS":
        counts = Counter((item.get("status") or "UNKNOWN") for _, item in all_items)
        known = [item.get("progress") for _, item in all_items
                 if item.get("status") == "IN_PROGRESS" and item.get("progress") is not None]
        progress = "확인 필요" if not known else f"{round(sum(known) / len(known))}%"
        lines = [
            f"{safe_text(subject)}는 {period} 확정 보고 기준 진행률 {progress}입니다.",
            f"완료 {counts['DONE']}건 · 진행 중 {counts['IN_PROGRESS']}건 · 예정 {counts['NOT_STARTED']}건 · 지연 {counts['DELAYED']}건",
        ]
    else:
        lines = [f"{period} 기준 {safe_text(subject)} 확정 보고 {len(reports)}건입니다."]

    for index, (row, item) in enumerate(all_items[:16], 1):
        project_label = PROJECTS.get(item.get("project"), "프로젝트 미선택")
        line = (f"{index}. {row.submitted_at:%Y-%m-%d %H:%M} · {_manager_text(row.author_username)} · "
                f"{_manager_text(project_label)} · {_manager_text(item.get('task') or '업무명 확인 필요')}"
                f" — {_status_text(item)}")
        if item.get("next_action"):
            line += f" · 다음 작업: {_manager_text(item['next_action'])}"
        if item.get("issue"):
            line += f" · 이슈: {_manager_text(item['issue'])}"
        lines.append(line)
    if len(all_items) > 16:
        lines.append(f"그 외 {len(all_items) - 16}건은 전체 현황에서 확인할 수 있습니다.")
    return "\n".join(lines), sources[:8]


def _dashboard_items(items: list[dict], project: str | None, status: str | None) -> list[dict]:
    if project:
        items = [item for item in items if item.get("project") == project]
    if status:
        items = [item for item in items if (item.get("status") or "UNKNOWN") == status]
    return items


def _stalled_tasks(rows: list[ChatDraft]) -> set[tuple[str, str, str]]:
    """Find active tasks whose numeric progress is unchanged in two consecutive reports."""
    history: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for draft in rows:
        for item in _items(draft):
            if item.get("status") != "IN_PROGRESS" or item.get("progress") is None:
                continue
            key = (draft.author_username, item.get("project") or "unassigned", item.get("task") or "")
            history[key].append(item["progress"])
    return {key for key, values in history.items() if len(values) >= 2 and values[0] == values[1]}


def _progress_trends(rows: list[ChatDraft], start_day: date, end_day: date,
                     project: str | None, status: str | None) -> list[dict]:
    """Return one daily point using each employee's last matching report of that day."""
    daily: dict[date, dict[str, list[dict]]] = defaultdict(dict)
    for draft in rows:
        report_day = draft.submitted_at.date()
        if not start_day <= report_day <= end_day or draft.author_username in daily[report_day]:
            continue
        items = _dashboard_items(_items(draft), project, status)
        if items:
            daily[report_day][draft.author_username] = items

    result = []
    for report_day in sorted(daily):
        items = [item for employee_items in daily[report_day].values() for item in employee_items]
        known = [item.get("progress") for item in items if item.get("progress") is not None]
        result.append({
            "date": report_day.isoformat(),
            "average_progress": round(sum(known) / len(known)) if known else None,
            "report_count": len(daily[report_day]),
            "task_count": len(items),
        })
    return result


def get_manager_dashboard(db: Session, today: date | None = None, *,
                          date_from: date | None = None, date_to: date | None = None,
                          project: str | None = None, employee: str | None = None,
                          status: str | None = None) -> dict:
    """Return filtered latest confirmed snapshots plus risks, trends, and source links."""
    selected_day = today or date.today()
    start = datetime.combine(selected_day, time.min)
    end = start + timedelta(days=1)
    rows = db.scalars(
        select(ChatDraft)
        .where(ChatDraft.state == "CONFIRMED")
        .order_by(ChatDraft.submitted_at.desc(), ChatDraft.id.desc())
    ).all()

    all_employees = sorted({row.author_username for row in rows})
    all_projects = sorted({item.get("project") or "unassigned" for row in rows for item in _items(row)})
    resolved_employee = _resolve_employee(employee, all_employees) if employee else None
    resolved_project = _resolve_project(project) if project else None
    if (employee and not resolved_employee) or (project and not resolved_project):
        rows_for_snapshot = []
    else:
        rows_for_snapshot = [row for row in rows if not resolved_employee or row.author_username == resolved_employee]
    if date_from:
        rows_for_snapshot = [row for row in rows_for_snapshot if row.submitted_at.date() >= date_from]
    if date_to:
        rows_for_snapshot = [row for row in rows_for_snapshot if row.submitted_at.date() <= date_to]

    latest_by_author: dict[str, tuple[ChatDraft, list[dict]]] = {}
    matching_reports: list[tuple[ChatDraft, list[dict]]] = []
    for row in rows_for_snapshot:
        items = _dashboard_items(_items(row), resolved_project, status)
        if not items:
            continue
        matching_reports.append((row, items))
        latest_by_author.setdefault(row.author_username, (row, items))

    stalled = _stalled_tasks(rows)

    project_items: dict[str, list[dict]] = defaultdict(list)
    employees = []
    status_counts: Counter[str] = Counter()
    risks = []
    source_links = []
    for author, (draft, items) in latest_by_author.items():
        for item in items:
            project_key = item.get("project") or "unassigned"
            project_items[project_key].append({**item, "author": author, **_source(draft)})
            status_counts[item.get("status") or "UNKNOWN"] += 1
            risk_type = None
            reason = None
            if item.get("issue"):
                risk_type, reason = "ISSUE", item["issue"]
            elif item.get("status") == "DELAYED":
                risk_type, reason = "DELAYED", "지연 상태로 보고됨"
            elif item.get("status") == "IN_PROGRESS" and item.get("progress") is None:
                risk_type, reason = "MISSING_PROGRESS", "진행 중이나 진행률이 기재되지 않음"
            elif (author, project_key, item.get("task") or "") in stalled:
                risk_type, reason = "STALLED", "최근 두 보고에서 진행률 변화가 없음"
            if reason:
                risks.append({
                    "project": PROJECTS.get(project_key, "프로젝트 미선택"),
                    "task": item.get("task") or "업무명 확인 필요",
                    "owner": author,
                    "reason": reason,
                    "risk_type": risk_type,
                    **_source(draft),
                })
        active = [item for item in items if item.get("status") == "IN_PROGRESS"]
        known = [item.get("progress") for item in active if item.get("progress") is not None]
        employees.append({
            "username": author,
            "reported_at": draft.submitted_at.isoformat(),
            "task_count": len(items),
            "active_count": len(active),
            "average_progress": round(sum(known) / len(known)) if known else None,
            "source_url": source_url(draft.room_id, draft.message_id),
        })
        source_links.append(source_url(draft.room_id, draft.message_id))

    projects = []
    for key, items in project_items.items():
        known = [item.get("progress") for item in items if item.get("progress") is not None]
        counts = Counter(item.get("status") or "UNKNOWN" for item in items)
        projects.append({
            "key": key,
            "name": PROJECTS.get(key, "프로젝트 미선택"),
            "progress": round(sum(known) / len(known)) if known else None,
            "task_count": len(items),
            "done_count": counts["DONE"],
            "in_progress_count": counts["IN_PROGRESS"],
            "planned_count": counts["NOT_STARTED"],
            "delayed_count": counts["DELAYED"],
            "sources": list(dict.fromkeys(item["source_url"] for item in items)),
        })
    projects.sort(key=lambda item: (item["delayed_count"] == 0, item["name"]))

    recent_reports = []
    for draft, items in matching_reports[:20]:
        recent_reports.append({
            "id": draft.id,
            "author": draft.author_username,
            "reported_at": draft.submitted_at.isoformat(),
            "items": [{
                "task": item.get("task") or "업무명 확인 필요",
                "project": PROJECTS.get(item.get("project"), "프로젝트 미선택"),
                "status": item.get("status") or "UNKNOWN",
                "status_label": STATUS_LABELS.get(item.get("status"), "확인 필요"),
                "progress": item.get("progress"),
            } for item in items],
            **_source(draft),
        })

    reported_today = len({row.author_username for row, _ in matching_reports if start <= row.submitted_at < end})
    current_items = sum(project_items.values(), [])
    known_progress = [item.get("progress") for item in current_items if item.get("progress") is not None]
    trend_end = date_to or selected_day
    trend_start = date_from or (trend_end - timedelta(days=13))
    trend_rows = [] if employee and not resolved_employee else [
        row for row in rows if not resolved_employee or row.author_username == resolved_employee]
    trends = _progress_trends(trend_rows, trend_start, trend_end, resolved_project, status)
    active_filters = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "project": resolved_project,
        "employee": resolved_employee,
        "status": status,
    }
    filter_count = sum(value is not None for value in active_filters.values())
    return {
        "generated_at": datetime.now().isoformat(),
        "basis": "직원별 최신 확정 보고" + (f" · 필터 {filter_count}개 적용" if filter_count else ""),
        "kpis": {
            "reported_today": reported_today,
            "employee_count": len(latest_by_author),
            "task_count": len(current_items),
            "average_progress": round(sum(known_progress) / len(known_progress)) if known_progress else None,
            "risk_count": len(risks),
        },
        "scope_reporter_count": len({row.author_username for row, _ in matching_reports}),
        "status_counts": {key: status_counts[key] for key in STATUS_LABELS},
        "projects": projects,
        "employees": sorted(employees, key=lambda item: item["username"]),
        "risks": risks[:20],
        "recent_reports": recent_reports,
        "sources": list(dict.fromkeys(source_links)),
        "trends": trends,
        "filters": active_filters,
        "filter_options": {
            "projects": [{"key": key, "name": PROJECTS.get(key, "프로젝트 미선택")} for key in all_projects],
            "employees": all_employees,
            "statuses": [{"key": key, "name": label} for key, label in STATUS_LABELS.items()],
        },
    }


def answer_manager_question(data: dict, question: str) -> tuple[str, list[str]]:
    normalized = "".join(question.lower().split())
    if any(word in normalized for word in ("리스크", "지연", "확인필요", "문제")):
        if not data["risks"]:
            return "현재 최신 확정 보고에서 명시된 지연·이슈는 없습니다.", data["sources"][:3]
        lines = [
            f"{index}. {safe_text(item['project'])} · {safe_text(item['task'])} — {safe_text(item['reason'])}"
            for index, item in enumerate(data["risks"][:4], 1)
        ]
        return "확인이 필요한 업무입니다.\n" + "\n".join(lines), [item["source_url"] for item in data["risks"][:4]]

    project = next((item for item in data["projects"] if
                    item["name"].replace(" ", "").lower() in normalized or
                    (item["key"] == "ai-assistant" and "업무비서" in normalized) or
                    (item["key"] == "spatial-agent" and "공간정보" in normalized)), None)
    if project:
        progress = "확인 필요" if project["progress"] is None else f"{project['progress']}%"
        return (
            f"{project['name']}는 최신 확정 보고 기준 진행률 {progress}입니다. "
            f"완료 {project['done_count']}건, 진행 중 {project['in_progress_count']}건, "
            f"예정 {project['planned_count']}건, 지연 {project['delayed_count']}건입니다.",
            project["sources"][:4],
        )

    employee = next((item for item in data["employees"] if item["username"].lower() in normalized), None)
    if employee:
        progress = "확인 필요" if employee["average_progress"] is None else f"{employee['average_progress']}%"
        return (
            f"{employee['username']}님의 최신 보고에는 업무 {employee['task_count']}건이 있고, "
            f"진행 중 {employee['active_count']}건의 평균 진행률은 {progress}입니다.",
            [employee["source_url"]],
        )

    kpis = data["kpis"]
    average = "확인 필요" if kpis["average_progress"] is None else f"{kpis['average_progress']}%"
    return (
        f"최신 확정 보고 기준 직원 {kpis['employee_count']}명, 업무 {kpis['task_count']}건입니다. "
        f"기재된 진행률 평균은 {average}이고, 확인할 리스크는 {kpis['risk_count']}건입니다.",
        data["sources"][:4],
    )


def format_manager_answer(data: dict, question: str, dashboard_url: str) -> str:
    answer, _sources = answer_manager_question(data, question)
    lines = ["**관리자 업무 요약**", answer]
    lines.extend(["", f"[전체 프로젝트·직원·리스크 보기]({dashboard_url})",
                  "출처: 직원별 최신 확정 보고 · 일반 대화와 미확정 초안은 제외"])
    return "\n".join(lines)


def format_structured_manager_answer(answer: str, _sources: list[str], dashboard_url: str,
                                     model: str, llm_used: bool,
                                     heading: str = "관리자 업무 비서") -> str:
    lines = [f"**{heading}**", answer]
    lines.extend(["", f"[전체 프로젝트·직원·리스크 보기]({dashboard_url})",
                  "조회 대상: 직원이 확인한 확정 보고 DB · 일반 대화와 미확정 초안 제외",
                  f"질문 해석: {safe_text(model) if llm_used else '규칙 기반 대체 처리'}"])
    return "\n".join(lines)
