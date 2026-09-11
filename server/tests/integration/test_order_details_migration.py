from datetime import date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    OrderDetail,
    OrderImportCandidate,
    OrderImportCandidateLine,
    OrderImportRun,
    OrderImportSourceCursor,
    OrderImportSourceRecord,
    ProcessingContract,
    QuantityLedger,
)
from app.modules.orders import AssignmentInput, DraftLineInput, OrderService
from tests.integration.test_order_lifecycle import _seed_order_dependencies


def test_upgrade_preserves_execution_ids_and_unassigned_legacy_drafts(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    admin, factory, _, variant = _seed_order_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderService(sessions)
    inputs = [DraftLineInput(variant, 100, [AssignmentInput(factory, 100, 60, date(2026, 9, 30))])]
    draft = service.create_draft(
        actor_id=admin,
        order_no="LEGACY-DRAFT",
        order_date=None,
        tracker="松子",
        lines=inputs,
        request_id="draft",
    )
    published = service.create_draft(
        actor_id=admin,
        order_no="LEGACY-PUBLISHED",
        order_date=None,
        tracker="松子",
        lines=inputs,
        request_id="published",
    )
    published = service.publish(
        actor_id=admin,
        order_id=published.order_id,
        version=published.version,
        request_id="publish",
        idempotency_key="publish",
    )
    unassigned = service.create_draft(
        actor_id=admin,
        order_no="NO-FACTORY",
        order_date=None,
        tracker="松子",
        lines=[DraftLineInput(variant, 50, [])],
        request_id="unassigned",
    )
    with Session(test_database_engine) as session, session.begin():
        session.add(
            QuantityLedger(
                order_assignment_id=published.lines[0].assignments[0].assignment_id,
                source_type="shipment",
                source_id="historical-shipment",
                quantity_delta=7,
                actor_id=admin,
                created_at=datetime(2026, 9, 1),
            )
        )
        session.add(
            ProcessingContract(
                contract_id="historical-contract",
                order_id=published.order_id,
                factory_id=factory,
                signing_date=date(2026, 9, 1),
                daily_sequence=1,
                contract_no="20260901-KK-A",
                contract_snapshot={"quantity": 100, "productName": "历史合同名称"},
                template_version="v1",
                created_by=admin,
                created_at=datetime(2026, 9, 1),
            )
        )
    tables = [
        "orders",
        "order_lines",
        "order_assignments",
        "quantity_ledger",
        "processing_contracts",
        "outbox_messages",
    ]
    with test_database_engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table}")).mappings().all()
            for table in tables
        }
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20260909_0033")
    try:
        # These columns also exist at revision 0033. Seed actual pre-migration import data.
        with Session(test_database_engine) as session, session.begin():
            now = datetime(2026, 9, 1)
            session.add(
                OrderImportRun(
                    run_id="legacy-run",
                    status="COMPLETED",
                    started_at=now,
                    requested_by=admin,
                    request_id="legacy-run",
                )
            )
            session.flush()
            session.add(
                OrderImportSourceCursor(
                    source_scope="legacy",
                    successful_modified_at=now,
                    successful_run_id="legacy-run",
                    successful_at=now,
                )
            )
            for order, count in [(published, 1), (draft, 2)]:
                candidate = OrderImportCandidate(
                    candidate_id=order.order_id,
                    order_no=order.order_no,
                    status="IMPORTED",
                    validation_state="READY",
                    validation_issues=[],
                    date_overrides={},
                    source_record_count=count,
                    total_quantity=100,
                    shipped_quantity=60,
                    pending_quantity=40,
                    imported_order_id=order.order_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(candidate)
                session.flush()
                for index in range(count):
                    source = OrderImportSourceRecord(
                        source_scope="legacy",
                        source_record_id=f"{order.order_no}-{index}",
                        order_no=order.order_no,
                        raw_fields={"下单数": 100, "出货总数": 60},
                        normalized_fields={},
                        parse_status="PARSED",
                        source_modified_at=now,
                        first_seen_run_id="legacy-run",
                        last_seen_run_id="legacy-run",
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    session.add(source)
                    session.flush()
                    session.add(
                        OrderImportCandidateLine(
                            candidate_id=candidate.candidate_id,
                            source_record_pk=source.source_record_pk,
                            order_quantity=100,
                            shipped_quantity=60,
                            pending_quantity=40,
                            matched_variant_id=variant,
                            matched_factory_id=factory,
                            source_contract_ship_date=date(2026, 9, 30),
                            validation_issues=[],
                        )
                    )
        command.upgrade(config, "head")
        with test_database_engine.connect() as connection:
            for table in tables:
                assert (
                    connection.execute(text(f"SELECT * FROM {table}")).mappings().all()
                    == before[table]
                )
        with Session(test_database_engine) as session:
            details = session.scalars(select(OrderDetail).order_by(OrderDetail.sort_order)).all()
            assert len(details) == 3
            by_order = {row.order_id: row for row in details}
            assert (
                by_order[published.order_id].assignment_id
                == published.lines[0].assignments[0].assignment_id
            )
            assert by_order[published.order_id].source_shipped_quantity == 60
            assert by_order[published.order_id].dispatch_state == "ASSIGNED"
            assert by_order[draft.order_id].dispatch_state == "UNASSIGNED"
            assert by_order[unassigned.order_id].assignment_id is None
            assert by_order[unassigned.order_id].order_quantity == 50
            assert by_order[published.order_id].source_record_pk is not None
            assert by_order[published.order_id].accepted_raw_fields == {
                "下单数": 100,
                "出货总数": 60,
            }
            assert by_order[published.order_id].accepted_source_hash is not None
            assert by_order[draft.order_id].source_record_pk is None
            assert by_order[draft.order_id].parse_issues == ["LEGACY_SOURCE_MAPPING_UNRESOLVED"]
            assert by_order[unassigned.order_id].source_record_pk is None
            assert session.get(OrderImportSourceCursor, "legacy") is None
        # Migration snapshots must not break the established manual draft editor.
        saved = service.save_draft(
            actor_id=admin,
            order_id=draft.order_id,
            version=draft.version,
            order_no=draft.order_no,
            order_date=None,
            tracker="松子",
            lines=inputs,
            request_id="save",
        )
        assert saved.total_quantity == 100 and saved.shipped_quantity == 60
    finally:
        command.upgrade(config, "head")


def test_downgrade_refuses_new_source_data_before_altering_schema(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    from app.db.models import Order

    admin, _, _, _ = _seed_order_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            Order(
                order_id="new-source",
                order_no="NEW-SOURCE",
                source="feishu",
                detail_mode=True,
                lifecycle="DRAFT",
                created_by=admin,
                updated_by=admin,
            )
        )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="拒绝有损回滚"):
        command.downgrade(config, "20260909_0033")
    assert OrderService(sessionmaker(test_database_engine)).get(order_id="new-source").detail_mode
