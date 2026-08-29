#!/usr/bin/env bash
set -euo pipefail

backup_dir=${1:-}
restore_bucket=${2:-}
if [[ ${ORDER_TRACKING_RESTORE_CONFIRMED:-} != "restore-test-only" ]]; then
  echo "set ORDER_TRACKING_RESTORE_CONFIRMED=restore-test-only for an isolated restore bucket" >&2
  exit 1
fi
[[ -d "${backup_dir}" && "${restore_bucket}" == *-restore ]] || {
  echo "backup directory is required and restore bucket must end in -restore" >&2
  exit 2
}
command -v ossutil >/dev/null || { echo "Alibaba Cloud ossutil 2.x is required" >&2; exit 1; }
: "${OSS_REGION:?set the isolated restore OSS region in the protected shell environment}"
: "${OSS_ENDPOINT:?set the isolated restore OSS endpoint in the protected shell environment}"
: "${OSS_ACCESS_KEY_ID:?set the isolated restore OSS access key id}"
: "${OSS_ACCESS_KEY_SECRET:?set the isolated restore OSS access key secret}"

ossutil cp -r "${backup_dir%/}/" "oss://${restore_bucket}/"
echo "restore completed into isolated OSS bucket ${restore_bucket}"
