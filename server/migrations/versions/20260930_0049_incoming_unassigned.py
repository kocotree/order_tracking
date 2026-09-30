import sqlalchemy as sa
from alembic import op

revision = "20260930_0049"
down_revision = "20260929_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quantity_ledger", sa.Column("order_detail_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_quantity_ledger_detail", "quantity_ledger", "order_details",
                          ["order_detail_id"], ["detail_id"], ondelete="RESTRICT")
    op.alter_column("quantity_ledger", "order_assignment_id", existing_type=sa.BigInteger(),
                    nullable=True)
    op.create_check_constraint("ck_quantity_ledger_owner", "quantity_ledger",
                               "(order_assignment_id IS NULL) <> (order_detail_id IS NULL)")
    op.create_unique_constraint("uq_quantity_ledger_detail_source", "quantity_ledger",
                                ["source_type", "source_id", "order_detail_id"])
    op.create_index("ix_quantity_ledger_detail", "quantity_ledger", ["order_detail_id"])
    op.alter_column("incoming_diff_records", "order_assignment_id",
                    existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM quantity_ledger WHERE order_detail_id IS NOT NULL) "
        "OR EXISTS(SELECT 1 FROM incoming_diff_records WHERE order_assignment_id IS NULL)"
    )):
        raise RuntimeError("存在未派工数量记录，禁止删除明细关联")
    op.alter_column("incoming_diff_records", "order_assignment_id",
                    existing_type=sa.BigInteger(), nullable=False)
    op.drop_constraint("ck_quantity_ledger_owner", "quantity_ledger", type_="check")
    op.drop_constraint("uq_quantity_ledger_detail_source", "quantity_ledger", type_="unique")
    op.drop_constraint("fk_quantity_ledger_detail", "quantity_ledger", type_="foreignkey")
    op.drop_index("ix_quantity_ledger_detail", table_name="quantity_ledger")
    op.drop_column("quantity_ledger", "order_detail_id")
    op.alter_column("quantity_ledger", "order_assignment_id", existing_type=sa.BigInteger(),
                    nullable=False)
