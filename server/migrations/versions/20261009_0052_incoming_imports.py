import sqlalchemy as sa
from alembic import op

revision = "20261009_0052"
down_revision = "20261006_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_incoming_diff_batches_status", "incoming_diff_batches", type_="check")
    op.create_check_constraint("ck_incoming_diff_batches_status", "incoming_diff_batches",
        "status IN ('COLLECTING', 'RECOGNIZING', 'READY', 'CONFIRMED', 'FAILED', "
        "'VALIDATING', 'NEEDS_DECISION', 'NEEDS_SELECTION', 'SUPERSEDED')")
    op.add_column("incoming_diff_batches", sa.Column(
        "source_kind", sa.String(8), nullable=False, server_default="PHOTO"))
    op.add_column("incoming_diff_batches", sa.Column("source_message_id", sa.String(191)))
    op.add_column("incoming_diff_batches", sa.Column("source_sent_at", sa.BigInteger))
    op.add_column("incoming_diff_batches", sa.Column("attachments", sa.JSON))
    op.add_column("incoming_diff_batches", sa.Column(
        "review_revision", sa.Integer, nullable=False, server_default="0"))
    op.create_unique_constraint("uq_incoming_diff_batches_message", "incoming_diff_batches",
                                ["source_message_id"])
    op.drop_constraint("ck_incoming_diff_workbooks_direction", "incoming_diff_workbooks",
                       type_="check")
    op.create_check_constraint("ck_incoming_diff_workbooks_direction", "incoming_diff_workbooks",
                               "direction IN ('GENERATED', 'UPLOADED', 'IMPORTED')")
    op.alter_column("incoming_diff_workbooks", "file_id", existing_type=sa.BigInteger,
                    nullable=True)
    op.create_table("incoming_diff_import_files",
        sa.Column("import_file_id", sa.String(36), primary_key=True),
        sa.Column("workbook_id", sa.String(36), sa.ForeignKey(
            "incoming_diff_workbooks.workbook_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("file_id", sa.BigInteger, sa.ForeignKey(
            "stored_files.file_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.UniqueConstraint("workbook_id", "position",
                            name="uq_incoming_diff_import_file_position"))
    op.alter_column("incoming_diff_records", "image_id", existing_type=sa.String(36), nullable=True)
    op.add_column("incoming_diff_records", sa.Column("import_file_id", sa.String(36),
        sa.ForeignKey("incoming_diff_import_files.import_file_id", ondelete="RESTRICT",
                      name="fk_incoming_diff_records_import_file")))
    op.add_column("incoming_diff_records", sa.Column("source_sheet_name", sa.String(31)))
    op.add_column("incoming_diff_records", sa.Column("source_row_number", sa.Integer))
    op.create_check_constraint("ck_incoming_diff_records_source", "incoming_diff_records",
        "image_id IS NOT NULL OR (import_file_id IS NOT NULL "
        "AND source_sheet_name IS NOT NULL AND source_row_number IS NOT NULL "
        "AND source_row_number >= 2)")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS(SELECT 1 FROM incoming_diff_batches "
        "WHERE source_kind='FILE' OR review_revision > 0) "
        "OR EXISTS(SELECT 1 FROM incoming_diff_import_files)"
    )):
        raise RuntimeError("已有文件导入，禁止降级删除来源及审计")
    op.drop_constraint("ck_incoming_diff_records_source", "incoming_diff_records", type_="check")
    op.drop_constraint("fk_incoming_diff_records_import_file", "incoming_diff_records",
                       type_="foreignkey")
    for name in ("import_file_id", "source_sheet_name", "source_row_number"):
        op.drop_column("incoming_diff_records", name)
    op.alter_column("incoming_diff_records", "image_id", existing_type=sa.String(36),
                    nullable=False)
    op.drop_table("incoming_diff_import_files")
    op.alter_column("incoming_diff_workbooks", "file_id", existing_type=sa.BigInteger,
                    nullable=False)
    op.drop_constraint("ck_incoming_diff_workbooks_direction", "incoming_diff_workbooks",
                       type_="check")
    op.create_check_constraint("ck_incoming_diff_workbooks_direction", "incoming_diff_workbooks",
                               "direction IN ('GENERATED', 'UPLOADED')")
    op.drop_constraint("uq_incoming_diff_batches_message", "incoming_diff_batches", type_="unique")
    for name in ("source_kind", "source_message_id", "source_sent_at", "attachments",
                 "review_revision"):
        op.drop_column("incoming_diff_batches", name)
    op.drop_constraint("ck_incoming_diff_batches_status", "incoming_diff_batches", type_="check")
    op.create_check_constraint("ck_incoming_diff_batches_status", "incoming_diff_batches",
        "status IN ('COLLECTING', 'RECOGNIZING', 'READY', 'CONFIRMED', 'FAILED')")
