#!/usr/bin/env bash
set -euo pipefail

environment=${1:-}
bucket=${2:-}
backup_root=${ORDER_TRACKING_MINIO_BACKUP_DIR:?set an absolute protected backup directory}
: "${MC_HOST_order_tracking:?set MC_HOST_order_tracking in the protected shell environment}"
command -v mc >/dev/null || { echo "MinIO mc is required" >&2; exit 1; }
[[ "${backup_root}" = /* && -n "${environment}" && -n "${bucket}" ]] || {
  echo "environment, bucket, and an absolute backup directory are required" >&2
  exit 2
}
target="${backup_root}/${environment}/${bucket}/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${target}"
chmod 700 "${backup_root}"
mc mirror --overwrite --preserve "order_tracking/${bucket}" "${target}"
find "${target}" -type f -exec sha256sum {} + >"${target}.sha256"
echo "MinIO backup created at ${target}"
