from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Integer, MetaData, create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.shipment_sync_feed import create_shipment_sync_feed_router
from app.db.models import (
    ShipmentWritebackClaim,
    ShipmentWritebackControl,
    ShipmentWritebackFact,
    ShipmentWritebackRow,
    ShipmentWritebackStage,
)
from app.modules.shipment_writeback.facts import utc_naive
from app.modules.shipment_writeback.periods import SHANGHAI, month_stages
from app.modules.shipment_writeback.service import ShipmentWriteback
from app.settings.config import Settings

FEED = "/api/v1/integrations/shipment-sync/feed"
TOKEN = "test-integration-token-for-shipment-feed"


def test_net_feed_disabled_until_activation_is_explicitly_configured():
    service = Mock()
    app = FastAPI()
    app.include_router(create_shipment_sync_feed_router(
        service, table_id="tblTest", token=TOKEN, start=date(2026, 11, 9),
    ))
    with TestClient(app) as client:
        assert client.get(FEED.replace('/feed', '/net-feed'), headers={
            "Authorization": f"Bearer {TOKEN}",
        }).status_code == 404
    service.net_feed.assert_not_called()


def test_net_feed_authenticates_and_reports_pinned_activation():
    activation = datetime(2026, 11, 12, 8, tzinfo=UTC)
    service = Mock()
    service.net_feed.return_value = {"activation": activation.isoformat(),
                                     "cutoff": activation.isoformat(), "snapshots": []}
    app = FastAPI()
    app.include_router(create_shipment_sync_feed_router(
        service, table_id="tblTest", token=TOKEN, start=date(2026, 11, 9),
        returns_from=activation,
    ))
    with TestClient(app) as client:
        endpoint = FEED.replace('/feed', '/net-feed')
        assert client.get(endpoint).status_code == 401
        response = client.get(endpoint, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.json()['activation'] == activation.isoformat()
        assert client.get(endpoint, params={'after': '2026-11-12T08:00:00'}, headers={
            "Authorization": f"Bearer {TOKEN}",
        }).status_code == 422


def test_disabled_feed_does_not_query_snapshot():
    service = Mock()
    app = FastAPI()
    app.include_router(create_shipment_sync_feed_router(
        service, table_id="tblTest", token=TOKEN, start=None,
    ))
    with TestClient(app) as client:
        assert client.get(FEED, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 404
    service.feed.assert_not_called()


def test_feed_requires_dedicated_token_and_does_not_cache_data():
    service = Mock()
    service.feed.return_value = {
        "stage": "2026-11-09", "cutoff": "2026-11-10T22:00:00+08:00",
        "field": "26.11.09-11.15出货", "rows": [],
    }
    app = FastAPI()
    app.include_router(create_shipment_sync_feed_router(
        service, table_id="tblTest", token=TOKEN, start=date(2026, 11, 9),
    ))
    with TestClient(app) as client:
        assert client.get(FEED).status_code == 401
        assert client.get(FEED, headers={"Authorization": "Bearer other"}).status_code == 401
        service.feed.assert_not_called()
        response = client.get(FEED, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"table_id": "tblTest", **service.feed.return_value}


def test_unready_source_does_not_look_like_a_successful_empty_snapshot():
    service = Mock()
    service.feed.side_effect = ValueError("history not ready")
    app = FastAPI()
    app.include_router(create_shipment_sync_feed_router(
        service, table_id="tblTest", token=TOKEN, start=date(2026, 11, 9),
    ))
    with TestClient(app) as client:
        response = client.get(FEED, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503

def test_midnight_cutover_preserves_old_freeze_and_has_no_gap():
    first, second, third, _ = month_stages(2026, 11, midnight_from=date(2026, 11, 9))
    assert first.until.astimezone(SHANGHAI).isoformat() == "2026-11-08T22:00:00+08:00"
    assert second.since == first.until
    assert second.until.astimezone(SHANGHAI).isoformat() == "2026-11-16T00:00:00+08:00"
    assert second.until == third.since


def test_preview_replays_midnight_cutoffs_independently_of_legacy_claims():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for model in (ShipmentWritebackClaim, ShipmentWritebackControl, ShipmentWritebackFact,
                  ShipmentWritebackRow, ShipmentWritebackStage):
        table = model.__table__.to_metadata(metadata)
        if "id" in table.c:
            table.c.id.type = Integer()
    metadata.create_all(engine)
    sessions = sessionmaker(engine)
    start = date(2026, 11, 9)
    prior, _, _, _ = month_stages(2026, 11, midnight_from=start)
    service = ShipmentWriteback(sessions, source_scope="test")

    def frozen(stage):
        return ShipmentWritebackStage(
            stage_key=stage.key, source_scope="test", since=utc_naive(stage.since),
            until=utc_naive(stage.until), excluded={},
        )

    with sessions.begin() as session:
        session.add_all([
            ShipmentWritebackControl(id=1, history_ready=True, structure={}),
            frozen(prior),
        ])
        for index, (hour, minute, qty) in enumerate([(14, 20, 12), (15, 36, 7)]):
            session.add(ShipmentWritebackFact(
                root_id=f"shipment-{index}", event_key=f"submit-{index}", status="SHIPPED",
                occurred_at=datetime(2026, 11, 15, hour, minute),
                lines=[{"record_id": "recA", "order_no": "O1", "detail_id": "D1",
                        "quantity": qty, "source_scope": "test"}],
            ))

        facts = list(session.query(ShipmentWritebackFact).order_by(ShipmentWritebackFact.id))
        session.add(ShipmentWritebackFact(
            root_id=facts[-1].root_id, event_key="resubmit", status="SHIPPED",
            occurred_at=datetime(2026, 11, 15, 16, 10), lines=facts[-1].lines,
        ))
        legacy = month_stages(2026, 11)
        session.add_all([frozen(legacy[1]), frozen(legacy[2])])
        session.flush()
        session.add_all([
            ShipmentWritebackClaim(root_id=fact.root_id, fact_id=fact.id, stage_key=stage.key)
            for fact, stage in zip(facts, legacy[1:3], strict=True)
        ])

    @event.listens_for(engine, "before_cursor_execute")
    def reject_writes(_conn, _cursor, statement, _params, _context, _executemany):
        assert statement.lstrip().upper().startswith("SELECT"), statement

    before_midnight = service.feed(start=start, now=datetime(2026, 11, 15, 15, 5, tzinfo=UTC))
    assert before_midnight is not None
    assert before_midnight["cutoff"] == "2026-11-15T23:00:00+08:00"
    assert before_midnight["rows"][0]["quantity"] == 12
    after_midnight = datetime(2026, 11, 15, 17, 5, tzinfo=UTC)
    final = service.feed(start=start, now=after_midnight, final=True)
    assert final is not None
    assert final["stage"] == "2026-11-09"
    assert final["cutoff"] == "2026-11-16T00:00:00+08:00"
    assert final["rows"][0]["quantity"] == 19
    current = service.feed(start=start, now=after_midnight)
    assert current is not None and current["stage"] == "2026-11-16"
    assert current["rows"] == []
    engine.dispose()


def test_feed_can_be_enabled_with_legacy_writeback_disabled():
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        shipment_sync_feed_enabled=True,
        shipment_sync_feed_token=TOKEN,
        shipment_sync_midnight_from=date(2026, 11, 9),
        feishu_order_app_token="base",
        feishu_order_table_id="table",
        feishu_order_app_id="app",
        feishu_order_app_secret="test-secret",
        feishu_order_view_id="view",
        feishu_order_field_ids={"订单编号": "field"},
    )
    assert settings.shipment_sync_feed_enabled
    assert not settings.shipment_writeback_enabled


@pytest.mark.parametrize("token", ["", "short"])
def test_feed_enabled_rejects_missing_or_short_token(token):
    with pytest.raises(ValueError, match="shipment sync feed"):
        Settings(
            _env_file=None,
            database_url="sqlite://",
            shipment_sync_feed_enabled=True,
            shipment_sync_feed_token=token,
            shipment_sync_midnight_from=date(2026, 11, 9),
            feishu_order_app_token="base",
            feishu_order_table_id="table",
        )
