"""Export source without private configuration, generated files or runtime data."""
import hashlib
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    excluded = {'.git', 'node_modules', '.yarn', '__pycache__', '.runtime', '.venv',
                '.build-venv', 'dist', 'build', 'reports', 'backups', '.cache',
                '.pytest_cache', '.mypy_cache', '.ruff_cache', 'coverage'}
    safe_envs = {'.env.example', '.env.vm.example', '.env.sample'}
    blocked_suffixes = {'.pyc', '.pyo', '.db', '.sqlite', '.sqlite3', '.key', '.pem',
                        '.pfx', '.p12', '.crt', '.log', '.tar', '.gz', '.tgz', '.zip',
                        '.whl', '.tsbuildinfo'}
    if (ROOT / '.git').exists():
        # A freshly synchronized feature can include new, unstaged source files.
        # Include them without staging changes; existing ignore/export filters apply.
        raw = subprocess.check_output(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
        files = [ROOT / name.decode('utf-8') for name in raw.split(b'\0') if name]
    else:
        files = []
        for directory, dirs, names in os.walk(ROOT):
            dirs[:] = sorted(name for name in dirs if name not in excluded
                             and not name.endswith('.egg-info')
                             and not (Path(directory) / name).is_symlink())
            files.extend(Path(directory) / name for name in names)
    selected = []
    for path in files:
        relative = path.relative_to(ROOT)
        if any(part in excluded or part.endswith('.egg-info') for part in relative.parts):
            continue
        if path.is_symlink():
            raise SystemExit('Review symlink before exporting: ' + relative.as_posix())
        source_fixture = (relative.parts[:4] == ('outline', 'server', 'test', 'fixtures')
                          and path.suffix.lower() == '.zip')
        if not path.is_file() or (path.suffix.lower() in blocked_suffixes and not source_fixture):
            continue
        if path.name.startswith('.env') and path.name not in safe_envs:
            continue
        if (path.suffix.lower() in {'.md', '.mdx'} and relative.as_posix() != 'README.md'
                and not path.name.upper().startswith(('LICENSE', 'NOTICE', 'COPYING', 'COPYRIGHT'))):
            continue
        if path.name in {'checksums.json', '.DS_Store', 'Thumbs.db'}:
            continue
        selected.append(path)
    if not selected:
        raise SystemExit('No source files found. Add the intended sources to Git first.')
    destination = ROOT / 'dist' / 'outline-authentik-source.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(selected):
            archive.write(path, 'outline-authentik/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise SystemExit('ZIP CRC verification failed.')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(
        digest + '  ' + destination.name + '\n', encoding='ascii')
    print(f'Source ZIP: {len(selected)} files, {destination.stat().st_size:,} bytes')
    print(destination)


if __name__ == '__main__':
    main()
