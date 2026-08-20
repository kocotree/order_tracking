"""Create factory master data and user affiliation.

Revision ID: 20260820_0009
Revises: 20260820_0008
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0009"
down_revision: str | None = "20260820_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "factories",
        sa.Column("factory_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_number", sa.String(length=32), nullable=False),
        sa.Column("factory_name", sa.String(length=100), nullable=False),
        sa.Column("factory_code", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("legal_representative", sa.String(length=100), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql"),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql"),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("factory_id"),
        sa.UniqueConstraint("supplier_number", name="uq_factories_supplier_number"),
        sa.UniqueConstraint("factory_name", name="uq_factories_name"),
        sa.UniqueConstraint("factory_code", name="uq_factories_code"),
    )
    op.create_table(
        "factory_contacts",
        sa.Column("contact_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("factory_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql"),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql"),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.factory_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_id"),
        sa.UniqueConstraint("factory_id", "display_order", name="uq_factory_contacts_order"),
    )
    op.create_index("ix_factory_contacts_factory", "factory_contacts", ["factory_id"])
    op.add_column("users", sa.Column("factory_id", sa.String(length=36), nullable=True))
    op.add_column("users", sa.Column("factory_position", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "fk_users_factory_id_factories",
        "users",
        "factories",
        ["factory_id"],
        ["factory_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_users_factory_position",
        "users",
        "factory_position IS NULL OR factory_position IN ('owner', 'employee')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_factory_position", "users", type_="check")
    op.drop_constraint("fk_users_factory_id_factories", "users", type_="foreignkey")
    op.drop_column("users", "factory_position")
    op.drop_column("users", "factory_id")
    op.drop_index("ix_factory_contacts_factory", table_name="factory_contacts")
    op.drop_table("factory_contacts")
    op.drop_table("factories")
