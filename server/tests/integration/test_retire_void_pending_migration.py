from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, MetaData, Table, delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import OutboxMessage, Shipment, ShipmentVoidRequest
from tests.api.test_shipment_api import FACTORY_IDS, USER_IDS, _seed


@pytest.mark.parametrize("legacy_state", ["shipment", "request", "event"])
def test_retirement_blocks_pending_data_and_preserves_archive(
    test_database_engine: Engine, test_database_url: str, legacy_state: str,
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    _seed(test_database_engine)
    command.downgrade(config, "20260930_0049")
    shipments = Table("shipments", MetaData(), autoload_with=test_database_engine)
    try:
        with Session(test_database_engine) as session, session.begin():
            session.execute(shipments.insert().values(
                shipment_id="legacy-approval", factory_id=FACTORY_IDS[0],
                created_by=USER_IDS[0],
                status="VOID_PENDING" if legacy_state == "shipment" else "SHIPPED",
            ))
            session.flush()
            session.add(ShipmentVoidRequest(
                request_id="legacy-request", shipment_id="legacy-approval",
                requested_by=USER_IDS[0], reason="历史原因", idempotency_key="legacy",
                status="PENDING" if legacy_state == "request" else "REJECTED",
                created_at=datetime(2026, 9, 1),
            ))
            if legacy_state == "event":
                session.add(OutboxMessage(
                    event_type="shipment.void_approved", aggregate_type="shipment",
                    aggregate_id="legacy-approval", dedupe_key="legacy-approval-event",
                    payload={}, status="pending", available_at=datetime(2026, 9, 1),
                ))
        with pytest.raises(RuntimeError, match="历史待审核"):
            command.upgrade(config, "head")
        with Session(test_database_engine) as session, session.begin():
            shipment = session.execute(select(shipments).where(
                shipments.c.shipment_id == "legacy-approval",
            )).mappings().one()
            request = session.get(ShipmentVoidRequest, "legacy-request")
            assert shipment is not None and request is not None
            assert shipment["status"] == (
                "VOID_PENDING" if legacy_state == "shipment" else "SHIPPED"
            )
            assert request.status == ("PENDING" if legacy_state == "request" else "REJECTED")
            assert request.reason == "历史原因"
            # 测试模拟人工完成核对，迁移本身不做状态转换。
            session.execute(update(shipments).where(
                shipments.c.shipment_id == "legacy-approval",
            ).values(status="SHIPPED"))
            request.status = "REJECTED"
            event = session.query(OutboxMessage).filter_by(
                dedupe_key="legacy-approval-event"
            ).one_or_none()
            if legacy_state == "event":
                assert event is not None and event.status == "pending"
                event.status = "completed"
        command.upgrade(config, "head")
        with Session(test_database_engine) as session:
            assert session.get(ShipmentVoidRequest, "legacy-request").reason == "历史原因"
        with (
            pytest.raises(DBAPIError, match="ck_shipments_status"),
            Session(test_database_engine) as session,
            session.begin(),
        ):
            session.get(Shipment, "legacy-approval").status = "VOID_PENDING"
    finally:
        with Session(test_database_engine) as session, session.begin():
            session.execute(delete(OutboxMessage).where(
                OutboxMessage.dedupe_key == "legacy-approval-event"
            ))
            session.execute(delete(ShipmentVoidRequest).where(
                ShipmentVoidRequest.request_id == "legacy-request"
            ))
            session.execute(delete(Shipment).where(Shipment.shipment_id == "legacy-approval"))
        command.upgrade(config, "head")
