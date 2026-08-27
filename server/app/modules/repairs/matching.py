from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, Product, ProductVariant
from app.modules.repairs.workbook import InspectionWorkbookLine, InspectionWorkbookSnapshot

InspectionMatchIssue = dict[str, str | int]


@dataclass(frozen=True)
class MatchedInspectionLine:
    source_line: InspectionWorkbookLine
    product_id: str
    variant_id: str


@dataclass(frozen=True)
class InspectionMatchResult:
    factory_id: str | None
    lines: tuple[MatchedInspectionLine, ...]
    issues: tuple[InspectionMatchIssue, ...]


class InspectionCatalogMatcher:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def match(self, snapshot: InspectionWorkbookSnapshot) -> InspectionMatchResult:
        with self._session_factory() as session:
            factory = session.scalar(
                select(Factory).where(
                    Factory.supplier_number == snapshot.supplier_number,
                    Factory.factory_name == snapshot.factory_name,
                    Factory.is_enabled.is_(True),
                )
            )
            if factory is None:
                return InspectionMatchResult(
                    factory_id=None,
                    lines=(),
                    issues=(
                        {
                            "code": "factory_not_available",
                            "message": "工厂编号和名称未同时匹配已启用工厂",
                            "sheet": "Sheet1",
                            "row": snapshot.lines[0].source_row,
                            "field": "A:B",
                        },
                    ),
                )

            matched_lines: list[MatchedInspectionLine] = []
            issues: list[InspectionMatchIssue] = []
            for line in snapshot.lines:
                row = session.execute(
                    select(Product, ProductVariant)
                    .join(ProductVariant, ProductVariant.product_id == Product.product_id)
                    .where(
                        ProductVariant.source_sku_id == line.source_sku_id,
                        Product.source_i_id == line.source_product_id,
                        Product.name == line.product_name,
                        ProductVariant.properties_value == line.properties_value,
                        Product.is_available.is_(True),
                        ProductVariant.is_available.is_(True),
                    )
                ).one_or_none()
                if row is None:
                    issues.append(
                        {
                            "code": "product_variant_not_available",
                            "message": "商品和规格未严格匹配当前可用资料",
                            "sheet": "Sheet1",
                            "row": line.source_row,
                            "field": "C:F",
                        }
                    )
                    continue
                product, variant = row
                matched_lines.append(
                    MatchedInspectionLine(
                        source_line=line,
                        product_id=product.product_id,
                        variant_id=variant.variant_id,
                    )
                )
            return InspectionMatchResult(
                factory_id=factory.factory_id,
                lines=tuple(matched_lines),
                issues=tuple(issues),
            )
