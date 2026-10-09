import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REVISION = "a" * 40


class DeployTaskTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.deploy = self.root / "release/deploy"
        shutil.copytree(SCRIPTS, self.deploy / "scripts")
        (self.root / "deploy").mkdir()
        self.config = self.root / "deploy/.env.production"
        self.config.write_text("ORDER_TRACKING_DEPLOY_VERSION=v1.0.0\n")
        (self.deploy / ".env.production").symlink_to(self.config)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.gate = self.root / "continue"
        self.env = {
            **os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "CALLS": str(self.calls), "GATE": str(self.gate), "REVISION": REVISION,
            "FAILURE": "", "PYTHON": sys.executable,
        }
        self.executable("docker", '''#!/bin/bash
if [[ "$1" == login ]]; then
  cat > "$DOCKER_CONFIG/config.json"
  cat "$DOCKER_CONFIG/config.json" >&2
  [[ "$FAILURE" != registry-login ]] || exit 21
  exit 0
fi
printf '%s\\n' "$*" >> "$CALLS"
if [[ "$1 $2" == 'image inspect' ]]; then echo "$REVISION"; fi
if [[ "$*" == *'run --rm migrate'* && "$FAILURE" == migration ]]; then exit 23; fi
if [[ "$*" == *'up -d'* && "$FAILURE" == containers ]]; then exit 24; fi
if [[ "$*" == *'top worker'* ]]; then
  for role in sync incoming notification shipment; do echo "python -m app.worker --role $role"; done
fi
if [[ "$*" == *'exec -T api'* && "$FAILURE" == health ]]; then exit 25; fi
''')
        self.executable("python3", '''#!/bin/bash
if [[ "$1" == *backup-production.py ]]; then
  echo backup >> "$CALLS"
  while [[ ! -f "$GATE" ]]; do sleep 0.05; done
  [[ "$FAILURE" != backup ]] || exit 22
else
  exec "$PYTHON" "$@"
fi
''')
        # macOS 没有 flock 命令；测试替身使用相同的内核文件锁。
        if sys.platform == "darwin":
            helper = self.root / "flock.py"
            helper.write_text("import fcntl\nimport sys\nfcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n")
            self.executable("flock", f'#!/bin/bash\nexec "$PYTHON" "{helper}" "$@"\n')

    def executable(self, name, content):
        target = self.bin / name
        target.write_text(content)
        target.chmod(0o755)

    def command(self, action, version="v1.0.1", revision=REVISION):
        return [sys.executable, str(self.deploy / "scripts/deploy-task.py"),
                action, str(self.root), version, revision, "test-user"]

    def invoke(self, action, version="v1.0.1", revision=REVISION):
        result = subprocess.run(self.command(action, version, revision), env=self.env,
                                input="test-registry-secret\n", capture_output=True,
                                text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail("Timed out waiting for isolated deployment")

    def finish(self):
        self.gate.touch()
        self.wait_for(lambda: self.invoke("status")["status"] != "running")
        return self.invoke("status")

    def tearDown(self):
        self.gate.touch()

    def test_failures_keep_phase_and_never_replay(self):
        self.gate.touch()
        for failure, code in (("registry-login", 21), ("backup", 22), ("migration", 23), ("containers", 24), ("health", 25)):
            with self.subTest(failure=failure):
                self.env["FAILURE"] = failure
                version = f"v1.0.{code}"
                self.invoke("start", version)
                self.wait_for(lambda version=version: self.invoke("status", version)["status"] != "running")
                result = self.invoke("start", version)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["stage"], failure)
                self.assertEqual(result["exit_code"], code)
                self.assertIn("v1.0.0", self.config.read_text())
                self.assertFalse((self.root / "runtime/releases.tsv").exists())
                task = self.root / "runtime/deployments" / version
                self.assertFalse((task / "registry/config.json").exists())
                self.assertNotIn("test-registry-secret", (task / "events.log").read_text())
        self.assertEqual(self.calls.read_text().count("backup\n"), 4)

    def test_other_version_obeys_existing_deployment_lock(self):
        self.invoke("start")
        self.wait_for(lambda: self.calls.exists() and "backup\n" in self.calls.read_text())
        self.invoke("start", "v1.0.2")
        self.wait_for(lambda: self.invoke("status", "v1.0.2")["status"] != "running")
        result = self.invoke("status", "v1.0.2")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "deployment-lock")
        self.assertEqual(self.finish()["status"], "succeeded")
        self.assertEqual(self.calls.read_text().count("backup\n"), 1)

    def test_version_cannot_be_rebound_to_another_revision(self):
        self.invoke("start")
        self.assertEqual(self.invoke("start", revision="b" * 40)["status"], "identity-conflict")
        self.assertEqual(self.finish()["status"], "succeeded")

    def test_simultaneous_starts_register_one_task(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.invoke("start"), range(2)))
        self.assertEqual([result["status"] for result in results], ["running", "running"])
        self.assertEqual(self.finish()["status"], "succeeded")
        self.assertEqual(self.calls.read_text().count("backup\n"), 1)

    def test_killed_supervisor_keeps_running_child_locked_then_reports_unknown(self):
        self.invoke("start")
        self.wait_for(lambda: self.calls.exists() and "backup\n" in self.calls.read_text())
        os.kill(self.invoke("status")["pid"], signal.SIGKILL)
        self.assertEqual(self.invoke("start")["status"], "running")
        self.assertEqual(self.finish()["status"], "unknown")
        self.assertEqual(self.invoke("start")["status"], "unknown")
        self.assertEqual(self.calls.read_text().count("backup\n"), 1)

    def test_killed_process_group_reports_unknown_without_replay(self):
        self.invoke("start")
        self.wait_for(lambda: self.calls.exists() and "backup\n" in self.calls.read_text())
        os.killpg(self.invoke("status")["pid"], signal.SIGKILL)
        self.wait_for(lambda: self.invoke("status")["status"] == "unknown")
        self.assertEqual(self.invoke("start")["status"], "unknown")
        self.assertEqual(self.calls.read_text().count("backup\n"), 1)

    def test_missing_or_incomplete_state_is_unknown_and_never_restarted(self):
        task = self.root / "runtime/deployments/v1.0.1"
        task.mkdir(parents=True)
        self.assertEqual(self.invoke("start")["status"], "unknown")
        (task / "state.json").write_text('{"broken":')
        self.assertEqual(self.invoke("start")["status"], "unknown")
        (task / "lease").touch()
        for state in (
            {"status": "running"},
            {"status": "succeeded", "exit_code": 0, "finished_at": "2026-10-09"},
        ):
            (task / "state.json").write_text(json.dumps({"version": "v1.0.1", "revision": REVISION, **state}))
            self.assertEqual(self.invoke("start")["status"], "unknown")
        (task / "stage").write_text("")
        self.assertEqual(self.invoke("start")["status"], "unknown")
        self.assertFalse(self.calls.exists())

    def test_disconnect_and_duplicate_start_keep_one_deployment(self):
        caller = subprocess.Popen(
            ["bash", "-c", '"$@"; sleep 30', "caller", *self.command("start")],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        caller.stdin.write("test-registry-secret\n")
        caller.stdin.close()
        try:
            self.wait_for(lambda: self.calls.exists() and "backup\n" in self.calls.read_text())
        finally:
            os.killpg(caller.pid, signal.SIGHUP)
            caller.wait(timeout=5)
            caller.stdout.close()
            caller.stderr.close()
        self.assertEqual(self.invoke("start")["status"], "running")
        result = self.finish()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["version"], "v1.0.1")
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual(self.invoke("start")["status"], "succeeded")
        calls = self.calls.read_text()
        self.assertEqual(calls.count("backup\n"), 1)
        self.assertEqual(calls.count("run --rm migrate"), 1)
        self.assertEqual(calls.count("up -d"), 1)
        self.assertIn("v1.0.1", self.config.read_text())
        for path in (self.root / "runtime/deployments").rglob("*"):
            if path.is_file():
                self.assertNotIn("test-registry-secret", path.read_text())


if __name__ == "__main__":
    unittest.main()
