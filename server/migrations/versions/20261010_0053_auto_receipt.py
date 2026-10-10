import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20261010_0053"
down_revision = "20261009_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("first_submitted_at", mysql.DATETIME(fsp=6)))
    op.alter_column("shipment_receipts", "saved_by", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM shipment_receipts WHERE saved_by IS NULL) "
        "OR EXISTS(SELECT 1 FROM shipments WHERE first_submitted_at IS NOT NULL)"
    )):
        raise RuntimeError("已有自动收货或首次提交记录，禁止降级删除业务事实")
    op.alter_column("shipment_receipts", "saved_by", existing_type=sa.String(36), nullable=False)
    op.drop_column("shipments", "first_submitted_at")
