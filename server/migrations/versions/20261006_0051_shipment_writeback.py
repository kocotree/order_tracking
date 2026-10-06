import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261006_0051"
down_revision = "20261006_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("shipment_writeback_control",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("history_ready", sa.Boolean, nullable=False),
        sa.Column("structure", sa.JSON, nullable=False))
    op.create_table("shipment_writeback_facts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("root_id", sa.String(36), nullable=False),
        sa.Column("event_key", sa.String(191), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", DATETIME(fsp=6), nullable=False),
        sa.Column("lines", sa.JSON, nullable=False),
        sa.UniqueConstraint("event_key", name="uq_writeback_fact_event"))
    op.create_index("ix_writeback_fact_time", "shipment_writeback_facts", ["occurred_at", "id"])
    op.create_table("shipment_writeback_stages",
        sa.Column("stage_key", sa.String(10), primary_key=True),
        sa.Column("source_scope", sa.String(191), nullable=False),
        sa.Column("since", DATETIME(fsp=6), nullable=False),
        sa.Column("until", DATETIME(fsp=6), nullable=False),
        sa.Column("excluded", sa.JSON, nullable=False))
    op.create_table("shipment_writeback_claims",
        sa.Column("root_id", sa.String(36), primary_key=True),
        sa.Column("stage_key", sa.String(10),
                  sa.ForeignKey("shipment_writeback_stages.stage_key"), nullable=False),
        sa.Column("fact_id", sa.BigInteger,
                  sa.ForeignKey("shipment_writeback_facts.id"), nullable=False))
    op.create_table("shipment_writeback_rows",
        sa.Column("stage_key", sa.String(10),
                  sa.ForeignKey("shipment_writeback_stages.stage_key"), primary_key=True),
        sa.Column("record_id", sa.String(100), primary_key=True),
        sa.Column("identity", sa.JSON, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("field_id", sa.String(100)),
        sa.Column("before_value", sa.JSON),
        sa.Column("verified", sa.Boolean, nullable=False))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM shipment_writeback_facts) "
        "OR EXISTS(SELECT 1 FROM shipment_writeback_stages) "
        "OR EXISTS(SELECT 1 FROM shipment_writeback_control WHERE JSON_LENGTH(structure) > 0)"
    )):
        raise RuntimeError("已有汇总事实或回填记录，禁止降级删除；请保留数据并核验兼容性")
    for table in ("shipment_writeback_rows", "shipment_writeback_claims",
                  "shipment_writeback_stages", "shipment_writeback_facts",
                  "shipment_writeback_control"):
        op.drop_table(table)
