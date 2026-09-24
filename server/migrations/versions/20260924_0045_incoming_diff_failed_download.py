import sqlalchemy as sa
from alembic import op

revision = "20260924_0045"
down_revision = "20260924_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("incoming_diff_images", "file_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column(
        "incoming_diff_images", "file_id", existing_type=sa.BigInteger(), nullable=False,
    )
