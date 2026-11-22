import argparse,hashlib,json,pathlib,re,subprocess
parser=argparse.ArgumentParser(description='Compare deployed app files with current source, without printing content.')
parser.add_argument('--project',default='unified-work-assistant')
args=parser.parse_args()
if not re.fullmatch(r'[a-z0-9-]+',args.project):raise ValueError('Invalid project name')
root=pathlib.Path(__file__).resolve().parents[1];report={}
for service,sub,remote,recursive in [('workhub','src/workhub','/app/workhub',True),('document-agent','src/document-agent','/app',False)]:
 base=root/sub
 files=[p for p in (base.rglob('*') if recursive else base.glob('*.py')) if p.is_file() and p.suffix in ('.py','.html','.js','.css','.sql','.png','.svg') and '__pycache__' not in p.parts]
 expected={p.relative_to(base).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
 code='import pathlib,hashlib,json; root=pathlib.Path('+repr(remote)+'); names='+repr(list(expected))+'; print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).exists() else None for n in names}))'
 proc=subprocess.run(['docker','exec',args.project+'-'+service+'-1','python','-c',code],capture_output=True,text=True,check=True)
 actual=json.loads(proc.stdout);mismatch=[n for n in expected if expected[n]!=actual[n]]
 report[service]={'files':len(expected),'mismatches':mismatch}
print(json.dumps(report))
(root/('reports/release-source-audit-'+args.project+'.json')).write_text(json.dumps(report,indent=2))
raise SystemExit(1 if any(r['mismatches'] for r in report.values()) else 0)
