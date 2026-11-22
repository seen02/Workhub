import httpx
import pytest

from evals.compare_models import DATA, EvaluationClient, score
import json


def test_comparison_labels_cover_ambiguous_progress():
    cases = json.loads(DATA.read_text(encoding='utf-8'))['cases']
    assert len(cases) == len({case['id'] for case in cases}) == 50
    assert len({case['category'] for case in cases}) == 10
    assert sum(case['expected']['progress'] is None for case in cases) >= 10


def test_score_does_not_reward_invented_progress_or_missing_issue():
    expected = {'progress': None, 'status': 'IN_PROGRESS', 'task_any': ['검토'],
                'issue_any': ['지연'], 'next_action_any': None}
    checks = score({'progress': 100, 'status': 'IN_PROGRESS', 'task': '문서 검토',
                    'issue': None, 'next_action': None}, expected)
    assert not checks['progress'] and not checks['issue']
    assert checks['task'] and checks['next_action']


@pytest.mark.anyio
async def test_gemma_transport_preserves_unicode_and_omits_think():
    async def handler(request):
        body = json.loads(request.content)
        assert body['messages'][0]['content'] == '업무보고'
        assert 'think' not in body
        assert int(request.headers['content-length']) == len(request.content)
        return httpx.Response(200, json={})
    async with EvaluationClient(transport=httpx.MockTransport(handler), base_url='http://test') as client:
        await client.post('/api/chat', json={'model':'gemma3:4b', 'think':False,
                                             'messages':[{'content':'업무보고'}]})
