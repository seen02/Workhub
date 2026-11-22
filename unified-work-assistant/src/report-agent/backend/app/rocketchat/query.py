"""Read-only, author-scoped retrieval of confirmed reports; no LLM or raw SQL."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from urllib.parse import quote

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import ChatDraft, ChatDraftItem, Project, Report, Task
from .draft import safe_text
from .workspace import source_url

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ReportQuery:
    start: date
    end: date  # inclusive date, SQL uses next midnight exclusively
    keyword: str = ""
    incomplete: bool = False


def parse_query(text: str, today: date | None = None) -> ReportQuery:
    today = today or datetime.now(KST).date()
    text = re.sub(r"^!?조회\s*", "", text.strip())
    if re.search(r"전체\s*(직원|팀)|팀\s*전체|팀원|다른\s*(사람|직원)|동료|전사|부서별", text):
        raise ValueError("지금은 본인이 확정한 보고만 조회할 수 있어요. '오늘 보고'라고 입력해 주세요.")
    start, end = today - timedelta(days=29), today
    date_tokens = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if date_tokens:
        if len(date_tokens) > 2:
            raise ValueError("날짜는 하나 또는 시작일~종료일로 입력해 주세요.")
        try:
            start = date.fromisoformat(date_tokens[0])
            end = date.fromisoformat(date_tokens[-1])
        except ValueError as exc:
            raise ValueError("날짜를 YYYY-MM-DD 형식으로 확인해 주세요.") from exc
        if end == date.max or end < start or (end - start).days > 365:
            raise ValueError("조회 기간은 시작일 이후, 최대 366일로 입력해 주세요.")
        text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text).replace("~", " ")
    elif "이번 주" in text or "이번주" in text:
        start = today - timedelta(days=today.weekday())
    elif "지난 주" in text or "지난주" in text:
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
    elif "어제" in text:
        start = end = today - timedelta(days=1)
    elif "오늘" in text:
        start = today
    elif re.search(r"최근\s*30일", text):
        pass
    elif re.search(r"\d+\s*월|\d+\s*일|작년|올해|이번\s*달|지난\s*달|내일|전체\s*기간", text):
        raise ValueError("오늘·어제·이번 주·지난 주 또는 YYYY-MM-DD~YYYY-MM-DD로 조회해 주세요.")
    incomplete = bool(re.search(r"미완료|완료하지\s*않은|완료되지\s*않은|안\s*끝난", text))
    text = re.sub(r"미완료|아직\s*완료하지\s*않은|아직\s*완료되지\s*않은|완료하지\s*않은|완료되지\s*않은|안\s*끝난", " ", text)
    text = re.sub(r"이번\s*주|지난\s*주|오늘|어제|최근\s*30일", " ", text)
    text = re.sub(r"보여\s*줘|보여주세요|알려\s*줘|알려주세요|찾아\s*줘|찾아주세요|조회해\s*줘|내가|내\s*보고|본인|진행\s*상황|보고한|업무보고|업무|보고|내용|목록|내역|좀|아직", " ", text)
    keyword = " ".join(text.strip(" ?.!:").split())
    if len(keyword) > 80:
        raise ValueError("검색어는 80자 이내로 입력해 주세요.")
    return ReportQuery(start, end, keyword, incomplete)


def search_reports(db: Session, user_id: str, room_id: str, query: ReportQuery, limit: int = 10) -> dict:
    from .workspace import is_personal
    if is_personal(room_id):
        return search_personal(db, user_id, room_id, query, limit)
    stmt = (select(Report, Task, Project, ChatDraft)
        .join(ChatDraftItem, ChatDraftItem.report_id == Report.id)
        .join(ChatDraft, ChatDraft.id == ChatDraftItem.draft_id)
        .join(Task, Task.id == Report.task_id).join(Project, Project.id == Task.project_id)
        .where(ChatDraft.author_id == user_id, ChatDraft.room_id == room_id, ChatDraft.state == "CONFIRMED",
               Report.created_at >= datetime.combine(query.start, time.min),
               Report.created_at < datetime.combine(query.end + timedelta(days=1), time.min)))
    if query.incomplete:
        stmt = stmt.where(Task.status != "DONE")
    for word in query.keyword.split():
        stmt = stmt.where(or_(Task.title.contains(word, autoescape=True), Project.name.contains(word, autoescape=True),
                             Report.next_action.contains(word, autoescape=True), Report.issue.contains(word, autoescape=True)))
    rows = db.execute(stmt.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit + 1)).all()
    items = [{
        "report_id": report.id, "task": task.title, "status": task.status,
        "progress": report.progress, "next_action": report.next_action, "issue": report.issue,
        "author": draft.author_username, "project": project.name,
        "reported_at": report.created_at.isoformat(), "updated_at": report.updated_at.isoformat(),
        "source_url": source_url(draft.room_id, draft.message_id),
        "review_url": f"http://127.0.0.1:8003/#{draft.id}",
    } for report, task, project, draft in rows[:limit]]
    return {"items": items, "has_more": len(rows) > limit, "start": query.start.isoformat(),
            "end": query.end.isoformat(), "keyword": query.keyword, "incomplete": query.incomplete,
            "scope": "본인 · 이 테스트방 · 확정 보고 DB", "date_basis": "원문 보고 시각(KST)", "llm_used": False}


def search_personal(db, user_id, room_id, query, limit):
    import json
    from .workspace import PROJECTS
    rows = db.scalars(select(ChatDraft).where(ChatDraft.author_id == user_id, ChatDraft.room_id == room_id,
        ChatDraft.state == "CONFIRMED", ChatDraft.submitted_at >= datetime.combine(query.start, time.min),
        ChatDraft.submitted_at < datetime.combine(query.end + timedelta(days=1), time.min))
        .order_by(ChatDraft.submitted_at.desc(), ChatDraft.id.desc()))
    items = []
    for draft in rows:
        for n, item in enumerate(json.loads(draft.current_data)):
            title = PROJECTS.get(item.get("project"), "프로젝트 미선택")
            haystack = " ".join(str(item.get(k) or "") for k in ("task", "next_action", "issue")) + " " + title
            if (query.incomplete and item["status"] == "DONE") or any(w not in haystack for w in query.keyword.split()):
                continue
            items.append({**item, "project": title, "author": draft.author_username,
                "report_id": f"{draft.id[:8]}-{n+1}", "reported_at": draft.submitted_at.isoformat(),
                "updated_at": draft.updated_at.isoformat(), "source_url": source_url(room_id, draft.message_id),
                "review_url": f"http://127.0.0.1:8003/#{draft.id}"})
            if len(items) > limit:
                break
        if len(items) > limit:
            break
    return {"items": items[:limit], "has_more": len(items) > limit, "start": query.start.isoformat(),
        "end": query.end.isoformat(), "keyword": query.keyword, "incomplete": query.incomplete,
        "scope": "본인 개인 저장 보고 · 게시 여부와 별개", "date_basis": "원문 보고 시각(KST)", "llm_used": False}


def format_results(result: dict) -> str:
    condition = f"{result['start']} ~ {result['end']}" + (" · 미완료" if result["incomplete"] else "")
    if result["keyword"]:
        condition += " · " + safe_text(result["keyword"])
    lines = ["[내 확정 보고 조회]", condition]
    if not result["items"]:
        lines.extend(["", "조건에 맞는 확정 보고가 없어요. 아직 초안이면 먼저 '확정'해 주세요."])
    names = {"DONE": "완료", "IN_PROGRESS": "진행중", "NOT_STARTED": "예정", "DELAYED": "지연"}
    for n, row in enumerate(result["items"], 1):
        progress = "진행률 미기재" if row["progress"] is None else f"{row['progress']}%"
        progress_suffix = f" · {progress}" if row["status"] == "IN_PROGRESS" else ""
        lines.extend(["", f"{n}. {safe_text(row['task'])} — {names.get(row['status'], '확인 필요')}{progress_suffix}",
            f"   {safe_text(row['author'][:60])} · {row['reported_at'][:16].replace('T', ' ')} KST · 보고 #{row['report_id']}"])
        if row["next_action"]:
            lines.append("   다음: " + safe_text(row["next_action"][:100]))
        if row["issue"]:
            lines.append("   이슈: " + safe_text(row["issue"][:120]))
        lines.append(f"   [원문 보기]({row['source_url']}) · [수정·이력]({row['review_url']})")
    if result["has_more"]:
        lines.append(f"\n최신 {len(result['items'])}개 업무만 표시했어요. 날짜나 검색어를 더 붙여 주세요.")
    lines.append("\n출처: 본인이 확정한 보고 DB · AI 추측/과거 채팅 수집 없음")
    rendered = "\n".join(lines)
    # Stay below Rocket.Chat's default message size even after Markdown escaping.
    if len(rendered) > 4800 and len(result["items"]) > 1:
        return format_results({**result, "items": result["items"][:-1], "has_more": True})
    return rendered
