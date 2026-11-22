"""Gemma-backed intent extraction for manager questions, with a safe local fallback."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..llm.local import LocalLLMError, LocalProvider
from .workspace import PROJECTS


class ManagerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "OVERVIEW", "EMPLOYEE_REPORTS", "PROJECT_REPORTS", "PROJECT_STATUS", "RISKS", "UNSUPPORTED"
    ]
    period: Literal["TODAY", "YESTERDAY", "SPECIFIC_DATE", "LATEST", "RECENT"] = "LATEST"
    target_date: date | None = None
    employee: str | None = Field(default=None, max_length=100)
    project: str | None = Field(default=None, max_length=100)


def _compact(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).lower()


def fallback_manager_query(question: str, today: date | None = None) -> ManagerQuery:
    """Keep common manager questions usable when Ollama is temporarily unavailable."""
    selected_day = today or date.today()
    normalized = _compact(question)
    period = "LATEST"
    target_date = None
    if "오늘" in normalized or "금일" in normalized:
        period, target_date = "TODAY", selected_day
    elif "어제" in normalized:
        period, target_date = "YESTERDAY", selected_day - timedelta(days=1)
    else:
        match = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", question)
        if match:
            try:
                target_date = date(*(int(value) for value in match.groups()))
                period = "SPECIFIC_DATE"
            except ValueError:
                target_date = None
        if any(word in normalized for word in ("관련", "전부", "모두", "다보여", "보고된거", "보고된것")):
            period = "RECENT"

    project = next((key for key, name in PROJECTS.items()
                    if _compact(name) in normalized
                    or (key == "ai-assistant" and "업무비서" in normalized)
                    or (key == "spatial-agent" and "공간정보" in normalized)), None)
    if any(word in normalized for word in ("리스크", "지연", "문제", "이슈")):
        intent = "RISKS"
    elif project and any(word in normalized for word in ("진행", "현황", "어디까지", "상태")):
        intent = "PROJECT_STATUS"
    elif project and any(word in normalized for word in ("보고", "보여", "목록", "다알려")):
        intent = "PROJECT_REPORTS"
    elif any(word in normalized for word in ("보고", "보여")) and any(
            title in normalized for title in ("사원", "직원", "대리", "과장", "차장", "팀장", "님")):
        intent = "EMPLOYEE_REPORTS"
    elif any(word in normalized for word in ("업무", "전체", "요약", "현황")):
        intent = "OVERVIEW"
    else:
        intent = "UNSUPPORTED"

    employee = None
    if intent == "EMPLOYEE_REPORTS":
        cleaned = re.sub(r"오늘자?|금일|어제|보고(?:를|서)?|전부|모두|다|좀|보여\s*줘|알려\s*줘", " ", question)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!\n\t")
        employee = cleaned or None
    return ManagerQuery(intent=intent, period=period, target_date=target_date,
                        employee=employee, project=project)


class ManagerQueryProvider(LocalProvider):
    async def parse_question(self, question: str, employees: list[str], today: date | None = None) -> ManagerQuery:
        if not 1 <= len(question) <= 500:
            raise ValueError("관리자 질문은 1~500자로 입력해 주세요.")
        selected_day = today or date.today()
        schema = ManagerQuery.model_json_schema()
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": 350},
            "messages": [
                {"role": "system", "content": (
                    "너는 관리자 업무보고 질문을 검색 조건으로 바꾸는 분류기다. 답변을 작성하지 말고 JSON만 반환한다. "
                    "질문 속 직원명과 프로젝트명은 새로 만들지 말고 보이는 표현을 그대로 사용한다. "
                    "'오늘 누구 사원 보고 보여줘'는 EMPLOYEE_REPORTS/TODAY, "
                    "'오늘 업무비서 프로젝트 보고 다 보여줘'는 PROJECT_REPORTS/TODAY, "
                    "'업무비서 프로젝트 진행사항 알려줘'는 PROJECT_STATUS/LATEST, "
                    "지연·문제·리스크 질문은 RISKS, 전체 요약은 OVERVIEW다. "
                    "날짜 없이 '관련 보고된 거', '다 보여줘', '전부', '모두'라고 하면 RECENT다. "
                    "그 밖에 날짜가 없으면 LATEST이며 SPECIFIC_DATE일 때만 target_date를 YYYY-MM-DD로 채운다. "
                    "업무보고와 무관한 질문은 UNSUPPORTED다."
                )},
                {"role": "user", "content": json.dumps({
                    "today": selected_day.isoformat(),
                    "known_employees": employees,
                    "known_projects": PROJECTS,
                    "question": question,
                }, ensure_ascii=False)},
            ],
        }
        if not self.model.startswith("gemma"):
            body["think"] = False
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = await self._post("/api/chat", body)
                result = ManagerQuery.model_validate_json(response.json()["message"]["content"])
                anchors = fallback_manager_query(question, selected_day)
                # Small local models can omit explicit names or dates. Re-anchor
                # fields that can be verified directly against the question.
                if anchors.period != "LATEST":
                    result.period, result.target_date = anchors.period, anchors.target_date
                elif result.period == "TODAY":
                    result.target_date = selected_day
                elif result.period == "YESTERDAY":
                    result.target_date = selected_day - timedelta(days=1)
                elif result.period == "LATEST":
                    result.target_date = None
                mentioned_employee = next((name for name in employees if _compact(name) in _compact(question)), None)
                if mentioned_employee:
                    result.employee = mentioned_employee
                elif result.intent == "EMPLOYEE_REPORTS" and not result.employee:
                    result.employee = anchors.employee
                if anchors.project:
                    result.project = anchors.project
                if result.intent == "UNSUPPORTED" and anchors.intent != "UNSUPPORTED":
                    result.intent = anchors.intent
                return result
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    await asyncio.sleep(0.25)
        raise LocalLLMError("Gemma가 관리자 질문의 조회 조건을 해석하지 못했습니다.") from last_error
