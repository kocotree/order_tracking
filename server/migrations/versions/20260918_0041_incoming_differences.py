"""Create incoming-difference batches, images, workbooks, records and adjustments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260918_0041"
down_revision: str | None = "20260916_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incoming_diff_batches",
        sa.Column("batch_id", sa.String(36), primary_key=True),
        sa.Column("batch_no", sa.String(32), nullable=False),
        sa.Column(
            "submitter_id",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("feishu_chat_id", sa.String(64)),
        sa.Column("feishu_open_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recognition_error_code", sa.String(64)),
        sa.Column("recognition_error_summary", sa.String(500)),
        sa.Column("current_workbook_id", sa.String(36)),
        sa.Column(
            "confirmed_by", sa.String(36), sa.ForeignKey("users.user_id", ondelete="RESTRICT")
        ),
        sa.Column("confirmed_at", mysql.DATETIME(fsp=6)),
        sa.Column("confirmed_record_count", sa.Integer()),
        sa.Column("confirmed_factory_count", sa.Integer()),
        sa.Column("frozen_at", mysql.DATETIME(fsp=6)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("batch_no", name="uq_incoming_diff_batches_no"),
        sa.CheckConstraint(
            "status IN ('COLLECTING', 'RECOGNIZING', 'READY', 'CONFIRMED', 'FAILED')",
            name="ck_incoming_diff_batches_status",
        ),
    )
    op.create_index(
        "ix_incoming_diff_batches_status", "incoming_diff_batches", ["status", "created_at"]
    )
    op.create_table(
        "incoming_diff_images",
        sa.Column("image_id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_batches.batch_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("feishu_message_id", sa.String(64)),
        sa.Column("feishu_image_key", sa.String(191), nullable=False),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("stored_files.file_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("ocr_status", sa.String(16), nullable=False),
        sa.Column("recognition_payload", sa.JSON()),
        sa.Column("recognition_model", sa.String(100)),
        sa.Column("recognition_finished_at", mysql.DATETIME(fsp=6)),
        sa.Column("failure_reason", sa.String(500)),
        sa.Column(
            "duplicate_of_batch_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_batches.batch_id", ondelete="RESTRICT"),
        ),
        sa.Column("duplicate_ack_at", mysql.DATETIME(fsp=6)),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint(
            "batch_id", "feishu_image_key", name="uq_incoming_diff_images_source"
        ),
        sa.CheckConstraint(
            "ocr_status IN ('PENDING', 'SUCCEEDED', 'FAILED')",
            name="ck_incoming_diff_images_ocr_status",
        ),
    )
    op.create_index(
        "ix_incoming_diff_images_batch", "incoming_diff_images", ["batch_id", "sort_order"]
    )
    op.create_index("ix_incoming_diff_images_sha", "incoming_diff_images", ["content_sha256"])
    op.create_table(
        "incoming_diff_workbooks",
        sa.Column("workbook_id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_batches.batch_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("stored_files.file_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(128)),
        sa.Column("line_snapshot", sa.JSON(), nullable=False),
        sa.Column("validation_issues", sa.JSON()),
        sa.Column(
            "submitted_by",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("batch_id", "version", name="uq_incoming_diff_workbooks_version"),
        sa.CheckConstraint(
            "direction IN ('GENERATED', 'UPLOADED')",
            name="ck_incoming_diff_workbooks_direction",
        ),
    )
    op.create_foreign_key(
        "fk_incoming_diff_batches_current_workbook",
        "incoming_diff_batches",
        "incoming_diff_workbooks",
        ["current_workbook_id"],
        ["workbook_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "incoming_diff_records",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_batches.batch_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workbook_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_workbooks.workbook_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "image_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_images.image_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.String(36),
            sa.ForeignKey("orders.order_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "detail_id",
            sa.String(36),
            sa.ForeignKey("order_details.detail_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_assignment_id",
            sa.BigInteger(),
            sa.ForeignKey("order_assignments.order_assignment_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.String(36),
            sa.ForeignKey("product_variants.variant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purchase_order_id", sa.String(191), nullable=False),
        sa.Column("purchase_order_item_id", sa.String(191), nullable=False),
        sa.Column(
            "shipment_id",
            sa.String(36),
            sa.ForeignKey("shipments.shipment_id", ondelete="RESTRICT"),
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("initial_quantity", sa.Integer(), nullable=False),
        sa.Column("source_business_date", sa.Date(), nullable=False),
        sa.Column("product_code_snapshot", sa.String(100), nullable=False),
        sa.Column("product_name_snapshot", sa.String(255), nullable=False),
        sa.Column("spec_snapshot", sa.String(255), nullable=False),
        sa.Column("registered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "registered_by",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("quantity <> 0", name="ck_incoming_diff_records_quantity_nonzero"),
    )
    op.create_index(
        "ix_incoming_diff_records_order",
        "incoming_diff_records",
        ["order_id", "registered_at", "record_id"],
    )
    op.create_index(
        "ix_incoming_diff_records_assignment", "incoming_diff_records", ["order_assignment_id"]
    )
    op.create_index("ix_incoming_diff_records_batch", "incoming_diff_records", ["batch_id"])
    op.create_table(
        "incoming_diff_adjustments",
        sa.Column("adjustment_id", sa.String(36), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(36),
            sa.ForeignKey("incoming_diff_records.record_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("before_quantity", sa.Integer(), nullable=False),
        sa.Column("after_quantity", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("delta <> 0", name="ck_incoming_diff_adjustments_delta_nonzero"),
    )
    op.create_index(
        "ix_incoming_diff_adjustments_record",
        "incoming_diff_adjustments",
        ["record_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("incoming_diff_adjustments")
    op.drop_table("incoming_diff_records")
    op.drop_constraint(
        "fk_incoming_diff_batches_current_workbook", "incoming_diff_batches", type_="foreignkey"
    )
    op.drop_table("incoming_diff_workbooks")
    op.drop_table("incoming_diff_images")
    op.drop_table("incoming_diff_batches")
