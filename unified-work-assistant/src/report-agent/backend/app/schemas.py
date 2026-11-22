from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TaskStatus = Literal["NOT_STARTED", "IN_PROGRESS", "DONE", "DELAYED"]


class ParsedWorkReport(BaseModel):
    employee: str
    task: str
    start_time: str | None = None
    end_time: str | None = None
    duration_hours: float | None = Field(default=None, ge=0, le=24)
    status: TaskStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    issue: str | None = None
    next_action: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)

    @field_validator("issue", "next_action", mode="before")
    @classmethod
    def normalize_empty(cls, value):
        if isinstance(value, str) and value.strip().lower() in {"", "없음", "없습니다", "none", "null"}:
            return None
        return value


class ReportCreate(BaseModel):
    employee_id: int
    project_id: int
    raw_message: str = Field(min_length=5, max_length=4000)


class ReportConfirm(ReportCreate):
    parsed: ParsedWorkReport


class ParseResult(BaseModel):
    parsed: ParsedWorkReport
    provider: str
    fallback_used: bool
    elapsed_ms: int


class ReportResult(BaseModel):
    id: int
    parsed: ParsedWorkReport
    created_at: datetime


class ReportListItem(BaseModel):
    id: int
    employee_id: int
    employee: str
    project_id: int
    project: str
    task: str
    progress: int | None
    status: TaskStatus
    next_action: str | None
    created_at: datetime
    updated_at: datetime


class ReportRevisionResult(BaseModel):
    id: int
    changed_by: str
    before: dict
    after: dict
    reason: str
    created_at: datetime


class ReportDetail(ReportListItem):
    source_url: str | None = None
    review_url: str | None = None
    raw_message: str
    parsed: ParsedWorkReport
    duration_hours: float | None
    issue: str | None
    revisions: list[ReportRevisionResult]


class ReportUpdate(BaseModel):
    task: str = Field(min_length=1, max_length=180)
    status: TaskStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    duration_hours: float | None = Field(default=None, ge=0, le=24)
    issue: str | None = Field(default=None, max_length=1000)
    next_action: str | None = Field(default=None, max_length=240)
    edit_reason: str = Field(default="사용자 수정", min_length=2, max_length=240)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]


class SimpleRecord(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)
