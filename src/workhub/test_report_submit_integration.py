"""Real submit/proposal/ACL/format logic, isolated SQLite and HTTP boundary only."""
import copy
import json
import tempfile
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from . import store, outline, reports, criteria, report_transport, lifecycle

USER={'sub':'alice','email':'alice@example.com','admin':False}


class SubmitIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.mock(store,'DB',temp.name+'/test.db');store.init()
        self.mock(store,'now',lambda:'2026-09-30T00:00:00+00:00')
        self.mock(lifecycle,'enabled',lambda:False)
        self.mock(outline,'PROJECTS_CACHE',{'until':0,'available':{}})
        self.cols=[{'id':p,'name':p,'permission':'read_write'} for p in ('p','q')]
        store.put('projects',copy.deepcopy(self.cols))
        self.docs={};self.messages={};self.writes=Counter();self.revoked=False
        self.after_post=lambda:None;self.after_write=lambda doc:None
        for p in ('p','q'):
            self.docs['parent-'+p]={'id':'parent-'+p,'collectionId':p,'title':'업무 목록','text':'','publishedAt':'now','revision':1,'updatedAt':'before','url':'/doc/parent-'+p}
            store.put('task-parent:'+p,{'id':'parent-'+p,'ready':True})
        self.groups=[]
        for did,p,title,criterion,state in [('login','p','로그인','화면 만들기','완료'),('deploy','q','배포 업무','파일 만들기','진행 중')]:
            text=f'담당자: Alice (alice@example.com)\n\n시작일: 미정\n\n마감일: 미정\n\n상태: 미착수\n\n## 업무 내용\n\n{title}\n\n## 완료 기준\n\n- [ ] {criterion} — 담당자: Alice (alice@example.com)\n\n## 진행 기록\n\n## 결과물 및 참고 자료'
            self.docs[did]={'id':did,'collectionId':p,'title':title,'parentDocumentId':'parent-'+p,'text':text,'publishedAt':'now','revision':1,'updatedAt':'before','url':'/doc/'+did}
            self.groups.append({'kind':'update','state':'PENDING','task_id':did,'project_id':p,'project_name':p,'title':title,
                'before':text,'revision':1,'updatedAt':'before','evidence':criterion+' '+state,'items':[{'title':criterion,'state':state}]})
        fixture=self
        def send(client,request,*a,**kw):return fixture.http(request)
        self.mock(httpx.Client,'send',send)
        for g in self.groups:g['items'][0]['id']=criteria.parse(g['before'])[0]['id']
        self.mock(report_transport,'require_dm',lambda *args:None)
        self.mock(report_transport,'destination',lambda *args:{'id':'room','name':'demo','kind':'채널'})
        self.mock(report_transport,'client',lambda:SimpleNamespace(bot_id='bot'))
        self.mock(report_transport,'lookup',lambda mid:self.messages.get(mid))
        self.mock(report_transport,'link',lambda rid,mid:'http://chat/channel/demo?msg='+mid)
        def post(rid,text,mid,author=None):
            self.messages[mid]={'_id':mid,'rid':rid,'msg':text,'u':{'_id':'bot'}}
            self.after_post()
        self.mock(report_transport,'send',post)
        reports.save({'id':'report','version':1,'owner':'alice','author':USER['email'],'uid':'u','dm':'dm',
            'when':store.now(),'raw':'여러 업무 보고','groups':self.groups,'posting':{'state':'NOT_POSTED'},'destination':None})

    def mock(self,obj,name,value):
        p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def http(self,request):
        method=request.url.path.rsplit('/',1)[-1]
        body=json.loads(request.content or b'{}')
        if method=='users.list':data=[{'id':'alice','email':USER['email'],'name':'Alice','role':'member','isSuspended':self.revoked}]
        elif method=='collections.list':data=self.cols
        elif method=='documents.info':
            data=self.docs.get(body['id'])
            if data is None:return httpx.Response(404,request=request)
        elif method=='documents.list':data=[d for d in self.docs.values() if d['collectionId']==body['collectionId']]
        elif method=='documents.update':
            d=self.docs[body['id']]
            if body['lastRevision']!=d['revision']:return httpx.Response(409,request=request)
            d.update(text=body['text'],revision=d['revision']+1,updatedAt='after')
            self.writes[d['id']]+=1;data=d;self.after_write(d)
        elif method=='documents.create':
            self.assertNotIn(body['id'],self.docs)
            data={**body,'publishedAt':'now','revision':1,'updatedAt':'after','url':'/doc/'+body['id']}
            self.docs[data['id']]=data;self.writes[data['id']]+=1
        else:raise AssertionError('Unexpected external request: '+method)
        return httpx.Response(200,json={'data':copy.deepcopy(data)},request=request)

    def test_multi_project_update_and_new_task_submit_then_duplicate(self):
        r=reports.get(USER,'report')
        r['groups'].append({'kind':'create','state':'PENDING','task_id':'','project_id':'p','project_name':'p','title':'검수 업무',
            'evidence':'PC 확인 완료','items':[{'title':'PC 확인','state':'완료'}]})
        reports.save(r)
        result=reports.submit(USER,'report',1,'room')
        self.assertEqual(result['posting']['state'],'POSTED')
        self.assertEqual([g['state'] for g in result['groups']],['APPLIED']*3,result)
        for g in result['groups']:
            did=g['task_id'] or g['result']['doc_id']
            self.assertEqual(criteria.parse(self.docs[did]['text'])[0]['state'],g['items'][0]['state'])
            self.assertIn('보고 ID: report',self.docs[did]['text'])
            self.assertIn('시작일: '+('2026-09-30' if g['kind']=='create' else '미정'),self.docs[did]['text'])
            self.assertIn('마감일: 미정',self.docs[did]['text'])
        expected=reports.text(result)
        self.assertEqual(next(iter(self.messages.values()))['msg'],expected)
        for g in result['groups']:
            did=g['task_id'] or g['result']['doc_id']
            self.assertIn(f']({outline.PUBLIC}/doc/{did})',expected)
            if g['kind']=='create':self.assertEqual(g['planned_document_id'],did)
        self.assertTrue(expected.endswith(reports.REPORT_SEPARATOR))
        self.assertIn('1. 화면 만들기(✅ 완료)',expected)
        self.assertIn('1. 파일 만들기(⏳ 진행 중)',expected)
        reports.submit(USER,'report',result['version'])
        self.assertEqual(len(self.messages),1)
        self.assertEqual(sorted(self.writes.values()),[1,1,1])

    def test_rocket_chat_report_preserves_manual_status_and_updates_own_criterion(self):
        d=self.docs['login']
        d['text']=outline.apply_changes(d['text'],{'kanban_status':'보류'})
        report=reports.get(USER,'report');report['groups']=report['groups'][:1]
        report['groups'][0]['before']=d['text'];reports.save(report)
        result=reports.submit(USER,'report',1,'room')
        self.assertEqual(result['groups'][0]['state'],'APPLIED',result)
        self.assertEqual(result['groups'][0]['result']['result']['status'],'보류')
        self.assertEqual(result['groups'][0]['result']['result']['progress'],'100%')
    def test_report_after_removed_kanban_label_uses_document_status(self):
        from . import task_status, domain
        d=self.docs['login']
        d['text']=outline.apply_changes(d['text'],{'kanban_status':'보류'})
        task_status.remember(d['id'],d['text'],kanban=True)
        d['text']=d['text'].replace('상태 관리: 칸반','')
        report=reports.get(USER,'report');report['groups']=report['groups'][:1]
        report['groups'][0]['before']=d['text'];reports.save(report)
        result=reports.submit(USER,'report',1,'room')
        self.assertEqual(result['groups'][0]['state'],'APPLIED',result)
        self.assertEqual(domain.parse(d['text'])['status'],'보류')
        self.assertEqual(domain.parse(d['text'])['progress'],'100%')
        self.assertEqual(len(self.messages),1)
        self.assertIn('상태: 보류',self.docs['login']['text'])
        self.assertTrue(all(i['state']=='완료' for i in criteria.parse(self.docs['login']['text'])))
        self.assertIn('화면 만들기(✅ 완료)',next(iter(self.messages.values()))['msg'])
        self.assertIn('보고 ID: report',self.docs['login']['text'])

    def test_permission_revoked_after_post_prevents_all_document_writes(self):
        self.after_post=lambda:setattr(self,'revoked',True)
        try:result=reports.submit(USER,'report',1,'room')
        except Exception:result=store.get('report-v2:report')
        self.assertEqual(result['posting']['state'],'POSTED')
        self.assertEqual(len(self.messages),1);self.assertFalse(self.writes)

    def test_concurrent_second_document_edit_is_not_overwritten(self):
        def edit(d):
            if d['id']=='login':self.docs['deploy'].update(text=self.docs['deploy']['text']+'\n외부 수정',revision=2)
        self.after_write=edit
        result=reports.submit(USER,'report',1,'room')
        self.assertEqual([g['state'] for g in result['groups']],['APPLIED','FAILED'])
        self.assertEqual(self.writes,{'login':1})
        self.assertTrue(self.docs['deploy']['text'].endswith('외부 수정'))

    def test_committed_write_response_lost_is_reconciled_without_duplicate(self):
        def lost(d):raise httpx.ReadTimeout('response lost after commit')
        self.after_write=lost
        result=reports.submit(USER,'report',1,'room')
        self.assertEqual([g['state'] for g in result['groups']],['APPLIED','APPLIED'],result)
        reports.submit(USER,'report',result['version'])
        self.assertEqual(self.writes,{'login':1,'deploy':1});self.assertEqual(len(self.messages),1)
