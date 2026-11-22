from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    team: Mapped[str] = mapped_column(String(80))

    tasks: Mapped[list[Task]] = relationship(back_populates="employee")
    reports: Mapped[list[Report]] = relationship(back_populates="employee")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="IN_PROGRESS")
    expected_progress: Mapped[int] = mapped_column(Integer, default=0)

    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    project: Mapped[Project] = relationship(back_populates="tasks")
    employee: Mapped[Employee] = relationship(back_populates="tasks")
    reports: Mapped[list[Report]] = relationship(back_populates="task")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    raw_message: Mapped[str] = mapped_column(Text)
    structured_summary: Mapped[str] = mapped_column(Text)
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(240), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    employee: Mapped[Employee] = relationship(back_populates="reports")
    task: Mapped[Task] = relationship(back_populates="reports")
    revisions: Mapped[list[ReportRevision]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="ReportRevision.created_at.desc()"
    )


class ReportRevision(Base):
    __tablename__ = "report_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    changed_by: Mapped[str] = mapped_column(String(80))
    before_data: Mapped[str] = mapped_column(Text)
    after_data: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(240), default="사용자 수정")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    report: Mapped[Report] = relationship(back_populates="revisions")


class ChatDraft(Base):
    __tablename__ = "chat_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(100))
    message_id: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[str] = mapped_column(String(100), index=True)
    author_username: Mapped[str] = mapped_column(String(100))
    raw_message: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    model: Mapped[str] = mapped_column(String(100))
    ai_data: Mapped[str] = mapped_column(Text)
    current_data: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ChatDraftItem(Base):
    __tablename__ = "chat_draft_items"
    draft_id: Mapped[str] = mapped_column(ForeignKey("chat_drafts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), unique=True)


class ChatDraftRevision(Base):
    __tablename__ = "chat_draft_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("chat_drafts.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    before_data: Mapped[str] = mapped_column(Text)
    after_data: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ChatPublication(Base):
    __tablename__ = "chat_publications"
    draft_id: Mapped[str] = mapped_column(ForeignKey("chat_drafts.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[str] = mapped_column(String(100))
    message_id: Mapped[str] = mapped_column(String(100), unique=True)
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    actor_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
