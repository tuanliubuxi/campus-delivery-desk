#!/usr/bin/env bash
set -euo pipefail

# Build private project, virtualenv, and Docker archives under tags/.
# Usage: ./build-release.sh [amd64|arm64] [release-name]
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"

detected_arch="$(uname -m)"
case "$detected_arch" in
  x86_64) detected_arch="amd64" ;;
  aarch64|arm64) detected_arch="arm64" ;;
esac
target_arch="${1:-$detected_arch}"
case "$target_arch" in
  amd64|arm64) ;;
  *) echo "[ERROR] Architecture must be amd64 or arm64." >&2; exit 1 ;;
esac

for command_name in docker git tar sha256sum; do
  command -v "$command_name" >/dev/null || {
    echo "[ERROR] $command_name was not found." >&2
    exit 1
  }
done
docker info >/dev/null 2>&1 || {
  echo "[ERROR] Docker Engine is not running or is not accessible." >&2
  exit 1
}

project_version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -n 1)"
[[ -n "$project_version" ]] || { echo "[ERROR] Could not read pyproject.toml version." >&2; exit 1; }
release_name="${2:-campus-delivery-desk-v${project_version}-$(date +%Y%m%d)}"
[[ "$release_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  echo "[ERROR] Invalid release name: $release_name" >&2
  exit 1
}

[[ -f .env ]] || { echo "[ERROR] .env was not found." >&2; exit 1; }
if grep -Fq 'DJANGO_SECRET_KEY=replace-with-a-long-random-secret' .env; then
  echo "[ERROR] Refusing to package the example DJANGO_SECRET_KEY." >&2
  exit 1
fi
git diff --quiet && git diff --cached --quiet || {
  echo "[ERROR] Commit tracked changes before creating a versioned release archive." >&2
  exit 1
}
if [[ -n "$(docker compose ps --status running -q 2>/dev/null)" ]]; then
  echo "[ERROR] Compose services are running. Stop them before copying runtime data." >&2
  exit 1
fi

mkdir -p tags
project_archive="tags/${release_name}-project-private.tar.gz"
venv_archive="tags/${release_name}-venv-linux-${target_arch}.tar.gz"
docker_archive="tags/${release_name}-docker-linux-${target_arch}.tar"
manifest="tags/${release_name}-manifest.txt"
for target in "$project_archive" "$venv_archive" "$docker_archive" "$manifest"; do
  [[ ! -e "$target" ]] || { echo "[ERROR] Refusing to overwrite $target" >&2; exit 1; }
done

echo "[INFO] Building application image for linux/${target_arch}..."
docker buildx build --platform "linux/${target_arch}" --load \
  -t campus-delivery-desk-app:local \
  -t "campus-delivery-desk-app:${release_name}" .
echo "[INFO] Preparing Caddy image for linux/${target_arch}..."
docker pull --platform "linux/${target_arch}" caddy:2
echo "[INFO] Exporting Docker images..."
docker image save -o "$docker_archive" \
  campus-delivery-desk-app:local "campus-delivery-desk-app:${release_name}" caddy:2

stage_dir="$(mktemp -d)"
cleanup() { rm -rf -- "$stage_dir"; }
trap cleanup EXIT
mkdir -p "$stage_dir/$release_name"
tar -C "$root_dir" \
  --exclude='./.venv' --exclude='./tags' --exclude='./.ruff_cache' \
  --exclude='./.pytest_cache' --exclude='*/__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
  -cf - . | tar -C "$stage_dir/$release_name" -xf -
tar -C "$stage_dir" -czf "$root_dir/$project_archive" "$release_name"

if [[ -d .venv ]]; then
  echo "[INFO] Archiving the Linux virtual environment separately..."
  tar -czf "$venv_archive" .venv
else
  echo "[WARN] .venv was not found; no virtualenv archive was created."
  venv_archive=""
fi

{
  echo "Release: $release_name"
  echo "Project version: $project_version"
  echo "Git commit: $(git rev-parse HEAD)"
  echo "Docker platform: linux/$target_arch"
  echo "Created: $(date --iso-8601=seconds)"
  echo
  sha256sum "$project_archive" "$docker_archive"
  [[ -z "$venv_archive" ]] || sha256sum "$venv_archive"
} >"$manifest"

echo "[OK] Release artifacts created in tags/:"
echo "  $project_archive"
[[ -z "$venv_archive" ]] || echo "  $venv_archive"
echo "  $docker_archive"
echo "  $manifest"
echo "[WARN] The private project archive contains .env and data. Store and transfer it securely."
