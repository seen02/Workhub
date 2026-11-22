import json, os, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone

LOCK = threading.RLock()
DB = os.getenv('WORKHUB_DB','/app/data/workhub.sqlite3')
def now(): return datetime.now(timezone.utc).isoformat()
def dump(v): return json.dumps(v, ensure_ascii=False)
@contextmanager
def db():
    with LOCK:
        c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()
def init():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,body TEXT NOT NULL,source_key TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,doc_id TEXT NOT NULL,source_key TEXT NOT NULL,observed TEXT NOT NULL,actor TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(doc_id,source_key));
        ''')
    from . import project_service
    project_service.init()
    if get('projects') is None:put('projects',[])
def get(k,default=None):
    with db() as c:r=c.execute('SELECT v FROM kv WHERE k=?',(k,)).fetchone()
    return json.loads(r[0]) if r else default
def put(k,v):
    with db() as c:c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(k,dump(v)))
