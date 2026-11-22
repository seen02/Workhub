import unittest
from unittest.mock import patch
from . import outline,main

class TeamTests(unittest.TestCase):
    def test_existing_membership_is_not_rewritten(self):
        with patch.object(outline,'all_items',return_value=[{'id':'u','email':'a@example.com'}]),patch.object(outline,'projects',return_value=[{'id':'p'}]),patch.object(outline,'api',return_value={'memberships':[{'userId':'u','permission':'read'}]}) as api:
            outline.ensure_member({'email':'a@example.com','admin':False})
            api.assert_not_called()

    def test_workhub_role_change_does_not_rewrite_outline_membership(self):
        with patch.object(outline,'all_items',return_value=[{'id':'u','email':'a@example.com'}]),patch.object(outline,'projects',return_value=[{'id':'p'}]),patch.object(outline,'api',return_value={'memberships':[{'userId':'u','permission':'admin'}]}) as api:
            outline.ensure_member({'email':'a@example.com','admin':False})
            api.assert_not_called()

    def test_stats_filters_items_inside_shared_task(self):
        task={'fields':{'owner':'lead@example.com','status':'진행 중','due':'미정','progress':'50%','blocker':'없음'},'criteria':[{'owner':'a@example.com','state':'예정'},{'owner':'b@example.com','state':'완료'}]}
        with patch.object(outline,'tasks',return_value=[task]),patch.object(outline,'history',return_value=[]),patch.object(main.store,'get',return_value=None):
            a=main.stats(owner='a@example.com',user={'admin':True})
            b=main.stats(owner='b@example.com',user={'admin':True})
        self.assertEqual(a['summary']['total'],1)
        self.assertEqual(a['criteria']['total'],1)
        self.assertEqual(a['criteria']['progress'],0)
        self.assertEqual(b['criteria']['progress'],100)
        self.assertEqual(set(a['criteria']['owners']),{'a@example.com'})
