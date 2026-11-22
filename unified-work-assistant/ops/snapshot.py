import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
phase=sys.argv[1]
prefix='outline' if phase=='before' else 'unified-work-assistant'
def run(args):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError('Snapshot command failed: '+p.stderr[-300:])
    return p.stdout
def counts(container,user,db,tables):
    sql=' UNION ALL '.join(f'SELECT \'{t}\',count(*) FROM "{t}"' for t in tables)
    rows=run(['docker','exec',container,'psql','-U',user,'-d',db,'-At','-c',sql]).strip().splitlines()
    return {k:int(v) for k,v in (r.split('|') for r in rows)}
containers={
 'outline':f'{prefix}-postgres-1',
 'auth':('outline-authentik-postgresql-1' if phase=='before' else prefix+'-postgresql-1'),
 'rag':('outline-ai-rag-postgres-1' if phase=='before' else prefix+'-rag-postgres-1'),
 'webui':('outline-ai-open-webui-1' if phase=='before' else prefix+'-open-webui-1'),
 'agent':('outline-ai-document-agent-1' if phase=='before' else prefix+'-document-agent-1')}
data={
 'outline':counts(containers['outline'],'outline','outline',['documents','revisions','collections','users','attachments']),
 'authentik':counts(containers['auth'],'authentik','authentik',['authentik_core_user','authentik_core_application']),
 'rag':counts(containers['rag'],'rag','rag',['rag_documents','rag_chunks'])}
for name,path,tables in [('webui','/app/backend/data/webui.db',['chat','user','model','tool']),('agent','/app/data/agent.sqlite3',['drafts','events','research','files'])]:
    code=f"import sqlite3,json; c=sqlite3.connect('file:{path}?mode=ro',uri=True); print(json.dumps({{t:c.execute('select count(*) from '+t).fetchone()[0] for t in {tables!r}}}))"
    data[name]=json.loads(run(['docker','exec',containers[name],'python','-c',code]))
dest=ROOT/'.local'/f'snapshot-{phase}.json';dest.write_text(json.dumps(data,indent=2),encoding='utf-8')
if phase=='before':
    backup=ROOT/'backups/pre-migration';backup.mkdir(parents=True,exist_ok=True)
    for name,user,db in [('outline','outline','outline'),('auth','authentik','authentik'),('rag','rag','rag')]:
        run(['docker','exec',containers[name],'pg_dump','-U',user,'-d',db,'-Fc','-f','/tmp/unified-migration.dump'])
        run(['docker','cp',containers[name]+':/tmp/unified-migration.dump',str(backup/(name+'.dump'))])
else:
    before=json.loads((ROOT/'.local/snapshot-before.json').read_text())
    assert data==before,{'before':before,'after':data}
print(json.dumps({'phase':phase,'counts':data,'matched':phase!='before'},ensure_ascii=False))
