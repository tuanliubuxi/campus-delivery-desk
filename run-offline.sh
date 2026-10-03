#!/usr/bin/env bash
set -euo pipefail

# Root mode extracts a selected runtime archive under deployments/.
# Runtime mode imports the Docker tar next to this script and starts production.
# Usage: ./run-offline.sh [runtime.tar.gz|docker-images.tar]
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"

command -v docker >/dev/null || { echo "[ERROR] Docker CLI was not found." >&2; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "[ERROR] Docker Engine is not running or is not accessible." >&2
  exit 1
}

host_arch="$(uname -m)"
case "$host_arch" in
  x86_64) host_arch="amd64" ;;
  aarch64|arm64) host_arch="arm64" ;;
  *) echo "[ERROR] Unsupported host architecture: $host_arch" >&2; exit 1 ;;
esac

select_candidate() {
  local label="$1"
  shift
  local -a choices=("$@")
  echo "[INFO] Available ${label}:"
  for index in "${!choices[@]}"; do
    printf '  [%d] %s\n' "$((index + 1))" "${choices[index]}"
  done
  if (( ${#choices[@]} == 1 )); then
    selected="${choices[0]}"
    echo "[INFO] Automatically selected the only available candidate."
    return
  fi
  while true; do
    read -r -p "Select [1-${#choices[@]}] or 0 to cancel: " choice
    [[ "$choice" == "0" ]] && exit 1
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#choices[@]} )); then
      selected="${choices[choice - 1]}"
      return
    fi
    echo "[ERROR] Invalid selection." >&2
  done
}

absolute_candidates() {
  while IFS= read -r item; do
    readlink -f -- "$item"
  done | sort -u
}

argument="${1:-}"
image_archive=""
runtime_archive=""
if [[ -n "$argument" ]]; then
  case "$argument" in
    *.tar.gz) runtime_archive="$(readlink -f -- "$argument")" ;;
    *) image_archive="$(readlink -f -- "$argument")" ;;
  esac
else
  shopt -s nullglob
  local_images=(./*-docker-linux-"${host_arch}".tar)
  shopt -u nullglob
  if (( ${#local_images[@]} > 0 )); then
    mapfile -t candidates < <(printf '%s\n' "${local_images[@]}" | absolute_candidates)
    select_candidate "Docker archives" "${candidates[@]}"
    image_archive="$selected"
  else
    shopt -s nullglob
    runtime_archives=(tags/*/*-offline-runtime-"${host_arch}".tar.gz tags/*-offline-runtime-"${host_arch}".tar.gz)
    shopt -u nullglob
    if (( ${#runtime_archives[@]} > 0 )); then
      mapfile -t candidates < <(printf '%s\n' "${runtime_archives[@]}" | absolute_candidates)
      select_candidate "offline runtime bundles for ${host_arch}" "${candidates[@]}"
      runtime_archive="$selected"
    else
      shopt -s nullglob
      legacy_images=(tags/*/*-docker-linux-"${host_arch}".tar tags/*-docker-linux-"${host_arch}".tar ../*-docker-linux-"${host_arch}".tar)
      shopt -u nullglob
      (( ${#legacy_images[@]} > 0 )) || {
        echo "[ERROR] No ${host_arch} offline runtime bundle or Docker archive was found." >&2
        exit 1
      }
      mapfile -t candidates < <(printf '%s\n' "${legacy_images[@]}" | absolute_candidates)
      select_candidate "legacy Docker archives for ${host_arch}" "${candidates[@]}"
      image_archive="$selected"
    fi
  fi
fi

if [[ -n "$runtime_archive" ]]; then
  [[ -f "$runtime_archive" ]] || { echo "[ERROR] Runtime bundle not found: $runtime_archive" >&2; exit 1; }
  [[ -f .env ]] || { echo "[ERROR] Root .env was not found. It is shared by deployments." >&2; exit 1; }
  if grep -Fq 'DJANGO_SECRET_KEY=replace-with-a-long-random-secret' .env; then
    echo "[ERROR] Refusing to deploy with the example root DJANGO_SECRET_KEY." >&2
    exit 1
  fi
  deployment_name="$(basename "$runtime_archive" .tar.gz)"
  deployments_dir="$root_dir/deployments"
  deployment_dir="$deployments_dir/$deployment_name"
  mkdir -p "$deployments_dir"
  if [[ ! -d "$deployment_dir" ]]; then
    echo "[INFO] Extracting $runtime_archive"
    echo "[INFO] Deployment directory: $deployment_dir"
    tar -xzf "$runtime_archive" -C "$deployments_dir"
  else
    echo "[INFO] Reusing existing deployment directory: $deployment_dir"
  fi
  [[ -f "$deployment_dir/run-offline.sh" ]] || {
    echo "[ERROR] The runtime bundle did not contain the expected deployment directory." >&2
    exit 1
  }
  mkdir -p data/{db,media,backups,tmp,logs}
  (
    cd "$deployment_dir"
    export CDD_DATA_PATH="../../data"
    export CDD_ENV_FILE="../../.env"
    bash ./run-offline.sh
  )
  exit $?
fi

[[ -f "$image_archive" ]] || { echo "[ERROR] Docker archive not found: $image_archive" >&2; exit 1; }
env_file="${CDD_ENV_FILE:-.env}"
export CDD_ENV_FILE="$env_file"
export CDD_DATA_PATH="${CDD_DATA_PATH:-./data}"
[[ -f "$env_file" ]] || { echo "[ERROR] Environment file not found: $env_file" >&2; exit 1; }
if grep -Fq 'DJANGO_SECRET_KEY=replace-with-a-long-random-secret' "$env_file"; then
  echo "[ERROR] Refusing to start with the example DJANGO_SECRET_KEY." >&2
  exit 1
fi

compose() { docker compose --env-file "$env_file" "$@"; }

echo "[INFO] Importing application and Caddy images..."
docker image load -i "$image_archive"
compose config --quiet
echo "[INFO] Applying database migrations..."
compose run --rm --no-deps --pull never web python manage.py migrate
echo "[INFO] Seeding initial configuration..."
compose run --rm --no-deps --pull never web python manage.py seed_initial_config

set +e
compose run --rm --no-deps --pull never web python manage.py shell -c \
  "from apps.accounts.models import User; from apps.common.enums import UserRole; raise SystemExit(0 if User.objects.filter(role=UserRole.ADMIN).exists() else 42)"
admin_check=$?
set -e
if (( admin_check == 42 )); then
  echo "[INFO] No administrator exists. Create the first administrator now."
  compose run --rm --no-deps --pull never web python manage.py create_app_admin
elif (( admin_check != 0 )); then
  echo "[ERROR] Could not check the administrator state." >&2
  exit 1
fi

echo "[INFO] Starting services without downloads or builds..."
if ! compose up -d --no-build --pull never; then
  echo "[ERROR] Service startup failed. Cleaning up partially started containers..." >&2
  compose down --remove-orphans
  exit 1
fi
compose ps
echo "[OK] Offline production services started."
