"""A direct report must consume all text and keep live authorization checks."""
import copy
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from . import report_parser as parser, execution

PROJECTS=[{'id':'p','name':'시연'},{'id':'q','name':'팀 협업 시연'}]
TASKS=[{'id':'login','project_id':'p','title':'로그인','criteria':[
    {'id':'screen','title':'화면 만들기'},{'id':'error','title':'오류 안내 확인'}]},
    {'id':'deploy','project_id':'p','title':'배포 업무','criteria':[{'id':'file','title':'파일 만들기'}]},
    {'id':'new','project_id':'q','title':'새로운 업무','criteria':[{'id':'one','title':'기준 1'}]}]
SHORT='시연 프로젝트에서 로그인 화면 구현은 끝났고 배포 파일 만들기는 진행중이야.'
MULTI='시연 프로젝트에서 로그인 화면 만들기 끝냈어. 팁 협업 시연 프로젝트는 새로운 업무 기준 1 완료했고.'

def live_tasks():
    return [{**copy.deepcopy(t),'collectionId':t['project_id'],
             'collectionName':next(p['name'] for p in PROJECTS if p['id']==t['project_id']),'text':''} for t in TASKS]

class FastpathTests(unittest.TestCase):
    def test_multi_task_and_multi_project_keep_every_reported_state(self):
        for raw,expected in [(SHORT,[('login','screen','완료'),('deploy','file','진행 중')]),
                             (MULTI,[('login','screen','완료'),('new','one','완료')])]:
            result=parser.extract_literal(raw,PROJECTS,TASKS)
            self.assertEqual([(g.task_id,i.criterion_id,i.state) for g in result.groups for i in g.items],expected)
            self.assertTrue(all(g.evidence in raw and all(i.evidence in raw for i in g.items) for g in result.groups))
    def test_does_not_invent_unmentioned_criteria(self):
        result=parser.extract_literal('시연 프로젝트 로그인 화면 만들기 완료.',PROJECTS,TASKS)
        self.assertEqual([i.criterion_id for g in result.groups for i in g.items],['screen'])
    def test_unknown_task_or_project_requires_full_fallback(self):
        for raw in [SHORT+' 새로운 알림 업무 알림 만들기 완료.',
                    '시연 프로젝트 로그인 화면 만들기 완료. 미등록 프로젝트 업무 완료.',
                    '새로운 일도 끝냈어. '+SHORT]:
            self.assertIsNone(parser.extract_literal(raw,PROJECTS,TASKS),raw)
    def test_negation_future_conditions_and_unparsed_tail_fall_back(self):
        for tail in ['화면 만들기 아직 못 끝냈어','화면 만들기 완료할 예정',
                     '화면 만들기 완료했고 담당자는 김철수','화면 만들기 완료했고 오류도 수정 중',
                     '화면 만들기 완료인지 모르겠어','화면 만들기 완료했고 기준 추가해줘']:
            self.assertIsNone(parser.extract_literal('시연 프로젝트 로그인 '+tail,PROJECTS,TASKS),tail)
    def test_ambiguous_task_alias_and_project_name_fall_back(self):
        twins=TASKS+[dict(TASKS[1],id='deploy-twin',title='배포')]
        self.assertIsNone(parser.extract_literal(SHORT,PROJECTS,twins))
        ps=PROJECTS+[{'id':'other','name':'시연'}]
        self.assertIsNone(parser.extract_literal(SHORT,ps,TASKS))
    def test_duplicate_criterion_title_falls_back(self):
        tasks=copy.deepcopy(TASKS);tasks[0]['criteria'].append({'id':'duplicate','title':'화면 만들기'})
        self.assertIsNone(parser.extract_literal('시연 프로젝트 로그인 화면 만들기 완료.',PROJECTS,tasks))
    def test_clear_input_uses_no_retrieval_model_or_model_lock(self):
        lock=MagicMock();lock.acquire.side_effect=AssertionError('Model lock on a literal report')
        with patch.object(parser,'inventory',return_value=(PROJECTS,live_tasks())), \
             patch.object(parser,'resolve_items') as resolve,patch.object(parser.search,'agent') as rag, \
             patch.object(parser.search,'sync_registry') as sync,patch.object(parser,'extract_scoped',AsyncMock()) as ai, \
             patch.object(parser.assistant,'LLM_LOCK',lock):
            groups,mode=parser.plan({},SHORT)
        self.assertEqual(mode,'literal');self.assertEqual(len(groups),2)
        self.assertEqual(resolve.call_count,2);rag.assert_not_called();sync.assert_not_called();ai.assert_not_called()
    def test_mixed_literal_and_unknown_clause_keeps_existing_full_fallback(self):
        raw='시연 프로젝트 로그인 화면 만들기 완료했고 새 알림 업무 알림 만들기 진행 중'
        fallback=parser.Extract(groups=[parser.Group(project_id='p',task_id='login',title='로그인',evidence=raw,
                  items=[parser.Item(title='화면 만들기',criterion_id='screen',state='완료',evidence=raw)])])
        extract=AsyncMock(return_value=fallback)
        with patch.object(parser,'inventory',return_value=(PROJECTS,live_tasks())),patch.object(parser,'resolve_items'), \
             patch.object(parser.search,'sync_registry'),patch.object(parser.search,'agent',return_value={'mode':'hybrid','candidates':[]}) as rag, \
             patch.object(parser,'extract_scoped',extract):
            groups,mode=parser.plan({},raw)
        self.assertEqual(mode,'hybrid');rag.assert_called_once();extract.assert_awaited_once()
        self.assertEqual(extract.call_args.args[0],raw)
    def test_latest_criterion_ids_and_permissions_are_rechecked(self):
        raw='시연 프로젝트 로그인 화면 만들기 완료.'
        doc={'text':'new revision','revision':2,'updatedAt':'now','url':'/doc/login'}
        with patch.object(parser,'inventory',return_value=(PROJECTS,live_tasks())), \
             patch.object(parser.outline,'document',return_value=doc) as document,patch.object(parser.outline,'can_report'), \
             patch.object(parser.criteria,'parse',return_value=[{'id':'replacement','title':'화면 만들기'}]), \
             patch.object(parser.search,'agent') as rag:
            groups,mode=parser.plan({},raw)
        self.assertEqual(mode,'literal');self.assertEqual(groups[0]['kind'],'unresolved')
        document.assert_called_once_with('login',{},normalize_fields=False);rag.assert_not_called()
    def test_revoked_access_does_not_return_ready_report(self):
        with patch.object(parser,'inventory',return_value=(PROJECTS,live_tasks())), \
             patch.object(parser.outline,'document',side_effect=HTTPException(403,'권한 없음')):
            groups,_=parser.plan({},'시연 프로젝트 로그인 화면 만들기 완료.')
        self.assertEqual(groups[0]['kind'],'unresolved');self.assertIn('권한',groups[0]['issue'])
    def test_conflicting_repeated_task_states_remain_unresolved(self):
        raw='시연 프로젝트 로그인 화면 만들기 완료. 시연 프로젝트 로그인 화면 만들기 진행 중.'
        with patch.object(parser,'inventory',return_value=(PROJECTS,live_tasks())),patch.object(parser,'resolve_items'):
            groups,mode=parser.plan({},raw)
        self.assertEqual(mode,'literal');self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['kind'],'unresolved');self.assertIn('상태',groups[0]['issue'])
    def test_many_candidates_do_not_truncate_explicit_reported_tasks(self):
        tasks=live_tasks()+[dict(live_tasks()[0],id=f'other-{n}',title=f'기타 업무 {n}') for n in range(20)]
        with patch.object(parser,'inventory',return_value=(PROJECTS,tasks)),patch.object(parser,'resolve_items'),patch.object(parser.search,'agent') as rag:
            groups,mode=parser.plan({},MULTI)
        self.assertEqual([g['task_id'] for g in groups],['login','new']);rag.assert_not_called()

if __name__=='__main__':unittest.main()
