import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20260928_0046"
down_revision = "20260924_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_variants", sa.Column("image_source_ref", sa.String(1000)))
    op.add_column("product_variants", sa.Column("image_object_key", sa.String(500)))
    op.add_column("product_variants", sa.Column(
        "image_cache_status", sa.String(32), nullable=False, server_default="missing",
    ))
    op.add_column("product_variants", sa.Column("image_cache_error", sa.String(100)))
    op.add_column("product_variants", sa.Column("image_revision", sa.String(36)))
    op.add_column("product_variants", sa.Column("image_source_modified_at", DATETIME(fsp=6)))


def downgrade() -> None:
    for name in (
        "image_source_modified_at", "image_revision", "image_cache_error",
        "image_cache_status", "image_object_key", "image_source_ref",
    ):
        op.drop_column("product_variants", name)
