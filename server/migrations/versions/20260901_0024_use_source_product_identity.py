"""Use 聚水潭 source identifiers as product identities.

Revision ID: 20260901_0024
Revises: 20260901_0023
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0024"
down_revision: str | None = "20260901_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_products_name", "products", type_="unique")
    op.create_index(
        "ix_product_variants_product_id",
        "product_variants",
        ["product_id"],
        unique=False,
    )
    op.drop_constraint(
        "uq_product_variants_product_properties",
        "product_variants",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_product_variants_product_properties",
        "product_variants",
        ["product_id", "properties_value"],
    )
    op.drop_index("ix_product_variants_product_id", table_name="product_variants")
    op.create_unique_constraint("uq_products_name", "products", ["name"])
