"""Cold copy one volume and verify byte content, ownership and modes."""
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

src=Path('/source');dst=Path('/target')
if any(dst.iterdir()):raise RuntimeError('Target volume must be empty')
shutil.copytree(src,dst,dirs_exist_ok=True,symlinks=True)
count=0;size=0;summary=hashlib.sha256()
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
for p in [src,*sorted(src.rglob('*'))]:
    rel=p.relative_to(src);q=dst/rel;s=p.lstat()
    os.chown(q,s.st_uid,s.st_gid,follow_symlinks=False)
    if not p.is_symlink():os.chmod(q,stat.S_IMODE(s.st_mode))
    if p.is_symlink():assert os.readlink(p)==os.readlink(q)
    elif p.is_file():
        a=digest(p);b=digest(q);assert a==b,str(rel)
        count+=1;size+=s.st_size;summary.update((str(rel)+a).encode())
    t=q.lstat();assert (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(t.st_uid,t.st_gid,stat.S_IMODE(t.st_mode))
os.sync()
print(json.dumps({'verified_files':count,'bytes':size,'content_manifest_sha256':summary.hexdigest()}))
