#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# != 1 )); then
  echo "Usage: $0 IMAGE_TAG" >&2
  exit 2
fi

image_tag="$1"
if [[ ! "$image_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Invalid Docker image tag: $image_tag" >&2
  exit 2
fi

app_dir="${APP_DIR:-$HOME/apps/custom_outline_deploy}"
upload_dir="${UPLOAD_DIR:-$HOME/custom-outline-upload}"
env_file="$app_dir/.env"
outline_archive="$upload_dir/outline-image-$image_tag.tar"
workhub_archive="$upload_dir/workhub-image-$image_tag.tar"
if [[ ! -f "$outline_archive" ]]; then
  outline_archive="$upload_dir/outline-image.tar"
fi
if [[ ! -f "$workhub_archive" ]]; then
  workhub_archive="$upload_dir/workhub-image.tar"
fi
checksum_file="$upload_dir/images.sha256"

for path in "$env_file" "$app_dir/compose.yaml" "$outline_archive" "$workhub_archive" "$checksum_file"; do
  if [[ ! -f "$path" ]]; then
    echo "Required file not found: $path" >&2
    exit 1
  fi
done

if ! command -v sha256sum >/dev/null 2>&1; then
  echo 'sha256sum is required on the VM.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'python3 is required on the VM.' >&2
  exit 1
fi

echo 'Checking uploaded image files'
(cd "$upload_dir" && sha256sum --check images.sha256)

timestamp="$(date +%Y%m%d-%H%M%S)"
env_backup="$app_dir/.env.before-update-$timestamp"
if [[ -e "$env_backup" ]]; then
  echo "Backup already exists: $env_backup" >&2
  exit 1
fi
cp -p "$env_file" "$env_backup"
echo "Saved environment backup: $env_backup"

echo 'Loading Outline image'
sudo docker load --input "$outline_archive"
echo 'Loading Workhub image'
sudo docker load --input "$workhub_archive"

outline_image="custom-outline/outline:$image_tag"
workhub_image="custom-outline/workhub:$image_tag"
sudo docker image inspect "$outline_image" >/dev/null
sudo docker image inspect "$workhub_image" >/dev/null

python3 - "$env_file" "$image_tag" <<'PY'
import os
from pathlib import Path
import stat
import sys
import tempfile

env_path = Path(sys.argv[1])
tag = sys.argv[2]
text = env_path.read_text(encoding='utf-8')
lines = text.splitlines(keepends=True)
replacements = {
    'OUTLINE_IMAGE': f'custom-outline/outline:{tag}',
    'WORKHUB_IMAGE': f'custom-outline/workhub:{tag}',
}

for key, value in replacements.items():
    matches = [index for index, line in enumerate(lines) if line.startswith(key + '=')]
    if len(matches) != 1:
        raise SystemExit(f'{key} must appear exactly once in {env_path}.')
    index = matches[0]
    ending = '\r\n' if lines[index].endswith('\r\n') else '\n' if lines[index].endswith('\n') else ''
    lines[index] = f'{key}={value}{ending}'

original_mode = stat.S_IMODE(env_path.stat().st_mode)
fd, temp_name = tempfile.mkstemp(prefix='.env.deploy-', dir=env_path.parent)
try:
    with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
        stream.writelines(lines)
    os.chmod(temp_name, original_mode)
    os.replace(temp_name, env_path)
except BaseException:
    try:
        os.unlink(temp_name)
    except FileNotFoundError:
        pass
    raise
PY

cd "$app_dir"
if ! sudo docker compose config --quiet; then
  cp -p "$env_backup" "$env_file"
  echo 'Compose configuration failed. Restored the previous .env.' >&2
  exit 1
fi

echo "Deploying $outline_image and $workhub_image"
sudo docker compose up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 180 outline workhub
sudo docker compose ps outline workhub
echo 'Deployment completed.'
