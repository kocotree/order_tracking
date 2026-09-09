"""Keep separate edit and historical contents for a stable shipment number."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0032"
down_revision: str | None = "20260908_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("source_shipment_id", sa.String(36), nullable=True))
    op.create_index("ix_shipments_source_shipment_id", "shipments", ["source_shipment_id"])
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status",
        "shipments",
        "status IN ('DRAFT', 'SHIPPED', 'VOID_PENDING', 'VOIDED', 'WITHDRAWN')",
    )
    op.create_index("ix_shipment_files_stored_file", "shipment_files", ["stored_file_id"])
    op.drop_constraint("uq_shipment_files_stored_file", "shipment_files", type_="unique")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM shipments WHERE source_shipment_id IS NOT NULL "
            "OR status = 'WITHDRAWN'"
        )
    ):
        raise RuntimeError("Withdraw history exists; restore a verified backup before downgrade")
    op.create_unique_constraint(
        "uq_shipment_files_stored_file", "shipment_files", ["stored_file_id"]
    )
    op.drop_index("ix_shipment_files_stored_file", "shipment_files")
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status",
        "shipments",
        "status IN ('DRAFT', 'SHIPPED', 'VOID_PENDING', 'VOIDED')",
    )
    op.drop_index("ix_shipments_source_shipment_id", "shipments")
    op.drop_column("shipments", "source_shipment_id")
