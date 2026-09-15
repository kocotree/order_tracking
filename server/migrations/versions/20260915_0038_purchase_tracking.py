"""Add purchase source overrides and tracker collections."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0038"
down_revision = "20260911_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_import_candidates",
        sa.Column("field_overrides", sa.JSON(), nullable=True),
    )
    op.add_column(
        "order_import_candidates",
        sa.Column("trackers", sa.JSON(), nullable=True),
    )
    op.add_column(
        "orders", sa.Column("trackers", sa.JSON(), nullable=True)
    )
    op.add_column(
        "order_details",
        sa.Column("source_trackers", sa.JSON(), nullable=True),
    )
    op.add_column(
        "order_details",
        sa.Column("factory_override_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "order_details",
        sa.Column("shipped_override_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    for table in ("order_import_candidates", "orders"):
        op.execute(
            f"UPDATE {table} SET trackers=JSON_ARRAY(tracker) WHERE tracker IS NOT NULL"
        )
    op.execute(
        "UPDATE order_details SET source_trackers=JSON_ARRAY(source_tracker) "
        "WHERE source_tracker IS NOT NULL"
    )
    op.execute("UPDATE order_import_candidates SET field_overrides=JSON_OBJECT()")
    op.execute("UPDATE order_import_candidates SET trackers=JSON_ARRAY() WHERE trackers IS NULL")
    op.execute("UPDATE orders SET trackers=JSON_ARRAY() WHERE trackers IS NULL")
    op.execute(
        "UPDATE order_details SET source_trackers=JSON_ARRAY() WHERE source_trackers IS NULL"
    )
    op.alter_column(
        "order_import_candidates", "field_overrides", existing_type=sa.JSON(), nullable=False
    )
    op.alter_column(
        "order_import_candidates", "trackers", existing_type=sa.JSON(), nullable=False
    )
    op.alter_column("orders", "trackers", existing_type=sa.JSON(), nullable=False)
    op.alter_column(
        "order_details", "source_trackers", existing_type=sa.JSON(), nullable=False
    )


def downgrade() -> None:
    conn = op.get_bind()
    if (
        conn.execute(
            sa.text(
                "SELECT 1 FROM order_assignments "
                "WHERE is_active = 0 OR detail_id IS NOT NULL LIMIT 1"
            )
        ).first()
        or conn.execute(
            sa.text(
                "SELECT 1 FROM order_import_candidates "
                "WHERE JSON_LENGTH(field_overrides) > 0 OR JSON_LENGTH(trackers) > 1 LIMIT 1"
            )
        ).first()
        or conn.execute(
            sa.text("SELECT 1 FROM orders WHERE JSON_LENGTH(trackers) > 1 LIMIT 1")
        ).first()
        or conn.execute(
            sa.text(
                "SELECT 1 FROM order_details WHERE factory_override_enabled = 1 "
                "OR shipped_override_enabled = 1 OR JSON_LENGTH(source_trackers) > 1 LIMIT 1"
            )
        ).first()
    ):
        raise RuntimeError("存在采购来源维护或多人跟单资料，拒绝有损回滚")
    op.drop_column("order_details", "shipped_override_enabled")
    op.drop_column("order_details", "factory_override_enabled")
    op.drop_column("order_details", "source_trackers")
    op.drop_column("orders", "trackers")
    op.drop_column("order_import_candidates", "trackers")
    op.drop_column("order_import_candidates", "field_overrides")
