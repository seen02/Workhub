"""Stop only the three Outline projects, clone cold data, keep originals intact."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local'
def run(args):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError(f'Command failed: {args[:3]}: {p.stderr[-600:]}')
    return p.stdout
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    plan=json.loads((LOCAL/'migration.json').read_text(encoding='utf-8'))
    report_path=LOCAL/'migration-verification.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {'volumes':{},'bindings':{}}
    if plan['status'] not in ('prepared','copying'):raise RuntimeError('Migration already finished')
    for name in plan['original_containers']:
        info=json.loads(run(['docker','inspect',name]))[0]
        assert info['Config']['Labels']['com.docker.compose.project'] in ('outline','outline-ai','outline-authentik')
    # Stop writers before databases. docker stop waits for clean process exit.
    names=plan['original_containers']
    writers=[n for n in names if not any(x in n for x in ('postgres','redis','ollama'))]
    stores=[n for n in names if n not in writers]
    run(['docker','stop','-t','60',*writers]);run(['docker','stop','-t','60',*stores])
    plan['status']='copying';(LOCAL/'migration.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Original Outline containers stopped cleanly.',flush=True)
    for old,new in plan['volumes'].items():
        if old in report['volumes']:continue
        if any(c['State']['Running'] for c in json.loads(run(['docker','inspect',*names]))):raise RuntimeError('Original source still running')
        run(['docker','volume','create','--label','owner=unified-work-assistant',new])
        output=run(['docker','run','--rm','--user','0','--network','none','--entrypoint','python',
          '-v',old+':/source:ro','-v',new+':/target','-v',str(ROOT/'ops')+':/ops:ro',
          'unified-work-assistant/document-agent:migration-baseline','/ops/clone_volume.py'])
        report['volumes'][old]={'target':new,**json.loads(output)}
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(f'Copied and verified {old}: {report["volumes"][old]["verified_files"]} files',flush=True)
    for a,b in plan['bindings'].items():
        if a in report['bindings']:continue
        src=Path(a);dst=Path(b)
        assert dst.resolve().is_relative_to(ROOT.resolve())
        dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir():shutil.copytree(src,dst,dirs_exist_ok=False)
        else:shutil.copy2(src,dst)
        files=list(src.rglob('*')) if src.is_dir() else [src]
        checked=0
        for f in files:
            if f.is_file():
                target=dst/f.relative_to(src) if src.is_dir() else dst
                assert sha(f)==sha(target);checked+=1
        report['bindings'][a]={'target':b,'verified_files':checked}
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Copied and verified bind data: {checked} files',flush=True)
    plan['status']='copied';(LOCAL/'migration.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Cold-copy migration complete. Original containers and volumes preserved.',flush=True)
if __name__=='__main__':main()
