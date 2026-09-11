"""Keep source links on withdrawn assignments when redispatching."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_0037"
down_revision = "20260911_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_order_assignments_detail", "order_assignments", ["detail_id"])
    op.drop_index("uq_order_assignments_detail", table_name="order_assignments")
    op.execute(
        "UPDATE order_assignments a JOIN order_lines l USING (order_line_id) "
        "JOIN orders o USING (order_id) SET a.is_active = 0 WHERE o.lifecycle = 'DRAFT'"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM order_assignments "
                "WHERE is_active = 0 OR detail_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("存在新派工或撤回资料，拒绝有损回滚")
    op.create_unique_constraint("uq_order_assignments_detail", "order_assignments", ["detail_id"])
    op.drop_index("ix_order_assignments_detail", table_name="order_assignments")
