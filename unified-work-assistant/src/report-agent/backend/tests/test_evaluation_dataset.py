import json
from pathlib import Path

from app.logic import calculate_duration, calculate_progress_from_text, extract_time_range


CASES = json.loads((Path(__file__).parents[1] / "evals" / "work_reports.json").read_text(encoding="utf-8"))


def test_realistic_report_examples_meet_deterministic_quality_gate():
    for case in CASES:
        assert calculate_progress_from_text(case["raw"]) == case["progress"], case["raw"]
        start, end = extract_time_range(case["raw"])
        duration = calculate_duration(start, end) if start and end else None
        assert duration == case["duration_hours"], case["raw"]


def test_evaluation_dataset_has_enough_variety():
    assert len(CASES) >= 8
    assert len({case["progress"] for case in CASES}) >= 6
