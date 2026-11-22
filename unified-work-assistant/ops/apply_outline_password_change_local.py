"""Select the password-change Outline image without changing credentials or volumes."""
import argparse
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
parser.add_argument('--rollback', action='store_true')
args = parser.parse_args()
config_path = root / '.local/compose.json'
backup_path = root / '.local/password-change-before-20261027/compose.private.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
image = 'unified-work-assistant/outline:password-change-20261027'
if args.rollback:
    previous = json.loads(backup_path.read_text(encoding='utf-8-sig'))
    image = previous['services']['outline']['image']
print('outline: ' + image)
if args.apply:
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, backup_path)
    config['services']['outline']['image'] = image
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Updated Outline image only; volumes and credentials preserved.')
