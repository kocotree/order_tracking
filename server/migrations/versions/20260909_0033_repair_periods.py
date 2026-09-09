"""Group source sheets by factory and fixed half-year; retain source return facts."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260909_0033"
down_revision: str | None = "20260909_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT COUNT(*) FROM repair_return_drafts WHERE JSON_LENGTH(entries) > 0")
    ).scalar():
        raise RuntimeError("存在旧返修草稿，需先核对上线前提；迁移未转换或删除草稿")
    if bind.execute(
        sa.text("SELECT COUNT(*) FROM repair_orders WHERE archived_at IS NOT NULL")
    ).scalar():
        raise RuntimeError("存在旧归档记录，需先核对上线前提")
    op.create_table(
        "repair_periods",
        sa.Column("period_id", sa.String(36), primary_key=True),
        sa.Column(
            "factory_id",
            sa.String(36),
            sa.ForeignKey("factories.factory_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("archived_at", mysql.DATETIME(fsp=6)),
        sa.Column(
            "archived_by", sa.String(36), sa.ForeignKey("users.user_id", ondelete="RESTRICT")
        ),
        sa.UniqueConstraint("factory_id", "start_date", name="uq_repair_period_factory_start"),
    )
    op.add_column("repair_orders", sa.Column("period_id", sa.String(36)))
    op.create_foreign_key(
        "fk_repair_order_period",
        "repair_orders",
        "repair_periods",
        ["period_id"],
        ["period_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_repair_orders_period_id", "repair_orders", ["period_id"])
    op.create_table(
        "repair_period_batches",
        sa.Column("batch_id", sa.String(36), primary_key=True),
        sa.Column(
            "period_id",
            sa.String(36),
            sa.ForeignKey("repair_periods.period_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("idempotency_key", sa.String(191), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("submitted_by", "idempotency_key", name="uq_repair_period_batch_key"),
    )
    op.add_column("repair_return_batches", sa.Column("period_batch_id", sa.String(36)))
    op.create_foreign_key(
        "fk_repair_return_period_batch",
        "repair_return_batches",
        "repair_period_batches",
        ["period_batch_id"],
        ["batch_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_repair_return_batches_period_batch_id", "repair_return_batches", ["period_batch_id"]
    )
    op.create_table(
        "repair_period_drafts",
        sa.Column(
            "repair_id",
            sa.String(36),
            sa.ForeignKey("repair_periods.period_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
    )
    # Only group existing source facts; no old drafts/archives are converted.
    from datetime import date

    periods = {}
    for row in (
        bind.execute(sa.text("SELECT repair_id, factory_id, return_date FROM repair_orders"))
        .mappings()
        .all()
    ):
        day = row["return_date"]
        year = day.year - (day.month == 1)
        first = 2 <= day.month <= 7
        start = date(day.year, 2, 1) if first else date(year, 8, 1)
        end = date(day.year, 7, 31) if first else date(year + 1, 1, 31)
        key = (row["factory_id"], start)
        if key not in periods:
            periods[key] = str(uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO repair_periods "
                    "(period_id, factory_id, start_date, end_date, label) "
                    "VALUES (:id, :factory, :start, :end, :label)"
                ),
                dict(
                    id=periods[key],
                    factory=key[0],
                    start=start,
                    end=end,
                    label=f"{start.year}.{start.month}-{end.year}.{end.month}",
                ),
            )
        bind.execute(
            sa.text("UPDATE repair_orders SET period_id=:period WHERE repair_id=:id"),
            dict(period=periods[key], id=row["repair_id"]),
        )


def downgrade() -> None:
    op.drop_table("repair_period_drafts")
    op.drop_constraint("fk_repair_return_period_batch", "repair_return_batches", type_="foreignkey")
    op.drop_index("ix_repair_return_batches_period_batch_id", "repair_return_batches")
    op.drop_column("repair_return_batches", "period_batch_id")
    op.drop_table("repair_period_batches")
    op.drop_constraint("fk_repair_order_period", "repair_orders", type_="foreignkey")
    op.drop_index("ix_repair_orders_period_id", "repair_orders")
    op.drop_column("repair_orders", "period_id")
    op.drop_table("repair_periods")
