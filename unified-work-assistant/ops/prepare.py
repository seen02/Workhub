"""Prepare a separate Compose workspace without mutating running services.

Resolved configuration, including secrets, is saved only under .local.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent
OLD = WORK / 'Outline'
REPORT = WORK / 'ai-agent-main' / 'ai-agent-main'
LOCAL = ROOT / '.local'

def run(args):
    p = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(f'{args[0]} command failed, exit {p.returncode}')
    return p.stdout

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def resolved(path):
    args = ['docker', 'compose']
    if (path.parent / '.env').exists():
        args += ['--env-file', str(path.parent / '.env')]
    return json.loads(run(args + ['-f', str(path), '--profile', '*', 'config', '--format', 'json']))

def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    if (LOCAL / 'migration.json').exists() and json.loads((LOCAL/'migration.json').read_text(encoding='utf-8'))['status']!='prepared':
        raise RuntimeError('Migration already started. Do not overwrite the migration baseline.')
    source_manifest = []
    for source, dest in [(OLD/'local-ai', ROOT/'src/document-agent'), (REPORT, ROOT/'src/report-agent')]:
        if not dest.exists():
            shutil.copytree(source, dest, ignore=shutil.ignore_patterns('.env', '.local', 'data', '__pycache__', '.venv', 'node_modules', '*.log', '.git', 'backups'), dirs_exist_ok=False)
        source_manifest.append({'source':str(source), 'copy':str(dest)})
    ids = run(['docker','ps','-aq']).split()
    live = json.loads(run(['docker','inspect',*ids]))
    projects = {'outline','outline-ai','outline-authentik'}
    live = [c for c in live if c['Config'].get('Labels',{}).get('com.docker.compose.project') in projects]
    by_service = {(c['Config']['Labels']['com.docker.compose.project'],c['Config']['Labels']['com.docker.compose.service']):c for c in live}
    write(LOCAL/'original-containers.json',live)
    configs = {'outline': resolved(OLD/'compose.yml'), 'outline-ai':resolved(OLD/'local-ai/compose.yml'), 'outline-authentik':resolved(OLD/'authentik/compose.yml')}
    write(LOCAL/'original-compose.json',configs)
    combined={'name':'unified-work-assistant','services':{},'networks':{},'volumes':{}}
    volume_map={}; bindings={}; original_names=[]
    for project, cfg in configs.items():
        rename={'server':'authentik-server','worker':'authentik-worker'} if project=='outline-authentik' else {}
        nets={key:('outline-net' if value.get('name')=='outline_default' else project+'-net') for key,value in cfg.get('networks',{}).items()}
        for net in nets.values(): combined['networks'].setdefault(net,{})
        volumes={}
        for key, value in cfg.get('volumes',{}).items():
            actual=[]
            for svc, definition in cfg['services'].items():
                current=by_service.get((project,svc))
                if current:
                    for mount in definition.get('volumes',[]):
                        if mount['type']=='volume' and mount['source']==key:
                            actual.extend(m['Name'] for m in current['Mounts'] if m['Type']=='volume' and m['Destination']==mount['target'])
            if len(set(actual))!=1:raise RuntimeError(f'Cannot resolve live volume {project}/{key}')
            old=actual[0]
            newkey=project+'-'+key
            new='unified-work-assistant_'+newkey
            volume_map[old]=new
            volumes[key]=newkey
            combined['volumes'][newkey]={'name':new,'external':True}
        for name, original in cfg['services'].items():
            item=copy.deepcopy(original)
            current=by_service.get((project,name))
            if not current: raise RuntimeError(f'Missing existing container: {project}/{name}')
            original_names.append(current['Name'].lstrip('/'))
            item.pop('profiles',None);item.pop('container_name',None)
            # The baseline uses the exact locally running image, with a human-readable pin.
            tag='unified-work-assistant/'+rename.get(name,name)+':migration-baseline'
            run(['docker','tag',current['Image'],tag]);item['image']=tag
            if name=='document-agent':item['build']={'context':str(ROOT/'src/document-agent')}
            if name=='embedding-worker':item['build']={'context':str(ROOT/'src/document-agent'),'dockerfile':'Dockerfile.embedding'}
            if 'depends_on' in item:item['depends_on']={rename.get(k,k):v for k,v in item['depends_on'].items()}
            item['networks']={nets[k]:v for k,v in item.get('networks',{'default':None}).items()}
            newvols=[]
            for mount in item.get('volumes',[]):
                if mount['type']=='volume':mount['source']=volumes[mount['source']]
                else:
                    src=Path(mount['source'])
                    if src==OLD/'nginx.conf':dest=ROOT/'config/nginx.conf'
                    elif src==OLD/'local-ai/data':dest=ROOT/'runtime/document-agent'
                    elif src.is_relative_to(OLD/'authentik'):dest=ROOT/'runtime/authentik'/src.relative_to(OLD/'authentik')
                    else:raise RuntimeError(f'Unexpected bind mount {src}')
                    bindings[str(src)]=str(dest)
                    mount['source']=str(dest)
                newvols.append(mount)
            item['volumes']=newvols
            combined['services'][rename.get(name,name)]=item
    # Preserve DNS used by existing Outline OIDC URLs.
    combined['services']['authentik-server']['networks']['outline-net']={'aliases':['authentik-server']}
    # One loaded model and one inference at a time; no WSL memory increase.
    combined['services']['ollama']['environment']['OLLAMA_KEEP_ALIVE']='60s'
    combined['services']['ollama']['environment']['OLLAMA_MAX_LOADED_MODELS']='1'
    combined['services']['ollama']['environment']['OLLAMA_NUM_PARALLEL']='1'
    combined['services']['document-agent']['environment']['OUTLINE_URL']='http://host.docker.internal:8090/api'
    write(LOCAL/'compose.json',combined)
    migration={'project':'unified-work-assistant','original_containers':original_names,'volumes':volume_map,'bindings':bindings,'source_copies':source_manifest,'status':'prepared'}
    write(LOCAL/'migration.json',migration)
    print(json.dumps({'services':len(combined['services']),'volumes':len(volume_map),'binds':len(bindings),'source_copies':source_manifest},ensure_ascii=False))

if __name__=='__main__':main()
