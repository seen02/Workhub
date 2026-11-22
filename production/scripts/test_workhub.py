"""Run regressions in temporary SQLite databases without starting services."""
import os
import io
import json
import logging
import pathlib
import sys
import tempfile
import unittest

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'workhub/src'))
os.environ.setdefault('OUTLINE_URL', 'http://fixture.invalid')
os.environ.setdefault('OUTLINE_PUBLIC_URL', 'http://outline.custom-outline.test:18880')
os.environ.setdefault('OUTLINE_API_KEY', 'fixture-only')
temp = tempfile.TemporaryDirectory()
os.environ['WORKHUB_DB'] = str(pathlib.Path(temp.name) / 'default.sqlite3')
from workhub import store
store.init()
logging.disable(logging.CRITICAL)
suite = unittest.defaultTestLoader.discover(str(root / 'workhub/src/workhub'), 'test_*.py', str(root / 'workhub/src'))
compact = '--compact' in sys.argv
result = unittest.TextTestRunner(stream=io.StringIO() if compact else sys.stderr, verbosity=2).run(suite)
if compact:
    print(json.dumps({'tests': result.testsRun, 'failures': [(str(t),e.splitlines()[-1]) for t,e in result.failures],
                      'errors': [(str(t),e.splitlines()[-1]) for t,e in result.errors]}, ensure_ascii=False))
raise SystemExit(0 if result.wasSuccessful() else 1)
