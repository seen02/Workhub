"""Build on Linux or launch prepared application artifacts on Windows/Linux."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from configure import ROOT, load_env


def environment(service, values):
    template = json.loads((ROOT / f'config/native-{service}.json').read_text(encoding='utf-8'))
    def expand(text):
        return re.sub(r'\$\{([A-Z_]+)(?::-([^}]*))?\}', lambda match: values.get(match[1], match[2] or ''), text)
    env = {**os.environ, **{key: expand(value) for key, value in template.items()}}
    if service == 'outline':
        env.update(PORT=values['NATIVE_OUTLINE_PORT'],
                   DATABASE_URL=f"postgres://outline:{values['OUTLINE_DB_PASSWORD']}@127.0.0.1:{values['DB_PORT']}/outline",
                   REDIS_URL=f"redis://127.0.0.1:{values['REDIS_PORT']}",
                   WORKHUB_INTERNAL_URL=f"http://127.0.0.1:{values['NATIVE_WORKHUB_PORT']}",
                   FILE_STORAGE_LOCAL_ROOT_DIR=str(ROOT / '.runtime/outline-files'))
    else:
        env.update(OUTLINE_URL=f"http://127.0.0.1:{values['NATIVE_OUTLINE_PORT']}",
                   AUTHENTIK_API_URL=f"http://127.0.0.1:{values['HTTP_PORT']}",
                   AUTHENTIK_API_HOST=f"{values['AUTH_DOMAIN']}:{values['HTTP_PORT']}",
                   WORKHUB_DB=str(ROOT / '.runtime/workhub.sqlite3'))
    return env


def run(command, cwd=None, env=None):
    subprocess.run(command, cwd=cwd or ROOT, env=env, check=True)


def build():
    if os.name == 'nt':
        raise SystemExit('Use Linux or WSL for the native Outline build (upstream build scripts require a POSIX shell).')
    for executable in ['node', 'corepack', 'yarn']:
        if not shutil.which(executable):
            raise SystemExit(f'{executable} is missing. Install Node 26.3.0 and run corepack enable.')
    version = subprocess.check_output(['node','--version'], text=True).strip()
    if version != 'v26.3.0':
        raise SystemExit('Use Node 26.3.0 to match the Docker build and the source engine constraint.')
    source = ROOT / 'outline'
    target = ROOT / 'dist/outline'
    if target.exists():
        raise SystemExit('dist/outline already exists. Move it aside before creating a new release.')
    for command in [['corepack','yarn','install','--immutable'], ['corepack','yarn','patch-package'],
                    ['corepack','yarn','tsc','--noEmit'], ['corepack','yarn','build'], ['corepack','yarn','workspaces','focus','--production'],
                    ['corepack','yarn','patch-package']]:
        run(command,source)
    target.mkdir(parents=True)
    for name in ['build','server','public','node_modules']:
        shutil.copytree(source/name,target/name,symlinks=True)
    for name in ['package.json','.sequelizerc','LICENSE']:
        shutil.copy2(source/name,target/name)
    run([sys.executable,'-m','pip','install','build==1.2.2.post1'])
    run([sys.executable,'-m','build','--outdir',str(ROOT/'dist/workhub'),str(ROOT/'workhub')])
    run([sys.executable,'-m','venv',str(ROOT/'.venv')])
    wheels=list((ROOT/'dist/workhub').glob('*.whl'))
    if len(wheels)!=1:raise SystemExit('Expected exactly one Workhub wheel.')
    run([str(ROOT/'.venv/bin/python'),'-m','pip','install',str(wheels[0])])
    print('Built dist/outline and dist/workhub. No application server was started.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['build','outline','workhub','manage'])
    parser.add_argument('--outline-dir', type=Path, help='Prepared Outline directory (default: dist/outline-direct or dist/outline)')
    parser.add_argument('manage_args',nargs='*')
    args=parser.parse_args()
    if args.command=='build':
        build();return
    env=load_env()
    if env.get('DEPLOY_MODE')!='native':raise SystemExit('This .env was created for Docker. Use a separate deployment copy for native mode.')
    (ROOT/'.runtime/outline-files').mkdir(parents=True,exist_ok=True)
    if args.command=='outline':
        target=args.outline_dir
        if target is None:
            target=ROOT/('dist/outline-direct' if (ROOT/'dist/outline-direct').exists() else 'dist/outline')
        elif not target.is_absolute():
            target=ROOT/target
        if not (target/'build/server/index.js').exists():raise SystemExit('Extract the Outline build package first.')
        if not (target/'node_modules').exists():raise SystemExit('Install production Node dependencies in the extracted Outline directory first.')
        runtime=environment('outline',env)
        run(['node','build/server/index.js'],target,runtime)
    else:
        python=ROOT/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
        if not python.exists():raise SystemExit('Create .venv and install the Workhub wheel first.')
        runtime=environment('workhub',env)
        if args.command=='manage':
            run([str(python),'-m','workhub.manage',*args.manage_args],env=runtime)
        else:
            run([str(python),'-m','uvicorn','workhub.main:app','--host','127.0.0.1','--port',env['NATIVE_WORKHUB_PORT'],
                 '--workers','1','--no-access-log'],env=runtime)


if __name__=='__main__':
    main()
