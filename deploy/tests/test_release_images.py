"""Failure boundaries for production orchestration; never contacts Docker or a DB."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ReleaseImagesTest(unittest.TestCase):
    def run_release(self, failure=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy = root / "deploy"
            shutil.copytree(Path(__file__).resolve().parents[1] / "scripts", deploy / "scripts")
            config = deploy / ".env.production"
            config.write_text("ORDER_TRACKING_DEPLOY_VERSION=v1.0.0\n")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "calls"
            scripts = {
                "docker": '''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ "$1 $2" == 'image inspect' ]]; then
  if [[ "$FAILURE" == label ]]; then echo wrong; else echo "$REVISION"; fi
fi
if [[ "$*" == *'run --rm migrate'* && "$FAILURE" == migration ]]; then exit 1; fi
if [[ "$*" == *'up -d'* && "$FAILURE" == health ]]; then exit 1; fi
''',
                "python3": f'''#!/bin/bash
if [[ "$1" == *backup-production.py ]]; then
  echo backup >> "$CALLS"
  [[ "$FAILURE" != backup ]]
else
  exec "{sys.executable}" "$@"
fi
''',
                "flock": "#!/bin/bash\nexit 0\n",
            }
            for name, content in scripts.items():
                path = bin_dir / name
                path.write_text(content)
                path.chmod(0o755)
            revision = "a" * 40
            result = subprocess.run(
                ["bash", str(deploy / "scripts/release-images.sh"), "v1.0.1", revision],
                env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                     "CALLS": str(log), "FAILURE": failure, "REVISION": revision},
                capture_output=True, text=True,
            )
            return result, log.read_text(), config.read_text(), (root / "runtime/releases.tsv").exists()

    def test_mismatched_images_stop_before_backup_and_migration(self):
        result, calls, config, recorded = self.run_release("label")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("backup\n", calls)
        self.assertNotIn("run --rm migrate", calls)
        self.assertIn("v1.0.0", config)
        self.assertFalse(recorded)

    def test_failed_backup_stops_migration(self):
        result, calls, config, recorded = self.run_release("backup")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("run --rm migrate", calls)
        self.assertIn("v1.0.0", config)
        self.assertFalse(recorded)

    def test_failed_migration_stops_container_replacement(self):
        result, calls, config, recorded = self.run_release("migration")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("up -d", calls)
        self.assertIn("v1.0.0", config)
        self.assertFalse(recorded)

    def test_failed_health_does_not_record_success(self):
        result, calls, config, recorded = self.run_release("health")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("up -d", calls)
        self.assertIn("v1.0.0", config)
        self.assertFalse(recorded)

    def test_healthy_release_records_version(self):
        result, calls, config, recorded = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(calls.index("backup\n"), calls.index("run --rm migrate"))
        self.assertIn("v1.0.1", config)
        self.assertTrue(recorded)


if __name__ == "__main__":
    unittest.main()
