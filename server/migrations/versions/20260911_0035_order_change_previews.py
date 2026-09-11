"""Order source update previews and idempotent results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20260911_0035"
down_revision = "20260911_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_change_previews",
        sa.Column("preview_id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.order_id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("consumed_at", DATETIME(fsp=6)),
    )
    op.add_column("idempotency_records", sa.Column("request_hash", sa.String(64)))
    op.add_column("idempotency_records", sa.Column("result", sa.JSON()))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT COUNT(*) FROM idempotency_records WHERE request_hash IS NOT NULL")
    ).scalar():
        raise RuntimeError("存在来源更新幂等结果，拒绝有损回滚；请按已审核备份恢复方案处理")
    op.drop_table("order_change_previews")
    op.drop_column("idempotency_records", "result")
    op.drop_column("idempotency_records", "request_hash")
