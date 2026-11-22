"""Add local Rocket.Chat infrastructure; legacy report services stay opt-in."""
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local'
PY=os.sys.executable
def run(args,**kwargs):
    p=subprocess.run(args,capture_output=True,encoding='utf-8',errors='replace',**kwargs)
    if p.returncode:raise RuntimeError(f'Command failed: {args[:3]}')
    return p.stdout
def main():
    source=ROOT/'src/report-agent/rocketchat'
    run(['docker','run','--rm','--network','none','--entrypoint','python','-v',str(source)+':/setup',
         'unified-work-assistant/document-agent:migration-baseline','/setup/setup.py','init'])
    cfg=json.loads(run(['docker','compose','--env-file',str(source/'.local/compose.env'),'-f',str(source/'compose.yml'),'config','--format','json']))
    path=LOCAL/'compose.json';combined=json.loads(path.read_text(encoding='utf-8'))
    combined['networks']['chat-data']={'internal':True};combined['networks']['chat-net']={}
    rename={'review':'report-review','worker':'report-worker'}
    for name,item in cfg['services'].items():
        new=rename.get(name,name)
        item['networks']={'chat-data' if key=='database' else 'chat-net':v for key,v in item['networks'].items()}
        if 'depends_on' in item:item['depends_on']={rename.get(k,k):v for k,v in item['depends_on'].items()}
        if name in ('review','worker','reportdb'):item['profiles']=['legacy-report']
        if name in ('review','worker'):
            item['build']={'context':str(ROOT/'src/report-agent/backend')}
            item['environment']['OLLAMA_BASE_URL']='http://ollama:11434'
            item['networks']['outline-ai-net']=None
        if name=='rocketchat':
            item['environment']['NODE_OPTIONS']='--max-old-space-size=1280'
            item['environment']['OVERWRITE_SETTING_Site_Name']='통합 AI 업무 비서'
            item['healthcheck']={'test':['CMD','node','-e',"fetch('http://127.0.0.1:3000/api/info').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"],'interval':'20s','timeout':'10s','retries':20,'start_period':'180s'}
        combined['services'][new]=item
    for key,value in cfg['volumes'].items():combined['volumes'][key]={'name':'unified-work-assistant_'+key}
    path.write_text(json.dumps(combined,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Rocket.Chat and MongoDB added. Legacy report DB/bot/review are opt-in only.')
if __name__=='__main__':main()
