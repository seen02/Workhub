import asyncio,copy,json,unittest
from unittest.mock import AsyncMock,MagicMock,patch
from . import report_scope as scope,report_parser as parser,outline,criteria

RAW='시연 프로젝트에서 로그인 화면 만들기 끝냈어. 팁 협업 시연 프로젝트는 새로운 업무 기준 1 완료했고.'
PROJECTS=[{'id':'short','name':'시연'},{'id':'long','name':'팀 협업 시연'}]
TASKS=[{'id':'login','project_id':'short','title':'로그인','criteria':[{'id':'C-11111111','title':'화면 만들기'}]},
       {'id':'existing-new','project_id':'long','title':'새로운 업무','criteria':[{'id':'C-22222222','title':'기준 1'},{'id':'C-33333333','title':'기준 2'}]}]
def groups():
    return [{'project_id':p['id'],'task_id':t['id'],'title':t['title'],'evidence':sentence,
       'items':[{'title':t['criteria'][0]['title'],'criterion_id':t['criteria'][0]['id'],'state':'완료','evidence':sentence}]}
       for p,t,sentence in zip(PROJECTS,TASKS,RAW.split('. ') )]

class ScopeTests(unittest.TestCase):
    def test_typo_and_short_name_are_two_separate_projects(self):
        hits=scope.mentions(RAW,PROJECTS)
        self.assertEqual([h['id'] for h in hits],['short','long'])
        self.assertTrue(hits[1]['text'].startswith('팁 협업 시연'))
        self.assertEqual(scope.required_tasks(RAW,PROJECTS,TASKS),{'login','existing-new'})
    def test_long_name_does_not_also_mean_short_name(self):
        self.assertEqual([h['id'] for h in scope.mentions('팀 협업 시연 프로젝트의 새로운 업무 기준 1 완료',PROJECTS)],['long'])
    def test_close_typo_candidates_do_not_guess(self):
        ps=[{'id':'a','name':'팀 협업 시연'},{'id':'b','name':'탑 협업 시연'}]
        self.assertEqual(scope.mentions('팁 협업 시연 프로젝트의 업무 완료',ps),[])
    def test_omitted_project_rejected_and_complete_report_accepted(self):
        with self.assertRaisesRegex(ValueError,'프로젝트를 빠뜨렸'):
            scope.check_coverage(RAW,PROJECTS,TASKS,parser.Extract(groups=groups()[:1]))
        scope.check_coverage(RAW,PROJECTS,TASKS,parser.Extract(groups=groups()))
    def test_missing_named_task_in_same_project_rejected(self):
        raw='시연 프로젝트의 로그인 완료, 배포 완료'
        extra={'id':'deploy','project_id':'short','title':'배포','criteria':[]}
        with self.assertRaisesRegex(ValueError,'업무를 빠뜨렸'):
            scope.check_coverage(raw,PROJECTS,TASKS+[extra],parser.Extract(groups=groups()[:1]))
    def test_model_omission_is_retried_not_returned_as_success(self):
        replies=[]
        for values in [groups()[:1],groups()]:
            reply=MagicMock();reply.json.return_value={'message':{'content':json.dumps({'groups':values})}};replies.append(reply)
        provider=MagicMock(model='test');provider._post=AsyncMock(side_effect=replies)
        with patch.object(parser,'DraftProvider',return_value=provider):result=asyncio.run(parser.extract(RAW,PROJECTS,TASKS,{}))
        self.assertEqual(len(result.groups),2);self.assertEqual(provider._post.await_count,2)
        schema=provider._post.call_args.args[1]['format']['$defs']
        self.assertTrue({'project_id','task_id'}<=set(schema['Group']['required']))
        self.assertIn('criterion_id',schema['Item']['required'])
    def test_repeated_omission_blocks_partial_draft(self):
        reply=MagicMock();reply.json.return_value={'message':{'content':json.dumps({'groups':groups()[:1]})}}
        provider=MagicMock(model='test');provider._post=AsyncMock(return_value=reply)
        with patch.object(parser,'DraftProvider',return_value=provider):
            with self.assertRaises(ValueError):asyncio.run(parser.extract(RAW,PROJECTS,TASKS,{}))
    def test_plan_keeps_second_project_and_task_despite_exact_short_match(self):
        ts=[{**t,'collectionId':t['project_id'],'collectionName':PROJECTS[n]['name'],'text':''} for n,t in enumerate(TASKS)]
        extract=AsyncMock(side_effect=[parser.Extract(groups=[g]) for g in groups()])
        with patch.object(parser,'inventory',return_value=(PROJECTS,ts)),patch.object(parser,'extract',extract),patch.object(parser,'resolve_items'),patch.object(parser.search,'sync_registry'),patch.object(parser.search,'agent',return_value={'candidates':[],'mode':'keyword'}):
            result,_=parser.plan({},RAW)
        self.assertEqual([g['task_id'] for g in result],['login','existing-new'])
        self.assertEqual([[i['title'] for i in g['items']] for g in result],[['화면 만들기'],['기준 1']])
        self.assertEqual([g['kind'] for g in result],['update','update'])
    def test_unscoped_prefix_is_not_lost_by_splitting(self):
        raw='두 업무 모두 홍길동 담당입니다. '+RAW
        extract=AsyncMock(return_value=parser.Extract(groups=groups()))
        with patch.object(parser,'extract',extract):asyncio.run(parser.extract_scoped(raw,PROJECTS,TASKS,{}))
        self.assertEqual(extract.await_count,1)
        self.assertEqual(extract.call_args.args[0],raw)
    def test_comma_separated_projects_keep_each_others_criteria_out(self):
        raw=RAW.replace('. 팁',', 팁')
        extract=AsyncMock(side_effect=[parser.Extract(groups=[g]) for g in groups()])
        with patch.object(parser,'extract',extract):result=asyncio.run(parser.extract_scoped(raw,PROJECTS,TASKS,{}))
        self.assertEqual([g.task_id for g in result.groups],['login','existing-new'])
        self.assertEqual([[i.title for i in g.items] for g in result.groups],[['화면 만들기'],['기준 1']])
        self.assertTrue(all(g.evidence in raw for g in result.groups))
    def test_numbered_reference_uses_live_order_but_literal_name_wins(self):
        for live,title,expected in [
          ([{'id':'one','title':'화면 구현'},{'id':'two','title':'테스트'}],'기준 1','one'),
          ([{'id':'two','title':'기준 2'},{'id':'one','title':'기준 1'}],'기준 1','one')]:
            row={'task_id':'t','items':[{'title':title,'state':'완료'}],'evidence':'기준 1 완료'}
            with patch.object(outline,'document',return_value={'text':'same','revision':1,'updatedAt':'now','url':'/doc'}),patch.object(outline,'can_report'),patch.object(outline,'authorize_changes'),patch.object(criteria,'parse',return_value=live),patch.object(parser.assistant,'parse_criteria') as llm:
                parser.resolve_items({},row)
            self.assertEqual(row['items'][0]['id'],expected);llm.assert_not_called()
    def test_literal_guard_consumes_entire_report_and_preserves_states(self):
        task=TASKS[1]
        result=parser.literal_items_only('팁 협업 시연 프로젝트의 새로운 업무 기준 1도 완료했고, 기준 2는 진행 중.',PROJECTS,task)
        self.assertEqual([(i['title'],i['state']) for i in result],[('기준 1','완료'),('기준 2','진행 중')])
        for tail in ['기준 1 완료할 예정','기준 1 완료 안 했어','기준 1 완료했고 담당자는 김철수','기준 1 완료했고 문서도 수정 중','기준 1 완료했고 기준 1 진행 중']:
            self.assertIsNone(parser.literal_items_only('팀 협업 시연 프로젝트의 새로운 업무 '+tail,PROJECTS,task))
    def test_unmentioned_model_criterion_removed_only_for_fully_literal_report(self):
        raw='시연 프로젝트의 로그인 화면 만들기는 완료했고, '
        task=copy.deepcopy(TASKS[0]);task['criteria'].append({'id':'C-44444444','title':'오류 안내 확인'})
        g=groups()[0];g['evidence']=raw;g['items'][0]['evidence']=raw
        g['items'].append({'title':'오류 안내 확인','state':'진행 중','evidence':raw})
        reply=MagicMock();reply.json.return_value={'message':{'content':json.dumps({'groups':[g]})}}
        provider=MagicMock(model='test');provider._post=AsyncMock(return_value=reply)
        with patch.object(parser,'DraftProvider',return_value=provider):result=asyncio.run(parser.extract(raw,PROJECTS[:1],[task],{}))
        self.assertEqual([(i.title,i.state) for i in result.groups[0].items],[('화면 만들기','완료')])

    def demo_tasks(self):
        login=copy.deepcopy(TASKS[0]);login['criteria'].append({'id':'error','title':'오류 안내 확인'})
        deploy={'id':'deploy','project_id':'short','title':'배포 업무','criteria':[{'id':'file','title':'파일 만들기'},{'id':'install','title':'설치 확인'}]}
        unrelated={'id':'unrelated','project_id':'long','title':'일정 시연 로그인 오류 재검증','criteria':[{'id':'check','title':'재현 조건 확인'}]}
        return [login,deploy,unrelated]
    def test_real_short_and_full_task_names_have_only_reported_items(self):
        for raw in ['시연 프로젝트에서 로그인 화면 구현은 끝났고 배포 파일 만들기는 진행중이야.',
                    '시연 프로젝트에서 로그인 화면 구현은 끝났고 배포 업무에서 파일 만들기는 진행중이야.']:
            result=asyncio.run(parser.extract_scoped(raw,PROJECTS,self.demo_tasks(),{}))
            self.assertEqual([(g.project_id,g.task_id,[(i.title,i.state) for i in g.items]) for g in result.groups],
              [('short','login',[('화면 만들기','완료')]),('short','deploy',[('파일 만들기','진행 중')])])
            self.assertTrue(all(i.evidence in raw for g in result.groups for i in g.items))
    def test_short_task_name_is_protected_from_candidate_truncation(self):
        raw='시연 프로젝트에서 로그인 화면 구현은 끝났고 배포 파일 만들기는 진행중이야.'
        self.assertEqual(scope.required_tasks(raw,PROJECTS,self.demo_tasks()),{'login','deploy'})
        with self.assertRaisesRegex(ValueError,'배포 업무'):
            scope.check_coverage(raw,PROJECTS,self.demo_tasks(),parser.Extract(groups=groups()[:1]))
    def test_unknown_project_does_not_get_forced_into_first_project(self):
        raw='시연 프로젝트의 로그인 완료. 미등록 프로젝트의 배포 완료.'
        self.assertEqual(scope.project_clauses(raw,PROJECTS),[])
    def test_ambiguous_task_alias_is_not_auto_selected(self):
        tasks=self.demo_tasks()+[{'id':'other','project_id':'short','title':'배포','criteria':[]}]
        self.assertEqual(scope.task_mentions('배포 파일 만들기 진행 중',tasks),[])
    def test_extra_project_group_is_rejected(self):
        raw='시연 프로젝트 로그인 화면 만들기 완료.'
        with self.assertRaisesRegex(ValueError,'프로젝트 밖'):
            scope.check_coverage(raw,PROJECTS,TASKS,parser.Extract(groups=groups()))
    def test_literal_parser_does_not_discard_negation_future_or_conditions(self):
        task=self.demo_tasks()[0]
        for body in ['화면 구현 완료할 예정','화면 구현은 아직 못 끝냈어','화면 구현 완료했고 담당자는 김철수',
                     '화면 구현 완료했고 오류도 수정 중','화면 구현 완료했고 화면 구현 진행 중']:
            self.assertIsNone(parser.literal_task_items(body,task))
    def test_unknown_new_task_is_preserved_for_general_extraction(self):
        raw='시연 프로젝트 로그인 화면 만들기 완료했고 신규 알림 업무는 알림 만들기 진행 중'
        extract=AsyncMock(return_value=parser.Extract(groups=groups()[:1]))
        with patch.object(parser,'extract',extract):asyncio.run(parser.extract_scoped(raw,PROJECTS,self.demo_tasks(),{}))
        self.assertEqual(extract.call_args.args[0],raw)
        self.assertEqual([p['id'] for p in extract.call_args.args[1]],['short'])
    def test_task_fallback_rejects_unmentioned_criterion(self):
        task=self.demo_tasks()[0];raw='로그인 화면 구현 아직 못 끝냈어'
        g=groups()[0];g['items'].append({'title':'오류 안내 확인','criterion_id':'error','state':'진행 중','evidence':raw})
        for cid in ['error','']:
            g['items'][-1]['criterion_id']=cid
            with patch.object(parser,'extract',AsyncMock(return_value=parser.Extract(groups=[g]))):
                with self.assertRaisesRegex(ValueError,'오류 안내 확인'):
                    asyncio.run(parser.extract_task({'task':task,'text':raw,'body':' 화면 구현 아직 못 끝냈어'},PROJECTS[0],{}))

if __name__=='__main__':unittest.main()
