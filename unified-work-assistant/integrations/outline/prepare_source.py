"""Materialize the pinned upstream and apply the reviewed patch in a fresh folder."""
import hashlib,json,subprocess,tarfile,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
lock=json.loads((root/'upstream.lock.json').read_text())
archive=root/'upstream.tar.gz';target=root/('outline-'+lock['commit'])
if target.exists():raise SystemExit('Source directory already exists; refusing to overwrite local changes.')
if not archive.exists():urllib.request.urlretrieve(lock['archiveUrl'],archive)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock['archiveSha256']:raise SystemExit('Upstream archive checksum mismatch.')
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        # CLAUDE.md is a symlink to AGENTS.md; skip symlinks on Windows.
        if member.issym() or member.islnk():continue
        resolved=(root/member.name).resolve()
        if not resolved.is_relative_to(target.resolve()):raise SystemExit('Unexpected archive member')
        tar.extract(member,root,filter='data')
subprocess.run(['git','apply','--check',str(root/'patches/0001-workhub-project-management.patch')],cwd=target,check=True)
subprocess.run(['git','apply',str(root/'patches/0001-workhub-project-management.patch')],cwd=target,check=True)
print('Prepared pinned Outline source with project management integration.')
