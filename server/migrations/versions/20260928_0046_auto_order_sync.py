import sqlalchemy as sa
from alembic import op

revision = "20260928_0046"
down_revision = "20260924_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("order_import_runs", "requested_by", existing_type=sa.String(36), nullable=True)
    op.add_column("order_import_runs", sa.Column("sync_result", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE order_import_runs SET sync_result = JSON_OBJECT()"))
    op.alter_column("order_import_runs", "sync_result", existing_type=sa.JSON(), nullable=False)
    for column in ("created_by", "updated_by"):
        op.alter_column("orders", column, existing_type=sa.String(36), nullable=True)
    op.add_column(
        "order_details",
        sa.Column("auto_dispatch_paused", sa.Boolean(), nullable=False, server_default="0"),
    )
    # 失效派工反向关联或历史发布时间区分撤回与从未派工的旧草稿。
    op.execute(sa.text("""
        UPDATE order_details d
        SET d.auto_dispatch_paused = 1
        WHERE d.dispatch_state = 'UNASSIGNED'
          AND EXISTS (
            SELECT 1 FROM order_assignments a
            WHERE a.is_active = 0
              AND (a.detail_id = d.detail_id OR a.order_assignment_id = d.assignment_id)
              AND (a.detail_id IS NOT NULL OR EXISTS (
                SELECT 1 FROM orders o
                WHERE o.order_id = d.order_id AND o.published_at IS NOT NULL
              ))
          )
    """))
    op.execute(sa.text("""
        UPDATE orders o SET o.detail_mode = 1
        WHERE o.source = 'feishu' AND EXISTS (
            SELECT 1 FROM order_details d WHERE d.order_id = o.order_id
        )
    """))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("""
        SELECT EXISTS(SELECT 1 FROM orders WHERE created_by IS NULL OR updated_by IS NULL)
            OR EXISTS(SELECT 1 FROM order_import_runs WHERE requested_by IS NULL)
    """)):
        raise RuntimeError("存在系统执行记录，须先明确数据恢复方案，拒绝有损降级")
    op.drop_column("order_import_runs", "sync_result")
    op.alter_column(
        "order_import_runs", "requested_by", existing_type=sa.String(36), nullable=False
    )
    # 系统创建的订单需要先明确人工归属，禁止降级时静默伪造操作人。
    for column in ("created_by", "updated_by"):
        op.alter_column("orders", column, existing_type=sa.String(36), nullable=False)
    op.drop_column("order_details", "auto_dispatch_paused")
