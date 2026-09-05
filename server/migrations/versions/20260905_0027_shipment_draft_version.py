"""Add optimistic concurrency version for shipment drafts."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0027"
down_revision: str | None = "20260904_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shipments", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("shipments", "version")
