import json,pathlib,tempfile,unittest
from unittest.mock import patch
import manage
import backup_cycle

class DeploymentSafety(unittest.TestCase):
    def test_original_project_is_not_an_allowed_target(self):
        for name in ('unified-work-assistant','outline','../workhub-server','workhub-server;rm','WORKHUB-server'):
            with self.assertRaises(ValueError):manage.project_name(name)
    def test_managed_names(self):
        self.assertEqual(manage.volume_name('workhub-server','workhub-data'),'workhub-server_workhub-data')
        with self.assertRaises(ValueError):manage.volume_name('workhub-server','../../data')
    def test_project_networks_avoid_current_lan(self):
        from ipaddress import ip_network
        a=manage.network_subnets('workhub-server');b=manage.network_subnets('workhub-restore-check')
        self.assertEqual(a,manage.network_subnets('workhub-server'))
        self.assertTrue(all(not ip_network(x).overlaps(ip_network('192.168.0.0/16')) for x in a+b))
        self.assertTrue(all(not ip_network(x).overlaps(ip_network(y)) for x in a for y in b))
    def test_active_containers_prevent_snapshot(self):
        with self.assertRaises(RuntimeError):manage.stopped([{'State':{'Running':True}}])
    def test_checksums_detect_damage(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);(root/'data.tar').write_bytes(b'backup')
            manage.write(root/'manifest.json',{'volumes':{'v':{'file':'data.tar','sha256':manage.sha(root/'data.tar')}},'files':{}})
            manage.verify_backup(root);(root/'data.tar').write_bytes(b'changed')
            with self.assertRaises(RuntimeError):manage.verify_backup(root)
    def test_manifest_cannot_escape_backup_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);manage.write(root/'manifest.json',{'volumes':{},'files':{'../outside':'x'}})
            with self.assertRaises(RuntimeError):manage.verify_backup(root)
    def test_configuration_mismatch_prevents_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);package=root/'package';saved=root/'backup'
            (package/'.private').mkdir(parents=True);saved.mkdir()
            (package/'compose.json').write_text('current')
            (saved/'compose.json').write_text('different')
            (package/'.private/environment.json').write_text('private')
            (saved/'environment.private.json').write_text('private')
            with patch.object(manage,'ROOT',package),patch.object(manage,'PRIVATE',package/'.private'):
                with self.assertRaises(RuntimeError):manage.matching_configuration(saved)
    def test_nonempty_restore_target_is_rejected_before_extraction(self):
        manifest={'volumes':{'workhub-data':{'file':'workhub-data.tar'}},'release':{'images':{}}}
        with patch.object(manage,'containers',return_value=[]),patch.object(manage,'verify_backup',return_value=manifest),\
             patch.object(manage,'matching_configuration'),\
             patch.object(manage,'read',side_effect=[{'volumes':{'workhub-data':{}}},{'images':{}}]),\
             patch.object(manage.subprocess,'run',return_value=type('Result',(),{'returncode':0})()),\
             patch.object(manage,'helper',side_effect=RuntimeError('not empty')) as helper:
            with self.assertRaises(RuntimeError):manage.restore('workhub-rehearsal','backup')
            self.assertEqual(helper.call_count,1)
    def test_backup_failure_still_attempts_restart(self):
        with patch('sys.argv',['backup_cycle.py','--project','workhub-server']),\
             patch.object(manage,'status',return_value={'ok':True}),\
             patch.object(manage,'compose'),patch.object(manage,'backup',side_effect=RuntimeError('disk full')),\
             patch.object(manage,'start') as start:
            with self.assertRaises(RuntimeError):backup_cycle.main()
            start.assert_called_once_with('workhub-server')

if __name__=='__main__':unittest.main()
