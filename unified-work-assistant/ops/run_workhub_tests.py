"""Full Workhub regression suite; dummy endpoints and a temporary database only."""
import logging
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'src'
test_root = source if (source / 'workhub').is_dir() else Path('/app')
sys.path.insert(0,str(test_root))
legacy = source / 'report-agent/backend/app'
if legacy.is_dir():
    spec = importlib.util.spec_from_file_location('legacy_app', legacy / '__init__.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['legacy_app'] = module
    spec.loader.exec_module(module)

for key in ('OUTLINE_URL','OUTLINE_PUBLIC_URL','PUBLIC_URL','OIDC_ISSUER','CHAT_PUBLIC_URL','WEBUI_PUBLIC_URL'):
    os.environ[key]='http://fixture.invalid'
for key in ('OUTLINE_API_KEY','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET','AGENT_TOKEN'):
    os.environ[key]='fixture'
os.environ.pop('AUTHENTIK_DIRECTORY_TOKEN',None)
os.environ['OUTLINE_PROJECT_MANAGEMENT_ENABLED']='false'
os.environ['OUTLINE_AI_SEARCH_ENABLED']='false'
os.environ['ROCKETCHAT_KNOWLEDGE_ENABLED']='false'
with tempfile.TemporaryDirectory() as folder:
    os.environ['WORKHUB_DB']=folder+'/tests.sqlite3'
    from workhub import store
    store.init()
    names = sys.argv[1:]
    suite = (unittest.defaultTestLoader.loadTestsFromNames(names) if names else
             unittest.defaultTestLoader.discover(str(test_root / 'workhub'),top_level_dir=str(test_root)))
    logging.getLogger().setLevel(logging.WARNING)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
