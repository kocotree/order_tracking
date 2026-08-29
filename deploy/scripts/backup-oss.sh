#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
resolve_environment "${environment}"
command -v ossutil >/dev/null || { echo "Alibaba Cloud ossutil 2.x is required" >&2; exit 1; }

set -a
source "${environment_file}"
set +a
: "${ORDER_TRACKING_OSS_REGION:?set OSS region in the protected environment file}"
: "${ORDER_TRACKING_OSS_ENDPOINT:?set OSS endpoint in the protected environment file}"
: "${ORDER_TRACKING_OSS_ACCESS_KEY_ID:?set OSS access key id in the protected environment file}"
: "${ORDER_TRACKING_OSS_ACCESS_KEY_SECRET:?set OSS access key secret in the protected environment file}"
: "${ORDER_TRACKING_OSS_BUCKET:?set OSS bucket in the protected environment file}"

backup_root=${ORDER_TRACKING_OSS_BACKUP_DIR:?set an absolute protected backup directory}
[[ "${backup_root}" = /* ]] || { echo "backup directory must be absolute" >&2; exit 2; }
target="${backup_root}/${environment}/${ORDER_TRACKING_OSS_BUCKET}/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${target}"
chmod 700 "${backup_root}"

export OSS_REGION="${ORDER_TRACKING_OSS_REGION}"
export OSS_ENDPOINT="${ORDER_TRACKING_OSS_ENDPOINT}"
export OSS_ACCESS_KEY_ID="${ORDER_TRACKING_OSS_ACCESS_KEY_ID}"
export OSS_ACCESS_KEY_SECRET="${ORDER_TRACKING_OSS_ACCESS_KEY_SECRET}"
ossutil cp -r "oss://${ORDER_TRACKING_OSS_BUCKET}/" "${target}/"
find "${target}" -type f -exec sha256sum {} + >"${target}.sha256"
echo "OSS backup created at ${target}"
