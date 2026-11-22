"""Change only the Workhub image; preserve every other current setting."""
import argparse,json,shutil
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['apply','rollback'])
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
config=root/'.local/compose.json'
backup=root/'backups/report-fastpath-20261007/compose.private.json'
new='unified-work-assistant/workhub:report-fastpath-20261007'
data=json.loads(config.read_text(encoding='utf-8'))
if args.action=='apply':
    comparison=json.loads((root/'reports/report-fastpath-comparison-20261007.json').read_text(encoding='utf-8'))
    if comparison.get('decision')!='keep' or comparison.get('passed') is not True:raise SystemExit('Performance/correctness gate did not pass')
    if not backup.exists():shutil.copy2(config,backup)
    saved=json.loads(backup.read_text(encoding='utf-8'))
    old=saved['services']['workhub']['image']
    if data['services']['workhub']['image'] not in (old,new):raise SystemExit('Workhub image changed independently; preserve current settings')
    data['services']['workhub']['image']=new
else:
    saved=json.loads(backup.read_text(encoding='utf-8'))
    old=saved['services']['workhub']['image']
    if data['services']['workhub']['image'] not in (old,new):raise SystemExit('Workhub image changed independently; preserve current settings')
    data['services']['workhub']['image']=old
config.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Workhub image: '+data['services']['workhub']['image'])
