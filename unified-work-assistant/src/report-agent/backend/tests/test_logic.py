import pytest
from pydantic import ValidationError

from app.logic import (
    aggregate_project_progress,
    calculate_duration,
    calculate_progress_from_text,
    extract_time_range,
    infer_task_from_text,
    is_delayed,
    normalize_next_action,
)
from app.schemas import ParsedWorkReport


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("공간질의 3개 중 2개를 완료했습니다", 67),
        ("점검 항목 7/10 완료", 70),
        ("현재 진행률은 82%입니다", 82),
        ("진행 중입니다", None),
    ],
)
def test_progress_calculation(text, expected):
    assert calculate_progress_from_text(text) == expected


def test_duration_calculation():
    assert calculate_duration("09:00", "13:30") == 4.5
    assert calculate_duration(None, "13:30") is None


def test_deterministic_time_task_and_next_action_normalization():
    text = "09:00~13:00 PostGIS 자료조사를 진행했습니다."
    assert extract_time_range(text) == ("09:00", "13:00")
    assert infer_task_from_text(text, "도로명 컨설팅") == "PostGIS 공간질의 자료조사"
    assert normalize_next_action("FastAPI 연동 예정") == "FastAPI 연동"


def test_schema_rejects_invalid_progress():
    with pytest.raises(ValidationError):
        ParsedWorkReport(employee="김진성", task="테스트", status="IN_PROGRESS", progress=130)


def test_delayed_rule_and_project_aggregate():
    assert is_delayed(40, 65, "IN_PROGRESS") is True
    assert is_delayed(80, 65, "IN_PROGRESS") is False
    assert aggregate_project_progress([40, 60, 80]) == 60
