"""Apply only the local search images/flags; preserve every other runtime setting."""
import json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'.local/compose.json';config=json.loads(path.read_text(encoding='utf-8-sig'))
for name in ('outline','workhub','document-agent'):
    config['services'][name]['image']='unified-work-assistant/'+name+':search-20260930'
for name in ('outline','workhub'):
    config['services'][name]['environment']['OUTLINE_AI_SEARCH_ENABLED']='true'
config['services']['workhub']['environment']['ROCKETCHAT_KNOWLEDGE_ENABLED']='true'
path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
subprocess.run(['docker','compose','-p','unified-work-assistant','-f',str(path),'up','-d','--no-deps','document-agent','workhub','outline'],check=True)
print('Local search deployment applied. No database restore was performed.')
