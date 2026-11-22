import copy,os,tempfile,unittest
from unittest.mock import patch
from . import report_chat as ui,store,chat_ui

class ReportUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DB',os.path.join(self.tmp.name,'db'));p.start();self.addCleanup(p.stop);store.init()
        self.r={'id':'secret-id','version':1,'owner':'u','author':'private@example.com','uid':'uid','dm':'dm','when':'2026-09-29T06:00:00+00:00',
          'search_mode':'hybrid','posting':{'state':'NOT_POSTED'},'destination':None,'raw':'로그인 화면 끝났어',
          'groups':[{'title':'로그인','project_name':'시연','project_id':'p','task_id':'t','kind':'update','state':'PENDING','items':[{'title':'화면','state':'완료'}],'issue':''}]}
    def actions(self,attachments):return [a for x in attachments for a in x['actions']]
    def test_draft_exposes_edit_pick_and_cancel_beside_submit(self):
        body,rows=ui.view('u:dm',self.r)
        self.assertEqual([a['text'] for a in self.actions(rows)],['보고 및 반영','수정','업무 바꾸기','취소'])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['button_alignment'],'horizontal')
        for hidden in ('처리 정보','hybrid','private@example.com','미전송','미반영','연결 확인','시작일'):self.assertNotIn(hidden,body)
    def test_new_task_notice_is_visible_without_internal_fields(self):
        self.r['groups'][0]['kind']='create'
        body,_=ui.view('u:dm',self.r);self.assertIn('새로 만들 내 업무: **로그인**',body)
        self.assertNotIn('private@example.com',body)
    def test_technical_model_error_is_replaced_with_actionable_question(self):
        self.r['groups'][0].update(kind='unresolved',issue='상태 해석이 다릅니다. 초안을 수정하세요.')
        body,rows=ui.view('u:dm',self.r)
        self.assertNotIn('상태 해석',body);self.assertIn('어떤 항목을 끝냈고',body)
        self.assertEqual([a['text'] for a in self.actions(rows)],['내용 고치기','업무 고르기','업무 바꾸기','취소'])
    def test_posting_receipt_is_short_and_next_action_is_save(self):
        self.r.update(destination={'name':'demo'});self.r['posting']={'state':'POSTED','url':'http://chat/post'}
        body,rows=ui.view('u:dm',self.r,receipt=True)
        self.assertNotIn('[업무목록]',body);self.assertIn('demo에 보고했어요',body.replace('**',''))
        self.assertEqual([a['text'] for a in self.actions(rows)],['반영 다시 시도','보고 보기','새 보고','내 업무 다시 보기'])
    def test_completed_report_has_only_links_and_new_report(self):
        self.r.update(destination={'name':'demo'});self.r['posting']={'state':'POSTED','url':'http://chat/post'}
        self.r['groups'][0].update(state='APPLIED',result={'url':'http://outline/task'})
        body,rows=ui.view('u:dm',self.r)
        self.assertNotIn('[업무목록]',body);self.assertIn('업무 1건을 저장했어요',body)
        self.assertEqual([a['text'] for a in self.actions(rows)],['보고 보기','업무 보기','새 보고','내 업무 다시 보기'])
    def test_old_more_button_shows_full_report_with_direct_actions(self):
        choice={'kind':'report-v2','id':self.r['id'],'version':1,'op':'more'}
        with patch.object(ui.report_transport,'require_dm'),patch.object(ui.reports,'get',return_value=self.r):
            body,rows=ui.route({},'uid','dm','u:dm',{},'',choice)
        self.assertIn('**업무목록**',body)
        self.assertEqual([a['text'] for a in self.actions(rows)],['보고 및 반영','수정','업무 바꾸기','취소'])
        self.assertEqual([chat_ui.resolve('u:dm',a['msg'])['op'] for a in self.actions(rows)],['destinations','edit','pick','cancel'])
    def test_action_command_hides_ids_and_versions_but_old_binding_stays(self):
        old=ui.action('u:dm',self.r,'보고하기','publish');self.r['version']=2
        new=ui.action('u:dm',self.r,'보고하기','publish')
        self.assertEqual(old['text'],new['text']);self.assertNotIn('secret-id',old['msg'])
        self.assertEqual(chat_ui.resolve('u:dm',old['msg'])['version'],1)
        self.assertEqual(chat_ui.resolve('u:dm',new['msg'])['version'],2)
    def test_publish_without_destination_opens_picker_not_error_or_post(self):
        choice={'kind':'report-v2','id':self.r['id'],'version':1,'op':'publish'}
        with patch.object(ui.report_transport,'require_dm'),patch.object(ui.reports,'get',return_value=self.r),patch.object(ui.reports,'publish') as send,patch.object(ui.report_transport,'destinations',return_value=[{'id':'r','name':'demo'}]):
            body,rows=ui.route({},'uid','dm','u:dm',{},'button',choice)
        send.assert_not_called();self.assertIn('어디에 보고할까요',body);self.assertEqual(self.actions(rows)[0]['text'],'demo')
        self.assertEqual(self.actions(rows)[-1]['text'],'뒤로 가기')
    def test_saved_destination_still_requires_channel_selection_and_back_has_no_effect(self):
        self.r['destination']={'id':'old','name':'old'}
        with patch.object(ui.report_transport,'require_dm'),patch.object(ui.reports,'get',return_value=self.r),patch.object(ui.reports,'submit') as submit,patch.object(ui.report_transport,'destinations',return_value=[{'id':'r','name':'demo'}]):
            _,rows=ui.route({},'uid','dm','u:dm',{},'',{'kind':'report-v2','id':self.r['id'],'version':1,'op':'publish'})
            back=chat_ui.resolve('u:dm',self.actions(rows)[-1]['msg'])
            body,draft=ui.route({},'uid','dm','u:dm',{},'',back)
        submit.assert_not_called();self.assertIn('**업무목록**',body)
        self.assertEqual(self.actions(draft)[0]['text'],'보고 및 반영')
    def test_selecting_channel_runs_combined_submit_and_shows_final_receipt(self):
        completed=copy.deepcopy(self.r);completed['posting']={'state':'POSTED','url':'http://chat/post'}
        completed['destination']={'id':'r','name':'demo'};completed['version']=2
        completed['groups'][0].update(state='APPLIED',result={'url':'http://outline/task'})
        with patch.object(ui.report_transport,'require_dm'),patch.object(ui.reports,'get',return_value=self.r),patch.object(ui.reports,'submit',return_value=completed) as submit:
            body,rows=ui.route({},'uid','dm','u:dm',{},'',{'kind':'report-v2','id':self.r['id'],'version':1,'op':'submit_destination','target':'r'})
        submit.assert_called_once_with({},self.r['id'],1,'r')
        self.assertIn('업무 1건을 저장했어요',body)
        self.assertEqual([a['text'] for a in self.actions(rows)],['보고 보기','업무 보기','새 보고','내 업무 다시 보기'])
    def test_raw_api_error_not_shown_in_report_card(self):
        self.r['groups'][0].update(state='FAILED',error='documents.update HTTP 503 secret details')
        body,_=ui.view('u:dm',self.r);self.assertNotIn('documents.update',body);self.assertIn('저장하지 못했어요',body)
    def test_document_links_disambiguate_same_task_name_across_projects(self):
        self.r['groups'][0].update(project_name='바다',state='APPLIED',result={'url':'http://outline/sea'})
        other=copy.deepcopy(self.r['groups'][0]);other.update(project_name='하늘',project_id='p2',result={'url':'http://outline/sky'})
        self.r['groups'].append(other)
        with patch.object(ui.report_transport,'require_dm'),patch.object(ui.reports,'get',return_value=self.r):
            _,rows=ui.route({},'uid','dm','u:dm',{},'',{'kind':'report-v2','id':self.r['id'],'version':1,'op':'documents'})
        self.assertEqual([a['text'] for a in self.actions(rows)],['로그인 (바다)','로그인 (하늘)','돌아가기'])

if __name__=='__main__':unittest.main()
