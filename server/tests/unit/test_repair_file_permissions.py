from app.api.repairs import _admin_can_download_repair_file


def test_admin_mini_can_download_formal_repair_file_but_not_preview_file() -> None:
    assert _admin_can_download_repair_file(terminal="web", formal_repair=True)
    assert _admin_can_download_repair_file(terminal="web", formal_repair=False)
    assert _admin_can_download_repair_file(terminal="mini", formal_repair=True)
    assert not _admin_can_download_repair_file(terminal="mini", formal_repair=False)
