"""Restore the previous local Outline/Workhub images, preserving current data."""
import json
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    config_path = root / '.local/compose.json'
    backup_path = root / '.local/outline-authentik-20261019-before/compose.private.json'
    previous = json.loads(backup_path.read_text(encoding='utf-8-sig'))
    original = config_path.read_text(encoding='utf-8-sig')
    current = json.loads(original)
    for name in ('outline', 'workhub'):
        image = previous['services'][name]['image']
        subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL, check=True)
        current['services'][name]['image'] = image
    config_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    command = ['docker', 'compose', '-f', str(root / 'compose.yml')]
    validation = subprocess.run(command + ['config', '--quiet'], cwd=root)
    if validation.returncode:
        config_path.write_text(original, encoding='utf-8')
        raise SystemExit(validation.returncode)
    subprocess.run(command + ['up', '-d', '--no-deps', '--no-build', '--force-recreate', 'outline', 'workhub'],
                   cwd=root, check=True)
    print('Restored the previous two images. Current databases, volumes and source files are retained.')


if __name__ == '__main__':
    main()
