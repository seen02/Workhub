import json
from pathlib import Path
root=Path(__file__).resolve().parents[1];src=root/'src/document-agent'
read=lambda f:(src/f).read_text(encoding='utf-8')
bridge=read('webui_bridge.py');attachment=read('webui_files.py').replace('async def read_outline_attachment(','async def _read_outline_attachment(')
out=[]
for ident,file in [('outline_read','webui_read.py'),('outline_write','webui_workflow.py'),('outline_files','webui_files.py'),('outline_edit','webui_edit.py')]:
    content=bridge+read(file)+(attachment if ident=='outline_write' else '')
    compile(content,ident,'exec');out.append({'kind':'tools','id':ident,'content':content})
content=bridge+read('webui_workflow.py')+attachment+read('webui_receipt.py')
compile(content,'outline_receipt','exec');out.append({'kind':'functions','id':'outline_receipt','content':content})
(root/'.local/permissions-tools.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
print('Compiled four WebUI tools and one result filter.')
