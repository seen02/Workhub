import json
from pathlib import Path
import pytest
from app.logic import calculate_progress_from_text
from app.schemas import ParsedWorkReport
from app.services import normalize_parsed

CASES = json.loads((Path(__file__).parents[1]/'evals/comparison_50.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_frozen_50_progress_cases(case):
    assert calculate_progress_from_text(case['raw']) == case['expected']['progress']
    parsed = ParsedWorkReport(employee='평가직원', task='테스트', status='IN_PROGRESS', progress=99)
    result = normalize_parsed(parsed, case['raw'], '평가직원', '프로젝트')
    assert result.progress == case['expected']['progress']


@pytest.mark.parametrize('text,expected', [
    ('목표 80%입니다. 현재 35% 진행했습니다.',35),
    ('현재 35%입니다. 목표는 80%입니다.',35),
    ('2/3일에 개발했습니다.',None),
    ('업무 A 40%, 업무 B 50% 진행했습니다.',None),
    ('로그인 일부 완료했습니다.',None),
    ('진행 중입니다.',None),
    ('10개 항목 중 7개 완료했습니다.',70),
])
def test_additional_unseen_wording(text, expected):
    assert calculate_progress_from_text(text) == expected
