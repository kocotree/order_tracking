"""Release must never accept CI from a different commit, branch, or event."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "verify_release_ci", Path(__file__).resolve().parents[1] / "scripts/verify-release-ci.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class VerifyReleaseCITest(unittest.TestCase):
    def setUp(self):
        self.revision = "a" * 40
        self.run = {"id": 42, "head_sha": self.revision, "head_branch": "main",
                    "event": "push", "status": "completed", "conclusion": "success"}
        self.jobs = [{"name": name, "status": "completed", "conclusion": "success"}
                     for name in gate.REQUIRED_JOBS]

    def verify(self, runs):
        def api(path):
            if "/jobs?" in path:
                self.assertIn("/runs/42/jobs?filter=latest", path)
                return {"jobs": self.jobs}
            self.assertIn(f"event=push&branch=main&head_sha={self.revision}", path)
            return {"workflow_runs": runs}
        return gate.verify_ci(api, "kocotree/order_tracking", self.revision)

    def test_accepts_exact_successful_main_ci(self):
        self.assertEqual(self.verify([self.run]), 42)

    def test_rejects_missing_and_unrelated_ci(self):
        for runs in ([], [{**self.run, "head_sha": "b" * 40}],
                     [{**self.run, "head_branch": "feature"}],
                     [{**self.run, "event": "pull_request"}]):
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                self.verify(runs)

    def test_rejects_failed_pending_cancelled_or_skipped_latest_ci(self):
        for status, conclusion in (("in_progress", None), ("completed", "failure"),
                                   ("completed", "cancelled"), ("completed", "skipped")):
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                self.verify([{**self.run, "id": 41},
                             {**self.run, "status": status, "conclusion": conclusion}])

    def test_rejects_missing_or_skipped_required_job(self):
        self.jobs[0]["conclusion"] = "skipped"
        with self.assertRaises(ValueError):
            self.verify([self.run])
        self.jobs.pop(0)
        with self.assertRaises(ValueError):
            self.verify([self.run])


if __name__ == "__main__":
    unittest.main()
