import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy-remote.py"
REVISION = "a" * 40


class DeployRemoteTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("deploy_remote", SCRIPT)
        self.remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.remote)

    def response(self, status, revision=REVISION):
        return subprocess.CompletedProcess([], 0, json.dumps({
            "version": "v1.0.1", "revision": revision, "status": status,
            "stage": "backup", "exit_code": 0 if status == "succeeded" else 22,
        }), "")

    def wait(self):
        return self.remote.wait_for_deployment(
            ["ssh", "host"], ["python3", "/release/deploy-task.py"],
            ["/production", "v1.0.1", REVISION, "user"], "secret",
        )

    def test_lost_start_reply_and_poll_disconnect_reconnect_to_same_task(self):
        disconnected = subprocess.CompletedProcess([], 255, "", "Broken pipe")
        with patch.object(self.remote.subprocess, "run", side_effect=[
            disconnected, self.response("running"), disconnected, self.response("succeeded"),
        ]) as run, patch.object(self.remote.time, "sleep"):
            self.assertEqual(self.wait(), 0)
        commands = [call.args[0][-1] for call in run.call_args_list]
        self.assertIn(" start ", commands[0])
        self.assertEqual(commands[0], commands[1])
        self.assertIn(" status ", commands[2])
        self.assertEqual(commands[2], commands[3])
        self.assertNotIn("secret", " ".join(commands))
        self.assertIsNone(run.call_args_list[2].kwargs["input"])

    def test_persistent_disconnect_reports_unconfirmed(self):
        with patch.object(self.remote.subprocess, "run", return_value=subprocess.CompletedProcess([], 255, "", "")) as run, patch.object(self.remote.time, "sleep"):
            self.assertEqual(self.wait(), 2)
        self.assertEqual(run.call_count, 12)

    def test_timeout_reconnects_without_restarting_an_accepted_task(self):
        with patch.object(self.remote.subprocess, "run", side_effect=[
            self.response("running"), subprocess.TimeoutExpired("ssh", 60), self.response("succeeded"),
        ]) as run, patch.object(self.remote.time, "sleep"):
            self.assertEqual(self.wait(), 0)
        self.assertIn(" status ", run.call_args_list[-1].args[0][-1])

    def test_wait_deadline_reports_unconfirmed_without_stopping_task(self):
        with patch.object(self.remote.subprocess, "run", return_value=self.response("running")) as run, patch.object(self.remote.time, "sleep"), patch.object(self.remote.time, "monotonic", side_effect=[0, 0, 10801]):
            self.assertEqual(self.wait(), 2)
        self.assertEqual(run.call_count, 1)

    def test_failure_unknown_missing_and_wrong_identity_never_start_again(self):
        for response, expected in (
            (self.response("failed"), 1), (self.response("unknown"), 2),
            (self.response("absent"), 2), (self.response("succeeded", "b" * 40), 2),
            (subprocess.CompletedProcess([], 0, "invalid JSON", ""), 2),
        ):
            with self.subTest(response=response), patch.object(self.remote.subprocess, "run", return_value=response) as run:
                self.assertEqual(self.wait(), expected)
                self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
