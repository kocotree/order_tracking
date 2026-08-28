#!/usr/bin/env bash
set -euo pipefail

backup_file=${1:-}
restore_env_file=${2:-}
if [[ ${ORDER_TRACKING_RESTORE_CONFIRMED:-} != "restore-test-only" ]]; then
  echo "set ORDER_TRACKING_RESTORE_CONFIRMED=restore-test-only for an isolated restore database" >&2
  exit 1
fi
[[ -f "${backup_file}" && -f "${restore_env_file}" ]] || {
  echo "backup and protected restore environment files are required" >&2
  exit 2
}
command -v mysql >/dev/null || { echo "mysql client is required" >&2; exit 1; }
sha256sum -c "${backup_file}.sha256"

client_file=$(mktemp)
trap 'rm -f "${client_file}"' EXIT
database_name=$(python3 - "${restore_env_file}" "${client_file}" <<'PY'
import pathlib
import sys
from urllib.parse import unquote, urlparse

values = {}
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
url = urlparse(values["ORDER_TRACKING_RESTORE_DATABASE_URL"])
database = url.path.lstrip("/")
if not database.endswith("_restore"):
    raise SystemExit("restore database name must end in _restore")
pathlib.Path(sys.argv[2]).write_text(
    "[client]\n"
    f"host={url.hostname}\nport={url.port or 3306}\n"
    f"user={unquote(url.username or '')}\npassword={unquote(url.password or '')}\n"
)
print(database)
PY
)
chmod 600 "${client_file}"
gzip -dc "${backup_file}" | mysql --defaults-extra-file="${client_file}" "${database_name}"
echo "restore completed into isolated database ${database_name}"
