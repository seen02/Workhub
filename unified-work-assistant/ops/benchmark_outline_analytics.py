"""Synthetic computation benchmark; permissions and upstream I/O are stubbed."""
import json, os, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/app')
for key in ('OUTLINE_URL','OUTLINE_PUBLIC_URL','PUBLIC_URL','OIDC_ISSUER','CHAT_PUBLIC_URL','WEBUI_PUBLIC_URL'):
    os.environ[key]='http://fixture.invalid'
for key in ('OUTLINE_API_KEY','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET','AGENT_TOKEN'):
    os.environ[key]='fixture'
os.environ.pop('AUTHENTIK_DIRECTORY_TOKEN',None)
with tempfile.TemporaryDirectory() as folder:
    os.environ['WORKHUB_DB']=folder+'/benchmark.sqlite3'
    from workhub import analytics_service, store
    store.init()
    user={'email':'benchmark@example.com','name':'검증 담당자','admin':False}
    projects=[{'id':f'11111111-1111-4111-8111-{i:012d}','name':f'검증 프로젝트 {i+1}','manager':user['email']} for i in range(10)]
    results=[]
    for size in (100,1000):
        tasks=[]
        for i in range(size):
            project=projects[i%10]
            tasks.append({'id':str(i),'title':f'부하 검증 업무 {i+1}','collectionId':project['id'],'collectionName':project['name'],'url':'/doc/fixture',
                'fields':{'owner':user['email'],'status':'완료' if i%5==0 else '진행 중','progress':'100%' if i%5==0 else '50%','start':'2026-09-28','due':'2026-10-05','blocker':'없음','next':'다음 기준 확인'},
                'criteria':[{'id':str(i)+'c','title':'검증 완료 기준','owner':user['email'],'state':'완료' if i%5==0 else '진행 중'}]})
        timings=[]
        with patch('workhub.analytics_service.permissions.projects',return_value=projects),patch('workhub.analytics_service.outline.tasks',return_value=tasks),patch('workhub.analytics_service.directory.names',return_value={user['email']:user['name']}):
            for _ in range(20):
                started=time.perf_counter();data=analytics_service.query(user);timings.append((time.perf_counter()-started)*1000)
        encoded=json.dumps(data,ensure_ascii=False)
        Path(f'/reports/outline-analytics-fixture-{size}.json').write_text(encoded,encoding='utf-8')
        timings.sort();results.append({'tasks':size,'samples':20,'p95Ms':round(timings[18],2),'responseBytes':len(encoded.encode())})
    Path('/reports/outline-analytics-benchmark.json').write_text(json.dumps({'synthetic':True,'limitations':'ACL와 Outline 네트워크 I/O 모의 처리; 계산 시간만 측정','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results))
