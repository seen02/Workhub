"""Stage exact live images and a cold data snapshot; always restart the originals."""
import argparse, datetime, importlib, json, pathlib, shutil, subprocess, sys, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
def run(arguments):
    result=subprocess.run(arguments,capture_output=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('Release snapshot operation failed; credentials are not printed.')
    return result.stdout
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',required=True)
    args=parser.parse_args()
    if not __import__('re').fullmatch(r'[0-9]{8}-[0-9]+',args.version):raise ValueError('Invalid release version')
    stage=ROOT/('deployment-next-'+args.version)
    if stage.exists():raise RuntimeError('Use a new staging directory; existing artifacts are preserved.')
    stage.mkdir();(stage/'reports').mkdir()
    for name in ('manage.py','audit.py','backup_cycle.py','configure_access.py','verify_preservation.py','test_manage.py','run.ps1'):
        shutil.copy2(ROOT/'deployment'/name,stage/name)
    sys.path.insert(0,str(stage));manage=importlib.import_module('manage');inventory=importlib.import_module('audit')
    ids=run(['docker','compose','-f',str(ROOT/'compose.yml'),'ps','-aq']).split()
    rows=json.loads(run(['docker','inspect',*ids]))
    if len(rows)!=16 or any(not row['State']['Running'] for row in rows):raise RuntimeError('Expected all 16 current services running')
    code="import sqlite3,json; c=sqlite3.connect('file:/app/data/workhub.sqlite3?mode=ro',uri=True); print(json.dumps(c.execute(\"SELECT count(*) FROM messages WHERE state='PROCESSING'\").fetchone()[0]))"
    if json.loads(run(['docker','exec','unified-work-assistant-workhub-1','python','-c',code])):
        raise RuntimeError('An active user request is being processed; retry after it finishes.')
    manage.compose=lambda project,*arguments:run(['docker','compose','-f',str(ROOT/'compose.yml'),*arguments])
    counts=inventory.capture('unified-work-assistant')
    manage.write(stage/'reports/inventory-source.json',{'at':manage.now(),'project':'unified-work-assistant','counts':counts})
    stopped_at=manage.now();restarted_at=None
    try:
        print('Stopping source services for a consistent snapshot...',flush=True)
        run(['docker','stop','--time','45',*ids])
        print(run([sys.executable,str(ROOT/'ops/prepare_deployment.py'),'--version',args.version,'--destination',str(stage)]).strip(),flush=True)
        print('Creating cold data baseline...',flush=True)
        manage.source_backup(stage/'.private/source-backup-recipe.json',stage/'artifacts/source-baseline')
    finally:
        print('Restarting the original 16 containers...',flush=True)
        run(['docker','start',*ids]);restarted_at=manage.now()
        manage.write(stage/'reports/source-maintenance.json',{'snapshot_started_at':stopped_at,'original_restart_requested_at':restarted_at,'original_container_ids':ids})
    print('Checking original service readiness...',flush=True)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        rows=json.loads(run(['docker','inspect',*ids]))
        if all(row['State']['Running'] and row['State'].get('Health',{}).get('Status') not in ('starting','unhealthy') for row in rows):break
        time.sleep(3)
    else:raise RuntimeError('Original containers started but did not all become ready')
    print('Original services are running; verifying snapshot checksums...',flush=True)
    manage.verify_backup(stage/'artifacts/source-baseline')
    shutil.copy2(ROOT/'reports/release-current-source-audit-20261007.json',stage/'source-audit.json')
    print(json.dumps({'passed':True,'version':args.version,'services':len(rows),'data_volumes':len(manage.read(stage/'artifacts/source-baseline/manifest.json')['volumes']),'stage':str(stage)}),flush=True)
if __name__=='__main__':main()
