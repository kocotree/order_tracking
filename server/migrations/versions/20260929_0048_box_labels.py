import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20260929_0048"
down_revision = "20260928_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "box_label_exports",
        sa.Column("export_id", sa.String(36), primary_key=True),
        sa.Column(
            "order_id", sa.String(36),
            sa.ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("group_id", sa.String(64), nullable=False),
        sa.Column(
            "factory_id", sa.String(36),
            sa.ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "product_id", sa.String(36),
            sa.ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("color", sa.String(255), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column(
            "stored_file_id", sa.BigInteger(),
            sa.ForeignKey("stored_files.file_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("order_id", "group_id", name="uq_box_label_order_group"),
    )


def downgrade() -> None:
    op.drop_table("box_label_exports")
