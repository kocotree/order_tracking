#!/usr/bin/env bash
set -euo pipefail

backup_dir=${1:-}
restore_bucket=${2:-}
: "${MC_HOST_order_tracking_restore:?set the isolated restore alias in the protected shell environment}"
if [[ ${ORDER_TRACKING_RESTORE_CONFIRMED:-} != "restore-test-only" ]]; then
  echo "set ORDER_TRACKING_RESTORE_CONFIRMED=restore-test-only for an isolated restore bucket" >&2
  exit 1
fi
[[ -d "${backup_dir}" && "${restore_bucket}" == *-restore ]] || {
  echo "backup directory is required and restore bucket must end in -restore" >&2
  exit 2
}
command -v mc >/dev/null || { echo "MinIO mc is required" >&2; exit 1; }
mc mirror --overwrite --preserve "${backup_dir}" "order_tracking_restore/${restore_bucket}"
echo "restore completed into isolated bucket ${restore_bucket}"
