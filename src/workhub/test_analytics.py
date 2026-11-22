import unittest
from datetime import date
from unittest.mock import patch
from fastapi.testclient import TestClient
from . import analytics, auth, outline
from .main import app

TODAY=date(2026,9,18)
PROJECTS=[{'id':'p','name':'포털'},{'id':'q','name':'문서화'},{'id':'empty','name':'빈 프로젝트'}]
def task(id='a',cid='p',state='진행 중',due='2026-09-17',criteria=None,**extra):
    return {'id':id,'title':id,'collectionId':cid,'collectionName':cid,'url':'/doc/'+id,'fields':{'owner':'lead@example.com','status':state,'due':due,'progress':'0%','blocker':'없음','next':'없음',**extra},'criteria':criteria or []}
def item(owner='a@example.com',state='예정'):return {'id':owner+state,'title':'검증','owner':owner,'state':state}

class AnalyticsTests(unittest.TestCase):
    def test_owner_task_buckets_partition_tasks_not_checklists(self):
        rows=[task('done',state='완료'),task('late',criteria=[item(),item(state='진행 중')]),task('future',due='2026-10-01'),task('undated',due='미정')]
        data=self.build(rows,owner_members={'lead@example.com':{},'idle@example.com':{}})
        owners={o['email']:o for o in data['owners']}
        lead=owners['lead@example.com']
        self.assertEqual((lead['tasks_completed'],lead['tasks_overdue'],lead['tasks_pending']),(1,1,2))
        self.assertEqual(sum(lead[k] for k in ('tasks_completed','tasks_overdue','tasks_pending')),lead['tasks'])
        self.assertEqual(owners['idle@example.com']['tasks_pending'],0)

    def build(self,ts,**kw):return analytics.build(ts,PROJECTS,today=TODAY,**kw)
    def test_counts_document_once_and_criteria_weighted_not_project_average(self):
        a=task(criteria=[item(state='완료')]);b=task('b','q',criteria=[item() for _ in range(3)])
        d=self.build([a,a,b]);self.assertEqual(d['summary']['total'],2);self.assertEqual(d['summary']['criteria_progress'],25)
    def test_completed_overdue_or_blocked_tasks_are_not_actionable(self):
        d=self.build([task(state='완료',blocker='승인 필요')]);self.assertEqual(d['summary']['overdue'],0);self.assertEqual(d['summary']['blocked'],0);self.assertEqual(d['actions'],[])
    def test_completed_list_is_scoped_deduplicated_and_matches_count(self):
        done=task('done',state='완료',due='미정',blocker='승인 필요',criteria=[item()])
        hidden=task('hidden','not-allowed',state='완료')
        other=task('other','q',state='완료')
        bad=task('bad',state='완료');bad['error']='invalid'
        d=self.build([done,done,hidden,other,bad,task('open')],owner='a@example.com',collection_id='p')
        self.assertEqual([t['id'] for t in d['completed_tasks']],['done'])
        self.assertEqual(len(d['completed_tasks']),d['summary']['completed'])
        self.assertEqual(d['completed_tasks'][0]['flags'],[])
        self.assertEqual(self.build([],owner='a@example.com')['completed_tasks'],[])

    def test_due_window_boundaries_and_korean_calendar(self):
        ts=[task(str(i),due=d) for i,d in enumerate(['2026-09-17','2026-09-18','2026-09-25','2026-09-26','미정'])]
        d=self.build(ts);self.assertEqual(d['summary']['overdue'],1);self.assertEqual(d['summary']['due_soon'],2);self.assertEqual(d['summary']['no_due'],1)
        self.assertEqual(sum(b['count'] for b in d['schedule']),5);self.assertEqual(d['as_of'],'2026-09-18')
    def test_owner_filter_uses_own_criteria_but_shared_task_status(self):
        ts=[task(criteria=[item(),item('b@example.com','완료')])]
        a=self.build(ts,owner='a@example.com');b=self.build(ts,owner='b@example.com')
        self.assertEqual(a['summary']['total'],1);self.assertEqual(a['summary']['criteria_total'],1);self.assertEqual(a['summary']['criteria_progress'],0);self.assertEqual(b['summary']['criteria_progress'],100)
        self.assertEqual(b['owners'][0]['overdue_items'],0);self.assertEqual(a['owners'][0]['overdue_items'],1)
    def test_missing_criteria_and_empty_data_are_not_zero_percent(self):
        d=self.build([task(due='미정',progress='미기재')]);self.assertIsNone(d['summary']['criteria_progress']);self.assertEqual(d['summary']['missing_progress'],1)
        empty=self.build([]);self.assertIsNone(empty['summary']['completion_rate']);self.assertIsNone(empty['summary']['criteria_progress'])
    def test_average_uses_reported_progress_without_treating_missing_as_zero(self):
        d=self.build([task(progress='60%'),task('b',progress='미기재'),task('c',progress='20%')])
        self.assertEqual(d['summary']['average_progress'],40);self.assertEqual(d['summary']['progress_known'],2)
        self.assertEqual(self.build([task(str(i),progress=p) for i,p in enumerate(['25%','0%','0%','0%'])])['summary']['average_progress'],6.3)
    def test_invalid_and_unlinked_documents_excluded_from_valid_denominator(self):
        bad={**task('bad'),'error':'잘못된 업무 양식','fields':{}}
        d=self.build([bad,task(),task('hidden','not-connected')]);self.assertEqual(d['summary']['total'],1);self.assertEqual(d['summary']['invalid'],1);self.assertEqual(len(d['invalid_tasks']),1)
    def test_project_progress_weights_projects_equally_and_excludes_empty(self):
        ts=[task('a',progress='100%',state='완료'),task('b',progress='100%',state='완료'),task('c','q',progress='20%')]
        d=self.build(ts)
        self.assertEqual(d['summary']['project_progress'],60)
        self.assertNotEqual(d['summary']['project_progress'],d['summary']['average_progress'])
        self.assertEqual(d['summary']['projects_measured'],2)
        self.assertEqual(d['summary']['projects_total'],3)
        scoped=self.build(ts,collection_id='q')['summary']
        self.assertEqual(scoped['project_progress'],20);self.assertEqual(scoped['projects_total'],1)
    def test_project_progress_unknown_and_owner_scope(self):
        ts=[task(progress='미기재'),task('b','q',progress='50%',criteria=[item()])]
        self.assertEqual(self.build(ts)['summary']['project_progress'],50)
        self.assertIsNone(self.build(ts,collection_id='p')['summary']['project_progress'])
        self.assertIsNone(self.build([])['summary']['project_progress'])
        self.assertEqual(self.build(ts,owner='a@example.com')['summary']['project_progress'],50)
        self.assertEqual(self.build(ts,owner='a@example.com')['summary']['projects_total'],1)
    def test_suggestions_do_not_overwrite_explicit_next_action(self):
        d=self.build([task(next='검증 결과를 팀장에게 전달')]);self.assertFalse(d['actions'][0]['next_is_suggestion']);self.assertEqual(d['actions'][0]['next'],'검증 결과를 팀장에게 전달')
        self.assertTrue(self.build([task()])['actions'][0]['next_is_suggestion'])
    def test_priority_and_horizon_change(self):
        ts=[task('later',due='2026-10-01'),task('no-due',due='미정'),task('blocked',due='2026-10-03',blocker='승인 필요'),task('late')]
        d=self.build(ts);self.assertEqual([t['id'] for t in d['actions']][:2],['late','blocked'])
        self.assertEqual(self.build(ts,horizon=14)['summary']['due_soon'],1)
    def test_project_scope_and_empty_participation(self):
        d=self.build([task(),task('b','q')],collection_id='q');self.assertEqual([p['id'] for p in d['projects']],['q']);self.assertEqual(d['summary']['total'],1)
        d=self.build([task()],owner='nobody@example.com');self.assertEqual(d['projects'],[]);self.assertEqual(d['summary']['total'],0)
    def test_worker_can_read_analytics_but_admin_actions_stay_restricted(self):
        app.dependency_overrides[auth.current]=lambda:{'sub':'worker','email':'a@example.com','admin':False}
        try:
            with patch.object(outline,'tasks',return_value=[task()]),patch('workhub.main.permissions.projects',return_value=PROJECTS),patch('workhub.main.directory.names',return_value={}),patch('workhub.main.store.get',return_value=None):
                client=TestClient(app);self.assertEqual(client.get('/api/analytics').status_code,200)
                self.assertEqual(client.get('/api/analytics?horizon=0').status_code,422)
                self.assertEqual(client.get('/api/weekly').status_code,403);self.assertEqual(client.get('/api/operations').status_code,403)
        finally:app.dependency_overrides.clear()
    def test_worker_statistics_are_personal_and_other_owner_is_denied(self):
        app.dependency_overrides[auth.current]=lambda:{'sub':'worker','email':'a@example.com','admin':False}
        try:
            rows=[task('mine',owner='a@example.com'),task('shared',owner='b@example.com',criteria=[item('a@example.com')]),task('other',owner='b@example.com'),task('forbidden','outside',owner='a@example.com')]
            with patch.object(outline,'tasks',return_value=rows),patch('workhub.main.permissions.projects',return_value=PROJECTS),patch('workhub.main.directory.names',return_value={}),patch('workhub.main.store.get',return_value=None):
                client=TestClient(app)
                self.assertEqual(client.get('/api/analytics?owner=b@example.com').status_code,403)
                d=client.get('/api/analytics').json()
                self.assertEqual({t['id'] for t in d['calendar_actions']},{'mine','shared'})
                self.assertEqual({t['id'] for t in d['actions']},{'mine','shared'})
                self.assertEqual(d['owner'],'a@example.com')
                self.assertEqual([p['email'] for p in d['owner_options']],['a@example.com'])
                self.assertEqual([p['email'] for p in d['owners']],['a@example.com'])
        finally:app.dependency_overrides.clear()

    def test_anonymous_analytics_denied(self):
        self.assertEqual(TestClient(app).get('/api/analytics').status_code,401)

    def test_project_roster_ignores_person_filter_and_includes_unassigned(self):
        ts=[task(criteria=[item('a@example.com'),item('b@example.com','완료')]),task('outside','q',criteria=[item('b@example.com')])]
        d=self.build(ts,owner='lead@example.com',collection_id='p',owner_members={'a@example.com':{},'b@example.com':{},'idle@example.com':{}})
        owners={r['email']:r for r in d['owners']}
        self.assertEqual(set(owners),{'a@example.com','b@example.com','idle@example.com'})
        self.assertEqual(owners['b@example.com']['tasks'],1)
        self.assertEqual(owners['b@example.com']['remaining'],0)
        self.assertEqual(owners['idle@example.com']['tasks'],0)
        self.assertIsNone(owners['idle@example.com']['progress'])
        self.assertNotIn('lead@example.com',owners)

    def test_managed_api_respects_acl_and_membership_even_with_owner_filter(self):
        user={'sub':'lead','email':'lead@example.com','admin':True}
        app.dependency_overrides[auth.current]=lambda:user
        try:
            ps=[{'id':'p','name':'P','manager':user['email']},{'id':'q','name':'Q','manager':'other@example.com'}]
            with patch.object(outline,'tasks',return_value=[task(criteria=[item()]),task('q','q')]),patch('workhub.main.permissions.projects',return_value=ps),patch('workhub.main.permissions.assignees',return_value=[{'email':'a@example.com','name':'실무자'},{'email':'idle@example.com','name':'미배정'}]) as roster,patch('workhub.main.directory.names',return_value={}),patch('workhub.main.store.get',return_value=None):
                d=TestClient(app).get('/api/analytics?managed=true&owner=lead@example.com').json()
                self.assertEqual([p['id'] for p in d['projects']],['p'])
                self.assertEqual({p['email'] for p in d['owners']},{'a@example.com','idle@example.com'})
                roster.assert_called_once_with(user,'p')
                self.assertEqual(d['owners_scope'],'project_members')
        finally:app.dependency_overrides.clear()

if __name__=='__main__':unittest.main()
