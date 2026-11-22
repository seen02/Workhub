"""Cold-backup original data, restart original, restore ONLY new isolated volumes.

No original volume is removed/replaced. Recovery databases have no published port
and no network. Model caches are excluded (downloadable); employee/business data,
uploads, Redis revocation records, credentials/config and matching source are saved.
"""
import datetime,hashlib,json,os,pathlib,shutil,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
STAMP=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
PREFIX='workhub-accounts-recovery-'+STAMP
DEST=ROOT/'backups'/('accounts-'+STAMP)
def run(args):
    p=subprocess.run(args,cwd=ROOT,capture_output=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError(args[0]+' failed: '+p.stderr[-400:])
    return p.stdout
def compose(*args):return run(['docker','compose',*args])
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
ids=compose('ps','-aq').split()
rows=json.loads(run(['docker','inspect',*ids]));by={r['Config']['Labels']['com.docker.compose.service']:r for r in rows}
helper_image=by['workhub']['Image']
def helper(mounts,code,archive=None):
    args=['docker','run','--rm','--network','none','--user','0','--memory','256m','--memory-swap','512m','--label','workhub.operation=accounts-recovery']
    if archive:args+=['-i']
    for m in mounts:args+=['--mount',m]
    args+=['--entrypoint','python',helper_image,'-c',code]
    if not archive:return run(args)
    # Stream from Windows through stdin, avoiding large bind-file reads in Docker.
    with archive.open('rb') as f:p=subprocess.run(args,stdin=f,capture_output=True,cwd=ROOT)
    if p.returncode:raise RuntimeError('Recovery helper failed: '+p.stderr.decode('utf-8',errors='replace')[-400:])
    return p.stdout.decode('utf-8')
def sql(container,env,query):
    return run(['docker','exec',container,'psql','-U',env.get('POSTGRES_USER','postgres'),'-d',env.get('POSTGRES_DB',env.get('POSTGRES_USER','postgres')),'-At','-c',query]).strip()
def env_of(r):return dict(x.split('=',1) for x in r['Config']['Env'] if '=' in x)
queries={'postgres':'SELECT (SELECT count(*) FROM users),(SELECT count(*) FROM documents),(SELECT count(*) FROM collections);',
         'postgresql':'SELECT (SELECT count(*) FROM authentik_core_user),(SELECT count(*) FROM authentik_core_group);',
         'rag-postgres':'SELECT (SELECT count(*) FROM rag_documents),(SELECT count(*) FROM rag_chunks);'}
expected={s:sql(by[s]['Id'],env_of(by[s]),q) for s,q in queries.items()}
expected['mongodb']=run(['docker','exec',by['mongodb']['Id'],'mongosh','--quiet','--eval',"JSON.stringify({users:db.getSiblingDB('rocketchat').users.countDocuments({}),messages:db.getSiblingDB('rocketchat').rocketchat_message.countDocuments({})})"]).strip()
mounts={};refs={}
for service,row in by.items():
    for m in row['Mounts']:
        if m['Destination'] in ('/models','/root/.ollama') or service=='reverse-proxy':continue
        source=m.get('Name',m['Source'])
        if source not in refs:
            key='data-'+str(len(refs)+1);refs[source]=key
            mounts[key]={'type':m['Type'],'source':source,'services':[]}
        mounts[refs[source]]['services'].append({'service':service,'destination':m['Destination']})
resume=os.getenv('WORKHUB_RECOVERY_BACKUP')
if resume:
    DEST=pathlib.Path(resume).resolve()
    assert DEST.is_relative_to(ROOT/'backups') and (DEST/'manifest.json').is_file()
else:DEST.mkdir(parents=True)
manifest={'created':STAMP,'source_project':'unified-work-assistant','mounts':mounts,'expected':expected,
          'images':{s:r['Image'] for s,r in by.items()},'excluded':['downloadable Ollama and embedding model caches'],'restored':{},'checks':[]}
try:
    if resume:raise StopIteration
    print('Stopping original briefly for a consistent data backup',flush=True)
    compose('stop','--timeout','35','workhub','document-agent','outline','rocketchat','open-webui','authentik-server','authentik-worker','embedding-worker')
    # Measure after application writers stop, while database engines still run.
    for s,q in queries.items():expected[s]=sql(by[s]['Id'],env_of(by[s]),q)
    expected['mongodb']=run(['docker','exec',by['mongodb']['Id'],'mongosh','--quiet','--eval',"JSON.stringify({users:db.getSiblingDB('rocketchat').users.countDocuments({}),messages:db.getSiblingDB('rocketchat').rocketchat_message.countDocuments({})})"]).strip()
    compose('stop','--timeout','35')
    current=json.loads(run(['docker','inspect',*ids]));assert not any(r['State']['Running'] for r in current)
    running=run(['docker','ps','-q']).split()
    others=json.loads(run(['docker','inspect',*running])) if running else []
    assert not any(m.get('RW') and m.get('Name',m['Source']) in refs for r in others for m in r['Mounts']),'Another container can write a backup source'
    for key,m in mounts.items():
        print('Backing up',key,[x['service'] for x in m['services']],flush=True)
        source=f"type={m['type']},source={m['source']},target=/source,readonly"
        helper([source,f'type=bind,source={DEST},target=/backup'],"import tarfile; t=tarfile.open('/backup/"+key+".tar.gz','w:gz',compresslevel=1); t.add('/source',arcname='.'); t.close()")
        m['archive']=key+'.tar.gz';m['sha256']=digest(DEST/m['archive'])
    shutil.copy2(ROOT/'.local/compose.json',DEST/'compose.private.json')
    shutil.copytree(ROOT/'config',DEST/'config')
    shutil.copytree(ROOT/'src/workhub',DEST/'source/workhub',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'src/document-agent',DEST/'source/document-agent',ignore=shutil.ignore_patterns('__pycache__','data'))
    manifest['checks'].append('original stopped; all business-data mounts cold-backed-up')
except StopIteration:
    manifest=json.loads((DEST/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['images']=={s:r['Image'] for s,r in by.items()},'Backup image versions must match'
    mounts=manifest['mounts'];expected=manifest['expected'];manifest['restored']={};manifest['checks']=manifest['checks'][:1]
    print('Resuming isolated restore from existing verified backup; original stays running',flush=True)
finally:
    if not resume:
        compose('up','-d','--no-build')
        print('Original services restarted; isolated restore follows',flush=True)
recovery=[]
try:
    for key,m in mounts.items():
        assert digest(DEST/m['archive'])==m['sha256']
        name=PREFIX+'-'+key
        existing=run(['docker','volume','ls','--format','{{.Name}}']).splitlines()
        assert name not in existing,'Only a NEW recovery volume is allowed'
        run(['docker','volume','create','--label','workhub.operation=accounts-recovery',name])
        print('Restoring',key,flush=True)
        helper([f'type=volume,source={name},target=/restore'],
               "import tarfile,os,sys; assert not os.listdir('/restore'); t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); t.extractall('/restore',filter='tar'); t.close()",DEST/m['archive'])
        # Verify every regular file byte-for-byte before starting database engines.
        result=helper([f'type=volume,source={name},target=/restore,readonly'],
            "import tarfile,hashlib,pathlib,sys\ndef sha(f):\n h=hashlib.sha256()\n for block in iter(lambda:f.read(1024*1024),b''):h.update(block)\n return h.hexdigest()\nt=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); n=0\nfor m in t:\n if m.isfile():\n  a=sha(t.extractfile(m))\n  with (pathlib.Path('/restore')/m.name).open('rb') as f:b=sha(f)\n  assert a==b,m.name; n+=1\nprint(n)",DEST/m['archive'])
        manifest['restored'][key]={'volume':name,'verified_files':int(result.strip())}
        if any(x['service'] in ('workhub','document-agent','open-webui') for x in m['services']):
            integrity=helper([f'type=volume,source={name},target=/restore'],
                "import pathlib,sqlite3,json; d={}\nfor p in pathlib.Path('/restore').rglob('*'):\n if p.is_file() and p.suffix in ('.db','.sqlite3'):\n  c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True); v=c.execute('PRAGMA integrity_check').fetchone()[0]; assert v=='ok'; d[p.name]=v;c.close()\nprint(json.dumps(d))")
            manifest['restored'][key]['sqlite_integrity']=json.loads(integrity)
    manifest['checks'].append('all archived files restored byte-identical; SQLite integrity passes')
    for service in (*queries,'mongodb'):
        row=by[service];name=PREFIX+'-'+service;recovery.append(name)
        envfile=DEST/(service+'.env.private');envfile.write_text('\n'.join(row['Config']['Env'])+'\n',encoding='utf-8')
        args=['docker','run','-d','--network','none','--name',name,'--label','workhub.operation=accounts-recovery','--env-file',str(envfile)]
        for key,m in mounts.items():
            for ref in m['services']:
                if ref['service']==service:args+=['--mount',f"type=volume,source={manifest['restored'][key]['volume']},target={ref['destination']}"]
        args+=[row['Image']]
        args+=(['mongod','--bind_ip','127.0.0.1','--noauth'] if service=='mongodb' else (row['Config'].get('Cmd') or []))
        run(args)
        for attempt in range(45):
            try:
                value=sql(name,env_of(row),queries[service]) if service in queries else run(['docker','exec',name,'mongosh','--quiet','--eval',"JSON.stringify({users:db.getSiblingDB('rocketchat').users.countDocuments({}),messages:db.getSiblingDB('rocketchat').rocketchat_message.countDocuments({})})"]).strip()
                break
            except RuntimeError:
                if attempt==44:raise
                time.sleep(1)
        assert value==expected[service],service+' record count mismatch'
        manifest['checks'].append(service+' restored engine starts and record counts match')
        print('PASS restored database',service,flush=True)
finally:
    for name in recovery:
        try:run(['docker','stop','--time','15',name])
        except RuntimeError:pass
    write(DEST/'manifest.json',manifest)
    write(ROOT/'reports/accounts-recovery-verification.json',{'backup':str(DEST),'checks':manifest['checks'],'expected':expected,'recovery_prefix':PREFIX,'volumes':len(mounts),'original_restarted':True})
print('Backup and isolated restore verified:',DEST,flush=True)
