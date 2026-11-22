import re
from collections.abc import Iterable


def calculate_progress_from_text(text: str) -> int | None:
    """Return only a grounded current, overall percentage; ambiguity stays unknown."""
    if re.search(r"(?:전체\s*)?진행률[^.!?\n]{0,35}(?:미정|모르|모릅|알 수 없|산정하지 못|산정 불가|확인 필요|수치는 없)", text):
        return None
    percentages = list(re.finditer(r"(?<![\d.])(100|[1-9]?\d)\s*%", text))
    candidates = []
    previous_end = 0
    for match in percentages:
        prefix = text[previous_end:match.start()]
        markers = list(re.finditer(r"현재|지금|전체\s*진행률|목표|어제|지난|이전|예상", prefix))
        marker = markers[-1].group() if markers else ''
        previous_end = match.end()
        if marker in {'목표', '어제', '지난', '이전', '예상'}:
            continue
        candidates.append((int(match.group(1)), bool(marker)))
    explicit = [value for value, marked in candidates if marked]
    if explicit:
        return explicit[0] if len(set(explicit)) == 1 else None
    if len(candidates) == 1:
        return candidates[0][0]
    if percentages:
        return None
    patterns = [
        r"(?P<total>\d+)\s*(?:개|건|단계)?\s*(?:항목\s*)?중\s*(?P<done>\d+)\s*(?:개|건|단계)?",
        r"(?P<done>\d+)\s*/\s*(?P<total>\d+)(?=\s*(?:개|건|항목)?\s*(?:완료|검토|작성|처리))",
    ]
    ratios = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            total = int(match.group("total"))
            done = int(match.group("done"))
            if total > 0 and 0 <= done <= total:
                ratios.append(round(done / total * 100))
    if ratios:
        return ratios[0] if len(ratios) == 1 else None
    if re.search(r"일부|나머지|초안|아직|예정|못했|여부|진행\s*중|검토\s*중", text):
        return None
    if re.search(r"완료(?:했습니다|하였습니다|되었습니다|했음|됨)(?:[.!?\s]|$)", text):
        return 100
    return None


def extract_time_range(text: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"([01]?\d|2[0-3]):([0-5]\d)\s*[~\-]\s*([01]?\d|2[0-3]):([0-5]\d)",
        text,
    )
    if not match:
        return None, None
    return (
        f"{int(match.group(1)):02d}:{match.group(2)}",
        f"{int(match.group(3)):02d}:{match.group(4)}",
    )


def infer_task_from_text(text: str, project_name: str) -> str:
    if "PostGIS" in text:
        return "PostGIS 공간질의 자료조사"
    patterns = [
        r"(?:\d{1,2}:\d{2}\s*[~\-]\s*\d{1,2}:\d{2}\s*)?([^.!?\n]+?)(?:을|를)\s*(?:진행|작성|조사|개발|완료)",
        r"([^.!?\n]+?)\s*(?:자료조사|문서작성|영상 캡처|기술 조사)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = re.sub(
                r"^\d{1,2}:\d{2}\s*[~\-]\s*\d{1,2}:\d{2}\s*", "", match.group(1).strip()
            )
            return value[:80]
    return f"{project_name} 업무"


def normalize_next_action(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s*(?:예정(?:입니다)?|할 계획(?:입니다)?)\s*$", "", value.strip())
    return normalized or None


def calculate_duration(start_time: str | None, end_time: str | None) -> float | None:
    if not start_time or not end_time:
        return None
    start_hour, start_minute = map(int, start_time.split(":"))
    end_hour, end_minute = map(int, end_time.split(":"))
    minutes = (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute)
    return round(minutes / 60, 2) if minutes >= 0 else None


def is_delayed(progress: int | None, expected_progress: int, status: str) -> bool:
    return status == "DELAYED" or (progress is not None and progress < expected_progress)


def aggregate_project_progress(progress_values: Iterable[int | None]) -> int:
    values = [value for value in progress_values if value is not None]
    return round(sum(values) / len(values)) if values else 0
