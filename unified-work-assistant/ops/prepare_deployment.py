"""Create a relocatable release from the STOPPED integration stack; never alters its volumes."""
import argparse, copy, datetime, hashlib, json, pathlib, re, shutil, subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
DEPLOY=ROOT/'deployment'
def run(args):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError('Docker preparation command failed; credentials are not printed.')
    return p.stdout
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    global DEPLOY
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--destination',type=pathlib.Path,default=DEPLOY)
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9]{8}-[0-9]+',args.version):raise ValueError('Expected YYYYMMDD-N release version.')
    DEPLOY=args.destination.resolve()
    if not DEPLOY.is_relative_to(ROOT):raise ValueError('Stage the release inside the repository.')
    if (DEPLOY/'release.json').exists():raise RuntimeError('Release already exists; use a new staging directory.')
    DEPLOY.mkdir(parents=True,exist_ok=True)
    source=read(ROOT/'.local/compose.json')
    ids=run(['docker','compose','-f',str(ROOT/'compose.yml'),'ps','-aq']).split()
    if not ids:raise RuntimeError('Original integration containers were not found.')
    current=json.loads(run(['docker','inspect',*ids]))
    if any(c['State']['Running'] for c in current):raise RuntimeError('Stop source containers before preparing release.')
    byservice={c['Config']['Labels']['com.docker.compose.service']:c for c in current}
    required={name for name,service in source['services'].items() if not service.get('profiles')}
    if len(byservice)!=len(current) or not required.issubset(byservice) or not set(byservice).issubset(source['services']):raise RuntimeError('Source services are missing or duplicated.')
    if any(c['Config']['Labels'].get('com.docker.compose.project')!='unified-work-assistant' for c in current):raise RuntimeError('Unexpected source project.')
    preserved={'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'project':'unified-work-assistant',
        'containers':[{'id':c['Id'],'name':c['Name'].lstrip('/'),'service':c['Config']['Labels']['com.docker.compose.service'],
                       'image':c['Image'],'state':c['State']['Status'],'mounts':c['Mounts']} for c in current]}
    cfg={'services':{},'networks':copy.deepcopy(source['networks']),'volumes':{}}
    private={};example={};images={};mounts={};bind_keys={};version=args.version
    for name in byservice:
        s=copy.deepcopy(source['services'][name]);c=byservice[name]
        s.pop('build',None);s.pop('profiles',None);s.pop('container_name',None)
        tag=f'workhub-release/{name}:{version}';run(['docker','image','tag',c['Image'],tag]);images[tag]=c['Image'];s['image']=tag
        s['logging']={'driver':'json-file','options':{'max-size':'10m','max-file':'3'}}
        s['stop_grace_period']='45s'
        s['restart']='unless-stopped'
        env=s.get('environment') or {}
        if isinstance(env,list):env=dict(v.split('=',1) if '=' in v else (v,'') for v in env)
        # Capture values after Compose expansion. Reusing the source's escaped $$
        # values inside a substituted environment variable would change secrets.
        actual_env=dict(v.split('=',1) for v in c['Config']['Env'] if '=' in v)
        if any(key not in actual_env for key in env):raise RuntimeError('Configured environment missing from source container.')
        env={key:actual_env[key] for key in env}
        replacement={}
        for key,val in env.items():
            token='DH_'+re.sub('[^A-Z0-9_]','_',name.upper())+'_'+key
            if isinstance(val,bool):val=str(val).lower()
            val='' if val is None else str(val);private[token]=val
            replacement[key]='${'+token+'?Missing private deployment setting}'
            sensitive=bool(re.search('SECRET|PASSWORD|PASS$|TOKEN|KEY$|DATABASE_URL|MONGO_URL|CLIENT_ID',key))
            example[token]='<private value required>' if sensitive else val
        s['environment']=replacement
        # Docker Desktop supplies this hostname; Linux Docker needs an explicit gateway mapping.
        if any('host.docker.internal' in str(v) for v in env.values()):
            s['extra_hosts']=['host.docker.internal:host-gateway']
        newmounts=[]
        for m in s.get('volumes',[]):
            actual=next(x for x in c['Mounts'] if x['Destination']==m['target'])
            if actual['Type']=='bind' and pathlib.Path(actual['Source']).is_file():
                if m['target']!='/etc/nginx/conf.d/default.conf':raise RuntimeError('Unexpected bind file')
                (DEPLOY/'config').mkdir(exist_ok=True);shutil.copy2(actual['Source'],DEPLOY/'config/nginx.conf')
                newmounts.append({'type':'bind','source':'./config/nginx.conf','target':m['target'],'read_only':True});continue
            if actual['Type']=='volume':key=m['source'];kind='volume';origin=actual['Name']
            else:
                origin=actual['Source'];kind='bind'
                if origin not in bind_keys:
                    key='workhub-data' if name=='workhub' else 'document-agent-data' if name=='document-agent' else 'authentik-'+m['target'].strip('/').replace('/','-')
                    bind_keys[origin]=key
                key=bind_keys[origin]
            if key in mounts and mounts[key]!={'kind':kind,'source':origin}:raise RuntimeError('Duplicate backup key')
            mounts[key]={'kind':kind,'source':origin}
            cfg['volumes'][key]={'external':True,'name':'${COMPOSE_PROJECT_NAME}_'+key}
            newmounts.append({'type':'volume','source':key,'target':m['target'],**({'read_only':True} if m.get('read_only') else {})})
        s['volumes']=newmounts
        cfg['services'][name]=s
    # Health checks for services that previously had only a running-process signal.
    for i,(key,network) in enumerate(cfg['networks'].items()):
        network['name']='${COMPOSE_PROJECT_NAME}_isolated_'+key
        network['ipam']={'config':[{'subnet':'${DH_NETWORK_'+str(i)+'?Missing deployment subnet}'}]}
    cfg['services']['ollama']['healthcheck']={'test':['CMD','ollama','list'],'interval':'30s','timeout':'10s','retries':5,'start_period':'30s'}
    cfg['services']['reverse-proxy'].setdefault('healthcheck',{'test':['CMD-SHELL','wget -q -O /dev/null http://127.0.0.1/'],'interval':'30s','timeout':'10s','retries':5,'start_period':'60s'})
    # Preserve vendor-provided checks for the remaining services.
    release={'version':version,'architecture':'linux/amd64','images':images,
        'helper_image':f'workhub-release/document-agent:{version}',
        'services':sorted(cfg['services']),'restore_mode':'cold volume snapshot with exact images',
        'source_project':preserved['project']}
    write(DEPLOY/'compose.json',cfg);write(DEPLOY/'release.json',release)
    write(DEPLOY/'.private/environment.json',private);write(DEPLOY/'environment.example.json',example)
    recipe={'source_project':preserved['project'],'container_ids':[c['id'] for c in preserved['containers']],'mounts':mounts}
    write(DEPLOY/'.private/source-backup-recipe.json',recipe)
    write(DEPLOY/'.private/preserved-containers.json',preserved)
    code={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for base in ('src/workhub','src/document-agent') for p in (ROOT/base).rglob('*')
          if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.css','.html','.sql')}
    write(DEPLOY/'source-manifest.json',{'captured_at':preserved['captured_at'],'version':version,'files':code})
    print(json.dumps({'services':len(cfg['services']),'data_volumes':len(mounts),'release':version,'original_containers':'stopped and unchanged'}))
if __name__=='__main__':main()
