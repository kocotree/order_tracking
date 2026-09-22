import sqlalchemy as sa
from alembic import op

revision = "20260922_0042"
down_revision = "20260921_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shipment_receipt_items",
        sa.Column("order_assignment_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_shipment_receipt_items_assignment",
        "shipment_receipt_items",
        "order_assignments",
        ["order_assignment_id"],
        ["order_assignment_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_shipment_receipt_items_assignment", "shipment_receipt_items", type_="foreignkey"
    )
    op.drop_column("shipment_receipt_items", "order_assignment_id")
