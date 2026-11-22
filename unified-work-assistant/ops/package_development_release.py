"""Package an explicit source allowlist; keep real settings/data in the private release."""
import argparse, datetime, hashlib, json, os, pathlib, re, subprocess, zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
IGNORED={'.git','.local','.private','__pycache__','node_modules','.venv','venv','data','uploads','logs','dist','build','coverage','results','secrets'}
EXTENSIONS={'.py','.js','.mjs','.cjs','.jsx','.ts','.tsx','.json','.sql','.html','.css','.svg','.png','.jpg','.jpeg','.webp','.gif','.txt','.md','.ps1','.sh','.yaml','.yml','.toml','.lock'}
def allowed(path):
    name=path.name.lower()
    if path.is_symlink() or any(part in IGNORED for part in path.relative_to(ROOT).parts):return False
    if (name.startswith('.env') and name!='.env.example') or 'credentials' in name or name.endswith(('.pem','.key','.crt','.p12','.pfx','.db','.sqlite','.sqlite3','.log')):return False
    return path.suffix.lower() in EXTENSIONS or name.startswith('dockerfile') or name in ('.gitignore','.dockerignore','license','notice')
def selected_files():
    paths=set()
    for base in ('src','ops','development'):
        for directory,folders,names in os.walk(ROOT/base):
            folders[:]=[name for name in folders if name not in IGNORED and not (pathlib.Path(directory)/name).is_symlink()]
            paths.update(pathlib.Path(directory)/name for name in names if allowed(pathlib.Path(directory)/name))
    paths.update(path for path in ROOT.iterdir() if path.is_file() and (path.suffix in ('.md','.ps1') or path.name in ('compose.yml','.gitignore','.dockerignore')))
    integration=ROOT/'integrations/outline'
    paths.update(integration/name for name in ('README.md','Dockerfile','Dockerfile.dependencies','prepare_source.py','export_patch.py','upstream.lock.json','upstream.tar.gz'))
    paths.update(path for path in (integration/'patches').rglob('*') if path.is_file())
    paths.add(ROOT/'config/nginx-local/default.conf')
    return sorted(paths)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[0-9]{8}-[0-9]+',args.version):raise ValueError('Invalid version')
    stage=ROOT/('deployment-next-'+args.version);release=json.loads((stage/'release.json').read_text(encoding='utf-8'))
    if release['version']!=args.version:raise ValueError('Release version mismatch')
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    version={'version':args.version,'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_kind':'current working tree including uncommitted changes','git_head':head,'runtime_images':release['images']}
    (ROOT/'development/version.json').write_text(json.dumps(version,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    paths=selected_files();expected={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    destination=stage/'artifacts'/('workhub-development-'+args.version+'.zip')
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in paths:archive.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist())==set(expected)
        assert all(hashlib.sha256(archive.read(name)).hexdigest()==sha for name,sha in expected.items())
        assert not any(any(part in ('.local','.private','runtime','backups','node_modules','__pycache__') for part in pathlib.PurePosixPath(name).parts) for name in archive.namelist())
    checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest={**version,'files':expected,'excluded':'real settings, credentials, certificates, databases, runtime data, caches and build outputs'}
    (stage/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    artifact={'file':destination.name,'bytes':destination.stat().st_size,'sha256':checksum,'files':len(expected),'verified_zip_entries':True}
    pathlib.Path(str(destination)+'.manifest.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    release['development_source']=artifact
    (stage/'release.json').write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # The restore baseline keeps its original matching runtime image/configuration metadata.
    # Development archive metadata does not alter runtime images or the backup's configuration.
    (stage/'reports/development-package.json').write_text(json.dumps({'passed':True,**artifact},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,**artifact},ensure_ascii=False))
if __name__=='__main__':main()
