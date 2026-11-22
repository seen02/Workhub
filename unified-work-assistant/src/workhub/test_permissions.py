import unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import permissions as acl,outline,search_identity

USER={'sub':'alice','email':'alice@example.com','admin':False}
class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.users=[{'id':'alice','email':USER['email'],'name':'홍길동','role':'member'},
                    {'id':'bob','email':'bob@example.com','name':'김철수','role':'member'},
                    {'id':'lead','email':'lead@example.com','name':'팀장','role':'admin'}]
        self.cols=[{'id':'a','name':'A','permission':None},{'id':'b','name':'B','permission':None},{'id':'shared','name':'공용','permission':'read'}]
        for col in self.cols:col['code']=col['id']
        self.groups={'ga':{'alice'},'gb':{'bob'}}
        self.direct={'a':{'lead'},'b':{'lead'}}
        self.calls=[]
        self.patches=[patch.object(outline,'all_items',side_effect=lambda method,*a:self.users if method=='users.list' else self.cols),
                      patch.object(outline,'projects',return_value=self.cols),patch.object(outline,'api',side_effect=self.api)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def api(self,method,body,**kw):
        self.calls.append(method)
        if method=='collections.memberships':return {'memberships':[{'userId':u,'permission':'read'} for u in self.direct.get(body['id'],set())]}
        if method=='collections.group_memberships':return {'groupMemberships':[{'groupId':'g'+body['id'],'permission':'read'}] if 'g'+body['id'] in self.groups else []}
        if method=='groups.memberships':return {'groupMemberships':[{'userId':u} for u in self.groups[body['id']]]}
        raise AssertionError(method)
    def test_group_grant_and_shared_collection(self):
        self.assertEqual([p['id'] for p in acl.projects(USER)],['a','shared'])
    def test_workhub_admin_does_not_bypass_outline_acl(self):
        self.assertEqual([p['id'] for p in acl.projects({**USER,'admin':True})],['a','shared'])
    def test_group_removal_applies_to_next_request(self):
        self.assertTrue(acl.Access(USER).readable('a'));self.groups['ga'].clear()
        self.assertFalse(acl.Access(USER).readable('a'))
    def test_acl_snapshot_reused_only_inside_same_request(self):
        token=acl.request_snapshots.set({})
        try:
            self.assertTrue(acl.Access(USER).readable('a'));self.groups['ga'].clear()
            self.assertTrue(acl.Access(USER).readable('a'))
        finally:acl.request_snapshots.reset(token)
        self.assertFalse(acl.Access(USER).readable('a'))
    def test_direct_grant_remains_after_group_removal(self):
        self.direct['a'].add('alice');self.groups['ga'].clear()
        self.assertTrue(acl.Access(USER).readable('a'))
    def test_guest_does_not_inherit_team_visible_permission(self):
        self.users[0]['role']='guest';self.assertFalse(acl.Access(USER).readable('shared'))
    def test_suspended_user_is_denied(self):
        self.users[0]['isSuspended']=True
        with self.assertRaises(HTTPException):acl.Access(USER)
    def test_assignees_include_group_members_not_other_project(self):
        with patch('workhub.directory.names',return_value={}):
            self.assertEqual({p['email'] for p in acl.assignees(USER,'a')},{'alice@example.com','lead@example.com'})
    def test_hidden_member_cannot_be_assigned_by_email(self):
        with patch('workhub.directory.names',return_value={}):
            with self.assertRaises(HTTPException):acl.validate_owners(USER,'a',[{'owner':'bob@example.com'}])
    def test_unchanged_former_assignee_can_be_preserved(self):
        old={'id':'c1','owner':'bob@example.com'}
        with patch('workhub.directory.names',return_value={}):acl.validate_owners(USER,'a',[old],[old])
    def test_login_identity_check_never_grants_membership(self):
        self.assertEqual(outline.ensure_member(USER),'alice')
        self.assertNotIn('collections.add_user',self.calls)
    def test_collection_membership_does_not_allow_deleted_document(self):
        with self.assertRaises(HTTPException):acl.document(USER,{'collectionId':'a','publishedAt':'now','deletedAt':'now'})
    def test_signed_search_identity_cannot_be_forged(self):
        token=search_identity.issue(USER);self.assertEqual(search_identity.decode(token)['sub'],'alice')
        with self.assertRaises(HTTPException):search_identity.decode(token+'x')

if __name__=='__main__':unittest.main()
