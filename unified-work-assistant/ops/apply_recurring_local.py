"""Apply/rollback recurring-task images in the existing local Compose, preserving data."""
import argparse
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.local/compose.json'
BACKUP = ROOT / '.local/recurring-before-20261028'
IMAGES = {name: 'unified-work-assistant/' + name + ':recurring-20261029' for name in ('outline', 'workhub')}


def run(*args):
    return subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apply', action='store_true')
    group.add_argument('--rollback', action='store_true')
    parser.add_argument('--start', action='store_true', help='Recreate only Outline and Workhub.')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    before = json.loads(json.dumps(config))
    if args.apply:
        for image in IMAGES.values():
            run('docker', 'image', 'inspect', image, '--format', '{{.Id}}')
        outline_env = config['services']['outline']['environment']
        workhub_env = config['services']['workhub']['environment']
        secret = outline_env.get('OUTLINE_WORKHUB_BRIDGE_SECRET')
        if not secret or secret != workhub_env.get('OUTLINE_WORKHUB_BRIDGE_SECRET'):
            raise SystemExit('Existing Outline/Workhub bridge configuration must match.')
        if any(env.get('OUTLINE_TASK_CREATION_ENABLED') != 'true' for env in (outline_env, workhub_env)):
            raise SystemExit('Enable the existing task creation feature first.')
        BACKUP.mkdir(parents=True, exist_ok=True)
        if not (BACKUP / 'compose.private.json').exists():
            shutil.copy2(CONFIG, BACKUP / 'compose.private.json')
        database = ROOT / 'runtime/workhub/workhub.sqlite3'
        if database.exists() and not (BACKUP / 'workhub.sqlite3').exists():
            with sqlite3.connect(str(database)) as source, sqlite3.connect(str(BACKUP / 'workhub.sqlite3')) as target:
                source.backup(target)
        for name, image in IMAGES.items():
            config['services'][name]['image'] = image
            config['services'][name]['environment']['OUTLINE_RECURRING_ENABLED'] = 'true'
    else:
        previous = json.loads((BACKUP / 'compose.private.json').read_text(encoding='utf-8-sig'))
        for name in IMAGES:
            config['services'][name]['image'] = previous['services'][name]['image']
            value = previous['services'][name]['environment'].get('OUTLINE_RECURRING_ENABLED')
            if value is None:
                config['services'][name]['environment'].pop('OUTLINE_RECURRING_ENABLED', None)
            else:
                config['services'][name]['environment']['OUTLINE_RECURRING_ENABLED'] = value
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        run('docker', 'compose', '-f', 'compose.yml', 'config', '--quiet')
        if args.start:
            run('docker', 'compose', '-f', 'compose.yml', 'up', '-d', '--no-deps', '--no-build', 'outline', 'workhub')
    except BaseException:
        CONFIG.write_text(json.dumps(before, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    for name in IMAGES:
        print(name + ': ' + config['services'][name]['image'])
    print('Data volumes, credentials and unrelated services preserved.')


if __name__ == '__main__':
    main()
