from datetime import UTC, datetime

import pytest

from app.modules.shipment_writeback.return_projection import project_returns

ACTIVATION = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def line(qty=100, record="recNew", assignment=1):
    return dict(record_id=record, detail_id=record, order_no="O1", quantity=qty,
                assignment_id=assignment, source_scope="test")


def fact(root, at, qty=100, status="SHIPPED", **kwargs):
    return dict(root_id=root, occurred_at=at, status=status, lines=[line(qty, **kwargs)])


def project(facts, returns=(), now=datetime(2026, 11, 17, 8, tzinfo=UTC), **kwargs):
    first = {f["root_id"]: min(v["occurred_at"] for v in facts
             if v["root_id"] == f["root_id"] and v["status"] == "SHIPPED") for f in facts}
    return project_returns(facts=facts, returns=list(returns), first_submitted=first,
                           activation=ACTIVATION, cutoff=now, source_scope="test",
                           baseline={"stage": "2026-11-09", "rows": [
                               dict(record_id="recOld", detail_id="old",
                                    order_no="old", quantity=700)
                           ]}, **kwargs)


def returned(root="new", qty=10, at=datetime(2026, 11, 17, 6, tzinfo=UTC)):
    return dict(root_id=root, assignment_id=1, quantity=qty, occurred_at=at)


def quantities(result):
    return {s["stage"]: {r["record_id"]: r["quantity"] for r in s["rows"]}
            for s in result}


def test_partial_return_adjusts_original_week_and_keeps_old_baseline():
    f = [fact("new", datetime(2026, 11, 13, 1, tzinfo=UTC))]
    q = quantities(project(f, [returned()]))
    assert q["2026-11-09"] == {"recOld": 700, "recNew": 90}


def test_full_return_zero_and_replacement_counts_in_its_new_week():
    f = [fact("new", ACTIVATION), fact("replacement", datetime(2026, 11, 17, 7, tzinfo=UTC))]
    q = quantities(project(f, [returned(qty=100)]))
    assert q["2026-11-09"]["recNew"] == 0
    assert q["2026-11-16"]["recNew"] == 100


def test_old_root_resubmission_and_returns_never_deduct_old_baseline():
    f = [fact("old", datetime(2026, 11, 11, 1, tzinfo=UTC)), fact("old", ACTIVATION)]
    assert quantities(project(f, [returned(root="old", qty=100)]))["2026-11-09"] == {
        "recOld": 700}


def test_future_returns_excluded_and_repeated_projection_identical():
    f = [fact("new", ACTIVATION)]
    r = [returned(at=datetime(2026, 11, 18, tzinfo=UTC))]
    assert project(f, r) == project(f)


def test_changed_old_stage_is_returned_after_cursor():
    f = [fact("new", ACTIVATION)]
    after = datetime(2026, 11, 17, 5, tzinfo=UTC)
    assert quantities(project(f, [returned()], after=after))["2026-11-09"]["recNew"] == 90


def test_over_return_fails_instead_of_silently_clamping():
    with pytest.raises(ValueError, match="return"):
        project([fact("new", ACTIVATION)], [returned(qty=101)])


def test_withdraw_before_close_then_resubmit_belongs_to_next_week_once():
    f = [fact("new", ACTIVATION),
         fact("new", datetime(2026, 11, 15, 10, tzinfo=UTC), status="WITHDRAWN"),
         fact("new", datetime(2026, 11, 17, 7, tzinfo=UTC))]
    q = quantities(project(f))
    assert q["2026-11-09"]["recNew"] == 0
    assert q["2026-11-16"]["recNew"] == 100


def test_boundary_is_inclusive_and_returns_share_correct_assignment():
    f = [fact("new", ACTIVATION, assignment=2)]
    with pytest.raises(ValueError, match="return"):
        project(f, [returned()])


def test_missing_source_scope_and_identity_stops_projection():
    f = fact("new", ACTIVATION)
    f["lines"][0].update(source_scope=None, record_id=None, detail_id=None)
    with pytest.raises(ValueError, match="identity"):
        project([f])


def test_late_return_from_previous_month_survives_incremental_cursor():
    f = [fact("new", ACTIVATION)]
    at = datetime(2027, 1, 3, 1, tzinfo=UTC)
    q = quantities(project(f, [returned(at=at)], now=at.replace(hour=2), after=at))
    assert q["2026-11-09"]["recNew"] == 90
    assert "2026-12-28" in q


def test_withdrawal_after_closed_week_never_counts_root_again():
    f = [fact("new", ACTIVATION),
         fact("new", datetime(2026, 11, 17, 1, tzinfo=UTC), status="WITHDRAWN"),
         fact("new", datetime(2026, 11, 17, 2, tzinfo=UTC))]
    q = quantities(project(f))
    assert q["2026-11-09"]["recNew"] == 100
    assert not q["2026-11-16"]


def test_real_sql_loader_reads_return_events_without_writing():
    from datetime import date
    from unittest.mock import patch

    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import sessionmaker

    from app.modules.shipment_writeback.service import ShipmentWriteback

    engine = create_engine("sqlite://")
    ddl = [
        "CREATE TABLE shipment_writeback_facts (id INTEGER PRIMARY KEY, root_id TEXT, "
        "event_key TEXT, status TEXT, occurred_at DATETIME, lines JSON)",
        "CREATE TABLE shipment_lines (line_id INTEGER PRIMARY KEY, "
        "shipment_id TEXT, order_assignment_id INTEGER)",
        "CREATE TABLE shipment_return_events "
        "(event_id TEXT, shipment_id TEXT, created_at DATETIME)",
        "CREATE TABLE shipment_return_lines "
        "(event_id TEXT, shipment_line_id INTEGER, quantity INTEGER)",
    ]
    import json
    with engine.begin() as c:
        for sql in ddl:
            c.execute(text(sql))
        c.execute(text("INSERT INTO shipment_writeback_facts VALUES "
                       "(1,'new','submit','SHIPPED','2026-11-12 06:00:00.000000',:lines)"),
                  {"lines": json.dumps([line()])})
        c.execute(text("INSERT INTO shipment_lines VALUES (1,'new',1)"))
        c.execute(text("INSERT INTO shipment_return_events VALUES "
                       "('ret','new','2026-11-17 06:00:00')"))
        c.execute(text("INSERT INTO shipment_return_lines VALUES ('ret',1,10)"))

    @event.listens_for(engine, "before_cursor_execute")
    def readonly(_conn, _cursor, statement, _parameters, _context, _many):
        assert statement.lstrip().upper().startswith("SELECT")

    service = ShipmentWriteback(sessionmaker(engine), source_scope="test")
    with patch.object(service, "feed", return_value={"stage": "2026-11-09", "rows": []}):
        result = service.net_feed(start=date(2026, 11, 9), activation=ACTIVATION,
                                  now=datetime(2026, 11, 17, 8, tzinfo=UTC))
    assert quantities(result["snapshots"])["2026-11-09"]["recNew"] == 90
    engine.dispose()
