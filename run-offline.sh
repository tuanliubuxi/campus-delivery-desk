#!/usr/bin/env bash
set -euo pipefail

# Import a prepared image archive and start production without pulling or building images.
# Usage: ./run-offline.sh [path-to-docker-images.tar]
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"

command -v docker >/dev/null || { echo "[ERROR] Docker CLI was not found." >&2; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "[ERROR] Docker Engine is not running or is not accessible." >&2
  exit 1
}
[[ -f .env ]] || { echo "[ERROR] .env was not found." >&2; exit 1; }
if grep -Fq 'DJANGO_SECRET_KEY=replace-with-a-long-random-secret' .env; then
  echo "[ERROR] Refusing to start with the example DJANGO_SECRET_KEY." >&2
  exit 1
fi

image_archive="${1:-}"
if [[ -z "$image_archive" ]]; then
  shopt -s nullglob
  candidates=(tags/*-docker-linux-*.tar ../*-docker-linux-*.tar ./*-docker-linux-*.tar)
  shopt -u nullglob
  if (( ${#candidates[@]} != 1 )); then
    echo "[ERROR] Pass the exact Docker archive path: ./run-offline.sh path/release-docker-linux-amd64.tar" >&2
    exit 1
  fi
  image_archive="${candidates[0]}"
fi
[[ -f "$image_archive" ]] || { echo "[ERROR] Docker archive not found: $image_archive" >&2; exit 1; }

echo "[INFO] Importing application and Caddy images..."
docker image load -i "$image_archive"
docker compose config --quiet
echo "[INFO] Applying database migrations..."
docker compose run --rm --no-deps --pull never web python manage.py migrate
echo "[INFO] Seeding initial configuration..."
docker compose run --rm --no-deps --pull never web python manage.py seed_initial_config

set +e
docker compose run --rm --no-deps --pull never web python manage.py shell -c \
  "from apps.accounts.models import User; from apps.common.enums import UserRole; raise SystemExit(0 if User.objects.filter(role=UserRole.ADMIN).exists() else 42)"
admin_check=$?
set -e
if (( admin_check == 42 )); then
  echo "[INFO] No administrator exists. Create the first administrator now."
  docker compose run --rm --no-deps --pull never web python manage.py create_app_admin
elif (( admin_check != 0 )); then
  echo "[ERROR] Could not check the administrator state." >&2
  exit 1
fi

echo "[INFO] Starting services without downloads or builds..."
docker compose up -d --no-build --pull never
docker compose ps
echo "[OK] Offline production services started."
