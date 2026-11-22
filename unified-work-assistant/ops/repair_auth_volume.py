"""Correct the Compose-directory versus explicit project-name volume mismatch."""
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local'
def run(args):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError(p.stderr[-400:])
    return p.stdout
def main():
    originals=json.loads((LOCAL/'original-containers.json').read_text(encoding='utf-8'))
    original=next(c for c in originals if c['Name']=='/outline-authentik-postgresql-1')
    source=next(m['Name'] for m in original['Mounts'] if m['Destination']=='/var/lib/postgresql/data')
    assert source=='outline-authentik_database'
    target='unified-work-assistant_outline-authentik-database-verified'
    run(['docker','compose','-f',str(ROOT/'compose.yml'),'stop','authentik-server','authentik-worker','postgresql'])
    assert not json.loads(run(['docker','inspect','outline-authentik-postgresql-1']))[0]['State']['Running']
    run(['docker','volume','create','--label','owner=unified-work-assistant',target])
    result=json.loads(run(['docker','run','--rm','--user','0','--network','none','--entrypoint','python',
      '-v',source+':/source:ro','-v',target+':/target','-v',str(ROOT/'ops')+':/ops:ro',
      'unified-work-assistant/document-agent:migration-baseline','/ops/clone_volume.py']))
    cp=LOCAL/'compose.json';cfg=json.loads(cp.read_text(encoding='utf-8'))
    cfg['volumes']['outline-authentik-database']['name']=target
    cp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    rp=LOCAL/'migration-verification.json';report=json.loads(rp.read_text(encoding='utf-8'))
    report['volumes']['authentik_database']['used']=False
    report['volumes'][source]={'target':target,**result,'used':True}
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    mp=LOCAL/'migration.json';plan=json.loads(mp.read_text(encoding='utf-8'))
    plan['volumes'].pop('authentik_database');plan['volumes'][source]=target
    mp.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'source':source,'target':target,**result}))
if __name__=='__main__':main()
