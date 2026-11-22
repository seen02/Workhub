"""Select the validated local daily-report images without changing service data."""
import argparse
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
parser.add_argument('--rollback', action='store_true')
parser.add_argument('--native', action='store_true', help='Use native editor integration; leave Workhub unchanged.')
args = parser.parse_args()
config_path = root / '.local/compose.json'
backup_path = root / ('.local/daily-reports-native-before-20261026/compose.private.json' if args.native else '.local/daily-reports-before-20261026/compose.private.json')
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
if args.rollback:
    previous = json.loads(backup_path.read_text(encoding='utf-8-sig'))
    images = {name: previous['services'][name]['image'] for name in (('outline',) if args.native else ('outline', 'workhub'))}
elif args.native:
    images = {'outline': 'unified-work-assistant/outline:daily-reports-native-20261026'}
else:
    images = {name: f'unified-work-assistant/{name}:daily-reports-20261026' for name in ('outline', 'workhub')}
for name, image in images.items():
    print(name + ': ' + image)
    config['services'][name]['image'] = image
if args.apply:
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, backup_path)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Updated image references only; volumes and credentials preserved.')
