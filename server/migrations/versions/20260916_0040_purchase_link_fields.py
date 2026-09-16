"""Persist purchase order links on accepted order details."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0040"
down_revision = "20260915_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_details", sa.Column("purchase_order_id", sa.Text(), nullable=True))
    op.add_column(
        "order_details", sa.Column("purchase_order_item_id", sa.Text(), nullable=True)
    )
    op.execute("""
        UPDATE order_details
        SET
            purchase_order_id = CASE
                WHEN JSON_TYPE(JSON_EXTRACT(
                    accepted_raw_fields, '$._purchase.mainOrderId'
                )) = 'STRING'
                THEN NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                    accepted_raw_fields, '$._purchase.mainOrderId'
                ))), '')
                ELSE NULL
            END,
            purchase_order_item_id = CASE
                WHEN JSON_TYPE(JSON_EXTRACT(
                    accepted_raw_fields, '$._purchase.childOrderId'
                )) = 'STRING'
                THEN NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                    accepted_raw_fields, '$._purchase.childOrderId'
                ))), '')
                ELSE NULL
            END
    """)


def downgrade() -> None:
    op.drop_column("order_details", "purchase_order_item_id")
    op.drop_column("order_details", "purchase_order_id")
