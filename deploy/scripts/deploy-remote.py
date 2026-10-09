import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


def wait_for_deployment(ssh, script, identity, token):
    action = "start"
    failures = 0
    deadline = time.monotonic() + 3 * 60 * 60
    while time.monotonic() < deadline:
        command = ssh + [shlex.join([*script, action, *identity])]
        try:
            result = subprocess.run(
                command, input=token + "\n" if action == "start" else None,
                capture_output=True, text=True, timeout=60, check=False,
            )
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(command, 255, "", "")
        if result.returncode == 255:
            failures += 1
            print(f"SSH unavailable ({failures}/12); deployment result unconfirmed", flush=True)
            if failures == 12:
                return 2
            time.sleep(10)
            continue
        if result.returncode:
            print("Remote query failed; deployment result unconfirmed", flush=True)
            return 2
        failures = 0
        try:
            record = json.loads(result.stdout)
        except json.JSONDecodeError:
            print("Invalid task response; deployment result unconfirmed", flush=True)
            return 2
        if (not isinstance(record, dict) or record.get("version") != identity[1]
                or record.get("revision") != identity[2]):
            print("Task identity mismatch; deployment result unconfirmed", flush=True)
            return 2
        state = record.get("status")
        print(f"{identity[1]} {identity[2]} status={state} "
              f"stage={record.get('stage')} exit_code={record.get('exit_code')}", flush=True)
        if state == "succeeded" and record.get("exit_code") == 0:
            return 0
        if state == "failed":
            return 1
        if state != "running":
            print("Deployment result unconfirmed; inspect the existing task before any recovery", flush=True)
            return 2
        action = "status"
        time.sleep(10)
    print("Wait deadline exceeded; remote task continues, deployment result unconfirmed", flush=True)
    return 2


def main():
    scratch = Path(sys.argv[1])
    remote_script = sys.argv[2]
    ssh = [
        "ssh", "-i", str(scratch / "key"), "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={scratch / 'known_hosts'}",
        "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
        "-p", os.environ["DEPLOY_PORT"], f"{os.environ['DEPLOY_USER']}@{os.environ['DEPLOY_HOST']}",
    ]
    return wait_for_deployment(
        ssh, ["python3", remote_script],
        [os.environ["DEPLOY_DIR"], os.environ["VERSION"], os.environ["GITHUB_SHA"], os.environ["REGISTRY_USER"]],
        os.environ["REGISTRY_TOKEN"],
    )


if __name__ == "__main__":
    sys.exit(main())
