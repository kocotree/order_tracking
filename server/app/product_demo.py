from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import FakeJstProductSource, SourceProductVariant
from app.db.models import Product
from app.modules.product_sync import ProductSyncService

LOCAL_DEMO_CATEGORIES = (
    "童帽春夏",
    "童配春夏",
    "童装春夏",
    "童帽秋冬",
    "童配秋冬",
    "童装秋冬",
)


def seed_local_demo_products(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        if session.scalar(select(Product.product_id).limit(1)) is not None:
            return
    records = [
        SourceProductVariant(
            i_id=f"DEMO-{index:02d}",
            sku_id=f"DEMO-SKU-{index:02d}",
            name=f"演示产品 {index:02d}",
            properties_value=f"演示色,{49 + index}",
            pic=None,
            category=LOCAL_DEMO_CATEGORIES[(index - 1) % len(LOCAL_DEMO_CATEGORIES)],
            enabled=1,
            source_modified_at=datetime(2026, 8, 21, 8, index),
        )
        for index in range(1, 13)
    ]
    records.extend(
        [
            SourceProductVariant(
                i_id="DEMO-IGNORED-CATEGORY",
                sku_id="DEMO-SKU-IGNORED-CATEGORY",
                name="演示范围外产品",
                properties_value="无关,00",
                pic=None,
                category="邮费",
                enabled=1,
                source_modified_at=datetime(2026, 8, 21, 9, 1),
            ),
            SourceProductVariant(
                i_id="DEMO-IGNORED-DISABLED",
                sku_id="DEMO-SKU-IGNORED-DISABLED",
                name="演示停用产品",
                properties_value="停用,00",
                pic=None,
                category="童帽春夏",
                enabled=0,
                source_modified_at=datetime(2026, 8, 21, 9, 2),
            ),
        ]
    )
    ProductSyncService(
        session_factory,
        source=FakeJstProductSource(
            initial_pages=[records[:8], records[8:]],
            candidate_cursor="local-demo-initial-v1",
        ),
    ).run_initial(
        request_id="local-demo-product-seed",
        worker_id="local-demo-startup",
    )
