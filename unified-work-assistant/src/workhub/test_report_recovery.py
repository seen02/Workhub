import json,unittest
from unittest.mock import patch,AsyncMock,Mock
from fastapi import HTTPException
from . import assistant

class ReportRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_neighbour_state_cannot_override_explicit_not_started(self):
        items=[{'id':'a','title':'자료 수집'},{'id':'b','title':'보고서 작성'}]
        raw='자료 수집은 진행 중이고 보고서 작성은 아직 시작 안 했어.'
        wrong=[assistant.CriterionUpdate(id=i['id'],state='진행 중',evidence=raw) for i in items]
        with self.assertRaises(ValueError):assistant.validate_not_started(raw,items,wrong)
        wrong[1].state='예정';assistant.validate_not_started(raw,items,wrong)

    def test_past_not_started_with_new_progress_is_not_rejected(self):
        raw='보고서 작성은 어제 시작 안 했지만 지금은 진행 중이야.'
        assistant.validate_not_started(raw,[{'id':'b','title':'보고서 작성'}],[assistant.CriterionUpdate(id='b',state='진행 중',evidence=raw)])

    async def test_missing_named_item_is_corrected_even_with_one_transport_attempt(self):
        raw='요구사항 정리는 진행 중이고 사용자 안내 작성은 아직 시작 안 했어.'
        items=[{'id':'a','title':'요구사항 정리'},{'id':'b','title':'사용자 안내 작성'}]
        first={'updates':[{'id':'a','state':'진행 중','evidence':raw}]}
        second={'updates':first['updates']+[{'id':'b','state':'예정','evidence':'사용자 안내 작성은 아직 시작 안 했어.'}]}
        provider=Mock(model='test',retries=1)
        responses=[Mock(json=Mock(return_value={'message':{'content':json.dumps(v)}})) for v in [first,second]]
        provider._post=AsyncMock(side_effect=responses)
        with patch.object(assistant,'DraftProvider',return_value=provider):draft=await assistant.parse_criteria(raw,items)
        self.assertEqual([u.id for u in draft.updates],['a','b'])
        self.assertEqual(provider._post.await_count,2)
        self.assertIn('누락',provider._post.call_args.args[1]['messages'][-1]['content'])

    async def test_fabricated_evidence_remains_rejected_after_correction(self):
        result={'updates':[{'id':'a','state':'완료','evidence':'했다고 지어낸 말'}]}
        provider=Mock(model='test',retries=1)
        provider._post=AsyncMock(return_value=Mock(json=Mock(return_value={'message':{'content':json.dumps(result)}})))
        with patch.object(assistant,'DraftProvider',return_value=provider):
            with self.assertRaises(HTTPException):await assistant.parse_criteria('요구사항은 진행 중이야.',[{'id':'a','title':'요구사항'}])
        self.assertEqual(provider._post.await_count,2)
