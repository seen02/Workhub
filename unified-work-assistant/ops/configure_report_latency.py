"""Guarded Workhub-only apply/rollback; preserve all unrelated live settings."""
import argparse,json,statistics
from pathlib import Path

cli=argparse.ArgumentParser();cli.add_argument('action',choices=('apply','rollback'));args=cli.parse_args()
root=Path(__file__).resolve().parents[1]
config=root/'.local/compose.json'
backup=root/'backups/report-latency-20261007/compose.private.json'
new='unified-work-assistant/workhub:report-latency-20261007'
current=json.loads(config.read_text(encoding='utf-8'))
saved=json.loads(backup.read_text(encoding='utf-8'))
old=saved['services']['workhub']['image']
assert current['services']['workhub']['image'] in (old,new),'Workhub image changed independently'
if args.action=='apply':
    tests=(root/'reports/report-latency-tests-20261007.txt').read_text(encoding='utf-8')
    assert tests.rstrip().endswith('OK') and 'Ran 442 tests' in tests,'Regression suite did not pass'
    before=json.loads((root/'reports/report-latency-before-20261007.json').read_text(encoding='utf-8'))
    after=json.loads((root/'reports/report-latency-final-20261007.json').read_text(encoding='utf-8'))
    assert after.get('passed') and after.get('documents_unchanged'),'Correctness or source-preservation gate failed'
    assert len(after['cases'])==4 and all(e['passed'] for e in after['cases'])
    assert all(e['seconds']<60 for e in after['cases']),'Latency gate failed'
    prior=[e['seconds'] for e in before['cases'] if e['case']=='ai']
    later=[e['seconds'] for e in after['cases'] if e['case']=='ai']
    assert len(prior)==len(later)==2
    assert statistics.mean(later)<=statistics.mean(prior),'AI path became slower; rollback required'
    current['services']['workhub']['image']=new
else:current['services']['workhub']['image']=old
config.write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Workhub image: '+current['services']['workhub']['image'])
