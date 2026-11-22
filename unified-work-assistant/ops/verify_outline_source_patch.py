"""Check that the exported patch reproduces every modified upstream source file."""
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
integration = root / 'integrations/outline'
lock = json.loads((integration / 'upstream.lock.json').read_text())
archive_path = integration / 'upstream.tar.gz'
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == lock['archiveSha256']
source = integration / ('outline-' + lock['commit'])
with tempfile.TemporaryDirectory(prefix='workhub-outline-patch-') as temporary:
    target = Path(temporary)
    with tarfile.open(archive_path) as archive:
        for name in lock['patchedFiles']:
            try:
                original = archive.extractfile('outline-' + lock['commit'] + '/' + name)
            except KeyError:
                continue
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(original.read())
    patch = str(integration / 'patches/0001-workhub-project-management.patch')
    subprocess.run(['git', 'apply', '--check', patch], cwd=target, check=True)
    subprocess.run(['git', 'apply', patch], cwd=target, check=True)
    for name in lock['patchedFiles']:
        assert (target / name).read_text(encoding='utf-8') == (source / name).read_text(encoding='utf-8'), name
print(f"PASS: archive SHA-256 and source text patch reproduction ({len(lock['patchedFiles'])} files; LF normalized)")
