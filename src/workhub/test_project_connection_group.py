"""Project creation validates the real API principal and its integration group."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import permissions, outline


class ProjectConnectionGroupTests(unittest.TestCase):
    def setUp(self):
        self.groups=[{'id':'connection-group','name':'Connect_as_a_project'}]
        self.members=[{'userId':'token-owner'}]
        self.person={'id':'token-owner','email':'admin@example.test'}
        for mock in (patch.object(outline,'all_items',side_effect=lambda *args:self.groups),
                     patch.object(outline,'api',side_effect=lambda *args:{'user':self.person}),
                     patch.object(permissions,'rows',side_effect=lambda *args:self.members),
                     patch.object(permissions,'active',return_value=True)):
            mock.start();self.addCleanup(mock.stop)

    def test_resolves_real_token_owner_without_relying_on_display_name(self):
        self.assertEqual(permissions.project_connection_group(),{'groupId':'connection-group','serviceUserId':'token-owner'})

    def test_missing_group_fails_before_creation(self):
        self.groups=[]
        with self.assertRaises(HTTPException) as error:permissions.project_connection_group()
        self.assertEqual(error.exception.status_code,409)

    def test_group_without_token_owner_is_rejected(self):
        self.members=[{'userId':'different-admin'}]
        with self.assertRaises(HTTPException) as error:permissions.project_connection_group()
        self.assertIn('API 키를 발급받은',error.exception.detail)

    def test_nested_membership_user_is_supported(self):
        self.members=[{'user':{'id':'token-owner'}}]
        self.assertEqual(permissions.project_connection_group()['serviceUserId'],'token-owner')

    def test_inactive_token_owner_is_rejected(self):
        with patch.object(permissions,'active',return_value=False):
            with self.assertRaises(HTTPException):permissions.project_connection_group()
