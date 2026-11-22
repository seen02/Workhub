"""Static package checks; Docker Compose parses YAML without starting services."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys
from configure import ROOT


def main():
    failures=[]
    count=0
    for path in [*ROOT.joinpath('workhub').rglob('*.py'), *ROOT.joinpath('scripts').glob('*.py')]:
        if any(part in ('build','__pycache__') or part.endswith('.egg-info') for part in path.parts):continue
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        count+=1
    runtime=ROOT/'workhub/src/workhub'
    modules={path.stem for path in runtime.glob('*.py')}
    forbidden={'bot','knowledge','search','search_identity','provision','assistant','ai_runtime','legacy_app','gpu_runtime'}
    for path in runtime.glob('*.py'):
        if path.name.startswith('test_'):continue
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                names=[node.module.split('.')[0]] if node.module else [a.name for a in node.names]
                if node.level and not set(names)<=modules:failures.append(f'{path.name}: missing relative import {names}')
                if set(names)&forbidden:failures.append(f'{path.name}: excluded dependency {names}')
    configurations=[('compose.yaml',8)]
    if (ROOT/'compose.native.yaml').exists():
        configurations.append(('compose.native.yaml',6))
    for name,expected in configurations:
        # Let Compose parse standard YAML and comments without adding a Python YAML dependency.
        # Disable interpolation and use example settings so checks do not need private credentials.
        result=subprocess.run(
            ['docker','compose','--env-file',str(ROOT/'.env.example'),
             '-f',str(ROOT/name),'config','--no-interpolate','--format','json'],
            capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            failures.append(name+': '+result.stderr.strip())
            continue
        config=json.loads(result.stdout)
        if len(config['services'])!=expected:failures.append(name+': wrong service count')
        for service,spec in config['services'].items():
            if spec.get('container_name'):failures.append(name+': globally fixed container name')
            for dependency in spec.get('depends_on',{}):
                if dependency not in config['services']:failures.append(name+': missing dependency '+dependency)
        if name=='compose.yaml' and config['services']['workhub'].get('ports'):failures.append('Workhub has a public port')
    source_files=[ROOT/'outline/app/scenes/Search/Search.tsx', ROOT/'outline/server/routes/api/index.ts']
    for path in source_files:
        if re.search(r'KnowledgeSearch|workhubSearch',path.read_text(encoding='utf-8')):failures.append('AI search reference remains')
    for path in ROOT.joinpath('config').rglob('*'):
        if path.is_file() and 'workhub.test' in path.read_text(encoding='utf-8'):failures.append('Old domain in '+str(path))
    if (ROOT/'.env').exists():
        print('A private .env exists; it must be excluded from release archives.')
    if failures:
        print('\n'.join(failures));raise SystemExit(1)
    service_counts=', '.join(f'{name}={expected} services' for name,expected in configurations)
    print(f'PASS: {count} Python files; runtime imports closed; {service_counts}; AI routes and old domains absent.')


if __name__=='__main__':main()
