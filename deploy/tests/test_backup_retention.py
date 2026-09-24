import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-production.py"
spec = importlib.util.spec_from_file_location("backup_production", SCRIPT)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def stamps(count):
    return [f"20260923T0931{index:02d}594950Z" for index in range(count)]


class PruneTest(unittest.TestCase):
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
