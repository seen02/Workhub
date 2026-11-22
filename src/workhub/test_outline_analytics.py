"""Statistics bridge isolation, parity, authentication and refresh concurrency."""
import hashlib, hmac, json, os, threading, time, unittest, uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
from . import analytics_service, outline, outline_bridge, store
from .main import app
from .test_analytics import task, item

CID='11111111-1111-4111-8111-111111111111'
USER={'sub':'employee','email':'a@example.com','name':'직원','admin':False}
PROJECTS=[{'id':CID,'name':'허용 프로젝트','manager':'a@example.com'}]

class OutlineAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'OUTLINE_ANALYTICS_ENABLED':'true','OUTLINE_WORKHUB_BRIDGE_SECRET':'test-only'})
        self.env.start();self.addCleanup(self.env.stop)
        self.actor=patch.object(outline_bridge,'actor',return_value=USER);self.actor.start();self.addCleanup(self.actor.stop)
        self.projects=patch('workhub.analytics_service.permissions.projects',return_value=PROJECTS);self.projects.start();self.addCleanup(self.projects.stop)
        tasks_patch=patch.object(outline,'tasks',return_value=[task('a',CID,criteria=[item('a@example.com')])]);self.tasks=tasks_patch.start();self.addCleanup(tasks_patch.stop)
        self.names=patch('workhub.analytics_service.directory.names',return_value={'a@example.com':'직원'});self.names.start();self.addCleanup(self.names.stop)
        self.client=TestClient(app)

    def post(self,action='query',body=None,signature=True):
        payload={'actor':{'outlineUserId':'outline-user','outlineTeamId':'team'},'managed':False,**(body or {})}
        raw=json.dumps(payload,separators=(',',':')).encode();path='/internal/outline-analytics/'+action
        stamp=str(int(time.time()));nonce=str(uuid.uuid4())
        message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
        sig=hmac.new(b'test-only',message.encode(),hashlib.sha256).hexdigest()
        headers={'Content-Type':'application/json','X-Workhub-Time':stamp,'X-Workhub-Nonce':nonce,'X-Workhub-Signature':sig if signature else 'wrong'}
        return self.client.post(path,content=raw,headers=headers),headers,raw

    def test_signed_query_matches_common_service(self):
        response,_,_=self.post()
        self.assertEqual(response.status_code,200)
        value=response.json();expected=analytics_service.query(USER)
        for key in ('summary','projects','owners','actions','calendar_actions','completed_tasks','schedule'):
            self.assertEqual(value[key],expected[key],key)
        self.assertEqual(value['viewer']['email'],USER['email'])
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_invalid_signature_and_nonce_replay(self):
        self.assertEqual(self.post(signature=False)[0].status_code,401)
        response,headers,raw=self.post()
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/internal/outline-analytics/query',content=raw,headers=headers).status_code,401)

    def test_analytics_flag_is_independent(self):
        with patch.dict(os.environ,{'OUTLINE_PROJECT_MANAGEMENT_ENABLED':'false','OUTLINE_AI_SEARCH_ENABLED':'false'}):
            self.assertEqual(self.post()[0].status_code,200)
        with patch.dict(os.environ,{'OUTLINE_ANALYTICS_ENABLED':'false'}):
            self.assertEqual(self.post()[0].status_code,404)

    def test_browser_identity_extra_fields_rejected(self):
        self.assertEqual(self.post(body={'admin':True})[0].status_code,422)
        self.assertEqual(self.post(body={'actor':{'outlineUserId':'x','outlineTeamId':'t','admin':True}})[0].status_code,422)

    def test_worker_cannot_request_managed_and_actor_failure_is_propagated(self):
        self.assertEqual(self.post(body={'managed':True})[0].status_code,403)
        with patch.object(outline_bridge,'actor',side_effect=HTTPException(403,'자격 없음')):
            self.assertEqual(self.post()[0].status_code,403)

    def test_invalid_period_and_unknown_owner(self):
        self.assertEqual(self.post(body={'horizon':14})[0].status_code,422)
        self.assertEqual(self.post(body={'owner':'other@example.com'})[0].status_code,403)
        self.assertEqual(self.post(body={'collectionId':'bad-id'})[0].status_code,422)

    def test_inaccessible_projects_and_labels_not_in_response(self):
        self.tasks.return_value=[task('a',CID,owner=USER['email']),task('hidden','forbidden',owner='hidden@example.com')]
        data=self.post()[0].json()
        self.assertEqual(data['summary']['total'],1)
        self.assertNotIn('hidden@example.com',data['names'])
        self.assertEqual([t['id'] for t in data['actions']],['a'])

    def test_selected_project_denied_before_refresh(self):
        with patch('workhub.analytics_service.permissions.project',side_effect=HTTPException(403,'거부')),patch.object(outline,'sync_shared') as sync:
            self.assertEqual(self.post('refresh',{'collectionId':CID})[0].status_code,403)
            sync.assert_not_called()

    def test_refresh_and_capabilities(self):
        with patch.object(outline,'sync_shared') as sync:
            self.assertEqual(self.post('refresh')[0].status_code,200);sync.assert_called_once()
        data=self.post('capabilities')[0].json()
        self.assertEqual(data['linked_ids'],[CID]);self.assertEqual(data['default_scope'],'all')

    def test_worker_cannot_bypass_personal_scope_by_omitting_owner_or_refreshing(self):
        self.tasks.return_value=[task('mine',CID,owner=USER['email']),
            task('shared',CID,criteria=[item(USER['email']),item('other@example.com','완료')]),
            task('other',CID,owner='other@example.com')]
        for owner in ('',USER['email'].upper()):
            data=self.post(body={'owner':owner})[0].json()
            self.assertEqual(data['owner'],USER['email'])
            self.assertEqual({t['id'] for t in data['actions']},{'mine','shared'})
            self.assertEqual({p['email'] for p in data['owners']},{USER['email']})
            self.assertEqual([p['email'] for p in data['owner_options']],[USER['email']])
            self.assertTrue(all(i['owner']==USER['email'] for t in data['actions'] for i in t['criteria']))
        with patch.object(outline,'sync_shared') as sync:
            self.assertEqual(self.post('refresh',{'owner':'other@example.com'})[0].status_code,403)
            sync.assert_not_called()

    def test_admin_can_compare_other_owners_within_readable_projects(self):
        self.tasks.return_value=[task('other',CID,owner='other@example.com')]
        with patch.object(outline_bridge,'actor',return_value={**USER,'admin':True}),patch('workhub.analytics_service.permissions.assignees',return_value=[{'email':'other@example.com','name':'동료'}]):
            data=self.post(body={'owner':'other@example.com'})[0].json()
            self.assertEqual(data['owner'],'other@example.com')
            self.assertEqual(data['summary']['total'],1)

    def test_admin_overview_is_independent_of_owner_and_excludes_inaccessible_tasks(self):
        self.tasks.return_value=[task('mine',CID,owner=USER['email'],progress='0%'),
            task('other',CID,owner='other@example.com',progress='100%'),
            task('hidden','forbidden',owner=USER['email'],progress='100%')]
        with patch.object(outline_bridge,'actor',return_value={**USER,'admin':True}),patch('workhub.analytics_service.permissions.assignees',return_value=[{'email':USER['email'],'name':'관리자'},{'email':'other@example.com','name':'직원'}]):
            responses=[self.post(body={'owner':owner})[0].json() for owner in (USER['email'],'other@example.com','')]
            self.assertEqual(responses[0]['summary']['project_progress'],0)
            self.assertEqual(responses[1]['summary']['project_progress'],100)
            for data in responses:
                self.assertEqual(data['portfolio']['summary']['total'],2)
                self.assertEqual(data['portfolio']['summary']['project_progress'],50)
                self.assertEqual([p['id'] for p in data['portfolio']['projects']],[CID])
        self.assertNotIn('portfolio',self.post()[0].json())

    def test_sync_requests_join_inflight_inventory(self):
        entered=threading.Event();release=threading.Event();results=[]
        def slow():entered.set();release.wait(2);return []
        with patch.object(outline,'sync',side_effect=slow) as sync:
            first=threading.Thread(target=lambda:results.append(outline.sync_shared()));first.start();entered.wait(1)
            second=threading.Thread(target=lambda:results.append(outline.sync_shared()));second.start()
            time.sleep(.03);release.set();first.join(2);second.join(2)
            self.assertEqual(sync.call_count,1);self.assertEqual(len(results),2)

    def test_empty_and_invalid_tasks_preserve_null_ratios(self):
        self.tasks.return_value=[]
        self.assertIsNone(self.post()[0].json()['summary']['project_progress'])
        row=task('invalid',CID);row['error']='형식 오류';row['fields']={'owner':USER['email']}
        self.tasks.return_value=[row]
        response=self.post()[0]
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['summary']['invalid'],1)

if __name__=='__main__':unittest.main()
