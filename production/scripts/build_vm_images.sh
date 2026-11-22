#!/usr/bin/env bash
set -euo pipefail

if (( $# > 2 )); then
  echo "Usage: $0 [IMAGE_TAG] [PLATFORM]" >&2
  exit 2
fi

image_tag="${1:-$(date +%Y%m%d-%H%M%S)}"
target_platform="${2:-linux/amd64}"
if [[ ! "$image_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Invalid Docker image tag: $image_tag" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI was not found. Install/start Docker Desktop and retry." >&2
  exit 1
fi

if ! engine_os="$(docker info --format '{{.OSType}}')"; then
  echo "Docker Engine is unavailable. Start Docker Desktop and retry." >&2
  exit 1
fi
if [[ "$engine_os" != "linux" ]]; then
  echo "Docker Engine must use Linux containers. Current engine: $engine_os" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
output_dir="$repo_root/dist/vm-images/$image_tag"

for dockerfile in docker/Dockerfile.outline docker/Dockerfile.workhub; do
  if [[ ! -f "$repo_root/$dockerfile" ]]; then
    echo "Dockerfile not found: $repo_root/$dockerfile" >&2
    exit 1
  fi
done

if [[ -e "$output_dir" ]]; then
  echo "Output directory already exists: $output_dir. Choose a new image tag." >&2
  exit 1
fi

for image_name in custom-outline/outline custom-outline/workhub; do
  image_ref="$image_name:$image_tag"
  if docker image inspect "$image_ref" >/dev/null 2>&1; then
    echo "Image tag already exists locally: $image_ref. Choose a new image tag." >&2
    exit 1
  fi
done

mkdir -p "$output_dir"

build_and_save() {
  local image_name="$1"
  local dockerfile="$2"
  local archive="$3"
  local image_ref="$image_name:$image_tag"

  echo "Building $image_ref"
  docker build --platform "$target_platform" --file "$repo_root/$dockerfile" --tag "$image_ref" "$repo_root"

  echo "Saving $output_dir/$archive"
  docker image save --output "$output_dir/$archive" "$image_ref"
}

build_and_save custom-outline/outline docker/Dockerfile.outline outline-image.tar
build_and_save custom-outline/workhub docker/Dockerfile.workhub workhub-image.tar

(
  cd "$output_dir"
  shasum -a 256 outline-image.tar workhub-image.tar > images.sha256
)

echo
echo "Images are ready for VM transfer:"
echo "  OUTLINE_IMAGE=custom-outline/outline:$image_tag"
echo "  WORKHUB_IMAGE=custom-outline/workhub:$image_tag"
echo "  $output_dir/outline-image.tar"
echo "  $output_dir/workhub-image.tar"
echo "  $output_dir/images.sha256"
echo "  IMAGE_TAG=$image_tag"
echo "  TARGET_PLATFORM=$target_platform"
