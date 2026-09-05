import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, Factory
from scripts.migrate_factory_codes import apply_plan, preview, rollback


def seed(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        for index, code in enumerate(
            ["希舟（帽厂）", "XZ-分厂", "松林", "重阳", "A1", "abc", None]
        ):
            session.add(
                Factory(
                    factory_id=f"f{index}",
                    supplier_number=f"S{index}",
                    factory_name=f"工厂{index}",
                    factory_code=code,
                )
            )


def test_preview_apply_and_rollback_are_auditable_and_protect_edits(
    test_database_engine: Engine, tmp_path: Path
) -> None:
    seed(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session)
    plan = preview(sessions)
    assert [row["after"] for row in plan["rows"]] == [None, None, "SL", None, None, "ABC", None]
    assert [row["reason"] for row in plan["rows"]][:4] == [
        "duplicate",
        "duplicate",
        "converted",
        "ambiguous",
    ]
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f0").factory_code == "希舟（帽厂）"
    backup = tmp_path / "backup.json"
    apply_plan(sessions, plan, backup)
    assert backup.stat().st_mode & 0o777 == 0o600
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f2").factory_code == "SL"
        assert len(session.scalars(select(AuditLog)).all()) == 6
    with pytest.raises(ValueError, match="stale"):
        apply_plan(sessions, plan, tmp_path / "second.json")
    tampered = json.loads(backup.read_text())
    tampered["rows"][0]["before"] = "WRONG"
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="matching committed migration"):
        rollback(sessions, tampered_path)
    rollback(sessions, backup)
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f0").factory_code == "希舟（帽厂）"
        assert session.get(Factory, "f5").factory_code == "abc"
    with pytest.raises(ValueError, match="stale"):
        rollback(sessions, backup)


def test_stale_plan_and_post_apply_edits_are_never_overwritten(
    test_database_engine: Engine, tmp_path: Path
) -> None:
    seed(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session)
    stale = preview(sessions)
    with Session(test_database_engine) as session, session.begin():
        session.get(Factory, "f0").version += 1
    with pytest.raises(ValueError, match="stale"):
        apply_plan(sessions, stale, tmp_path / "stale.json")
    assert not (tmp_path / "stale.json").exists()
    backup = tmp_path / "backup.json"
    apply_plan(sessions, preview(sessions), backup)
    with Session(test_database_engine) as session, session.begin():
        factory = session.get(Factory, "f2")
        factory.factory_code = "MANUAL"
        factory.version += 1
    with pytest.raises(ValueError, match="stale"):
        rollback(sessions, backup)
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f2").factory_code == "MANUAL"
        assert session.get(Factory, "f5").factory_code == "ABC"


def test_cli_defaults_to_preview_and_backup_cannot_be_overwritten(
    test_database_engine: Engine,
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    seed(test_database_engine)
    plan_path = tmp_path / "plan.json"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate_factory_codes", "--plan", str(plan_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert plan_path.exists()
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f0").factory_code == "希舟（帽厂）"
    sessions = sessionmaker(test_database_engine, class_=Session)
    with pytest.raises(FileExistsError):
        apply_plan(sessions, preview(sessions), plan_path)
    with Session(test_database_engine) as session:
        assert session.get(Factory, "f0").factory_code == "希舟（帽厂）"


def test_database_failure_rolls_back_all_codes_and_audits(
    test_database_engine: Engine,
    tmp_path: Path,
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    seed(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session)
    plan = preview(sessions)
    backup = tmp_path / "failed.json"
    # Allow the initial NULL pass, then fail the version update in the same transaction.
    # A CHECK constraint needs no SUPER privilege when MySQL binary logging is enabled.
    with test_database_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE factories ADD CONSTRAINT issue16_fail_update "
                "CHECK (factory_id <> 'f2' OR version = 1)"
            )
        )
    try:
        with pytest.raises(DBAPIError, match="issue16_fail_update"):
            apply_plan(sessions, plan, backup)
    finally:
        with test_database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE factories DROP CHECK issue16_fail_update"))
    assert preview(sessions) == plan
    with sessions() as session:
        assert session.scalars(select(AuditLog)).all() == []
    with pytest.raises(ValueError):
        rollback(sessions, backup)
