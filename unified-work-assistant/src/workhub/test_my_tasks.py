import unittest
from datetime import datetime, date, timezone
from unittest.mock import patch
from . import my_tasks, outline, permissions, domain, criteria

USER = {'sub':'s', 'email':'me@example.com', 'admin':False}
NOW = datetime(2026,9,30,0,0,tzinfo=my_tasks.KST)


def task(n='1', due='2026-09-30', owner='me@example.com', items=None, status='진행 중'):
    return {'id':n, 'title':'업무 '+n, 'collectionId':'p', 'collectionName':'프로젝트',
            'url':'http://outline.test/doc/'+n, 'fields':{'owner':owner,'due':due,'status':status,'start':'미정'},
            'criteria':items or [], 'revision':1}


def item(owner='me@example.com', state='예정', n=1):
    return {'id':f'C-{n:08x}','title':f'완료 기준 {n}','owner':owner,'state':state}


class PersonalTests(unittest.TestCase):
    def test_date_groups_and_overdue_days(self):
        for due,group,days in [('2026-09-28','overdue',2),('2026-09-30','today',0),
                                ('2026-10-01','upcoming',0),('미정','undated',0),('','undated',0)]:
            with self.subTest(due=due):
                r=my_tasks.personal(task(due=due),USER,NOW.date())
                self.assertEqual((r['group'],r['late_days']),(group,days))

    def test_shared_work_and_completed_personal_portion(self):
        t=task(owner='lead@example.com',items=[item(),item('other@example.com',n=2)])
        self.assertEqual(len(my_tasks.personal(t,USER,NOW.date())['mine']),1)
        t['criteria'][0]['state']='완료'
        self.assertIsNone(my_tasks.personal(t,USER,NOW.date()))

    def test_admin_does_not_get_other_people_work(self):
        self.assertIsNone(my_tasks.personal(task(owner='other@example.com'),{**USER,'admin':True},NOW.date()))
        self.assertIsNone(my_tasks.personal(task(items=[item('other@example.com')]),USER,NOW.date()))

    def test_no_criteria_complete_excluded_and_hold_included(self):
        self.assertIsNone(my_tasks.personal(task(status='완료'),USER,NOW.date()))
        self.assertEqual(my_tasks.personal(task(status='보류'),USER,NOW.date())['fields']['status'],'보류')

    def test_bad_date_is_not_undated(self):
        with self.assertRaises(ValueError):my_tasks.personal(task(due='다음주'),USER,NOW.date())

    @patch.object(permissions,'projects',return_value=[{'id':'p'},{'id':'q'},{'id':'r'}])
    def test_cross_project_dedup_partial_failure_and_invalid(self,_):
        with patch.object(outline,'read_project_tasks',side_effect=[([task()],0),([task(),task('2',due='미정')],1),RuntimeError('offline')]):
            d=my_tasks.collect(USER,NOW)
        self.assertEqual(len(d['rows']),2)
        self.assertEqual((d['failed'],d['invalid'],d['complete']),(1,1,False))

    @patch.object(permissions,'projects',return_value=[{'id':'p'}])
    def test_all_failure_is_not_zero_tasks_success(self,_):
        with patch.object(outline,'read_project_tasks',side_effect=RuntimeError()):d=my_tasks.collect(USER,NOW)
        self.assertTrue(d['all_failed']);self.assertFalse(d['complete'])

    @patch.object(permissions,'projects',side_effect=RuntimeError('ACL unavailable'))
    def test_acl_failure_propagates(self,_):
        with self.assertRaises(RuntimeError):my_tasks.collect(USER,NOW)

    @patch.object(permissions,'projects',return_value=[{'id':'p'}])
    def test_korean_midnight(self,_):
        with patch.object(outline,'read_project_tasks',return_value=([task(due='2026-09-29')],0)):
            before=my_tasks.collect(USER,datetime(2026,9,29,14,59,tzinfo=timezone.utc))
            after=my_tasks.collect(USER,datetime(2026,9,29,15,0,tzinfo=timezone.utc))
        self.assertEqual(before['rows'][0]['group'],'today');self.assertEqual(after['rows'][0]['group'],'overdue')

    @patch.object(permissions,'projects',return_value=[{'id':'p'}])
    def test_group_order_and_oldest_overdue_first(self,_):
        rows=[task('a','미정'),task('b','2026-09-29'),task('c','2025-12-01'),task('d','2026-10-01'),task('e')]
        with patch.object(outline,'read_project_tasks',return_value=(rows,0)):d=my_tasks.collect(USER,NOW)
        self.assertEqual([t['id'] for t in d['rows']],['c','b','e','d','a'])


class ReadOnlyInventoryTests(unittest.TestCase):
    def test_all_api_pages_and_missing_body_without_writes(self):
        raw=domain.render({'project':'P','owner':USER['email'],'status':'미착수','progress':'0%'})
        def doc(n):return {'id':str(n),'title':'업무','collectionId':'p','publishedAt':'x','updatedAt':'x','url':'/doc/'+str(n),'text':raw}
        first=[doc(n) for n in range(100)];last=doc(100);last.pop('text')
        calls=[]
        def api(method,body,**kw):
            calls.append((method,body))
            if method=='documents.list':return first if body['offset']==0 else [last]
            if method=='documents.info':return doc(100)
            self.fail('Unexpected API call: '+method)
        with patch.object(permissions,'project'),patch.object(outline,'project',return_value={'name':'P'}),patch.object(outline,'api',side_effect=api),patch.object(outline,'normalize') as normalize,patch.object(outline,'record') as record:
            rows,errors=outline.read_project_tasks(USER,'p')
        self.assertEqual((len(rows),errors),(101,0));normalize.assert_not_called();record.assert_not_called()
        self.assertEqual([c[1]['offset'] for c in calls if c[0]=='documents.list'],[0,100])

    def test_wrong_collection_unpublished_deleted_template_excluded(self):
        base={'id':'a','text':'x','collectionId':'p','publishedAt':'x'}
        docs=[{**base,'collectionId':'private'},{**base,'publishedAt':None},{**base,'deletedAt':'x'},{**base,'template':True}]
        with patch.object(permissions,'project'),patch.object(outline,'api',return_value=docs),patch.object(outline,'projected') as projected:
            self.assertEqual(outline.read_project_tasks(USER,'p'),([],0))
        projected.assert_not_called()

    def test_bad_api_page_is_failure(self):
        with patch.object(permissions,'project'),patch.object(outline,'api',return_value={'unexpected':[]}):
            with self.assertRaises(ValueError):outline.read_project_tasks(USER,'p')

    def test_invalid_document_is_counted(self):
        d={'id':'a','text':'x','collectionId':'p','publishedAt':'x'}
        with patch.object(permissions,'project'),patch.object(outline,'api',return_value=[d]),patch.object(outline,'projected',return_value={'error':'bad date'}):
            self.assertEqual(outline.read_project_tasks(USER,'p'),([],1))

    def test_checkbox_state_is_computed_without_normalizing_source(self):
        raw=domain.render({'project':'P','owner':USER['email'],'status':'미착수','progress':'0%'})+'\n\n'+criteria.render([item(state='완료'),item(n=2)])
        d={'id':'a','title':'A','text':raw,'collectionId':'p','publishedAt':'x','updatedAt':'x','url':'/a'}
        with patch.object(permissions,'project'),patch.object(outline,'project',return_value={'name':'P'}),patch.object(outline,'api',return_value=[d]) as api:
            rows,_=outline.read_project_tasks(USER,'p')
        self.assertEqual(rows[0]['fields']['progress'],'50%');self.assertEqual(d['text'],raw)
        self.assertEqual([c.args[0] for c in api.call_args_list],['documents.list'])


if __name__=='__main__':unittest.main()
