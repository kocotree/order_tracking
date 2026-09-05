"""Allow unresolved factory codes without weakening nonempty uniqueness."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0028"
down_revision: str | None = "20260905_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("factories", "factory_code", existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM factories WHERE factory_code IS NULL")
    )
    if count:
        raise RuntimeError("Fill or restore all empty factory codes before downgrade")
    op.alter_column("factories", "factory_code", existing_type=sa.String(32), nullable=False)
