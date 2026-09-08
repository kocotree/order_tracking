"""Add per-assignment dates; preserve existing dates without subtracting days."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0031"
down_revision: str | None = "20260907_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("order_assignments", sa.Column("contract_ship_date", sa.Date(), nullable=True))
    op.execute(
        "UPDATE order_assignments a JOIN order_lines l ON l.order_line_id=a.order_line_id "
        "JOIN orders o ON o.order_id=l.order_id SET a.contract_ship_date=o.contract_ship_date"
    )
    op.alter_column("orders", "contract_ship_date", existing_type=sa.Date(), nullable=True)
    op.add_column("order_import_candidates", sa.Column("date_overrides", sa.JSON(), nullable=True))
    op.execute("UPDATE order_import_candidates SET date_overrides=JSON_OBJECT()")
    op.alter_column(
        "order_import_candidates", "date_overrides", existing_type=sa.JSON(), nullable=False
    )
    for name in ("contract_ship_date", "source_contract_ship_date"):
        op.add_column("order_import_candidate_lines", sa.Column(name, sa.Date(), nullable=True))
    op.execute(
        "UPDATE order_import_candidate_lines l JOIN order_import_candidates c "
        "ON c.candidate_id=l.candidate_id SET l.contract_ship_date=c.contract_ship_date"
    )


def downgrade() -> None:
    # A rollback must never silently discard newly entered detail dates.
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM orders WHERE contract_ship_date IS NULL")
    ):
        raise RuntimeError(
            "Restore a pre-upgrade backup before downgrading orders with detail dates"
        )
    op.alter_column("orders", "contract_ship_date", existing_type=sa.Date(), nullable=False)
    for name in ("contract_ship_date", "source_contract_ship_date"):
        op.drop_column("order_import_candidate_lines", name)
    op.drop_column("order_import_candidates", "date_overrides")
    op.drop_column("order_assignments", "contract_ship_date")
