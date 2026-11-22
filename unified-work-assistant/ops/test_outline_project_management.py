"""Run regression suites with dummy credentials and isolated test databases."""
import os, unittest
for key in ('OUTLINE_URL','OUTLINE_PUBLIC_URL','PUBLIC_URL','OIDC_ISSUER','CHAT_PUBLIC_URL','WEBUI_PUBLIC_URL'):
    os.environ[key]='http://fixture.invalid'
for key in ('OUTLINE_API_KEY','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET','AGENT_TOKEN'):
    os.environ[key]='fixture'
os.environ.pop('AUTHENTIK_DIRECTORY_TOKEN',None)
os.environ['OUTLINE_PROJECT_MANAGEMENT_ENABLED']='false'
os.environ['WORKHUB_DB']='/tmp/workhub-project-tests.sqlite3'
from workhub import store
store.init()
names=['test_outline_project_management','test_unlink','test_project_managers','test_permissions','test_security','test_hierarchy','test_analytics','test_reports','test_report_recovery','test_report_scope','test_report_submit_integration','test_confirmation']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('workhub.'+name) for name in names)
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
