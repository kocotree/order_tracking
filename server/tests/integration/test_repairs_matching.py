from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, Product, ProductVariant
from app.modules.repairs.matching import InspectionCatalogMatcher
from app.modules.repairs.workbook import InspectionWorkbookLine, InspectionWorkbookSnapshot


@pytest.fixture(autouse=True)
def clean_repair_matching_records(test_database_engine: Engine) -> Iterator[None]:
    def clean() -> None:
        with Session(test_database_engine) as session, session.begin():
            session.execute(
                delete(ProductVariant).where(ProductVariant.variant_id == "repair-variant")
            )
            session.execute(delete(Product).where(Product.product_id == "repair-product"))
            session.execute(delete(Factory).where(Factory.factory_id == "repair-factory"))

    clean()
    yield
    clean()


def test_matcher_resolves_exact_enabled_factory_product_and_variant(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 26, 9, 0)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            Factory(
                factory_id="repair-factory",
                supplier_number="E28",
                factory_name="跃富",
                factory_code="RF",
                is_enabled=True,
            )
        )
        session.add(
            Product(
                product_id="repair-product",
                source_i_id="KQ26022",
                name="小动物软檐鸭舌帽",
                is_available=True,
                image_cache_status="missing",
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
        session.add(
            ProductVariant(
                variant_id="repair-variant",
                product_id="repair-product",
                source_sku_id="6941716599133",
                properties_value="兔兔奶糖S",
                is_available=True,
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
    line = InspectionWorkbookLine(
        source_row=2,
        supplier_number="E28",
        factory_name="跃富",
        source_sku_id="6941716599133",
        source_product_id="KQ26022",
        product_name="小动物软檐鸭舌帽",
        properties_value="兔兔奶糖S",
        quantity=51,
        box_number="1号箱",
        reason=None,
    )
    snapshot = InspectionWorkbookSnapshot(
        supplier_number="E28",
        factory_name="跃富",
        total_quantity=51,
        box_numbers=("1号箱",),
        lines=(line,),
    )
    matcher = InspectionCatalogMatcher(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )

    result = matcher.match(snapshot)

    assert result.factory_id == "repair-factory"
    assert result.issues == ()
    assert len(result.lines) == 1
    assert result.lines[0].source_line == line
    assert result.lines[0].product_id == "repair-product"
    assert result.lines[0].variant_id == "repair-variant"


def test_matcher_rejects_factory_when_number_and_name_do_not_match_together(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        session.add(
            Factory(
                factory_id="repair-factory",
                supplier_number="E28",
                factory_name="另一个工厂",
                factory_code="RF",
                is_enabled=True,
            )
        )
    line = InspectionWorkbookLine(
        source_row=2,
        supplier_number="E28",
        factory_name="跃富",
        source_sku_id="6941716599133",
        source_product_id="KQ26022",
        product_name="小动物软檐鸭舌帽",
        properties_value="兔兔奶糖S",
        quantity=51,
        box_number="1号箱",
        reason=None,
    )
    snapshot = InspectionWorkbookSnapshot(
        supplier_number="E28",
        factory_name="跃富",
        total_quantity=51,
        box_numbers=("1号箱",),
        lines=(line,),
    )

    result = InspectionCatalogMatcher(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    ).match(snapshot)

    assert result.factory_id is None
    assert result.lines == ()
    assert result.issues == (
        {
            "code": "factory_not_available",
            "message": "工厂编号和名称未同时匹配已启用工厂",
            "sheet": "Sheet1",
            "row": 2,
            "field": "A:B",
        },
    )
