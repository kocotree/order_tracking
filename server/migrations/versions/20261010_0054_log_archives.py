import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20261010_0054"
down_revision = "20261010_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("order_import_runs", "background_jobs", "outbox_messages"):
        op.add_column(name, sa.Column("archived_at", mysql.DATETIME(fsp=6), nullable=True))
        op.create_index(f"ix_{name}_archive", name, ["archived_at", "created_at"])
    op.create_index("ix_audit_logs_archive", "audit_logs", ["created_at", "id"])
    op.create_index("ix_product_sync_runs_archive", "product_sync_runs", ["created_at", "run_id"])
    op.create_table(
        "log_archive_entries",
        sa.Column("source_table", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("source_created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
    )
    op.create_index("ix_log_archive_expiry", "log_archive_entries", ["status", "expires_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM log_archive_entries LIMIT 1")).first():
        raise ValueError("log_archives_require_restore_before_downgrade")
    for name in ("order_import_runs", "background_jobs", "outbox_messages"):
        if connection.execute(sa.text(
            f"SELECT 1 FROM {name} WHERE archived_at IS NOT NULL LIMIT 1"
        )).first():
            raise ValueError("archived_content_requires_restore_before_downgrade")
    op.drop_table("log_archive_entries")
    op.drop_index("ix_audit_logs_archive", table_name="audit_logs")
    op.drop_index("ix_product_sync_runs_archive", table_name="product_sync_runs")
    for name in ("order_import_runs", "background_jobs", "outbox_messages"):
        op.drop_index(f"ix_{name}_archive", table_name=name)
        op.drop_column(name, "archived_at")
