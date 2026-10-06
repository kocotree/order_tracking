import sqlalchemy as sa
from alembic import op

revision = "20261006_0050"
down_revision = "20260930_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # 旧待处理记录必须人工核对，迁移不得改变数量或删除历史。
    pending = connection.scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM shipments WHERE status = 'VOID_PENDING') "
        "OR EXISTS(SELECT 1 FROM shipment_void_requests WHERE status = 'PENDING') "
        "OR EXISTS(SELECT 1 FROM outbox_messages WHERE status <> 'completed' "
        "AND event_type IN ('shipment.void_requested', 'shipment.void_approved', "
        "'shipment.void_rejected'))"
    ))
    if pending:
        raise RuntimeError("存在历史待审核发货申请或未完成审批通知，请核对后再升级；未修改数据")
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status", "shipments",
        "status IN ('DRAFT', 'SHIPPED', 'VOIDED', 'WITHDRAWN')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status", "shipments",
        "status IN ('DRAFT', 'SHIPPED', 'VOID_PENDING', 'VOIDED', 'WITHDRAWN')",
    )
