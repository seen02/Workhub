"""Read-only source audit by deployment location, including installed WebUI tools."""
import argparse, datetime, hashlib, json, pathlib, re, shlex, subprocess

ROOT=pathlib.Path(__file__).resolve().parents[1]
def digest(content):return hashlib.sha256(content).hexdigest()
def run(arguments):
    result=subprocess.run(arguments,capture_output=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('Container source audit failed; no credentials are printed.')
    return json.loads(result.stdout)
def remote_files(project,service,base,names):
    code='import pathlib,hashlib,json;root=pathlib.Path('+repr(base)+');names='+repr(names)+';print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).is_file() else None for n in names}))'
    return run(['docker','exec',project+'-'+service+'-1','python','-c',code])
def file_check(project,service,base,source,names,optional_tests=False):
    expected={name:digest((source/name).read_bytes()) for name in names}
    actual=remote_files(project,service,base,names)
    omitted=[name for name in names if actual[name] is None and optional_tests and pathlib.Path(name).name.startswith('test_')]
    mismatch=[name for name in names if name not in omitted and expected[name]!=actual[name]]
    return {'checked_files':len(names)-len(omitted),'mismatches':mismatch,'development_only_tests':omitted}
def agent_files():
    base=ROOT/'src/document-agent';names=set()
    for line in (base/'Dockerfile').read_text(encoding='utf-8').splitlines():
        if not line.startswith('COPY '):continue
        for pattern in shlex.split(line)[1:-1]:
            for path in base.glob(pattern):
                candidates=path.rglob('*') if path.is_dir() else [path]
                names.update(p.relative_to(base).as_posix() for p in candidates if p.is_file() and '__pycache__' not in p.parts)
    return sorted(names)
def webui_hashes():
    read=lambda name:(ROOT/'src/document-agent'/name).read_text(encoding='utf-8')
    bridge=read('webui_bridge.py')
    attachment=read('webui_files.py').replace('async def read_outline_attachment(','async def _read_outline_attachment(')
    expected={'tool':{},'function':{}}
    for ident,name in [('outline_read','webui_read.py'),('outline_write','webui_workflow.py'),('outline_files','webui_files.py'),('outline_edit','webui_edit.py')]:
        content=bridge+read(name)+(attachment if ident=='outline_write' else '')
        compile(content,ident,'exec');expected['tool'][ident]=digest(content.encode())
    content=bridge+read('webui_workflow.py')+attachment+read('webui_receipt.py')
    compile(content,'outline_receipt','exec');expected['function']['outline_receipt']=digest(content.encode())
    return expected
def audit(project):
    if not re.fullmatch(r'(?:unified-work-assistant|workhub-[a-z0-9-]+)',project):raise ValueError('Invalid project')
    base=ROOT/'src/workhub'
    names=sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.html','.js','.css','.png','.svg'))
    result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'project':project,
        'workhub':file_check(project,'workhub','/app/workhub',base,names,optional_tests=True),
        'document-agent':file_check(project,'document-agent','/app',ROOT/'src/document-agent',agent_files()),
        'embedding-worker':file_check(project,'embedding-worker','/app',ROOT/'src/document-agent',['embedding_worker.py','rag_chunks.py','install_rag_models.py'])}
    code="import sqlite3,json,hashlib;c=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True);print(json.dumps({table:{r[0]:hashlib.sha256(r[1].encode()).hexdigest() for r in c.execute('SELECT id,content FROM '+table) if r[0].startswith('outline_')} for table in ['tool','function']}))"
    installed=run(['docker','exec',project+'-open-webui-1','python','-c',code]);expected=webui_hashes()
    result['webui']={'checked_tools':5,'mismatches':[ident for table,rows in expected.items() for ident,sha in rows.items() if installed.get(table,{}).get(ident)!=sha]}
    lock=json.loads((ROOT/'integrations/outline/upstream.lock.json').read_text(encoding='utf-8'))
    names=[name for name in lock['patchedFiles'] if name.startswith('server/')]
    source=ROOT/'integrations/outline'/('outline-'+lock['commit'])
    expected={name:digest((source/name).read_text(encoding='utf-8').encode()) for name in names}
    code="const fs=require('fs'),crypto=require('crypto');let names="+json.dumps(names)+";console.log(JSON.stringify(Object.fromEntries(names.map(n=>[n,fs.existsSync('/opt/outline/'+n)?crypto.createHash('sha256').update(fs.readFileSync('/opt/outline/'+n,'utf8').replace(/\\r\\n/g,'\\n')).digest('hex'):null]))))"
    installed=run(['docker','exec',project+'-outline-1','node','-e',code])
    result['outline']={'checked_server_sources':len(names),'mismatches':[name for name in names if expected[name]!=installed.get(name)],
                       'frontend_provenance':'Exact current tested image is pinned; managed frontend sources are verified separately by patch reproduction.'}
    result['passed']=all(not result[name]['mismatches'] for name in ('workhub','document-agent','embedding-worker','webui','outline'))
    return result
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',default='unified-work-assistant');parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args();result=audit(args.project)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['passed'] else 1)
if __name__=='__main__':main()
