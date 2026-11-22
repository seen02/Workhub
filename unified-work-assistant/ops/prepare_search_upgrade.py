"""Local rollback snapshot; never print runtime credentials."""
import json, shutil, subprocess, zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
dest=root/'backups/search-upgrade-20260930'
dest.mkdir(exist_ok=True,parents=True)
if not (dest/'source.zip').exists():
    with zipfile.ZipFile(dest/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for folder in ('src/workhub','src/document-agent','config/nginx-local'):
            for p in (root/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in str(p):z.write(p,p.relative_to(root))
        for name in ('export_patch.py','upstream.lock.json','patches/0001-workhub-project-management.patch'):
            p=root/'integrations/outline'/name;z.write(p,p.relative_to(root))
    shutil.copy2(root/'.local/compose.json',dest/'compose.json')
    state={}
    for service in ('outline','workhub','document-agent'):
        container='unified-work-assistant-'+service+'-1'
        image=subprocess.check_output(['docker','inspect','--format','{{.Image}}',container],text=True).strip()
        tag='unified-work-assistant/'+service+':before-search-20260930'
        subprocess.run(['docker','tag',image,tag],check=True)
        state[service]={'image':image,'tag':tag}
    (dest/'images.json').write_text(json.dumps(state,indent=2))
    subprocess.run(['docker','exec','unified-work-assistant-workhub-1','python','-c',
      "import sqlite3; a=sqlite3.connect('/app/data/workhub.sqlite3'); b=sqlite3.connect('/tmp/search-before.sqlite3'); a.backup(b); b.close()"],check=True)
    subprocess.run(['docker','cp','unified-work-assistant-workhub-1:/tmp/search-before.sqlite3',str(dest/'workhub.sqlite3')],check=True)
print('Rollback source, configuration, image tags and Workhub database ready.')
