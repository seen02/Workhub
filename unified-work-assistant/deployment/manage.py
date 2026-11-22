"""Portable Docker deployment operations. Python 3.10+, Docker Compose v2.

Never deletes data volumes. Restore only accepts new, empty target volumes.
Commands operate exclusively on workhub-* projects, never the preserved development stack.
Compose may recreate deployment containers when their configuration changes.
"""
import argparse, datetime, hashlib, ipaddress, json, os, pathlib, re, shutil, subprocess, sys, time, urllib.request

ROOT=pathlib.Path(__file__).resolve().parent
PRIVATE=ROOT/'.private'

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(path):return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def write(path,obj):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def run(args,env=None):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace',env=env)
    if p.returncode:
        # Command output can include expanded secrets. Do not echo arguments or stdout.
        raise RuntimeError(f'{args[0]} failed (exit {p.returncode}); see Docker service status/logs locally.')
    return p.stdout
def project_name(value):
    if not re.fullmatch(r'workhub-[a-z0-9][a-z0-9-]{0,40}',value):
        raise ValueError('Use a separate workhub-* project, e.g. workhub-rehearsal or workhub-server.')
    return value
def network_subnets(project):
    # Small, deterministic per-project ranges avoid Docker's automatic 192.168 LAN overlap.
    octet=int(hashlib.sha256(project_name(project).encode()).hexdigest()[:4],16)%256
    return [f'10.240.{octet}.{i*32}/27' for i in range(len(read(ROOT/'compose.json')['networks']))]
def compose(project,*args):
    env=os.environ.copy();env.update({k:str(v) for k,v in read(PRIVATE/'environment.json').items()})
    env.update({'DH_NETWORK_'+str(i):s for i,s in enumerate(network_subnets(project))})
    return run(['docker','compose','-p',project_name(project),'-f',str(ROOT/'compose.json'),*args],env)
def containers(project):
    ids=compose(project,'ps','-aq').split()
    return json.loads(run(['docker','inspect',*ids])) if ids else []
def stopped(rows):
    if any(c['State']['Running'] for c in rows):raise RuntimeError('Stop the project before backup or restore.')
def helper_image():return read(ROOT/'release.json')['helper_image']
def helper(mounts,code,archive=None):
    args=['docker','run','--rm','--network','none','--memory','256m','--memory-swap','512m','--label','workhub.operation=backup-restore']
    if archive:args.append('-i')
    for mount in mounts:args+=['--mount',mount]
    args+=['--entrypoint','python',helper_image(),'-c',code]
    if not archive:return run(args)
    # Stream large backups from the host instead of memory-mapping Docker Desktop bind files.
    with pathlib.Path(archive).open('rb') as stream:
        result=subprocess.run(args,stdin=stream,capture_output=True)
    if result.returncode:raise RuntimeError('Backup extraction helper failed; inspect the local operation.')
    return result.stdout.decode('utf-8')
def archive_mount(kind,source,destination):
    dest=pathlib.Path(destination).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    if kind=='volume':run(['docker','volume','inspect',source])
    if ',' in str(source) or ',' in str(dest.parent):raise ValueError('Docker mount paths must not contain commas.')
    code="import tarfile; t=tarfile.open('/backup/"+dest.name+"','w'); t.add('/source',arcname='.'); t.close()"
    helper([f'type={kind},source={source},target=/source,readonly',f'type=bind,source={dest.parent},target=/backup'],code)
    return {'file':dest.name,'bytes':dest.stat().st_size,'sha256':sha(dest)}
def no_live_writers(sources):
    ids=run(['docker','ps','-q']).split()
    rows=json.loads(run(['docker','inspect',*ids])) if ids else []
    for row in rows:
        if any((m.get('Name') if m['Type']=='volume' else m['Source']) in sources and m.get('RW') for m in row['Mounts']):
            raise RuntimeError('A running container can still write the snapshot source. Stop it first.')
def source_backup(recipe_path,dest):
    recipe=read(recipe_path);ids=recipe['container_ids'];stopped(json.loads(run(['docker','inspect',*ids])))
    no_live_writers({m['source'] for m in recipe['mounts'].values()})
    return make_backup(recipe['mounts'],dest,recipe['source_project'])
def make_backup(mounts,dest,project):
    dest=pathlib.Path(dest).resolve()
    if dest.exists() and any(dest.iterdir()):raise RuntimeError('Backup destination must be empty.')
    dest.mkdir(parents=True,exist_ok=True)
    manifest={'format':1,'created_at':now(),'source_project':project,'release':read(ROOT/'release.json'),'volumes':{}}
    for key,m in mounts.items():
        print('Backing up:',key,flush=True)
        manifest['volumes'][key]=archive_mount(m['kind'],m['source'],dest/(key+'.tar'))
    # Backup the matching code/configuration, not only database files.
    shutil.copy2(ROOT/'compose.json',dest/'compose.json')
    shutil.copy2(ROOT/'release.json',dest/'release.json')
    shutil.copytree(ROOT/'config',dest/'config',dirs_exist_ok=True)
    shutil.copy2(PRIVATE/'environment.json',dest/'environment.private.json')
    manifest['files']={str(p.relative_to(dest)).replace('\\','/'):sha(p) for p in dest.rglob('*') if p.is_file() and p.suffix!='.tar'}
    write(dest/'manifest.json',manifest);print('Backup complete:',dest,flush=True)
    return manifest
def verify_backup(dest):
    dest=pathlib.Path(dest).resolve();m=read(dest/'manifest.json')
    expected={v['file']:v['sha256'] for v in m['volumes'].values()};expected.update(m['files'])
    for name,digest in expected.items():
        p=(dest/name).resolve()
        if not p.is_relative_to(dest) or not p.is_file() or sha(p)!=digest:raise RuntimeError('Backup checksum mismatch: '+name)
    return m
def volume_name(project,key):
    if not re.fullmatch('[a-z0-9_-]+',key):raise ValueError('Invalid volume key')
    return project_name(project)+'_'+key

def matching_configuration(backup):
    pairs=[(ROOT/'compose.json',backup/'compose.json'),
           (PRIVATE/'environment.json',backup/'environment.private.json')]
    pairs.extend((ROOT/'config'/p.relative_to(backup/'config'),p) for p in (backup/'config').rglob('*') if p.is_file())
    if any(not current.is_file() or sha(current)!=sha(saved) for current,saved in pairs):
        raise RuntimeError('Configuration differs from backup. Use its matching compose.json, config/ and private environment before restoring.')
def restore(project,backup):
    project_name(project);stopped(containers(project));backup=pathlib.Path(backup).resolve()
    m=verify_backup(backup);cfg=read(ROOT/'compose.json')
    if m['release']['images']!=read(ROOT/'release.json')['images']:
        raise RuntimeError('Use the matching release package for this backup.')
    if set(m['volumes'])!=set(cfg['volumes']):raise RuntimeError('Backup and Compose volume definitions differ.')
    matching_configuration(backup)
    targets=[]
    for key in m['volumes']:
        name=volume_name(project,key)
        exists=subprocess.run(['docker','volume','inspect',name],capture_output=True).returncode==0
        if exists:
            helper([f'type=volume,source={name},target=/target,readonly'],"import os; assert not os.listdir('/target'), 'Restore target is not empty'")
        targets.append((key,name,exists))
    # All targets are checked before any extraction. Original volume names are never used.
    for key,name,exists in targets:
        if not exists:run(['docker','volume','create','--label','workhub.managed=true','--label','workhub.project='+project,name])
        print('Restoring:',key,flush=True)
        archive=m['volumes'][key]['file']
        if not re.fullmatch('[a-z0-9_-]+[.]tar',archive):raise ValueError('Invalid archive name')
        code="import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|*'); t.extractall('/target',filter='tar'); t.close()"
        helper([f'type=volume,source={name},target=/target'],code,archive=backup/archive)
    # Workhub identities cache refresh tokens; require fresh sign-in after restoration.
    helper([f'type=volume,source={volume_name(project,"workhub-data")},target=/target'],
        "import sqlite3,pathlib; p=pathlib.Path('/target/workhub.sqlite3'); c=sqlite3.connect(p) if p.exists() else None; c and c.execute('DELETE FROM sessions'); c and c.execute('DELETE FROM identities'); c and c.commit(); c and c.close()")
    write(PRIVATE/(project+'-restored.json'),{'at':now(),'backup':str(backup),'volumes':[n for _,n,_ in targets]})
    print('Restored. Workhub users must sign in again. No source volume was modified.')
def export_images(dest):
    dest=pathlib.Path(dest).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    images=read(ROOT/'release.json')['images'];print('Exporting',len(images),'release images...',flush=True)
    run(['docker','image','save','-o',str(dest),*images])
    write(str(dest)+'.manifest.json',{'file':dest.name,'sha256':sha(dest),'bytes':dest.stat().st_size,'images':images})
    print('Image archive complete:',dest,flush=True)
def load_images(path):
    path=pathlib.Path(path).resolve();m=read(str(path)+'.manifest.json')
    if sha(path)!=m['sha256']:raise RuntimeError('Image archive checksum mismatch')
    run(['docker','image','load','-i',str(path)]);print('Loaded release images.')
def preflight(project):
    info=json.loads(run(['docker','info','--format','{{json .}}']))
    if info['OSType']!='linux':raise RuntimeError('Docker must run Linux containers.')
    if info.get('Architecture') not in ('x86_64','amd64'):raise RuntimeError('This release was captured as linux/amd64; prepare matching images for other architectures.')
    release=read(ROOT/'release.json');missing=[]
    for tag,expected in release['images'].items():
        p=subprocess.run(['docker','image','inspect',tag],capture_output=True,encoding='utf-8')
        if p.returncode or json.loads(p.stdout)[0]['Id']!=expected:missing.append(tag)
    if missing:raise RuntimeError('Release images absent or changed. Run load-images with this release archive.')
    network_ids=run(['docker','network','ls','-q']).split()
    planned=[ipaddress.ip_network(s) for s in network_subnets(project)]
    for net in json.loads(run(['docker','network','inspect',*network_ids])) if network_ids else []:
        if (net.get('Labels') or {}).get('com.docker.compose.project')==project:continue
        for item in net.get('IPAM',{}).get('Config') or []:
            subnet=item.get('Subnet')
            if subnet and any(ipaddress.ip_network(subnet).overlaps(s) for s in planned if ipaddress.ip_network(subnet).version==s.version):
                raise RuntimeError('Deployment subnet overlaps another Docker network. Use a different workhub-* project name.')
    compose(project,'config','--quiet')
    cfg=read(ROOT/'compose.json');ports=[int(p['published']) for s in cfg['services'].values() for p in s.get('ports',[])]
    other=[]
    ids=run(['docker','ps','-q']).split()
    for c in json.loads(run(['docker','inspect',*ids])) if ids else []:
        if c['Config'].get('Labels',{}).get('com.docker.compose.project')==project:continue
        for bindings in (c.get('NetworkSettings',{}).get('Ports') or {}).values():
            if any(int(b['HostPort']) in ports for b in bindings or []):other.append(c['Name'])
    if other:raise RuntimeError('Another Docker project uses these ports. Stop it without deleting data.')
    result={'at':now(),'project':project,'docker_os':info['OSType'],'architecture':info.get('Architecture'),
        'cpus':info['NCPU'],'docker_memory_gib':round(info['MemTotal']/1024**3,1),'package_disk_free_gib':round(shutil.disk_usage(ROOT).free/1024**3,1),
        'images_verified':len(release['images']),'ports':ports,'docker_subnets':network_subnets(project),'note':'100 registered users is not 100 simultaneous AI generations. Capacity must be measured on the target server.'}
    write(ROOT/'reports'/('preflight-'+project+'.json'),result);print(json.dumps(result,ensure_ascii=False))
def status(project,quiet=False):
    result={'at':now(),'project':project,'services':[],'ok':True}
    rows=containers(project);expected=set(read(ROOT/'compose.json')['services'])
    for c in rows:
        state=c['State'];health=state.get('Health',{}).get('Status','not_configured')
        result['services'].append({'service':c['Config']['Labels']['com.docker.compose.service'],'state':state['Status'],'health':health,'restarts':c['RestartCount']})
        if not state['Running'] or health in ('unhealthy','starting'):result['ok']=False
    if {s['service'] for s in result['services']}!=expected:result['ok']=False
    write(ROOT/'reports'/('status-'+project+'.json'),result)
    if not quiet:print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
def start(project):
    preflight(project)
    if not (PRIVATE/(project+'-restored.json')).exists():raise RuntimeError('Restore the supplied baseline before first startup.')
    print('Starting isolated deployment...',flush=True)
    compose(project,'up','-d','--no-build','--pull','never')
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        s=status(project,quiet=True)
        if s['ok']:
            try:
                compose(project,'exec','-T','workhub','python','-c',"import os,httpx; r=httpx.get(os.environ['OIDC_ISSUER'].rstrip('/')+'/.well-known/openid-configuration',timeout=4); r.raise_for_status(); assert r.json()['authorization_endpoint']")
                print('All deployment services are healthy and SSO discovery is reachable.');return
            except RuntimeError:pass
        time.sleep(3)
    raise RuntimeError('Services did not become ready. Run status and inspect the named service logs.')
def backup(project,dest):
    rows=containers(project);stopped(rows)
    if not rows:raise RuntimeError('No deployment containers found.')
    mounts={key:{'kind':'volume','source':volume_name(project,key)} for key in read(ROOT/'compose.json')['volumes']}
    no_live_writers({m['source'] for m in mounts.values()})
    make_backup(mounts,dest,project)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',default='workhub-server',type=project_name)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('preflight','start','stop','status'):sub.add_parser(name)
    for name in ('backup','restore','verify-backup','export-images','load-images'):
        sub.add_parser(name).add_argument('path')
    a=p.parse_args()
    try:
        if a.command=='preflight':preflight(a.project)
        elif a.command=='start':start(a.project)
        elif a.command=='stop':compose(a.project,'stop','--timeout','45');print('Stopped; containers and volumes preserved.')
        elif a.command=='status':sys.exit(0 if status(a.project)['ok'] else 2)
        elif a.command=='backup':backup(a.project,a.path)
        elif a.command=='restore':restore(a.project,a.path)
        elif a.command=='verify-backup':verify_backup(a.path);print('All backup checksums match.')
        elif a.command=='export-images':export_images(a.path)
        elif a.command=='load-images':load_images(a.path)
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
