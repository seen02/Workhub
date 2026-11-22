from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Actor = Literal["demo-editor", "demo-observer"]
TaskId = Annotated[str, StringConstraints(pattern=r"^DEMO-[0-9]{3}$")]


class Status(StrEnum):
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(BaseModel):
    id: TaskId
    title: str
    status: Status
    version: int


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=500)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_id: TaskId
    status: Status
    summary: str = Field(min_length=1, max_length=500)


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal: Proposal | None


class Draft(Proposal):
    id: str
    source: Literal["explicit", "fixture", "ollama"]
    expected_version: int


class Publication(Proposal):
    draft_id: str
    channel: Literal["demo-reports"]
    document_version: int
    message: str
