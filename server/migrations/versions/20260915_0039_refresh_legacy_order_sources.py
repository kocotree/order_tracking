"""Refresh legacy order sources for tracker collections."""

from alembic import op

revision = "20260915_0039"
down_revision = "20260915_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The next import must reparse unchanged legacy rows with the multi-tracker rules.
    op.execute("DELETE FROM order_import_source_cursors")


def downgrade() -> None:
    pass
