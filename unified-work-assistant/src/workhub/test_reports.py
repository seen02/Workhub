import asyncio,copy,json,os,tempfile,unittest
from unittest.mock import patch,MagicMock
from fastapi import HTTPException
from . import reports as r,store,report_transport as transport,report_chat,report_parser,outline,permissions,criteria,domain,human_tasks

USER={'sub':'alice','email':'alice@example.com','admin':False}

def group(kind='create',title='배포 업무'):
    return {'kind':kind,'state':'PENDING','project_id':'p','project_name':'프로젝트','task_id':'d' if kind=='update' else '',
      'title':title,'evidence':'파일 끝났고 검증 진행 중','items':[{'title':'파일 작성','state':'완료','evidence':'파일 끝났고'},
      {'title':'설치 검증','state':'진행 중','evidence':'검증 진행 중'}],'issue':''}

class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patch(store,'DB',new=os.path.join(self.tmp.name,'db'));store.init()
        self.patch(permissions,'project',side_effect=lambda u,c:{'id':c,'name':c})
        self.patch(permissions,'require_create');self.patch(permissions,'validate_owners');self.patch(permissions,'document')
        self.patch(transport,'require_dm');self.patch(human_tasks,'label',return_value='홍길동 (alice@example.com)')
        self.report={'id':'report','version':1,'owner':'alice','author':USER['email'],'uid':'u','dm':'dm',
          'when':'2026-09-29T04:00:00+00:00','raw':'파일 끝났고 검증 진행 중','search_mode':'hybrid',
          'groups':[group()],'posting':{'state':'NOT_POSTED'},'destination':{'id':'room','name':'보고','kind':'채널'}}
        r.save(self.report)
    def patch(self,obj,name,**kw):
        p=patch.object(obj,name,**kw);value=p.start();self.addCleanup(p.stop);return value
    def test_layout_and_status(self):
        output=r.text(self.report)
        self.assertIn('**업무목록**\n\n- 배포 업무',output)
        self.assertIn('화요일 : 13시 00분',output)
        self.assertIn('1. 파일 작성(✅ 완료)',output);self.assertIn('2. 설치 검증(⏳ 진행 중)',output)
        self.assertNotIn('- 프로젝트',output)
        self.assertTrue(output.endswith('\n\n'+r.REPORT_SEPARATOR))
    def test_task_links_disambiguate_projects_and_omit_unresolved_targets(self):
        self.report['groups']=[{**group('update','자료 정리'),'task_id':'first','project_name':'홈페이지'},
          {**group('update','자료 정리'),'task_id':'second','project_name':'교육'},
          {**group(),'kind':'unresolved'}]
        output=r.text(self.report)
        self.assertIn(f'[자료 정리 (홈페이지)]({outline.PUBLIC}/doc/first)',output)
        self.assertIn(f'[자료 정리 (교육)]({outline.PUBLIC}/doc/second)',output)
        self.assertIn('- 배포 업무\n',output)
        self.assertEqual(output.count(r.REPORT_SEPARATOR),1)
    def test_new_task_link_is_reserved_without_creating_a_document(self):
        self.posting();api=self.patch(outline,'api')
        posted=r.publish(USER,'report',1)
        planned=posted['groups'][0]['planned_document_id']
        self.assertIn(f'[배포 업무]({outline.PUBLIC}/doc/{planned})',posted['posting']['payload'])
        self.assertNotIn('creation',posted['groups'][0]);api.assert_not_called()
    def test_uncertain_old_message_reuses_original_payload(self):
        send,messages=self.posting()
        old='이전 형식의 보고';mid='previous-message'
        self.report['posting']={'state':'UNKNOWN','message_id':mid,'payload':old};r.save(self.report)
        messages[mid]={'rid':'room','msg':old,'u':{'_id':'bot'}}
        recovered=r.publish(USER,'report',1)
        self.assertEqual(recovered['posting']['state'],'POSTED')
        self.assertEqual(recovered['posting']['payload'],old);send.assert_not_called()
    def test_combined_submit_posts_then_applies_once(self):
        calls=[]
        self.patch(r,'preflight')
        def post(*args):
            calls.append('post');v=r.get(USER,'report');v['posting']['state']='POSTED';return r.save(v)
        def apply(*args):calls.append('apply');return r.get(USER,'report')
        self.patch(r,'publish',side_effect=post);self.patch(r,'apply',side_effect=apply)
        r.submit(USER,'report',1);self.assertEqual(calls,['post','apply'])
    def test_combined_submit_preflight_failure_does_not_publish_or_apply(self):
        self.patch(r,'preflight',side_effect=HTTPException(409,'원문이 바뀌었습니다'))
        post=self.patch(r,'publish');apply=self.patch(r,'apply')
        result=r.submit(USER,'report',1)
        post.assert_not_called();apply.assert_not_called();self.assertEqual(result['groups'][0]['state'],'CONFLICT')
    def test_combined_unknown_post_does_not_apply(self):
        self.patch(r,'preflight');value=copy.deepcopy(self.report);value['posting']['state']='UNKNOWN'
        self.patch(r,'publish',return_value=value);apply=self.patch(r,'apply')
        self.assertEqual(r.submit(USER,'report',1)['posting']['state'],'UNKNOWN');apply.assert_not_called()
    def test_combined_retry_keeps_post_and_resumes_apply(self):
        self.report['posting']['state']='POSTED';r.save(self.report)
        preflight=self.patch(r,'preflight');self.patch(r,'publish',return_value=self.report)
        apply=self.patch(r,'apply',return_value=self.report)
        r.submit(USER,'report',1);preflight.assert_not_called();apply.assert_called_once()
    def test_explicit_report_time_not_due_date(self):
        base=self.report['when']
        self.assertEqual(r.report_time('마감일은 2026-10-01 09:00',base),base)
        self.assertIn('T09:05',r.report_time('[9월 28일 월요일 : 09시 05분] 보고',base))
        self.assertIn('2026-09-28T09:05',r.report_time('보고 시각: 2026-09-28 09:05',base))
    def test_legacy_progress_preserves_explicit_percent(self):
        g=group();g['items']=[g['items'][1]];g['evidence']='설치 검증 80% 진행 중'
        self.assertEqual(r.changes_for(g),{'status':'진행 중','progress':'80%'})
        g['items'][0]['id']='C-12345678'
        self.assertEqual(r.changes_for(g),{'criterion_states':{'C-12345678':'진행 중'}})
    def test_each_task_numbering_restarts_and_duplicate_names_disambiguate(self):
        self.report['groups'].append({**group(),'project_name':'다른 프로젝트'})
        output=r.text(self.report)
        self.assertEqual(output.count('1. 파일 작성'),2);self.assertIn('배포 업무 (다른 프로젝트)',output)
    def test_owner_and_old_version(self):
        with self.assertRaises(HTTPException):r.get({**USER,'sub':'bob'},'report')
        with self.assertRaises(HTTPException):r.get(USER,'report',2)
    def test_revoked_project_access_on_read(self):
        with patch.object(permissions,'project',side_effect=HTTPException(403)):
            with self.assertRaises(HTTPException):r.get(USER,'report')
    def test_draft_never_writes_and_same_request_reuses(self):
        plan=self.patch(report_parser,'plan',return_value=([group()],'hybrid'))
        api=self.patch(outline,'api')
        a=r.create(USER,'파일 끝났고 검증 진행 중','m','u','dm');b=r.create(USER,'다른 내용입니다','m','u','dm')
        self.assertEqual(a['id'],b['id']);self.assertEqual(plan.call_count,1);api.assert_not_called()
    def test_revise_invalidates_buttons_and_preserves_time(self):
        self.patch(report_parser,'plan',return_value=([group(title='새 제목')],'keyword'))
        new=r.revise(USER,'report',1,'수정할 보고 원문')
        self.assertEqual(new['version'],2);self.assertEqual(new['when'],self.report['when'])
        with self.assertRaises(HTTPException):r.get(USER,'report',1)
    def test_no_edit_after_posting_attempt(self):
        self.report['posting']['state']='UNKNOWN';r.save(self.report)
        with self.assertRaises(ValueError):r.revise(USER,'report',1,'다시 작성합니다')
    def test_unknown_creation_cannot_be_edited_into_new_create_request(self):
        self.report['groups'][0].update(state='FAILED',creation={'id':'reserved','attempted':True});r.save(self.report)
        with self.assertRaises(ValueError):r.revise(USER,'report',1,'다시 작성합니다')
        with self.assertRaises(ValueError):r.cancel(USER,'report',1)
    def test_new_document_human_format_registration_day_and_unknown_due(self):
        self.patch(store,'now',return_value='2026-09-30T03:00:00+00:00')
        content=r.new_text(USER,group(),self.report)
        self.assertIn('시작일: 2026-09-30',content);self.assertIn('마감일: 미정',content)
        self.assertIn('- [x] 파일 작성 — 담당자:',content);self.assertIn('상태: 진행 중',content)
        self.assertNotIn('C-',content);self.assertIn('보고 ID: report',content)
    def test_new_document_registration_date_uses_korean_midnight(self):
        clock=self.patch(store,'now',return_value='2026-09-30T14:59:59+00:00')
        self.assertIn('시작일: 2026-09-30',r.new_text(USER,group(),self.report))
        clock.return_value='2026-09-30T15:00:00+00:00'
        self.assertIn('시작일: 2026-10-01',r.new_text(USER,group(),self.report))
    def test_post_without_destination_is_blocked(self):
        self.report['destination']=None;r.save(self.report)
        with self.assertRaises(ValueError):r.publish(USER,'report',1)
    def posting(self,fail=False):
        self.patch(transport,'destination',return_value=self.report['destination']);messages={}
        self.patch(transport,'lookup',side_effect=lambda mid:messages.get(mid))
        def send(rid,text,mid,author=None):
            messages[mid]={'_id':mid,'rid':rid,'msg':text,'u':{'_id':'bot'}}
            if fail:raise TimeoutError()
        self.patch(transport,'client',return_value=MagicMock(bot_id='bot'))
        self.patch(transport,'link',return_value='http://chat/report')
        return self.patch(transport,'send',side_effect=send),messages
    def test_publish_only_once_and_no_outline_write(self):
        send,_=self.posting();api=self.patch(outline,'api')
        self.assertEqual(r.publish(USER,'report',1)['posting']['state'],'POSTED')
        r.publish(USER,'report',1);self.assertEqual(send.call_count,1);api.assert_not_called()
        self.assertEqual(r.get(USER,'report')['groups'][0]['state'],'PENDING')
    def test_post_lost_response_reconciles(self):
        send,_=self.posting(fail=True)
        self.assertEqual(r.publish(USER,'report',1)['posting']['state'],'POSTED');self.assertEqual(send.call_count,1)
    def test_unknown_post_never_blindly_retries(self):
        send,_=self.posting();send.side_effect=TimeoutError()
        self.assertEqual(r.publish(USER,'report',1)['posting']['state'],'UNKNOWN')
        r.publish(USER,'report',1);self.assertEqual(send.call_count,1)
    def test_destination_change_does_not_repoint_other_report(self):
        self.patch(transport,'destination',return_value={'id':'other','name':'다른 보고','kind':'토론방'})
        b=copy.deepcopy(self.report);b['id']='second';r.save(b)
        r.set_destination(USER,'report',1,'other')
        self.assertEqual(r.get(USER,'second')['destination']['id'],'room')
    def test_oversize_post_not_truncated(self):
        self.patch(transport,'destination',return_value=self.report['destination']);self.patch(r,'text',return_value='가'*9001)
        send=self.patch(transport,'send')
        with self.assertRaises(ValueError):r.publish(USER,'report',1)
        send.assert_not_called()
    def test_unresolved_preflight_blocks_all_writes(self):
        self.report['groups']=[group(),{**group(),'kind':'unresolved','issue':'선택하세요'}];r.save(self.report)
        self.patch(outline,'all_items',return_value=[]);create=self.patch(r,'apply_new')
        r.apply(USER,'report',1);create.assert_not_called()
    def test_explicit_skip_allows_other_group(self):
        self.report['groups'].append({**group(),'kind':'unresolved','state':'SKIPPED'});r.save(self.report)
        self.patch(outline,'all_items',return_value=[]);create=self.patch(r,'apply_new',return_value={'doc_id':'new'})
        result=r.apply(USER,'report',1);self.assertEqual(create.call_count,1);self.assertEqual(result['groups'][1]['state'],'SKIPPED')
    def test_partial_apply_retries_only_failed_group_and_never_posts(self):
        self.report['groups'].append(group(title='검수 업무'));r.save(self.report)
        self.patch(outline,'all_items',return_value=[]);send=self.patch(transport,'send')
        create=self.patch(r,'apply_new',side_effect=[{'doc_id':'one'},TimeoutError(),{'doc_id':'two'}])
        result=r.apply(USER,'report',1);self.assertEqual([g['state'] for g in result['groups']],['APPLIED','FAILED'])
        result=r.apply(USER,'report',1);self.assertEqual(create.call_count,3);self.assertTrue(all(g['state']=='APPLIED' for g in result['groups']));send.assert_not_called()
    def test_new_task_duplicate_detected_before_create(self):
        self.patch(outline,'all_items',return_value=[{'title':'배포 업무'}]);create=self.patch(r,'apply_new')
        self.assertEqual(r.apply(USER,'report',1)['groups'][0]['state'],'FAILED');create.assert_not_called()
    def test_new_creation_response_loss_recovers_same_document(self):
        clock=self.patch(store,'now',return_value='2026-09-30T14:59:59+00:00')
        self.patch(outline,'task_parent',return_value={'id':'parent'});docs={}
        def api(name,body,**kw):
            if name=='documents.info':return docs.get(body['id'])
            docs[body['id']]={**body,'url':'/doc/new','publishedAt':'now','revision':1,'updatedAt':'now'}
            raise TimeoutError()
        self.patch(outline,'api',side_effect=api);record=self.patch(outline,'record')
        result=r.apply_new(USER,self.report['groups'][0],self.report)
        self.assertIn(result['doc_id'],docs);self.assertEqual(record.call_count,1)
        self.assertIn('시작일: 2026-09-30',docs[result['doc_id']]['text'])
        clock.return_value='2026-10-01T03:00:00+00:00'
        saved=r.get(USER,'report');r.apply_new(USER,saved['groups'][0],saved)
        self.assertEqual(len(docs),1)
        self.assertIn('시작일: 2026-09-30',docs[result['doc_id']]['text'])
    def test_creation_uncertain_missing_document_not_recreated(self):
        g=group();g['creation']={'id':'new','text':'body','parent':'parent','attempted':True}
        api=self.patch(outline,'api',return_value=None)
        with self.assertRaises(ValueError):r.apply_new(USER,g,self.report)
        self.assertEqual(api.call_count,1)
    def test_dm_buttons_bound_to_owner_room_and_version(self):
        _,attachments=report_chat.view('alice:dm',self.report)
        command=attachments[0]['actions'][0]['msg']
        from . import chat_ui
        self.assertEqual(chat_ui.resolve('alice:dm',command)['version'],1)
        self.assertIsNone(chat_ui.resolve('bob:dm',command))
    def test_skip_does_not_remove_from_posted_report(self):
        result=r.choose(USER,'report',1,0,'skip')
        self.assertIn('배포 업무',r.text(result));self.assertEqual(result['groups'][0]['state'],'SKIPPED')

class DestinationTests(unittest.TestCase):
    def test_default_posting_and_muted_username(self):
        b=MagicMock();db=b.mongo.rocketchat
        db.users.find_one.return_value={'active':True,'roles':['user'],'username':'alice'}
        db.rocketchat_subscription.find_one.return_value={'roles':[]}
        db.rocketchat_permissions.find_one.return_value=None
        self.assertTrue(transport.permitted(b,'u',{'_id':'r','t':'c'}))
        self.assertFalse(transport.permitted(b,'u',{'_id':'r','t':'c','muted':['alice']}))

    def test_readonly_muted_and_missing_membership_denied(self):
        b=MagicMock();db=b.mongo.rocketchat
        db.users.find_one.return_value={'active':True,'roles':['user']}
        db.rocketchat_subscription.find_one.return_value={'roles':[]}
        db.rocketchat_permissions.find_one.side_effect=lambda q:{'roles':['user']} if q['_id']=='send-message' else {'roles':['admin']}
        self.assertTrue(transport.permitted(b,'u',{'_id':'r','t':'c'}))
        for extra in ({'ro':True},{'muted':['u']},{'archived':True},{'encrypted':True},{'broadcast':True}):
            self.assertFalse(transport.permitted(b,'u',{'_id':'r','t':'c',**extra}))
        db.rocketchat_subscription.find_one.return_value=None
        self.assertFalse(transport.permitted(b,'u',{'_id':'r','t':'p'}))

class ParserTests(unittest.TestCase):
    def setUp(self):
        self.task={'id':'task','title':'로그인 업무','collectionId':'p','collectionName':'프로젝트','text':'업무 설명',
          'criteria':[{'id':'C-11111111','title':'화면 구현'},{'id':'C-22222222','title':'오류 검수'}]}
        self.group={'project_id':'p','task_id':'task','title':'로그인 업무','evidence':'화면 끝났고 오류 검수 중',
          'items':[{'title':'화면 구현','state':'완료','evidence':'화면 끝났고'},{'title':'오류 검수','state':'진행 중','evidence':'오류 검수 중'}]}
    def plan(self,groups,tasks=None,rag_fail=False):
        from unittest.mock import AsyncMock
        with patch.object(report_parser,'inventory',return_value=([{'id':'p','name':'프로젝트'}],tasks if tasks is not None else [self.task])),\
             patch.object(report_parser,'extract',AsyncMock(return_value=report_parser.Extract(groups=groups))),\
             patch.object(report_parser,'resolve_items'),patch.object(report_parser.search,'sync_registry'),\
             patch.object(report_parser.search,'agent',**({'side_effect':TimeoutError()} if rag_fail else {'return_value':{'candidates':[{'id':'task','score':.9}],'mode':'hybrid'}})):
            return report_parser.plan(USER,'화면 끝났고 오류 검수 중')
    def test_existing_task_uses_live_id_and_criteria(self):
        groups,mode=self.plan([self.group]);self.assertEqual(groups[0]['task_id'],'task');self.assertEqual(mode,'hybrid')
    def test_criterion_id_resolves_alias_without_second_model_call(self):
        row=copy.deepcopy(self.group)
        row['items'][0].update(title='화면',criterion_id='C-11111111')
        row['items'][1].update(title='에러 문구',criterion_id='C-22222222')
        d={**self.task,'revision':1,'updatedAt':'now','url':'/doc/task'}
        with patch.object(outline,'document',return_value=d),patch.object(outline,'can_report'),patch.object(outline,'authorize_changes'),patch.object(criteria,'parse',return_value=self.task['criteria']),patch.object(report_parser.assistant,'parse_criteria') as fallback:
            report_parser.resolve_items(USER,row)
            fallback.assert_not_called()
        self.assertEqual([i['title'] for i in row['items']],['화면 구현','오류 검수'])
        self.assertEqual([i['state'] for i in row['items']],['완료','진행 중'])
    def test_draft_document_read_does_not_normalize_or_write(self):
        d={'id':'d','collectionId':'p','publishedAt':'now','text':'unchanged'}
        with patch.object(outline,'api',return_value=d) as api,patch.object(outline,'projects',return_value=[{'id':'p'}]),patch.object(permissions,'document'),patch.object(outline,'normalize') as normalize:
            self.assertEqual(outline.document('d',USER,normalize_fields=False),d)
        api.assert_called_once_with('documents.info',{'id':'d'});normalize.assert_not_called()
    def test_wrong_task_criterion_id_requires_clarification(self):
        row=copy.deepcopy(self.group);row['items'][0]['criterion_id']='C-deadbeef'
        with patch.object(outline,'document',return_value=self.task),patch.object(outline,'can_report'),patch.object(criteria,'parse',return_value=self.task['criteria']):
            report_parser.resolve_items(USER,row)
        self.assertEqual(row['kind'],'unresolved')
    def test_rag_failure_keeps_keyword_existing_match(self):
        groups,mode=self.plan([self.group],rag_fail=True);self.assertEqual(groups[0]['kind'],'update');self.assertIn('keyword',mode)
    def test_same_title_needs_user_choice(self):
        groups,_=self.plan([self.group],[self.task,{**self.task,'id':'duplicate'}]);self.assertEqual(groups[0]['kind'],'unresolved');self.assertEqual(len(groups[0]['candidates']),2)
    def test_model_invented_id_never_becomes_write_target(self):
        groups,_=self.plan([{**self.group,'task_id':'invented'}]);self.assertEqual(groups[0]['task_id'],'');self.assertEqual(groups[0]['kind'],'unresolved')
    def test_missing_task_id_recovers_only_exact_unique_title_and_criterion_ids(self):
        g=copy.deepcopy(self.group);g['task_id']=''
        for n,i in enumerate(g['items']):i['criterion_id']=self.task['criteria'][n]['id']
        groups,_=self.plan([g]);self.assertEqual(groups[0]['kind'],'update');self.assertEqual(groups[0]['task_id'],'task')
        g['items'][0]['criterion_id']=''
        groups,_=self.plan([g]);self.assertEqual(groups[0]['kind'],'update')
        g['items'][0]['title']='화면 요것'
        groups,_=self.plan([g]);self.assertEqual(groups[0]['kind'],'unresolved')
    def test_model_duplicate_task_evidence_is_retried_not_shown(self):
        from unittest.mock import AsyncMock
        g=copy.deepcopy(self.group);duplicate={**g,'task_id':''}
        replies=[MagicMock(),MagicMock()]
        replies[0].json.return_value={'message':{'content':json.dumps({'groups':[g,duplicate]})}}
        replies[1].json.return_value={'message':{'content':json.dumps({'groups':[g]})}}
        provider=MagicMock();provider.model='test';provider._post=AsyncMock(side_effect=replies)
        with patch.object(report_parser,'DraftProvider',return_value=provider):
            result=asyncio.run(report_parser.extract('화면 끝났고 오류 검수 중',[{'id':'p','name':'프로젝트'}],[self.task],{}))
        self.assertEqual(len(result.groups),1);self.assertEqual(provider._post.await_count,2)
    def test_model_missing_explicit_criterion_is_recovered_from_exact_source(self):
        from unittest.mock import AsyncMock
        raw='화면 구현 완료, 오류 검수 진행 중'
        complete={**self.group,'evidence':raw,'items':[{'title':'화면 구현','state':'완료','evidence':'화면 구현 완료','criterion_id':'C-11111111'},{'title':'오류 검수','state':'진행 중','evidence':'오류 검수 진행 중','criterion_id':'C-22222222'}]}
        incomplete={**complete,'items':complete['items'][1:]}
        replies=[MagicMock(),MagicMock()]
        for response,g in zip(replies,[incomplete,complete]):response.json.return_value={'message':{'content':json.dumps({'groups':[g]})}}
        provider=MagicMock();provider.model='test';provider._post=AsyncMock(side_effect=replies)
        with patch.object(report_parser,'DraftProvider',return_value=provider):
            result=asyncio.run(report_parser.extract(raw,[{'id':'p','name':'프로젝트'}],[self.task],{}))
        self.assertEqual(len(result.groups[0].items),2);self.assertEqual(provider._post.await_count,1)
        self.assertEqual([i.state for i in result.groups[0].items],['완료','진행 중'])
    def test_explicit_recovery_does_not_guess_negative_or_ambiguous_states(self):
        task={**self.task,'criteria':[{'id':'C-11111111','title':'화면 구현'}]}
        for raw in ('화면 구현은 아직 완료 안 했어','화면 구현은 진행 중인지 완료인지 모르겠어','화면 구현 담당자가 바뀌었어'):
            self.assertEqual(report_parser.explicit_items(raw,task,[task]),[])
        self.assertEqual(report_parser.explicit_items('화면 구현은 완료할 예정이야',task,[task])[0]['state'],'예정')
    def test_missing_task_only_created_after_live_inventory(self):
        groups,_=self.plan([{**self.group,'task_id':'','title':'새 배포 업무'}],[]);self.assertEqual(groups[0]['kind'],'create')
    def test_ambiguous_project_does_not_default_to_recent(self):
        from unittest.mock import AsyncMock
        with patch.object(report_parser,'inventory',return_value=([{'id':'p','name':'A'},{'id':'q','name':'B'}],[])),patch.object(report_parser,'extract',AsyncMock(return_value=report_parser.Extract(groups=[{**self.group,'project_id':'','task_id':''}]))):
            groups,_=report_parser.plan(USER,'화면 끝났고 오류 검수 중',{'project_id':'p'})
        self.assertEqual(groups[0]['kind'],'unresolved');self.assertEqual(groups[0]['project_id'],'')

if __name__=='__main__':unittest.main()
