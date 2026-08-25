"""Add V1.45 initial shipped quantity baseline.

Revision ID: 20260825_0015
Revises: 20260824_0014
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0015"
down_revision: str | None = "20260824_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_assignments",
        sa.Column(
            "initial_shipped_quantity",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_order_assignments_initial_shipped_nonnegative",
        "order_assignments",
        "initial_shipped_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_order_assignments_quantity_covers_initial_shipped",
        "order_assignments",
        "assigned_quantity >= initial_shipped_quantity",
    )
    op.alter_column(
        "orders",
        "order_date",
        existing_type=sa.Date(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE orders SET order_date = DATE(created_at) WHERE order_date IS NULL")
    op.alter_column(
        "orders",
        "order_date",
        existing_type=sa.Date(),
        nullable=False,
    )
    op.drop_constraint(
        "ck_order_assignments_quantity_covers_initial_shipped",
        "order_assignments",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_assignments_initial_shipped_nonnegative",
        "order_assignments",
        type_="check",
    )
    op.drop_column("order_assignments", "initial_shipped_quantity")
