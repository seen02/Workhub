from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..logic import calculate_progress_from_text
from ..models import ChatDraft, ChatDraftItem, ChatDraftRevision, ChatPublication, Employee, Project, Report, ReportRevision, Task
from .workspace import source_url, is_personal
from ..schemas import ParsedWorkReport
from .draft import ReportDraft
from .project_match import suggest_project


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task: str = Field(min_length=2, max_length=160)
    status: Literal["DONE", "IN_PROGRESS", "NOT_STARTED", "DELAYED", "UNKNOWN"]
    progress: int | None = Field(default=None, ge=0, le=100, strict=True)
    next_action: str | None = Field(default=None, max_length=240)
    issue: str | None = Field(default=None, max_length=1000)
    project: Literal["ai-assistant", "spatial-agent"] | None = None


class ReviewEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(ge=1)
    items: list[ReviewItem] = Field(min_length=1, max_length=8)
    reason: str = Field(min_length=2, max_length=240)


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def report_key(entity: ChatDraft, position: int) -> str:
    normalized = " ".join(entity.raw_message.lower().split())
    return hashlib.sha256(f"chat-report:{entity.author_id}:{entity.submitted_at.date()}:{normalized}:{position}".encode()).hexdigest()


def register_draft(db: Session, message: dict, raw: str, draft: ReportDraft, model: str, *, import_reason: str | None = None) -> ChatDraft:
    identity = f"local-rocketchat:{message['rid']}:{message['_id']}"
    draft_id = hashlib.sha256(identity.encode()).hexdigest()
    existing = db.get(ChatDraft, draft_id)
    if existing:
        return existing
    items = []
    for item in draft.items:
        has_number = re.search(r"\d+(?:\.\d+)?\s*(?:%|퍼센트)|\d+\s*개\s*중\s*\d+", item.evidence)
        progress = calculate_progress_from_text(item.evidence) if has_number else None
        project = suggest_project(raw, item.evidence) if is_personal(message["rid"]) else None
        items.append(ReviewItem(task=item.task, status=item.status, progress=progress, project=project).model_dump())
    source_time = datetime.fromisoformat(message["ts"].replace("Z", "+00:00"))
    entity = ChatDraft(
        id=draft_id, room_id=message["rid"], message_id=message["_id"],
        author_id=message["u"]["_id"], author_username=message["u"]["username"],
        raw_message=raw, submitted_at=source_time.astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None),
        model=model, ai_data=draft.model_dump_json(), current_data=encode(items),
        state="DRAFT", version=1,
    )
    db.add(entity)
    if import_reason:
        db.flush()
        db.add(ChatDraftRevision(draft_id=entity.id, actor_id=entity.author_id, version=1,
            action="IMPORT", before_data="[]", after_data=entity.current_data, reason=import_reason))
    db.commit()
    return entity


def owned_draft(db: Session, draft_id: str, user: dict) -> ChatDraft:
    entity = db.get(ChatDraft, draft_id)
    if not entity or entity.author_id != user["_id"] or entity.room_id != user["room_id"]:
        raise HTTPException(404, "본인의 테스트방 보고만 조회·수정할 수 있습니다.")
    return entity


def serialize(db: Session, entity: ChatDraft) -> dict:
    mappings = db.scalars(select(ChatDraftItem).where(ChatDraftItem.draft_id == entity.id).order_by(ChatDraftItem.position)).all()
    revisions = db.scalars(select(ChatDraftRevision).where(ChatDraftRevision.draft_id == entity.id).order_by(ChatDraftRevision.id.desc())).all()
    return {
        "id": entity.id, "version": entity.version, "state": entity.state,
        "author": entity.author_username, "submitted_at": entity.submitted_at.isoformat(),
        "source_url": source_url(entity.room_id, entity.message_id),
        "private_mode": is_personal(entity.room_id),
        "publications": [{"version": p.version, "state": p.state,
                          "url": source_url(p.room_id, p.message_id)} for p in db.scalars(
            select(ChatPublication).where(ChatPublication.draft_id == entity.id).order_by(ChatPublication.version.desc()))],
        "room_id": entity.room_id, "message_id": entity.message_id,
        "raw_message": entity.raw_message, "model": entity.model,
        "ai": json.loads(entity.ai_data), "items": json.loads(entity.current_data),
        "report_ids": [item.report_id for item in mappings],
        "revisions": [{"version": rev.version, "actor": rev.actor_id, "action": rev.action,
                       "reason": rev.reason, "created_at": rev.created_at.isoformat(),
                       "before": json.loads(rev.before_data), "after": json.loads(rev.after_data)} for rev in revisions],
    }


def save_review(db: Session, entity: ChatDraft, user: dict, payload: ReviewEdit, confirm: bool) -> ChatDraft:
    after = encode([item.model_dump() for item in payload.items])
    if confirm and entity.state == "CONFIRMED" and after == entity.current_data:
        return entity  # identical confirmation retry is idempotent
    if entity.version != payload.version:
        raise HTTPException(409, "다른 화면에서 수정되었습니다. 새로 불러온 뒤 다시 확인하세요.")
    if confirm and any(item.status == "UNKNOWN" for item in payload.items):
        raise HTTPException(422, "상태 확인 필요 업무의 실제 상태를 선택한 뒤 확정하세요.")
    if entity.state == "CONFIRMED" and not confirm:
        raise HTTPException(409, "이미 확정된 보고입니다. '수정 내용 확정'으로 저장하세요.")
    mappings = db.scalars(select(ChatDraftItem).where(ChatDraftItem.draft_id == entity.id).order_by(ChatDraftItem.position)).all()
    if mappings and len(mappings) != len(payload.items):
        raise HTTPException(422, "확정 후에는 업무 개수를 바꿀 수 없습니다. 새 보고를 작성하세요.")
    if confirm and not mappings and db.scalar(select(Report.id).where(Report.fingerprint.in_([report_key(entity, n) for n in range(len(payload.items))]))):
        raise HTTPException(409, "같은 작성자·날짜·원문으로 확정된 보고가 있습니다. 기존 확정 보고를 수정하세요.")
    previous = entity.current_data
    new_version = entity.version + 1
    new_state = "CONFIRMED" if confirm else "DRAFT"
    result = db.execute(update(ChatDraft).where(ChatDraft.id == entity.id, ChatDraft.version == payload.version).values(
        current_data=after, version=new_version, state=new_state, updated_at=datetime.now()
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "동시 수정 충돌입니다. 새로 불러와 주세요.")
    # This check follows the row write lock so a publication reservation cannot race an edit.
    if db.scalar(select(ChatPublication).where(ChatPublication.draft_id == entity.id, ChatPublication.state == "PENDING")):
        db.rollback()
        raise HTTPException(409, "게시 결과 확인 중입니다. 같은 버전의 게시를 재시도해 결과를 확인한 뒤 수정하세요.")
    db.add(ChatDraftRevision(draft_id=entity.id, actor_id=user["_id"], version=new_version,
        action="CONFIRM" if confirm else "EDIT", before_data=previous, after_data=after, reason=payload.reason))
    if confirm and not is_personal(entity.room_id):
        # Explicitly isolated test identity/project: never overwrite an existing employee's latest task.
        employee_name = f"RC 테스트 · {entity.author_username}"
        employee = db.scalar(select(Employee).where(Employee.name == employee_name))
        if not employee:
            employee = Employee(name=employee_name, team="로켓챗 개발 테스트")
            db.add(employee)
        project = db.scalar(select(Project).where(Project.name == "Rocket.Chat 테스트"))
        if not project:
            project = Project(name="Rocket.Chat 테스트", status="IN_PROGRESS", expected_progress=0)
            db.add(project)
        db.flush()
        for position, item in enumerate(payload.items):
            parsed = ParsedWorkReport(employee=employee.name, task=item.task, status=item.status,
                                      progress=item.progress, next_action=item.next_action, issue=item.issue)
            if mappings:
                report = db.get(Report, mappings[position].report_id)
                before_report = report.structured_summary
                db.add(ReportRevision(report_id=report.id, changed_by=entity.author_username,
                    before_data=before_report, after_data=parsed.model_dump_json(), reason=payload.reason))
                task = db.get(Task, report.task_id)
            else:
                task = Task(employee_id=employee.id, project_id=project.id, title=item.task,
                            status=item.status, progress=item.progress, expected_progress=0,
                            started_at=entity.submitted_at.date())
                db.add(task)
                db.flush()
                report = Report(employee_id=employee.id, task_id=task.id, raw_message=entity.raw_message,
                    structured_summary=parsed.model_dump_json(),
                    fingerprint=report_key(entity, position),
                    created_at=entity.submitted_at, updated_at=datetime.now())
                db.add(report)
                db.flush()
                db.add(ChatDraftItem(draft_id=entity.id, position=position, report_id=report.id))
                db.add(ReportRevision(report_id=report.id, changed_by=entity.author_username,
                    before_data=encode({"ai": json.loads(entity.ai_data), "source_message_id": entity.message_id}),
                    after_data=parsed.model_dump_json(), reason="로켓챗 초안 최초 확정: " + payload.reason[:200]))
            task.title, task.status, task.progress = item.task, item.status, item.progress
            report.structured_summary = parsed.model_dump_json()
            report.progress, report.next_action, report.issue = item.progress, item.next_action, item.issue
            report.updated_at = datetime.now()
    db.commit()
    db.refresh(entity)
    return entity
