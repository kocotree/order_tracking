import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

# Retention only matches this script's own timestamped names, never manual artefacts.
MYSQL_BACKUPS = re.compile(r"production-\d{8}T\d{12}Z\.sql\.gz")
OSS_BACKUPS = re.compile(r"production-\d{8}T\d{12}Z")
MYSQL_RETAINED = 7
OSS_RETAINED = 3


def main():
    os.umask(0o077)
    config = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    if mode not in {"all", "mysql"}:
        raise ValueError("Expected all or mysql backup mode")
    values = {}
    for line in config.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if values.get("ORDER_TRACKING_APP_ENV") != "production":
        raise ValueError("Expected production configuration")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    keys = ["ORDER_TRACKING_MYSQL_BACKUP_DIR"]
    if mode == "all":
        keys.append("ORDER_TRACKING_OSS_BACKUP_DIR")
    roots = [Path(values[key]) for key in keys]
    for root in roots:
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("Backup directories must already exist and be absolute")
    url = urlsplit(values["ORDER_TRACKING_DATABASE_URL"])
    if url.scheme != "mysql+pymysql" or not all((url.hostname, url.username, url.password)):
        raise ValueError("Invalid database configuration")
    database = unquote(url.path.lstrip("/"))

    def quote(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'

    target = roots[0] / f"production-{stamp}.sql.gz"
    partial = target.with_suffix(".gz.partial")
    with tempfile.TemporaryDirectory(dir=roots[0]) as directory:
        client = Path(directory) / "client.cnf"
        client.write_text("[client]\n" + "\n".join((
            "host=" + quote(url.hostname), "port=" + str(url.port or 3306),
            "user=" + quote(unquote(url.username)), "password=" + quote(unquote(url.password)),
        )) + "\n")
        with partial.open("xb") as output:
            proc = subprocess.Popen([
                "mysqldump", "--defaults-extra-file=" + str(client), "--single-transaction",
                "--quick", "--no-tablespaces", "--set-gtid-purged=OFF", "--hex-blob",
                "--default-character-set=utf8mb4", database,
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            size = 0
            with gzip.GzipFile(fileobj=output, mode="wb") as archive:
                while chunk := proc.stdout.read(1024 * 1024):
                    archive.write(chunk)
                    size += len(chunk)
            if proc.wait() or not size:
                raise RuntimeError("MySQL backup failed")
    with gzip.open(partial, "rb") as archive:
        while archive.read(1024 * 1024):
            pass
    partial.rename(target)
    target.with_suffix(".gz.sha256").write_text(hash_file(target) + "  " + target.name + "\n")
    prune(roots[0], MYSQL_BACKUPS, MYSQL_RETAINED)
    if mode == "mysql":
        print(f"Backup complete: MySQL {target.name}")
        return
    oss_target = roots[1] / f"production-{stamp}"
    oss_partial = oss_target.with_name(oss_target.name + ".partial")
    oss_partial.mkdir(mode=0o700)
    env = os.environ.copy()
    for suffix in ("REGION", "ENDPOINT", "ACCESS_KEY_ID", "ACCESS_KEY_SECRET"):
        env["OSS_" + suffix] = values["ORDER_TRACKING_OSS_" + suffix]
    subprocess.run([
        "ossutil", "cp", "-r", "oss://" + values["ORDER_TRACKING_OSS_BUCKET"] + "/",
        str(oss_partial) + "/",
    ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    files = sorted(p for p in oss_partial.rglob("*") if p.is_file())
    oss_target.with_suffix(".sha256").write_text("".join(
        hash_file(p) + "  " + str(p.relative_to(oss_partial)) + "\n" for p in files
    ))
    oss_partial.rename(oss_target)
    # OSS 快照完成后只清理其独立保留池。
    prune(roots[1], OSS_BACKUPS, OSS_RETAINED)
    print(f"Backup complete: MySQL {target.name}; OSS {len(files)} files in {oss_target.name}")


def prune(root, pattern, keep):
    managed = [p for p in root.iterdir() if pattern.fullmatch(p.name)
               and not p.is_symlink()
               and p.with_name(p.name + ".sha256").is_file()
               and not p.with_name(p.name + ".sha256").is_symlink()
               and (p.is_file() if pattern is MYSQL_BACKUPS else p.is_dir())]
    for path in sorted(managed)[:-keep]:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        path.with_name(path.name + ".sha256").unlink(missing_ok=True)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database connection strings and external credentials must not enter CI logs.
        print("Production backup failed:", type(error).__name__, file=sys.stderr)
        sys.exit(1)
