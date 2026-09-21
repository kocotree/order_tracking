from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20260921_0041"
down_revision = "20260916_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_shared_authorizations",
        sa.Column("auth_id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_activity_at", DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", DATETIME(fsp=6)),
        sa.Column(
            "created_at", DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_shared_auth_user", "admin_shared_authorizations", ["user_id", "revoked_at"]
    )
    op.add_column(
        "user_sessions",
        sa.Column("shared_auth_id", sa.String(36)),
    )
    op.create_foreign_key(
        "fk_user_sessions_shared_auth", "user_sessions", "admin_shared_authorizations",
        ["shared_auth_id"], ["auth_id"], ondelete="SET NULL",
    )
    op.create_table(
        "agent_oauth_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(191), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("scope", sa.String(191), nullable=False),
        sa.Column("state", sa.String(500), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("browser_digest", sa.String(64), nullable=False),
        sa.Column("code_digest", sa.String(64), unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="SET NULL")),
        sa.Column(
            "shared_auth_id", sa.String(36),
            sa.ForeignKey("admin_shared_authorizations.auth_id", ondelete="SET NULL"),
        ),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("used_at", DATETIME(fsp=6)),
    )
    op.create_table(
        "agent_oauth_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_auth_id", sa.String(36),
            sa.ForeignKey("admin_shared_authorizations.auth_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(191), nullable=False),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("scope", sa.String(191), nullable=False),
        sa.Column(
            "created_at", DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False,
        ),
    )
    op.create_table(
        "agent_oauth_tokens",
        sa.Column("token_id", sa.String(36), primary_key=True),
        sa.Column(
            "grant_id", sa.String(36),
            sa.ForeignKey("agent_oauth_grants.grant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6)),
        sa.Column("consumed_at", DATETIME(fsp=6)),
        sa.Column("revoked_at", DATETIME(fsp=6)),
    )

    # 只关联仍能刷新的管理员会话，沿用最近一次实际活动时间。
    now = datetime.now(UTC).replace(tzinfo=None)
    connection = op.get_bind()
    active = connection.execute(
        sa.text("""
            SELECT s.user_id, MAX(s.last_activity_at) AS last_activity_at
            FROM user_sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.terminal = 'web' AND s.revoked_at IS NULL
              AND s.refresh_expires_at > :now AND u.role = 'admin' AND u.is_enabled = 1
            GROUP BY s.user_id
            HAVING MAX(s.last_activity_at) > :threshold
        """),
        {"now": now, "threshold": now - timedelta(days=30)},
    ).all()
    for user_id, last_activity_at in active:
        auth_id = str(uuid4())
        connection.execute(
            sa.text("""
                INSERT INTO admin_shared_authorizations (auth_id, user_id, last_activity_at)
                VALUES (:auth_id, :user_id, :last_activity_at)
            """),
            {"auth_id": auth_id, "user_id": user_id, "last_activity_at": last_activity_at},
        )
        connection.execute(
            sa.text("""
                UPDATE user_sessions SET shared_auth_id = :auth_id
                WHERE user_id = :user_id AND terminal = 'web' AND revoked_at IS NULL
                  AND refresh_expires_at > :now
            """),
            {"auth_id": auth_id, "user_id": user_id, "now": now},
        )


def downgrade() -> None:
    op.drop_table("agent_oauth_tokens")
    op.drop_table("agent_oauth_grants")
    op.drop_table("agent_oauth_requests")
    op.drop_constraint("fk_user_sessions_shared_auth", "user_sessions", type_="foreignkey")
    op.drop_column("user_sessions", "shared_auth_id")
    op.drop_table("admin_shared_authorizations")
