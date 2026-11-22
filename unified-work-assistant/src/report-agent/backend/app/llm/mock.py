import re

from .base import LLMProvider
from ..logic import (
    calculate_duration,
    calculate_progress_from_text,
    extract_time_range,
    infer_task_from_text,
    normalize_next_action,
)
from ..schemas import ParsedWorkReport


class MockProvider(LLMProvider):
    async def parse_report(
        self, raw_message: str, employee_name: str, project_name: str
    ) -> ParsedWorkReport:
        start_time, end_time = extract_time_range(raw_message)
        progress = calculate_progress_from_text(raw_message)

        next_match = re.search(
            r"(?:오후에는?|이후에는?|다음(?:에는| 작업은)?|향후)\s*([^.!?\n]+?)(?:\s*(?:예정|진행|할 계획|하겠습니다))?(?:입니다|입니다\.|[.!?\n]|$)",
            raw_message,
        )
        next_action = next_match.group(1).strip() if next_match else None
        next_action = normalize_next_action(next_action)

        issue = None
        if not re.search(r"(?:이슈|문제|특이사항)(?:는|이)?\s*(?:없|없습니다)", raw_message):
            issue_match = re.search(r"(?:이슈|문제|특이사항)(?:는|이|:)?\s*([^.!?\n]+)", raw_message)
            if issue_match:
                issue = issue_match.group(1).strip()
            elif any(word in raw_message for word in ("지연", "재작업", "오류", "막힘")):
                issue = next((sentence.strip() for sentence in re.split(r"[.!?\n]", raw_message) if any(word in sentence for word in ("지연", "재작업", "오류", "막힘"))), None)

        status = "IN_PROGRESS"
        if issue and "지연" in raw_message:
            status = "DELAYED"
        elif progress == 100 or re.search(r"(?:완료했습니다|완료함|작업 완료)", raw_message):
            status = "DONE"

        task = infer_task_from_text(raw_message, project_name)
        return ParsedWorkReport(
            employee=employee_name,
            task=task,
            start_time=start_time,
            end_time=end_time,
            duration_hours=calculate_duration(start_time, end_time),
            status=status,
            progress=progress,
            issue=issue,
            next_action=next_action,
            confidence=0.96 if progress is not None else 0.78,
        )

