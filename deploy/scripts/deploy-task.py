import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value):
    pending = path.with_suffix(".pending")
    with pending.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)
    sync_directory(path.parent)


def status(task, version, revision):
    result = {"version": version, "revision": revision, "status": "absent"}
    if not task.exists():
        return result
    result["status"] = "unknown"
    if any(not (task / name).exists() for name in ("state.json", "lease", "stage")):
        return result
    with (task / "lease").open("r") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            running = True
        else:
            running = False
        # 先查租约再读结果，避免完成瞬间把旧 running 快照误判为中断。
        try:
            record = json.loads((task / "state.json").read_text())
        except json.JSONDecodeError:
            return result
        if not isinstance(record, dict) or record.get("version") != version or record.get("revision") != revision:
            result["status"] = "identity-conflict"
            return result
        if record.get("status") not in ("running", "succeeded", "failed"):
            return result
        if not all(isinstance(record.get(field), str) and record[field]
                   for field in ("started_at", "release_dir")):
            return result
        stage = (task / "stage").read_text().strip()
        if stage not in ("registry-login", "deployment-lock", "compose-config", "image-pull",
                         "image-revision", "migration-check", "backup", "migration", "containers", "health", "record-version"):
            return result
        if record["status"] == "succeeded" and stage != "record-version":
            return result
        if running:
            record["status"] = "running"
        else:
            if (record["status"] == "running" or not record.get("finished_at")
                    or type(record.get("exit_code")) is not int
                    or (record["status"] == "succeeded" and record["exit_code"] != 0)
                    or (record["status"] == "failed" and record["exit_code"] == 0)):
                record["status"] = "unknown"
    record["stage"] = stage
    return record


def worker(task, version, revision, registry_user, lease_fd):
    state = json.loads((task / "state.json").read_text())
    state["pid"] = os.getpid()
    save(task / "state.json", state)
    registry = task / "registry"
    registry.mkdir(mode=0o700)
    env = {**os.environ, "DOCKER_CONFIG": str(registry),
           "ORDER_TRACKING_DEPLOY_TASK_DIR": str(task), "TMPDIR": str(task)}
    token = sys.stdin.buffer.readline().rstrip(b"\r\n")
    # 日志仅保存受控阶段与退出码，外部程序可能在错误中回显凭据。
    with (task / "events.log").open("a") as log:
        log.write(f"{now()} registry-login\n")
        log.flush()
        code = 2
        if token:
            code = subprocess.run(
                ["docker", "login", "ghcr.io", "-u", registry_user, "--password-stdin"],
                input=token, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, check=False,
            ).returncode
        del token
        try:
            if code == 0:
                code = subprocess.run(
                    ["bash", str(Path(__file__).with_name("release-images.sh")), version, revision],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env=env, pass_fds=(lease_fd,), check=False,
                ).returncode
        finally:
            (registry / "config.json").unlink(missing_ok=True)
        state.update(status="succeeded" if code == 0 else "failed",
                     exit_code=code, finished_at=now())
        log.write(f"{now()} {state['status']} exit_code={code}\n")
        log.flush()
        os.fsync(log.fileno())
        save(task / "state.json", state)


def main():
    os.umask(0o077)
    os.environ["PATH"] = str(Path.home() / "bin") + os.pathsep + os.environ["PATH"]
    action, root_arg, version, revision, registry_user = sys.argv[1:6]
    if (action not in ("start", "status", "worker")
            or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?", version)
            or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not re.fullmatch(r"[a-zA-Z0-9_-]+", registry_user)):
        raise ValueError("Invalid deployment identity")
    root = Path(root_arg).resolve(strict=True)
    task = root / "runtime/deployments" / version
    if action == "worker":
        worker(task, version, revision, registry_user, int(sys.argv[6]))
        return
    if action == "start":
        task.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 注册锁只保护创建；原 production-deploy.lock 继续保护所有部署步骤。
        with (task.parent / "dispatch.lock").open("a") as dispatch:
            fcntl.flock(dispatch, fcntl.LOCK_EX)
            if not task.exists():
                config = Path(__file__).resolve().parents[1] / ".env.production"
                if config.resolve(strict=True) != root / "deploy/.env.production":
                    raise ValueError("Deployment configuration does not belong to the requested root")
                task.mkdir(mode=0o700)
                sync_directory(task.parent)
                sync_directory(task.parent.parent)
                sync_directory(root)
                with (task / "lease").open("w") as lease:
                    fcntl.flock(lease, fcntl.LOCK_EX)
                    save(task / "state.json", {
                        "version": version, "revision": revision, "status": "running",
                        "started_at": now(), "release_dir": str(Path(__file__).resolve().parents[2]),
                    })
                    (task / "stage").write_text("registry-login\n")
                    token = sys.stdin.buffer.readline()
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()), "worker", str(root),
                         version, revision, registry_user, str(lease.fileno())],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True, pass_fds=(lease.fileno(),),
                    )
                    process.stdin.write(token)
                    process.stdin.close()
    print(json.dumps(status(task, version, revision)))


if __name__ == "__main__":
    main()
