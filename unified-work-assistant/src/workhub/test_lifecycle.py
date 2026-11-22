import json, os, tempfile, unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import lifecycle as lc, store, auth, provision

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DB',self.tmp.name+'/hub.db');p.start();self.addCleanup(p.stop);store.init()
        p=patch.dict(os.environ,{'AUTHENTIK_DIRECTORY_TOKEN':'test'});p.start();self.addCleanup(p.stop)
        self.user={'uuid':'uuid1','pk':10,'name':'직원','email':'a@example.com','username':'a','type':'internal','is_active':True,'groups_obj':[{'pk':'g','name':lc.GROUP}]}
        self.row={'sub':'uuid1','pk':10,'email':'a@example.com','username':'a','name':'직원','active':True,'groups':['g'],'admin':False}
    def test_failed_inventory_does_not_offboard(self):
        lc.save(self.row)
        with patch.object(lc,'inventory',side_effect=RuntimeError),patch.object(lc,'sync_account') as sync:
            self.assertFalse(lc.reconcile()['ok']);sync.assert_not_called()
        self.assertTrue(lc.records()[0]['active'])
    def test_incomplete_inventory_rejected(self):
        with patch.object(lc,'auth_api',return_value={'results':[self.user],'pagination':{'count':2,'next':0}}):
            with self.assertRaises(ValueError):lc.inventory('core/users/')
    def test_removed_account_offboarded_after_complete_snapshot(self):
        lc.save(self.row)
        with patch.object(lc,'inventory',return_value=[]),patch.object(lc,'sync_account') as sync:
            lc.reconcile();self.assertFalse(sync.call_args.args[0]['active'])
    def test_email_reuse_never_merges_identity(self):
        lc.save(self.row)
        other={**self.user,'uuid':'uuid2','pk':11}
        with patch.object(lc,'inventory',return_value=[self.user,other]),patch.object(lc,'sync_account'):
            lc.reconcile()
        self.assertIn('이메일 중복',store.get('employee:uuid2')['review'])
        self.assertFalse(lc.allowed_email('a@example.com'))
    def test_changed_login_requires_review(self):
        lc.save(self.row)
        with patch.object(lc,'inventory',return_value=[{**self.user,'username':'new'}]),patch.object(lc,'sync_account'):
            lc.reconcile()
        self.assertIn('관리자 확인',lc.records()[0]['review'])
    def test_two_new_accounts_with_same_email_are_both_quarantined(self):
        with patch.object(lc,'inventory',return_value=[self.user,{**self.user,'uuid':'uuid2','pk':11}]),patch.object(lc,'sync_account'):
            lc.reconcile()
        self.assertTrue(all(r.get('review') for r in lc.records()))
    def test_one_service_failure_does_not_skip_other_revocations(self):
        row={**self.row,'active':False}
        with patch.object(lc,'sync_outline',side_effect=RuntimeError),patch.object(lc,'sync_groups',return_value='ok'),patch.object(lc,'sync_chat',return_value='ok') as chat:
            lc.sync_account(row)
        chat.assert_called_once();self.assertFalse(row['services']['outline']['ok']);self.assertTrue(row['services']['chat']['ok'])
    def test_revokes_sessions_and_identities_preserves_history(self):
        with store.db() as c:
            c.execute('INSERT INTO sessions VALUES(?,?,?)',('s',json.dumps({'info':{'sub':'uuid1'}}),9999999999))
            c.execute('INSERT INTO identities VALUES(?,?,?)',('uuid1','a@example.com','{}'))
            c.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?)',('p','uuid1','i','{}','PENDING','now'))
        lc.revoke_local(self.row)
        with store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM identities').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM proposals').fetchone()[0],1)
    def test_manual_outline_suspension_never_reactivated(self):
        row={**self.row,'outline_id':'out'}
        with patch.object(lc.outline,'api',return_value={'id':'out','email':row['email'],'isSuspended':True}) as api:
            self.assertIn('수동 정지',lc.sync_outline(row));self.assertEqual(api.call_count,1)
    def test_own_suspension_reactivated(self):
        row={**self.row,'outline_id':'out','outline_suspended':True}
        with patch.object(lc.outline,'api',return_value={'id':'out','email':row['email'],'name':row['name'],'isSuspended':True}) as api:
            lc.sync_outline(row);self.assertEqual(api.call_args.args[0],'users.activate')
    def test_live_disabled_account_denied_before_poll(self):
        with patch.object(lc,'auth_api',return_value={'results':[{**self.user,'is_active':False}]}):
            with self.assertRaises(HTTPException) as e:lc.require_identity({'sub':'uuid1','email':'a@example.com'})
            self.assertEqual(e.exception.status_code,403)
    def test_identity_mismatch_and_auth_outage_fail_closed(self):
        with patch.object(lc,'auth_api',return_value={'results':[{**self.user,'uuid':'other'}]}):
            with self.assertRaises(HTTPException):lc.require_identity({'sub':'uuid1','email':'a@example.com'})
    def test_new_outline_invite_suppresses_email(self):
        with patch.object(lc.outline,'all_items',return_value=[]),patch.object(lc.outline,'api',return_value={'users':[{'id':'out','name':'직원','email':'a@example.com'}]}) as api:
            lc.sync_outline(self.row)
            self.assertTrue(api.call_args.args[1]['suppressEmail']);self.assertEqual(self.row['outline_id'],'out')
    def test_only_explicit_group_membership_is_managed(self):
        from . import permissions
        row={**self.row,'outline_id':'out'}
        store.put('employee_group_mappings',[{'outline_id':'managed','authentik_id':'g'}])
        with patch.object(permissions,'rows',return_value=[]),patch.object(lc.outline,'api') as api:
            lc.sync_groups(row)
            api.assert_called_once_with('groups.add_user',{'id':'managed','userId':'out'})
    def test_read_rate_limit_retries_but_write_never_repeats(self):
        import httpx
        busy=httpx.Response(429,headers={'Retry-After':'1'},json={'error':'rate_limit'})
        ok=httpx.Response(200,json={'data':{'id':'doc'}})
        with patch.object(lc.outline.http_pool,'request',side_effect=[busy,ok]) as post,patch.object(lc.outline.time,'sleep'):
            self.assertEqual(lc.outline.api('documents.info',{'id':'doc'})['id'],'doc');self.assertEqual(post.call_count,2)
        with patch.object(lc.outline.http_pool,'request',return_value=busy) as post:
            with self.assertRaises(HTTPException) as e:lc.outline.api('documents.update',{'id':'doc'})
            self.assertEqual(e.exception.status_code,503);self.assertEqual(post.call_count,1)

    def synced_row(self):
        row={**self.row,'authentik_active':True}
        row['security_state']=lc.security_state(row)
        lc.save(row)
        return row

    def test_name_only_change_does_not_call_services_in_background(self):
        self.synced_row()
        with patch.object(lc,'inventory',return_value=[{**self.user,'name':'새 이름'}]),patch.object(lc,'sync_account') as sync:
            lc.reconcile(sync_names=False);lc.reconcile(sync_names=False)
            sync.assert_not_called()
        self.assertEqual(lc.records()[0]['name'],'직원')
        self.assertIsNone(store.get('employee_sync'))
        self.assertTrue(store.get('employee_security_sync')['ok'])

    def test_manual_sync_propagates_name_after_idle_poll(self):
        self.synced_row()
        with patch.object(lc,'inventory',return_value=[{**self.user,'name':'새 이름'}]),patch.object(lc,'sync_account') as sync:
            lc.reconcile(sync_names=False);lc.reconcile()
            sync.assert_called_once()
            self.assertTrue(sync.call_args.kwargs['sync_names'])
            self.assertEqual(sync.call_args.args[0]['name'],'새 이름')

    def test_security_change_processed_once_without_name_sync(self):
        self.synced_row()
        with patch.object(lc,'inventory',return_value=[{**self.user,'is_active':False,'name':'새 이름'}]),patch.object(lc,'sync_account') as sync:
            lc.reconcile(sync_names=False);lc.reconcile(sync_names=False)
            sync.assert_called_once()
            self.assertFalse(sync.call_args.kwargs['sync_names'])
            self.assertFalse(sync.call_args.args[0]['active'])
            self.assertEqual(sync.call_args.args[0]['name'],'직원')

    def test_group_and_admin_changes_still_applied(self):
        self.synced_row()
        changed={**self.user,'groups_obj':self.user['groups_obj']+[{'pk':'admin-group','name':lc.ADMIN}]}
        with patch.object(lc,'inventory',return_value=[changed]),patch.object(lc,'sync_account') as sync:
            lc.reconcile(sync_names=False)
            self.assertTrue(sync.call_args.args[0]['admin'])
            self.assertIn('admin-group',sync.call_args.args[0]['groups'])

    def test_failed_security_action_retried_but_name_failure_preserved(self):
        row=self.synced_row();row['security_pending']=True
        row['services']={'outline':{'ok':False,'message':'이름 반영 실패'}};lc.save(row)
        with patch.object(lc,'inventory',return_value=[self.user]),patch.object(lc,'sync_outline',side_effect=[RuntimeError,'ok']) as outline_sync,patch.object(lc,'sync_groups',return_value='ok'),patch.object(lc,'sync_chat',return_value='ok'):
            lc.reconcile(sync_names=False);self.assertTrue(lc.records()[0]['security_pending'])
            lc.reconcile(sync_names=False);self.assertFalse(lc.records()[0]['security_pending'])
            lc.reconcile(sync_names=False);self.assertEqual(outline_sync.call_count,2)
        self.assertFalse(lc.records()[0]['services']['outline']['ok'])

    def test_background_reactivation_keeps_remote_display_name(self):
        row={**self.row,'outline_id':'out','outline_suspended':True}
        with patch.object(lc.outline,'api',return_value={'id':'out','email':row['email'],'name':'다른 이름','isSuspended':True}) as api:
            lc.sync_outline(row,sync_names=False)
            self.assertEqual([c.args[0] for c in api.call_args_list],['users.info','users.activate'])

    def test_security_loop_never_requests_name_sync(self):
        from unittest.mock import Mock
        stop=Mock();stop.is_set.side_effect=[False,True]
        with patch.object(lc,'reconcile') as sync:
            lc.run(stop);sync.assert_called_once_with(sync_names=False)

    def test_request_role_update_never_sends_name(self):
        from unittest.mock import MagicMock
        mongo=MagicMock();mongo.rocketchat.users.find_one.return_value={'_id':'chat1','roles':['user'],'name':'직원'}
        with patch.dict(os.environ,{'ROCKET_ADMIN_USERNAME':'configured'}),patch.object(provision,'mongo',mongo),patch.object(provision,'call') as call:
            provision.reconcile({'sub':'uuid1','email':'a@example.com','name':'새 이름','admin':False},sync_name=False)
            call.assert_not_called()
            provision.reconcile({'sub':'uuid1','email':'a@example.com','name':'새 이름','admin':True},sync_name=False)
            self.assertEqual(call.call_args.args[1]['data'],{'roles':['admin','user']})
            call.reset_mock()
            provision.reconcile({'sub':'uuid1','email':'a@example.com','name':'새 이름','admin':False})
            self.assertEqual(call.call_args.args[1]['data'],{'name':'새 이름'})

if __name__=='__main__':unittest.main()
