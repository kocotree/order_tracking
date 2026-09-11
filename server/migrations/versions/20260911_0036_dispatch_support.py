"""support detail-level dispatch with over-shipment

Revision ID: 20260911_0036
Revises: 20260911_0035
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260911_0036"
down_revision: str | None = "20260911_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Remove over-shipment blocker — allow initial_shipped > assigned_quantity.
    with op.batch_alter_table("order_assignments", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_order_assignments_quantity_covers_initial_shipped", type_="check"
        )

    # 2. Allow same SKU/factory from different source details — unique → index.
    with op.batch_alter_table("order_assignments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_order_assignments_line_factory", type_="unique")
        batch_op.create_index(
            "ix_order_assignments_line_factory",
            ["order_line_id", "factory_id"],
        )

    # 3. Link assignment back to its source detail.
    with op.batch_alter_table("order_assignments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("detail_id", sa.String(36), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_order_assignments_detail", ["detail_id"]
        )
        batch_op.create_foreign_key(
            "fk_order_assignments_detail",
            "order_details",
            ["detail_id"],
            ["detail_id"],
            ondelete="RESTRICT",
        )

    # 4. Mark an assignment as active/inactive (withdraw preserves history).
    with op.batch_alter_table("order_assignments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default="1",
            )
        )

    # 5. Batch tracking on order_details (for notification grouping).
    with op.batch_alter_table("order_details", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dispatch_batch_id", sa.String(36), nullable=True)
        )


def downgrade() -> None:
    # Guard: reject downgrade when new-style dispatch data may exist.
    conn = op.get_bind()
    new_assignments = conn.execute(
        sa.text("SELECT 1 FROM order_assignments WHERE detail_id IS NOT NULL LIMIT 1")
    ).fetchone()
    if new_assignments:
        raise RuntimeError(
            "New dispatch assignments with detail_id exist; "
            "backup, drop, and restore with old structure manually."
        )

    with op.batch_alter_table("order_details", schema=None) as batch_op:
        batch_op.drop_column("dispatch_batch_id")

    with op.batch_alter_table("order_assignments", schema=None) as batch_op:
        batch_op.drop_column("is_active")
        batch_op.drop_constraint("fk_order_assignments_detail", type_="foreignkey")
        batch_op.drop_constraint("uq_order_assignments_detail", type_="unique")
        batch_op.drop_column("detail_id")
        batch_op.drop_index("ix_order_assignments_line_factory")
        batch_op.create_unique_constraint(
            "uq_order_assignments_line_factory",
            ["order_line_id", "factory_id"],
        )
        batch_op.create_check_constraint(
            "ck_order_assignments_quantity_covers_initial_shipped",
            "assigned_quantity >= initial_shipped_quantity",
        )