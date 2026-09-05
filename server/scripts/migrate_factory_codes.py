"""One-time, explicitly approved factory-code conversion. Default mode is read-only."""

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from pypinyin import Style, pinyin
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, Factory
from app.db.session import create_database_engine, create_session_factory
from app.modules.factory_access.codes import code_prefix, normalize_factory_code
from app.settings.config import Settings


def _candidate(value: str | None) -> tuple[str | None, str]:
    if not value or not value.strip():
        return None, "empty"
    prefix = code_prefix(value)
    letters = []
    for char in prefix:
        if re.fullmatch("[A-Za-z]", char):
            letters.append(char.upper())
        elif "\u4e00" <= char <= "\u9fff":
            readings = pinyin(char, style=Style.TONE3, heteronym=True, strict=True)[0]
            if len(readings) != 1:
                return None, "ambiguous"
            if not re.fullmatch(r"[a-zü]+[1-5]?", readings[0]):
                return None, "invalid"
            letters.append(readings[0][0].upper())
        else:
            return None, "invalid"
    try:
        result = normalize_factory_code("".join(letters))
    except ValueError:
        return None, "invalid"
    if not result:
        return None, "invalid"
    return result, "unchanged" if result == value else "converted"


def _plan(factories: list[Factory]) -> dict[str, Any]:
    rows = []
    for factory in factories:
        after, reason = _candidate(factory.factory_code)
        rows.append(
            dict(
                factory_id=factory.factory_id,
                factory_name=factory.factory_name,
                before=factory.factory_code,
                version=factory.version,
                after=after,
                reason=reason,
            )
        )
    counts = Counter(row["after"] for row in rows if row["after"])
    for row in rows:
        if row["after"] and counts[row["after"]] > 1:
            row.update(after=None, reason="duplicate")
    return {"format": 1, "rows": rows}


def preview(sessions: sessionmaker[Session]) -> dict[str, Any]:
    with sessions() as session:
        return _plan(list(session.scalars(select(Factory).order_by(Factory.factory_id))))


def _write_private(path: Path, data: dict[str, Any]) -> None:
    # O_EXCL also prevents overwriting a backup or following an existing symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def _change(
    session: Session,
    factories: dict[str, Factory],
    rows: list[dict[str, Any]],
    *,
    reverse: bool,
    request_id: str,
) -> None:
    changed = [row for row in rows if row["before"] != row["after"]]
    # Clear all changing keys first so swaps cannot hit the unique index midway.
    for row in changed:
        factories[row["factory_id"]].factory_code = None
    session.flush()
    for row in changed:
        factory = factories[row["factory_id"]]
        source = row["after"] if reverse else row["before"]
        target = row["before"] if reverse else row["after"]
        factory.factory_code = target
        factory.version += 1
        session.add(
            AuditLog(
                request_id=request_id,
                action="factory.code_rollback" if reverse else "factory.code_migrated",
                target_type="factory",
                target_id=factory.factory_id,
                changes={"before": source, "after": target, "version": factory.version},
                actor_id=None,
                source_terminal="internal_cli",
            )
        )
    session.flush()


def _verify(sessions: sessionmaker[Session], rows: list[dict[str, Any]], *, reverse: bool) -> None:
    with sessions() as session:
        for row in rows:
            factory = session.get(Factory, row["factory_id"])
            expected = row["before"] if reverse else row["after"]
            if factory is None or factory.factory_code != expected:
                raise RuntimeError(
                    "Committed data changed before readback; inspect audit and backup"
                )


def apply_plan(sessions: sessionmaker[Session], plan: dict[str, Any], backup: Path) -> None:
    with sessions() as session, session.begin():
        factories = list(
            session.scalars(select(Factory).order_by(Factory.factory_id).with_for_update())
        )
        if _plan(factories) != plan:
            raise ValueError("stale or edited plan; preview again")
        request_id = uuid4().hex
        _write_private(backup, {**plan, "request_id": request_id})
        _change(
            session,
            {f.factory_id: f for f in factories},
            plan["rows"],
            reverse=False,
            request_id=request_id,
        )
    _verify(sessions, plan["rows"], reverse=False)


def rollback(sessions: sessionmaker[Session], backup: Path) -> None:
    saved = json.loads(backup.read_text())
    rows = saved["rows"]
    with sessions() as session, session.begin():
        factories = {
            f.factory_id: f
            for f in session.scalars(select(Factory).order_by(Factory.factory_id).with_for_update())
        }
        if set(factories) != {row["factory_id"] for row in rows}:
            raise ValueError("stale backup; factory set changed")
        for row in rows:
            factory = factories[row["factory_id"]]
            changed = row["before"] != row["after"]
            if factory.factory_code != row["after"] or factory.version != row["version"] + int(
                changed
            ):
                raise ValueError("stale backup; do not overwrite subsequent edits")
        # A pre-write backup can survive a failed transaction. Require its committed audit.
        audits = {
            audit.target_id: audit.changes
            for audit in session.scalars(
                select(AuditLog).where(
                    AuditLog.request_id == saved["request_id"],
                    AuditLog.action == "factory.code_migrated",
                )
            )
        }
        expected_audits = {
            row["factory_id"]: {
                "before": row["before"],
                "after": row["after"],
                "version": row["version"] + 1,
            }
            for row in rows
            if row["before"] != row["after"]
        }
        if audits != expected_audits:
            raise ValueError("backup has no matching committed migration")
        _change(session, factories, rows, reverse=True, request_id=uuid4().hex)
    _verify(sessions, rows, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", nargs="?", choices=("preview", "apply", "rollback"), default="preview"
    )
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.mode == "preview" and not args.plan:
        parser.error("preview requires --plan (new private file)")
    if args.mode == "apply" and (not args.plan or not args.backup):
        parser.error("apply requires --plan and --backup")
    if args.mode == "rollback" and not args.backup:
        parser.error("rollback requires --backup")
    engine = create_database_engine(Settings().database_url)
    sessions = create_session_factory(engine)
    try:
        if args.mode == "preview":
            plan = preview(sessions)
            _write_private(args.plan, plan)
            print(
                json.dumps(
                    {
                        "factories": len(plan["rows"]),
                        "reasons": dict(Counter(row["reason"] for row in plan["rows"])),
                    }
                )
            )
        elif args.mode == "apply":
            apply_plan(sessions, json.loads(args.plan.read_text()), args.backup)
            print("Applied and read back factory codes; retain backup for rollback.")
        else:
            rollback(sessions, args.backup)
            print("Rolled back and read back factory codes.")
    except (ValueError, OSError, SQLAlchemyError, RuntimeError):
        # Do not print DB URLs, SQL parameters or private mappings in logs.
        print(
            "Operation refused: check private plan/backup, permissions "
            "and current factory versions."
        )
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
