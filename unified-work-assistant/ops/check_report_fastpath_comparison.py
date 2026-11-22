"""Keep only an equivalent result that improved both two-run average times."""
import argparse,json,statistics
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--before',required=True)
parser.add_argument('--after',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
before=json.loads(Path(args.before).read_text(encoding='utf-8'))
after=json.loads(Path(args.after).read_text(encoding='utf-8'))
checks={'source_documents_unchanged':before.get('documents_unchanged') is True and after.get('documents_unchanged') is True,
        'exactly_two_repeats':before['repeats']==after['repeats']==2}
rows=[]
for name in ('short','multi'):
    b=sorted([c for c in before['cases'] if c['case']==name],key=lambda c:c['repeat'])
    a=sorted([c for c in after['cases'] if c['case']==name],key=lambda c:c['repeat'])
    checks[name+'_two_samples']=len(b)==len(a)==2 and [c['repeat'] for c in b]==[c['repeat'] for c in a]==[1,2]
    checks[name+'_same_output']=all(x['rendered']==y['rendered'] and x['resolved']==y['resolved'] for x,y in zip(b,a))
    bm=statistics.mean(c['plan']['seconds'] for c in b);am=statistics.mean(c['plan']['seconds'] for c in a)
    checks[name+'_faster']=am<bm
    checks[name+'_no_extra_ai']=all(c['plan']['ai_calls']==0 for c in a)
    checks[name+'_no_rag']=all(c['plan']['http_calls'].get('/agent/report-candidates',0)==0 for c in a)
    rows.append({'case':name,'before_seconds':[c['plan']['seconds'] for c in b],
        'after_seconds':[c['plan']['seconds'] for c in a],'before_mean':bm,'after_mean':am,
        'reduction_percent':100*(bm-am)/bm,'before_mode':[c['mode'] for c in b],'after_mode':[c['mode'] for c in a]})
result={'passed':all(checks.values()),'decision':'keep' if all(checks.values()) else 'rollback',
        'criterion':'Both two-run mean draft times must improve, with identical tasks/states/report text.',
        'checks':checks,'cases':rows,'sample_limitation':'Two runs per case; no population latency or concurrency guarantee.'}
Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(not result['passed'])
