from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.adapters.product import FakeJstProductSource, ProductSourceError, SourceProductVariant
from app.db.models import BackgroundJob, Order, ProductSyncRun
from app.modules.order_import import OrderImportService
from app.modules.order_import.auto_sync import OrderAutoSync
from app.modules.orders.source_update import OrderSourceUpdateService
from app.modules.product_sync import ProductSyncService
from tests.integration.test_order_auto_sync import complete_cycle
from tests.integration.test_order_dispatch import _row, setup_dispatch_order
from tests.integration.test_order_import import _seed_import_dependencies


class ProductSource(FakeJstProductSource):
    def __init__(self, records):
        super().__init__(candidate_cursor="unused")
        self.records = records
        self.calls = []

    def fetch_targeted_page(self, *, page_number, name=None, i_id=None, sku_id=None):
        self.calls.append((i_id, sku_id))
        records = [r for r in self.records if (
            r.sku_id == sku_id if sku_id else r.i_id == i_id
        )]
        return self._page([records], page_number)


def records():
    first = SourceProductVariant(
        i_id="KQ25112", sku_id="NEW-1", name="手套", properties_value="紫色",
        pic="https://example.test/1.png", category="儿童手套", enabled=1,
        source_modified_at=datetime(2026, 9, 30),
    )
    return [first, replace(first, sku_id="NEW-2", properties_value="蓝色")]


def test_recovery_syncs_style_once_and_retries_strict_match(test_database_engine: Engine):
    sessions = sessionmaker(test_database_engine)
    source = ProductSource(records())
    importer = OrderImportService(
        sessions, product_sync=ProductSyncService(sessions, source=source),
    )
    rows = [_row(source_sku_id=r.sku_id, product_name=r.name, properties_value=r.properties_value)
            for r in records()]
    importer.recover_products(rows + rows, request_id="recover")
    with sessions() as session:
        assert all(importer.match_source_row(session, row)[0] for row in rows)
        assert len(list(session.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "product-image-cache"
        )))) == 2
        runs = list(session.scalars(select(ProductSyncRun)))
        assert len(runs) == 1 and runs[0].success_cursor is None
    calls = list(source.calls)
    importer.recover_products(rows, request_id="again")
    assert source.calls == calls
    assert sum(sku is not None for _, sku in calls) == 1


@pytest.mark.parametrize("kind", ["missing", "disabled", "category", "name", "properties"])
def test_recovery_does_not_guess_matches(test_database_engine: Engine, kind: str):
    sessions = sessionmaker(test_database_engine)
    values = records()
    if kind == "missing":
        values = []
    elif kind == "disabled":
        values = [replace(r, enabled=0) for r in values]
    elif kind == "category":
        values = [replace(r, category="其他") for r in values]
    source = ProductSource(values)
    importer = OrderImportService(
        sessions, product_sync=ProductSyncService(sessions, source=source),
    )
    row = _row(source_sku_id="NEW-1", product_name="错误" if kind == "name" else "手套",
               properties_value="错误" if kind == "properties" else "紫色")
    importer.recover_products([row], request_id="unmatched")
    with sessions() as session:
        variant, _, issues = importer.match_source_row(session, row)
        assert variant is None and "PRODUCT_VARIANT_NOT_MATCHED" in issues


def test_auto_import_recovers_product_before_dispatch(test_database_engine: Engine):
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    row = _row(source_sku_id="NEW-1", product_name="手套", properties_value="紫色")
    sync = OrderAutoSync(
        sessions, source=FakeFeishuOrderSource([[row]]),
        product_sync=ProductSyncService(sessions, source=ProductSource(records())),
    )
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert session.scalar(select(Order.lifecycle)) == "PUBLISHED"


def test_recovery_updates_existing_name_and_keeps_old_source_protection(
    test_database_engine: Engine,
):
    sessions = sessionmaker(test_database_engine)
    source = ProductSource([replace(r, pic=None) for r in records()])
    sync = ProductSyncService(sessions, source=source)
    importer = OrderImportService(sessions, product_sync=sync)
    row = _row(source_sku_id="NEW-1", product_name="手套", properties_value="紫色")
    importer.recover_products([row], request_id="initial")
    source.records = [replace(r, name="新手套") for r in source.records]
    renamed = replace(row, product_name="新手套")
    importer.recover_products([renamed], request_id="rename")
    with sessions() as session:
        assert importer.match_source_row(session, renamed)[0] is not None
    source.records = [replace(r, source_modified_at=datetime(2026, 9, 29)) for r in records()]
    importer.recover_products([row], request_id="older")
    with sessions() as session:
        assert importer.match_source_row(session, row)[0] is None
        assert importer.match_source_row(session, renamed)[0] is not None


@pytest.mark.parametrize("automatic", [False, True])
def test_refresh_recovers_and_confirmation_does_not_refetch(
    test_database_engine: Engine, automatic: bool,
):
    row = _row(source_sku_id="NEW-1", product_name="手套", properties_value="紫色")
    sessions, order_source, order_id = setup_dispatch_order(test_database_engine, rows=[row])
    source = ProductSource(records())
    service = OrderSourceUpdateService(
        sessions, source=order_source, product_sync=ProductSyncService(sessions, source=source),
    )
    order = service.get(order_id=order_id)
    assert order.details[0].matched_variant_id is None
    if automatic:
        service.refresh_automatically(order_id=order_id, request_id="refresh")
    else:
        args = dict(actor_id="admin-order-import", order_id=order_id,
                    version=order.version, request_id="refresh")
        preview = service.preview(**args)
        calls = list(source.calls)
        service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="confirm")
        assert source.calls == calls
    assert service.get(order_id=order_id).details[0].matched_variant_id is not None


@pytest.mark.parametrize("kind", ["failure", "wrong_sku", "ambiguous"])
def test_query_errors_fail_without_writing_product(test_database_engine: Engine, kind: str):
    class InvalidSource(ProductSource):
        def fetch_targeted_page(self, **kwargs):
            if kind == "failure":
                raise ProductSourceError("upstream_failed")
            values = records()[:1]
            if kind == "wrong_sku":
                values = [replace(values[0], sku_id="WRONG")]
            else:
                values.append(replace(values[0], i_id="OTHER"))
            return self._page([values], kwargs["page_number"])

    sessions = sessionmaker(test_database_engine)
    importer = OrderImportService(
        sessions, product_sync=ProductSyncService(sessions, source=InvalidSource(records())),
    )
    with pytest.raises(ProductSourceError):
        importer.recover_products([_row(source_sku_id="NEW-1")], request_id="error")
    with sessions() as session:
        assert not list(session.scalars(select(BackgroundJob)))
