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
    op.execute(
        "ALTER TABLE order_assignments "
        "DROP CHECK ck_order_assignments_quantity_covers_initial_shipped"
    )
    # 2. Allow same SKU/factory from different source details — unique key to index.
    #    Create the replacement index first: MySQL refuses to drop the unique key
    #    while a foreign key still needs it as the backing index.
    op.create_index(
        "ix_order_assignments_line_factory",
        "order_assignments",
        ["order_line_id", "factory_id"],
    )
    op.drop_index("uq_order_assignments_line_factory", table_name="order_assignments")
    # 3. Link assignment back to its source detail.
    op.add_column("order_assignments", sa.Column("detail_id", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_order_assignments_detail", "order_assignments", ["detail_id"])
    op.create_foreign_key(
        "fk_order_assignments_detail",
        "order_assignments",
        "order_details",
        ["detail_id"],
        ["detail_id"],
        ondelete="RESTRICT",
    )
    # 4. Mark an assignment active/inactive (withdraw preserves history).
    op.add_column(
        "order_assignments",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
    )
    # 5. Batch tracking on order_details (for notification grouping).
    op.add_column("order_details", sa.Column("dispatch_batch_id", sa.String(36), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    new_assignments = conn.execute(
        sa.text("SELECT 1 FROM order_assignments WHERE detail_id IS NOT NULL LIMIT 1")
    ).fetchone()
    source_data = (
        conn.execute(
            sa.text("SELECT 1 FROM orders WHERE detail_mode = 1 OR tracker IS NULL LIMIT 1")
        ).fetchone()
        or conn.execute(sa.text("SELECT 1 FROM order_import_candidates LIMIT 1")).fetchone()
        or conn.execute(
            sa.text("SELECT 1 FROM order_details WHERE origin <> 'legacy' LIMIT 1")
        ).fetchone()
    )
    if new_assignments or source_data:
        raise RuntimeError("存在新来源或派工资料，拒绝有损回滚；请按已审核备份恢复方案处理")
    op.drop_column("order_details", "dispatch_batch_id")
    op.drop_column("order_assignments", "is_active")
    op.drop_constraint("fk_order_assignments_detail", "order_assignments", type_="foreignkey")
    op.drop_constraint("uq_order_assignments_detail", "order_assignments", type_="unique")
    op.drop_column("order_assignments", "detail_id")
    op.create_unique_constraint(
        "uq_order_assignments_line_factory", "order_assignments", ["order_line_id", "factory_id"]
    )
    op.drop_index("ix_order_assignments_line_factory", table_name="order_assignments")
    op.create_check_constraint(
        "ck_order_assignments_quantity_covers_initial_shipped",
        "order_assignments",
        "assigned_quantity >= initial_shipped_quantity",
    )
