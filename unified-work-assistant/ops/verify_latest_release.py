"""Restore into separate volumes, rehearse startup, then return to the original stack."""
import argparse, importlib, json, pathlib, subprocess, sys, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
def run(arguments):
    result=subprocess.run(arguments,capture_output=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('Release verification command failed; credentials are not printed.')
    return result.stdout
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',required=True)
    args=parser.parse_args()
    if not __import__('re').fullmatch(r'[0-9]{8}-[0-9]+',args.version):raise ValueError('Invalid version')
    stage=ROOT/('deployment-next-'+args.version);project='workhub-releasecheck-'+args.version.replace('-','')
    sys.path.insert(0,str(stage));manage=importlib.import_module('manage');inventory=importlib.import_module('audit')
    sys.path.insert(0,str(ROOT/'ops'));source_audit=importlib.import_module('audit_current_release')
    saved=manage.read(stage/'.private/preserved-containers.json');ids=[row['id'] for row in saved['containers']]
    if manage.containers(project):raise RuntimeError('A rehearsal already exists; preserve it and use a new version')
    print('Restoring into 14 separate data volumes...',flush=True)
    manage.restore(project,stage/'artifacts/source-baseline')
    original_stopped=False
    try:
        code="import sqlite3,json; c=sqlite3.connect('file:/app/data/workhub.sqlite3?mode=ro',uri=True); print(json.dumps(c.execute(\"SELECT count(*) FROM messages WHERE state='PROCESSING'\").fetchone()[0]))"
        if json.loads(run(['docker','exec','unified-work-assistant-workhub-1','python','-c',code])):raise RuntimeError('An active request must finish before rehearsal')
        print('Stopping originals briefly to avoid resource/port conflicts...',flush=True)
        original_stopped=True;run(['docker','stop','--time','45',*ids])
        manage.start(project)
        counts=inventory.capture(project);expected=manage.read(stage/'reports/inventory-source.json')['counts']
        result={'at':manage.now(),'project':project,'counts':counts,'matches_backup_inventory':counts==expected}
        if counts!=expected:result['differences']={key:{'before':expected[key],'after':counts[key]} for key in expected if counts[key]!=expected[key]}
        manage.write(stage/'reports/inventory-restored.json',result)
        if not result['matches_backup_inventory']:raise RuntimeError('Restored database counts differ; see private local verification report')
        audit=source_audit.audit(project);manage.write(stage/'reports/restored-source-audit.json',audit)
        if not audit['passed']:raise RuntimeError('Restored runtime source audit failed')
        code="import os,httpx,json; from workhub import store; h=httpx.get('http://127.0.0.1:8000/health').status_code; oidc=httpx.get(os.environ['OIDC_ISSUER'].rstrip('/')+'/.well-known/openid-configuration',timeout=5);oidc.raise_for_status(); bot=store.get('bot_status') or {}; blocked={path:httpx.get('http://workhub.test'+path).status_code for path in ['/internal/outline-projects/','/internal/outline-analytics/','/internal/outline-tasks/','/internal/outline-kanban/']}; print(json.dumps({'health':h,'oidc_discovery':bool(oidc.json().get('authorization_endpoint')),'bot_connected':bot.get('connected'),'bot_rooms':bot.get('rooms'),'blocked_internal_routes':blocked})); assert h==200 and bot.get('connected') is True and all(v==404 for v in blocked.values())"
        probe=json.loads(run(['docker','exec',project+'-workhub-1','python','-c',code]))
        print('Running the latest Workhub tests with dummy endpoints and a temporary database...',flush=True)
        run(['docker','exec',project+'-workhub-1','mkdir','-p','/tmp/release-tests'])
        run(['docker','cp',str(ROOT/'src/workhub'),project+'-workhub-1:/tmp/release-tests/workhub'])
        run(['docker','cp',str(ROOT/'ops/run_workhub_tests.py'),project+'-workhub-1:/tmp/run_release_tests.py'])
        code="from pathlib import Path; code=Path('/tmp/run_release_tests.py').read_text().replace('/app','/tmp/release-tests'); exec(compile(code,'isolated_release_tests','exec'))"
        tests=subprocess.run(['docker','exec',project+'-workhub-1','python','-c',code],capture_output=True,encoding='utf-8',errors='replace')
        (stage/'reports/workhub-tests.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
        if tests.returncode:raise RuntimeError('Workhub regression tests failed; see workhub-tests.txt')
        manage.write(stage/'reports/release-start-smoke.json',{'passed':True,'at':manage.now(),'project':project,'probes':probe,
            'checks':['16 healthy services','OIDC discovery','restored inventory equality','runtime source and WebUI tool hashes','blocked internal routes','latest Workhub regression tests'],
            'platform':'Windows Docker Desktop Linux amd64; not an actual Ubuntu host'})
        print('Isolated deployment and inventory/source checks passed.',flush=True)
    finally:
        try:
            if manage.containers(project):
                print('Stopping the rehearsal; its separate volumes are retained...',flush=True)
                manage.compose(project,'stop','--timeout','45')
        finally:
            if original_stopped:
                print('Restarting the original containers...',flush=True);run(['docker','start',*ids])
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    rows=json.loads(run(['docker','inspect',*ids]))
                    if all(row['State']['Running'] and row['State'].get('Health',{}).get('Status') not in ('starting','unhealthy') for row in rows):break
                    time.sleep(3)
                else:raise RuntimeError('Original containers restarted but are not all ready')
    proof=run([sys.executable,str(stage/'verify_preservation.py'),'--copy',project])
    print(proof.strip(),flush=True)
    print(json.dumps({'passed':True,'version':args.version,'rehearsal_project':project,'originals':'all running and preserved','copy':'stopped, separate volumes'}),flush=True)
if __name__=='__main__':main()
