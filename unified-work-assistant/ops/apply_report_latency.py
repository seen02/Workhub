"""Apply the validated image, verify it, and restore the prior image on failure."""
import hashlib,json,subprocess,sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
def run(*args):return subprocess.check_output(list(args),cwd=root,text=True,encoding='utf-8')
def state():
    ids=run('docker','compose','-f','.local/compose.json','ps','-q').split()
    rows=json.loads(run('docker','inspect',*ids))
    return {r['Config']['Labels']['com.docker.compose.service']:{'id':r['Id'],'image_id':r['Image'],'image':r['Config']['Image'],
        'status':r['State']['Status'],'health':r['State'].get('Health',{}).get('Status'),
        'mounts':sorted([{k:m.get(k) for k in ('Name','Source','Destination','Type')} for m in r['Mounts']],key=lambda m:m['Destination'])} for r in rows}

compose=json.loads((root/'.local/compose.json').read_text(encoding='utf-8'))
before=state()
(root/'reports/report-latency-apply-before-20261007.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
processing=run('docker','exec','unified-work-assistant-workhub-1','python','-c',
    "from workhub import store;c=store.db();db=c.__enter__();print(db.execute('SELECT count(*) FROM messages WHERE state=?',('PROCESSING',)).fetchone()[0]);c.__exit__(None,None,None)")
assert int(processing.strip())==0,'User request is in progress; defer restart'
print(run(sys.executable,'ops/configure_report_latency.py','apply'),flush=True)
try:
    print(run('docker','compose','-f','.local/compose.json','up','-d','--no-deps','--no-build','--wait','--wait-timeout','45','workhub'),flush=True)
    run('docker','cp','ops/verify_report_latency_deployment.py','unified-work-assistant-workhub-1:/tmp/verify_report_latency_deployment.py')
    verified=json.loads(run('docker','exec','-e','PYTHONPATH=/app','unified-work-assistant-workhub-1','python','/tmp/verify_report_latency_deployment.py'))
    assert verified['passed']
    for name,value in verified['source_sha256'].items():
        assert value==hashlib.sha256((root/'src/workhub'/name).read_bytes()).hexdigest(),name
    after=state()
    (root/'reports/report-latency-apply-after-20261007.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    assert set(before)==set(after) and len(after)==16
    for service,row in after.items():
        assert row['status']=='running' and row['health'] in ('healthy',None),service
        # Container identity, image tag and the full mount set prove that these
        # services weren't recreated. Health is checked separately above.
        if service!='workhub':
            for field in ('id','image','mounts'):assert row[field]==before[service][field],(service,field)
        else:assert row['mounts']==before[service]['mounts']
    updated=json.loads((root/'.local/compose.json').read_text(encoding='utf-8'))
    updated['services']['workhub']['image']=compose['services']['workhub']['image']
    assert updated==compose,'Unrelated Compose settings changed'
    metadata_changes={s:[k for k,v in row.items() if v!=before[s][k]] for s,row in after.items() if s!='workhub' and row!=before[s]}
    verified.update(runtime=after,other_services_unchanged=True,compose_image_only=True,reported_metadata_changes=metadata_changes)
    (root/'reports/report-latency-deployment-20261007.json').write_text(json.dumps(verified,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'services':len(after),'functional_checks':verified['functional_checks'],'documents_unchanged':verified['documents_unchanged']},ensure_ascii=False),flush=True)
except BaseException as error:
    print('Validation error: '+type(error).__name__+' '+str(error),flush=True)
    if isinstance(error,subprocess.CalledProcessError) and '/tmp/verify_report_latency_deployment.py' in error.cmd:
        print(error.output,flush=True)
    print(run(sys.executable,'ops/configure_report_latency.py','rollback'),flush=True)
    print(run('docker','compose','-f','.local/compose.json','up','-d','--no-deps','--no-build','--wait','--wait-timeout','45','workhub'),flush=True)
    print('Validation failed; prior Workhub image restored.',flush=True)
    raise
