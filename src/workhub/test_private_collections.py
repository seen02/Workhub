"""Service-admin inventory must not replace the requesting user's collection ACL."""
import copy
import tempfile
import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from . import outline, permissions, project_service, store, execution


USER={'sub':'owner','email':'owner@example.test','admin':False}


class PrivateCollectionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for replacement in [patch.object(store,'DB',folder.name+'/tests.db'),
                            patch.object(outline,'PROJECTS_CACHE',{'until':0,'available':{}}),
                            patch.object(outline.http_pool,'request',side_effect=self.api)]:
            replacement.start();self.addCleanup(replacement.stop)
        store.init();store.put('projects',[])
        self.users=[{'id':'owner','email':USER['email'],'name':'Owner','role':'member'},
                    {'id':'outsider','email':'outsider@example.test','name':'Outsider','role':'admin'}]
        self.collections=[{'id':cid,'name':cid,'permission':None} for cid in
                          ('private-direct','private-group','private-other','private-read')]
        self.collections += [{'id':'shared','name':'Shared','permission':'read'},
                             {'id':'public-write','name':'Public project','permission':'read_write'},
                             {'id':'archived','name':'Archived','permission':None,'archivedAt':'now'},
                             {'id':'deleted','name':'Deleted','permission':None,'deletedAt':'now'}]
        self.direct={'private-direct':[{'userId':'owner','permission':'admin'}],
                     'private-other':[{'userId':'outsider','permission':'admin'}],
                     'private-read':[{'userId':'owner','permission':'read'}]}
        self.group_users={'owner'};self.calls=[]
        self.service_grants={};self.bad_policy=False;self.info_forbidden=False

    def api(self,service,method,url,**kwargs):
        name=url.rsplit('/api/',1)[-1];body=kwargs.get('json',{});self.calls.append((name,copy.deepcopy(body)))
        if name=='collections.info':
            if self.info_forbidden:return httpx.Response(403,json={})
            collection=next(c for c in self.collections if c['id']==body['id'])
            permission=self.service_grants.get(body['id'],collection.get('permission'))
            abilities={'readDocument':permission in ('read','read_write','admin'),
                       'createDocument':permission in ('read_write','admin'),
                       'updateDocument':permission in ('read_write','admin')}
            if permission=='group-write':abilities={k:['service-group-membership'] for k in abilities}
            return httpx.Response(200,json={'data':collection,'policies':[] if self.bad_policy else [{'id':body['id'],'abilities':abilities}]})
        if name=='users.list':data=self.users
        elif name=='collections.list':
            data=self.collections if body.get('includeListOnly') else [c for c in self.collections if c.get('permission') is not None]
        elif name=='collections.memberships':data={'memberships':self.direct.get(body['id'],[])}
        elif name=='collections.group_memberships':
            data={'groupMemberships':[{'groupId':'private-managers','permission':'admin'}] if body['id']=='private-group' else []}
        elif name=='groups.memberships':data={'groupMemberships':[{'userId':uid} for uid in self.group_users]}
        else:raise AssertionError('Unexpected service request: '+name)
        if isinstance(data,list):data=data[body.get('offset',0):body.get('offset',0)+body.get('limit',100)]
        return httpx.Response(200,json={'data':data})

    def request(self,cid,revision=0):
        return {'collectionId':cid,'requestId':str(uuid.uuid4()),'expectedRevision':revision,
                'managerSubject':None,'deleteTaskList':False,'expectedParentId':None}

    def test_private_creator_loads_status_but_link_requires_service_access(self):
        self.assertNotIn('private-direct',[c['id'] for c in outline.all_items('collections.list')])
        info=project_service.info(USER,'private-direct',can_manage=True)
        self.assertFalse(info['linked']);self.assertTrue(info['permissions']['manage'])
        with patch.object(outline,'task_parent') as parent:
            for user in (USER,{**USER,'admin':True}):
                for cid in ('private-direct','private-group'):
                    with self.subTest(admin=user['admin'],collection=cid),self.assertRaises(HTTPException) as error:
                        project_service.mutate(user,'link',self.request(cid),can_manage=True)
                    self.assertEqual(error.exception.status_code,403)
                    self.assertEqual(error.exception.detail,permissions.PROJECT_LINK_ACCESS_ERROR)
            parent.assert_not_called()
        self.assertEqual(store.get('projects'),[])
        with store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM project_operations').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM project_link_state').fetchone()[0],0)

    def test_public_collection_can_still_link_preview_and_unlink(self):
        with patch.object(outline,'task_parent',return_value={'id':'parent'}) as parent:
            result=project_service.mutate(USER,'link',self.request('public-write'),can_manage=True)
        self.assertTrue(result['linked']);parent.assert_called_once_with('public-write')
        self.assertEqual([p['id'] for p in permissions.projects(USER)],['public-write'])
        self.assertTrue(project_service.preview(USER,'public-write',can_manage=True)['linked'])
        project_service.mutate(USER,'unlink',self.request('public-write',1),can_manage=True)
        self.assertEqual(permissions.projects(USER),[])

    def test_existing_private_project_can_still_be_unlinked(self):
        store.put('projects',[{'id':'private-direct','name':'Private'}]);project_service.init()
        result=project_service.mutate(USER,'unlink',self.request('private-direct',1),can_manage=True)
        self.assertFalse(result['linked']);self.assertEqual(store.get('projects'),[])

    def test_pending_link_rechecks_revoked_service_access(self):
        body=self.request('public-write')
        with patch.object(outline,'task_parent',side_effect=HTTPException(503,'response lost')):
            with self.assertRaises(HTTPException):project_service.mutate(USER,'link',body,can_manage=True)
        self.service_grants['public-write']='read'
        with patch.object(outline,'task_parent') as parent:
            with self.assertRaises(HTTPException) as error:
                project_service.resume(USER,'public-write',body['requestId'],None,can_manage=True)
        self.assertEqual(error.exception.status_code,403);parent.assert_not_called()
        self.assertEqual(store.get('projects'),[])

    def test_legacy_registration_also_requires_service_access(self):
        with self.assertRaises(HTTPException) as error:
            outline.register_project({**USER,'admin':True},'','private-direct','legacy-private')
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(store.get('projects'),[])

    def test_empty_registry_does_not_automatically_create_private_project(self):
        with store.db() as db:db.execute("DELETE FROM kv WHERE k='projects'")
        self.assertEqual(outline.projects(),[])
        self.assertFalse(any(name=='collections.create' for name,body in self.calls))

    def test_legacy_creation_does_not_create_or_register_a_private_collection(self):
        with self.assertRaises(HTTPException) as error:
            outline.register_project({**USER,'admin':True},'New private project',idem='legacy-new')
        self.assertEqual(error.exception.status_code,400)
        self.assertFalse(any(name=='collections.create' for name,body in self.calls))
        self.assertEqual(store.get('projects'),[])

    def test_private_collection_links_with_service_direct_or_group_write_access(self):
        for grant in ('read_write','group-write'):
            with self.subTest(grant=grant):
                self.service_grants['private-direct']=grant
                with patch.object(outline,'task_parent',return_value={'id':'parent'}):
                    result=project_service.mutate(USER,'link',self.request('private-direct',project_service.state('private-direct')['revision']),can_manage=True)
                self.assertTrue(result['linked'])
                self.assertIsNone(next(c for c in self.collections if c['id']=='private-direct')['permission'])
                project_service.mutate(USER,'unlink',self.request('private-direct',result['revision']),can_manage=True)
        self.assertFalse(any(name in ('collections.add_user','collections.add_group','collections.update') for name,body in self.calls))

    def test_read_only_service_cannot_link_even_public_collection(self):
        self.service_grants['public-write']='read'
        with patch.object(outline,'task_parent') as parent,self.assertRaises(HTTPException) as error:
            project_service.mutate(USER,'link',self.request('public-write'),can_manage=True)
        self.assertEqual(error.exception.status_code,403);parent.assert_not_called()
        self.assertEqual(store.get('projects'),[])
        with store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM project_operations').fetchone()[0],0)

    def test_missing_native_policies_fail_closed_before_any_write(self):
        self.bad_policy=True
        with patch.object(outline,'task_parent') as parent,self.assertRaises(HTTPException) as error:
            project_service.mutate(USER,'link',self.request('public-write'),can_manage=True)
        self.assertEqual(error.exception.status_code,503);parent.assert_not_called()
        self.assertEqual(store.get('projects'),[])

    def test_service_collection_info_forbidden_returns_access_guidance(self):
        self.info_forbidden=True
        with self.assertRaises(HTTPException) as error:
            permissions.require_project_linkable({'id':'private-direct'})
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(error.exception.detail,permissions.PROJECT_LINK_ACCESS_ERROR)

    def test_service_permissions_are_used_without_account_name_lookup(self):
        self.users[0]['name']='Admin'
        with self.assertRaises(HTTPException):permissions.require_project_linkable({'id':'private-direct'})
        self.service_grants['private-direct']='read_write'
        permissions.require_project_linkable({'id':'private-direct'})
        self.assertTrue(all(name not in ('users.list','auth.info') for name,body in self.calls))

    def test_service_revocation_is_not_cached_across_requests(self):
        self.service_grants['private-direct']='read_write'
        with execution.request('first',USER):
            permissions.require_project_linkable({'id':'private-direct'})
            permissions.require_project_linkable({'id':'private-direct'})
        self.service_grants.clear()
        with execution.request('next',USER),self.assertRaises(HTTPException) as error:
            permissions.require_project_linkable({'id':'private-direct'})
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(sum(name=='collections.info' for name,body in self.calls),2)

    def test_private_collection_group_admin_can_read_and_create(self):
        self.assertEqual(permissions.Access(USER).require('private-group')['id'],'private-group')
        permissions.require_create(USER,'private-group')
        self.assertTrue(project_service.info(USER,'private-group',can_manage=True)['permissions']['manage'])

    def test_inventory_does_not_grant_access_to_unrelated_private_collection(self):
        for user in (USER,{**USER,'admin':True}):
            with self.subTest(admin=user['admin']),self.assertRaises(HTTPException) as error:
                project_service.info(user,'private-other',can_manage=True)
            self.assertEqual(error.exception.status_code,403)
        store.put('projects',[{'id':'private-direct','name':'Direct'},{'id':'private-other','name':'Other'}])
        self.assertEqual([p['id'] for p in permissions.projects(USER)],['private-direct'])

    def test_service_metadata_does_not_grant_document_creation_to_reader(self):
        self.assertEqual(permissions.Access(USER).require('private-read')['id'],'private-read')
        with self.assertRaises(HTTPException) as error:permissions.require_create(USER,'private-read')
        self.assertEqual(error.exception.status_code,403)

    def test_group_revocation_is_checked_on_next_request(self):
        permissions.Access(USER).require('private-group');self.group_users.clear()
        with self.assertRaises(HTTPException) as error:permissions.Access(USER).require('private-group')
        self.assertEqual(error.exception.status_code,403)

    def test_deleted_and_archived_collections_are_not_authorization_targets(self):
        self.assertFalse({'archived','deleted'} & set(permissions.Access(USER).collections))

    def test_admin_inventory_flag_survives_pagination(self):
        self.collections.extend({'id':f'extra-{i}','name':'Extra','permission':None} for i in range(101))
        access=permissions.Access(USER)
        self.assertIn('extra-100',access.collections)
        pages=[body for name,body in self.calls if name=='collections.list']
        self.assertEqual([body['offset'] for body in pages],[0,100])
        self.assertTrue(all(body['includeListOnly'] for body in pages))


if __name__=='__main__':unittest.main()
