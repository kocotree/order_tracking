#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
resolve_environment "${environment}"
command -v mysqldump >/dev/null || { echo "mysqldump is required" >&2; exit 1; }

backup_dir=${ORDER_TRACKING_MYSQL_BACKUP_DIR:?set an absolute protected backup directory}
[[ "${backup_dir}" = /* ]] || { echo "backup directory must be absolute" >&2; exit 2; }
mkdir -p "${backup_dir}"
chmod 700 "${backup_dir}"

client_file=$(mktemp)
trap 'rm -f "${client_file}"' EXIT
database_name=$(python3 - "${environment_file}" "${client_file}" <<'PY'
import pathlib
import sys
from urllib.parse import unquote, urlparse

values = {}
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
url = urlparse(values["ORDER_TRACKING_DATABASE_URL"])
if url.scheme != "mysql+pymysql" or not all((url.hostname, url.username, url.password, url.path)):
    raise SystemExit("database URL is incomplete")
pathlib.Path(sys.argv[2]).write_text(
    "[client]\n"
    f"host={url.hostname}\nport={url.port or 3306}\n"
    f"user={unquote(url.username)}\npassword={unquote(url.password)}\n"
)
print(url.path.lstrip("/"))
PY
)
chmod 600 "${client_file}"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="${backup_dir}/${environment}-${database_name}-${timestamp}.sql.gz"
mysqldump --defaults-extra-file="${client_file}" --single-transaction --routines \
  --events --triggers --set-gtid-purged=OFF "${database_name}" | gzip -9 >"${target}"
sha256sum "${target}" >"${target}.sha256"
echo "MySQL backup created at ${target}"
