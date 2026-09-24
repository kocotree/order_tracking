"""Allow new incoming differences without an image business date."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0044"
down_revision: str | None = "20260923_0043"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "incoming_diff_records", "source_business_date",
        existing_type=sa.Date(), existing_nullable=False, nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "incoming_diff_records", "source_business_date",
        existing_type=sa.Date(), existing_nullable=True, nullable=False,
    )
