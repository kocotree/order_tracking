import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-production.py"
spec = importlib.util.spec_from_file_location("backup_production", SCRIPT)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def stamps(count):
    return [f"20260923T0931{index:02d}594950Z" for index in range(count)]


class PruneTest(unittest.TestCase):
    def test_failed_dump_does_not_publish_or_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.write_text("ORDER_TRACKING_APP_ENV=production\n"
                              "ORDER_TRACKING_DATABASE_URL=mysql+pymysql://user:fake@localhost/db\n"
                              f"ORDER_TRACKING_MYSQL_BACKUP_DIR={root}\n")
            process = Mock(stdout=io.BytesIO(b"partial"))
            process.wait.return_value = 1
            with patch.object(sys, "argv", ["backup", str(config), "mysql"]), \
                 patch.object(subprocess, "Popen", return_value=process), \
                 patch.object(backup, "prune") as prune:
                with self.assertRaisesRegex(RuntimeError, "MySQL backup failed"):
                    backup.main()
                prune.assert_not_called()
            self.assertEqual(list(root.glob("*.sql.gz")), [])

    def test_mysql_only_success_never_calls_oss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.write_text("ORDER_TRACKING_APP_ENV=production\n"
                              "ORDER_TRACKING_DATABASE_URL=mysql+pymysql://user:fake@localhost/db\n"
                              f"ORDER_TRACKING_MYSQL_BACKUP_DIR={root}\n")
            process = Mock(stdout=io.BytesIO(b"CREATE TABLE example (id INT);"))
            process.wait.return_value = 0
            with patch.object(sys, "argv", ["backup", str(config), "mysql"]), \
                 patch.object(subprocess, "Popen", return_value=process), \
                 patch.object(subprocess, "run") as command:
                backup.main()
                command.assert_not_called()
            self.assertEqual(len(list(root.glob("*.sql.gz.sha256"))), 1)

    def test_failed_oss_copy_does_not_publish_or_prune_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mysql = root / "mysql"
            oss = root / "oss"
            mysql.mkdir()
            oss.mkdir()
            for stamp in stamps(4):
                (oss / f"production-{stamp}").mkdir()
                (oss / f"production-{stamp}.sha256").write_text("verified")
            config = root / "config"
            config.write_text("ORDER_TRACKING_APP_ENV=production\n"
                              "ORDER_TRACKING_DATABASE_URL=mysql+pymysql://user:fake@localhost/db\n"
                              f"ORDER_TRACKING_MYSQL_BACKUP_DIR={mysql}\n"
                              f"ORDER_TRACKING_OSS_BACKUP_DIR={oss}\n"
                              + "".join(f"ORDER_TRACKING_OSS_{key}=fake\n" for key in (
                                  "REGION", "ENDPOINT", "ACCESS_KEY_ID", "ACCESS_KEY_SECRET", "BUCKET")))
            process = Mock(stdout=io.BytesIO(b"CREATE TABLE example (id INT);"))
            process.wait.return_value = 0
            with patch.object(sys, "argv", ["backup", str(config)]), \
                 patch.object(subprocess, "Popen", return_value=process), \
                 patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "oss")):
                with self.assertRaises(subprocess.CalledProcessError):
                    backup.main()
            self.assertEqual(len([p for p in oss.iterdir() if backup.OSS_BACKUPS.fullmatch(p.name)]), 4)
            self.assertEqual(len(list(oss.glob("*.partial"))), 1)

    def test_incomplete_and_symlink_backups_are_not_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in stamps(10):
                (root / f"production-{stamp}.sql.gz").write_text("incomplete")
            target = root / "manual"
            target.write_text("keep")
            link = root / "production-20260924T093100594950Z.sql.gz"
            link.symlink_to(target)
            link.with_name(link.name + ".sha256").write_text("hash")
            backup.prune(root, backup.MYSQL_BACKUPS, 7)
            self.assertEqual(len(list(root.glob("*.sql.gz"))), 11)
            self.assertEqual(target.read_text(), "keep")

    def test_keeps_the_newest_mysql_dumps_and_spares_manual_files(self):
        count = backup.MYSQL_RETAINED + 2
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in stamps(count):
                (root / f"production-{stamp}.sql.gz").write_text("dump")
                (root / f"production-{stamp}.sql.gz.sha256").write_text("hash")
            keepsakes = ["production-basic-data.sql", "order-cleanup-20260908T052343Z.json",
                         "production-order_tracking-20260914T055848Z.sql.gz"]
            for name in keepsakes:
                (root / name).write_text("manual")
            backup.prune(root, backup.MYSQL_BACKUPS, backup.MYSQL_RETAINED)
            remaining = sorted(p.name for p in root.iterdir() if p.name.endswith(".sql.gz"))
            self.assertEqual(remaining, [f"production-{stamp}.sql.gz" for stamp in stamps(count)[2:]]
                             + ["production-order_tracking-20260914T055848Z.sql.gz"])
            self.assertFalse((root / f"production-{stamps(count)[0]}.sql.gz.sha256").exists())
            for name in keepsakes:
                self.assertTrue((root / name).exists())

    def test_keeps_the_newest_oss_snapshots_with_their_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in stamps(5):
                (root / f"production-{stamp}").mkdir()
                (root / f"production-{stamp}" / "products").mkdir()
                (root / f"production-{stamp}.sha256").write_text("hash")
            (root / "product-images-preproduction.tar.gz").write_text("manual")
            backup.prune(root, backup.OSS_BACKUPS, backup.OSS_RETAINED)
            self.assertEqual(sorted(p.name for p in root.iterdir() if p.is_dir()),
                             [f"production-{stamp}" for stamp in stamps(5)[2:]])
            self.assertFalse((root / f"production-{stamps(5)[0]}.sha256").exists())
            self.assertTrue((root / "product-images-preproduction.tar.gz").exists())

    def test_keeps_everything_when_below_the_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in stamps(3):
                (root / f"production-{stamp}.sql.gz").write_text("dump")
            backup.prune(root, backup.MYSQL_BACKUPS, backup.MYSQL_RETAINED)
            self.assertEqual(len(list(root.iterdir())), 3)


if __name__ == "__main__":
    unittest.main()
