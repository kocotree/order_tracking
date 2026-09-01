from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "is_super_admin = 0 OR role = 'admin'",
            name="ck_users_super_admin_role",
        ),
        CheckConstraint(
            "factory_position IS NULL OR factory_position IN ('owner', 'employee')",
            name="ck_users_factory_position",
        ),
        UniqueConstraint("phone_digest", name="uq_users_phone_digest"),
    )

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(32))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    feishu_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    feishu_avatar_url: Mapped[str | None] = mapped_column(String(500))
    mini_avatar_external_url: Mapped[str | None] = mapped_column(String(500))
    phone_encrypted: Mapped[str | None] = mapped_column(Text)
    phone_digest: Mapped[str | None] = mapped_column(String(64))
    phone_masked: Mapped[str | None] = mapped_column(String(32))
    factory_id: Mapped[str | None] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT", use_alter=True)
    )
    factory_position: Mapped[str | None] = mapped_column(String(32))
    mini_avatar_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("stored_files.file_id", ondelete="SET NULL", use_alter=True)
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "scope",
            "platform_subject",
            name="uq_external_identity_scope_subject",
        ),
        Index("ix_external_identities_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(191), nullable=False)
    platform_subject: Mapped[str] = mapped_column(String(191), nullable=False)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    bound_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = (UniqueConstraint("state_digest", name="uq_oauth_states_digest"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal: Mapped[str] = mapped_column(String(32), nullable=False)
    return_to: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_user_sessions_token_digest"),
        UniqueConstraint("refresh_token_digest", name="uq_user_sessions_refresh_digest"),
        Index("ix_user_sessions_user_terminal", "user_id", "terminal", "revoked_at"),
    )

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    terminal: Mapped[str] = mapped_column(String(32), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_token_digest: Mapped[str | None] = mapped_column(String(64))
    csrf_digest: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_activity_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class SmsChallenge(Base):
    __tablename__ = "sms_challenges"
    __table_args__ = (
        Index("ix_sms_challenges_user_purpose_created", "user_id", "purpose", "created_at"),
    )

    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    phone_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    phone_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    send_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    invalidated_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class AdminApplication(Base):
    __tablename__ = "admin_applications"
    __table_args__ = (
        UniqueConstraint("pending_user_id", name="uq_admin_applications_pending_user"),
        Index("ix_admin_applications_status_submitted", "status", "submitted_at"),
    )

    application_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    pending_user_id: Mapped[str | None] = mapped_column(String(36))
    feishu_display_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    feishu_avatar_url_snapshot: Mapped[str | None] = mapped_column(String(500))
    phone_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    phone_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    previous_application_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_applications.application_id", ondelete="RESTRICT")
    )


class Factory(Base):
    __tablename__ = "factories"
    __table_args__ = (
        UniqueConstraint("supplier_number", name="uq_factories_supplier_number"),
        UniqueConstraint("factory_name", name="uq_factories_name"),
        UniqueConstraint("factory_code", name="uq_factories_code"),
    )

    factory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_number: Mapped[str] = mapped_column(String(32), nullable=False)
    factory_name: Mapped[str] = mapped_column(String(100), nullable=False)
    factory_code: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))
    legal_representative: Mapped[str | None] = mapped_column(String(100))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class FactoryContact(Base):
    __tablename__ = "factory_contacts"
    __table_args__ = (
        UniqueConstraint("factory_id", "display_order", name="uq_factory_contacts_order"),
        Index("ix_factory_contacts_factory", "factory_id"),
    )

    contact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class FactoryApplication(Base):
    __tablename__ = "factory_applications"
    __table_args__ = (
        UniqueConstraint("pending_user_id", name="uq_factory_applications_pending_user"),
        Index("ix_factory_applications_status_submitted", "status", "submitted_at"),
    )

    application_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    pending_user_id: Mapped[str | None] = mapped_column(String(36))
    real_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    phone_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False
    )
    bound_factory_id: Mapped[str | None] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    previous_application_id: Mapped[str | None] = mapped_column(
        ForeignKey("factory_applications.application_id", ondelete="RESTRICT")
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("source_i_id", name="uq_products_source_i_id"),)

    product_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_i_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    image_source_ref: Mapped[str | None] = mapped_column(String(1000))
    image_object_key: Mapped[str | None] = mapped_column(String(500))
    image_cache_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="missing"
    )
    image_cache_error: Mapped[str | None] = mapped_column(String(100))
    source_modified_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    first_synced_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("source_sku_id", name="uq_product_variants_source_sku_id"),
        Index("ix_product_variants_product_id", "product_id"),
        Index("ix_product_variants_available", "is_available", "variant_id"),
    )

    variant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False
    )
    source_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    properties_value: Mapped[str] = mapped_column(String(255), nullable=False)
    source_category: Mapped[str | None] = mapped_column(String(100))
    source_enabled: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    source_modified_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    first_synced_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class ProductSyncRun(Base):
    __tablename__ = "product_sync_runs"
    __table_args__ = (
        UniqueConstraint("active_key", name="uq_product_sync_runs_active_key"),
        Index("ix_product_sync_runs_success", "status", "finished_at"),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(64))
    start_cursor: Mapped[str | None] = mapped_column(String(255))
    candidate_cursor: Mapped[str | None] = mapped_column(String(255))
    success_cursor: Mapped[str | None] = mapped_column(String(255))
    source_checkpoint: Mapped[str | None] = mapped_column(Text)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0"
    )
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pages_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    included_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ignored_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    disabled_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    moved_out_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    image_jobs_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class ProductSyncStagedVariant(Base):
    __tablename__ = "product_sync_staged_variants"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_sku_id",
            name="uq_product_sync_staged_run_sku",
        ),
        Index("ix_product_sync_staged_run", "run_id", "staged_id"),
    )

    staged_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("product_sync_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    source_i_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    properties_value: Mapped[str | None] = mapped_column(String(255))
    pic: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[str | None] = mapped_column(String(100))
    enabled: Mapped[int | None] = mapped_column(Integer)
    source_modified_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class OrderImportRun(Base):
    __tablename__ = "order_import_runs"
    __table_args__ = (
        UniqueConstraint("active_key", name="uq_order_import_runs_active_key"),
        UniqueConstraint("idempotency_key", name="uq_order_import_runs_idempotency_key"),
        Index("ix_order_import_runs_latest", "started_at", "run_id"),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(191))
    pages_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    candidates_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    candidates_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class OrderImportSourceRecord(Base):
    __tablename__ = "order_import_source_records"
    __table_args__ = (
        UniqueConstraint("source_scope", "source_record_id", name="uq_import_source_record"),
        Index("ix_import_source_records_order", "order_no", "source_record_id"),
    )

    source_record_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_scope: Mapped[str] = mapped_column(String(191), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_detail_id: Mapped[str | None] = mapped_column(String(100))
    order_no: Mapped[str | None] = mapped_column(String(100))
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(255))
    first_seen_run_id: Mapped[str] = mapped_column(
        ForeignKey("order_import_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    last_seen_run_id: Mapped[str] = mapped_column(
        ForeignKey("order_import_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class OrderImportCandidate(Base):
    __tablename__ = "order_import_candidates"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_order_import_candidates_order_no"),
        Index("ix_order_import_candidates_list", "status", "validation_state", "updated_at"),
    )

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_no: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_issues: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    order_date: Mapped[date | None] = mapped_column(Date)
    tracker: Mapped[str | None] = mapped_column(String(32))
    contract_ship_date: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str | None] = mapped_column(String(100))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    shipped_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    imported_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.order_id", ondelete="RESTRICT")
    )
    imported_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    imported_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    excluded_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    excluded_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class OrderImportCandidateLine(Base):
    __tablename__ = "order_import_candidate_lines"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "source_record_pk", name="uq_import_candidate_line_source"
        ),
        Index("ix_import_candidate_lines_candidate", "candidate_id", "candidate_line_id"),
    )

    candidate_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("order_import_candidates.candidate_id", ondelete="CASCADE"), nullable=False
    )
    source_record_pk: Mapped[int] = mapped_column(
        ForeignKey("order_import_source_records.source_record_pk", ondelete="RESTRICT"),
        nullable=False,
    )
    source_sku_id: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(String(255))
    properties_value: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    factory_name: Mapped[str | None] = mapped_column(String(100))
    order_quantity: Mapped[int | None] = mapped_column(Integer)
    shipped_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matched_variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_variants.variant_id", ondelete="RESTRICT")
    )
    matched_factory_id: Mapped[str | None] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT")
    )
    image_object_key_snapshot: Mapped[str | None] = mapped_column(String(500))
    validation_issues: Mapped[list[Any]] = mapped_column(JSON, nullable=False)


class OrderImportValidationIssue(Base):
    __tablename__ = "order_import_validation_issues"
    __table_args__ = (Index("ix_import_validation_issues_candidate", "candidate_id", "sort_order"),)

    issue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("order_import_candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_import_candidate_lines.candidate_line_id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_orders_order_no"),
        CheckConstraint("source IN ('manual', 'feishu')", name="ck_orders_source"),
        CheckConstraint(
            "lifecycle IN ('DRAFT', 'PUBLISHED', 'COMPLETED')",
            name="ck_orders_lifecycle",
        ),
        Index("ix_orders_visible_status", "deleted_at", "lifecycle", "contract_ship_date"),
    )

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_no: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date)
    tracker: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    published_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    published_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    completed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "product_variant_id", name="uq_order_lines_variant"),
        CheckConstraint("order_quantity > 0", name="ck_order_lines_quantity_positive"),
        Index("ix_order_lines_order", "order_id", "order_line_id"),
    )

    order_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[str] = mapped_column(
        ForeignKey("product_variants.variant_id", ondelete="RESTRICT"), nullable=False
    )
    order_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_id_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    properties_value_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    category_snapshot: Mapped[str | None] = mapped_column(String(100))
    image_object_key_snapshot: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class OrderAssignment(Base):
    __tablename__ = "order_assignments"
    __table_args__ = (
        UniqueConstraint("order_line_id", "factory_id", name="uq_order_assignments_line_factory"),
        CheckConstraint("assigned_quantity > 0", name="ck_order_assignments_quantity_positive"),
        CheckConstraint(
            "initial_shipped_quantity >= 0",
            name="ck_order_assignments_initial_shipped_nonnegative",
        ),
        CheckConstraint(
            "assigned_quantity >= initial_shipped_quantity",
            name="ck_order_assignments_quantity_covers_initial_shipped",
        ),
        Index("ix_order_assignments_factory", "factory_id", "order_line_id"),
    )

    order_assignment_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("order_lines.order_line_id", ondelete="RESTRICT"), nullable=False
    )
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False
    )
    assigned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_shipped_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    factory_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class OrderCompletionRecord(Base):
    __tablename__ = "order_completion_records"
    __table_args__ = (
        CheckConstraint("action IN ('COMPLETE', 'REOPEN')", name="ck_order_completion_action"),
        Index("ix_order_completion_order", "order_id", "record_id"),
    )

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    source_terminal: Mapped[str] = mapped_column(String(32), nullable=False)
    before_lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    after_lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class ProcessingContract(Base):
    __tablename__ = "processing_contracts"
    __table_args__ = (
        UniqueConstraint("order_id", "factory_id", name="uq_processing_contract_order_factory"),
        UniqueConstraint("contract_no", name="uq_processing_contract_no"),
        UniqueConstraint(
            "signing_date",
            "factory_id",
            "daily_sequence",
            name="uq_processing_contract_daily_sequence",
        ),
        Index("ix_processing_contract_order", "order_id", "factory_id"),
    )

    contract_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False
    )
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False
    )
    signing_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_no: Mapped[str] = mapped_column(String(191), nullable=False)
    contract_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class ContractNumberCounter(Base):
    __tablename__ = "contract_number_counters"

    signing_date: Mapped[date] = mapped_column(Date, primary_key=True)
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), primary_key=True
    )
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class ContractExport(Base):
    __tablename__ = "contract_exports"
    __table_args__ = (
        UniqueConstraint(
            "exported_by",
            "idempotency_key",
            name="uq_contract_export_actor_idempotency",
        ),
        Index("ix_contract_exports_contract", "contract_id", "created_at"),
    )

    export_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("processing_contracts.contract_id", ondelete="RESTRICT"), nullable=False
    )
    exported_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    export_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    stored_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("stored_files.file_id", ondelete="RESTRICT", use_alter=True)
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("shipment_no", name="uq_shipments_no"),
        UniqueConstraint("active_draft_owner_id", name="uq_shipments_active_draft_owner"),
        CheckConstraint(
            "status IN ('DRAFT', 'SHIPPED', 'VOID_PENDING', 'VOIDED')",
            name="ck_shipments_status",
        ),
        Index("ix_shipments_factory_status", "factory_id", "status", "created_at"),
    )

    shipment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shipment_no: Mapped[str | None] = mapped_column(String(32))
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    business_date: Mapped[date | None] = mapped_column(Date)
    preferred_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.order_id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    active_draft_owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    submitted_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class ShipmentBox(Base):
    __tablename__ = "shipment_boxes"
    __table_args__ = (
        UniqueConstraint("shipment_id", "box_no", name="uq_shipment_boxes_no"),
        CheckConstraint("box_no > 0", name="ck_shipment_boxes_no_positive"),
    )

    box_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False
    )
    box_no: Mapped[int] = mapped_column(Integer, nullable=False)
    group_key: Mapped[str | None] = mapped_column(String(36))


class ShipmentBoxItem(Base):
    __tablename__ = "shipment_box_items"
    __table_args__ = (
        UniqueConstraint("box_id", "order_assignment_id", name="uq_shipment_box_items_line"),
        CheckConstraint("quantity > 0", name="ck_shipment_box_items_quantity_positive"),
    )

    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    box_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_boxes.box_id", ondelete="CASCADE"), nullable=False
    )
    order_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("order_assignments.order_assignment_id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class ShipmentLine(Base):
    __tablename__ = "shipment_lines"
    __table_args__ = (
        UniqueConstraint("shipment_id", "order_assignment_id", name="uq_shipment_lines_assignment"),
        CheckConstraint("quantity > 0", name="ck_shipment_lines_quantity_positive"),
    )

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.shipment_id", ondelete="RESTRICT"), nullable=False
    )
    order_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("order_assignments.order_assignment_id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_no_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    sku_id_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    properties_value_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)


class ShipmentVoidRequest(Base):
    __tablename__ = "shipment_void_requests"
    __table_args__ = (
        UniqueConstraint(
            "requested_by",
            "idempotency_key",
            name="uq_shipment_void_request_actor_idempotency",
        ),
        UniqueConstraint("active_shipment_id", name="uq_shipment_void_request_active"),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_shipment_void_requests_status",
        ),
        Index("ix_shipment_void_requests_shipment", "shipment_id", "created_at"),
    )

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.shipment_id", ondelete="RESTRICT"), nullable=False
    )
    active_shipment_id: Mapped[str | None] = mapped_column(
        ForeignKey("shipments.shipment_id", ondelete="RESTRICT")
    )
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    review_comment: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class ShipmentReturnEvent(Base):
    __tablename__ = "shipment_return_events"
    __table_args__ = (
        UniqueConstraint(
            "returned_by",
            "idempotency_key",
            name="uq_shipment_return_actor_idempotency",
        ),
        Index("ix_shipment_return_events_shipment", "shipment_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.shipment_id", ondelete="RESTRICT"), nullable=False
    )
    returned_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class ShipmentReturnLine(Base):
    __tablename__ = "shipment_return_lines"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "shipment_line_id", name="uq_shipment_return_lines_event_line"
        ),
        CheckConstraint("quantity > 0", name="ck_shipment_return_lines_quantity_positive"),
        Index("ix_shipment_return_lines_shipment_line", "shipment_line_id"),
    )

    return_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("shipment_return_events.event_id", ondelete="RESTRICT"), nullable=False
    )
    shipment_line_id: Mapped[int] = mapped_column(
        ForeignKey("shipment_lines.line_id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    before_shipped_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    after_shipped_quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class QuantityLedger(Base):
    __tablename__ = "quantity_ledger"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "order_assignment_id", name="uq_quantity_ledger_source"
        ),
        CheckConstraint("quantity_delta <> 0", name="ck_quantity_ledger_nonzero"),
        Index("ix_quantity_ledger_assignment", "order_assignment_id", "created_at"),
    )

    ledger_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("order_assignments.order_assignment_id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class ShipmentNumberCounter(Base):
    __tablename__ = "shipment_number_counters"

    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class MiniLoginAttempt(Base):
    __tablename__ = "mini_login_attempts"
    __table_args__ = (UniqueConstraint("token_digest", name="uq_mini_login_attempt_token"),)

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(191), nullable=False)
    platform_subject: Mapped[str] = mapped_column(String(191), nullable=False)
    wechat_avatar_url: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class StoredFile(Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_stored_files_object"),
        UniqueConstraint("uploaded_by", "idempotency_key", name="uq_stored_files_upload_request"),
    )

    file_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(191), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(191))
    replaced_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairPreview(Base):
    __tablename__ = "repair_previews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'INVALID', 'CONFIRMED')",
            name="ck_repair_previews_status",
        ),
        Index("ix_repair_previews_expiry", "status", "expires_at"),
        Index("ix_repair_previews_source_sha256", "source_sha256"),
    )

    preview_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    original_file_id: Mapped[int] = mapped_column(
        ForeignKey("stored_files.file_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    factory_id: Mapped[str | None] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT")
    )
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    box_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    confirmed_repair_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class RepairPreviewLine(Base):
    __tablename__ = "repair_preview_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_repair_preview_lines_quantity_positive"),
        UniqueConstraint("preview_id", "source_order", name="uq_repair_preview_lines_order"),
        UniqueConstraint(
            "preview_id",
            "source_sheet",
            "source_row",
            name="uq_repair_preview_lines_source_row",
        ),
        Index("ix_repair_preview_lines_preview", "preview_id", "source_order"),
    )

    line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    preview_id: Mapped[str] = mapped_column(
        ForeignKey("repair_previews.preview_id", ondelete="CASCADE"), nullable=False
    )
    source_sheet: Mapped[str] = mapped_column(String(100), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    box_number: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_number: Mapped[str] = mapped_column(String(32), nullable=False)
    factory_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    properties_value: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    matched_product_id: Mapped[str | None] = mapped_column(
        ForeignKey("products.product_id", ondelete="RESTRICT")
    )
    matched_variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_variants.variant_id", ondelete="RESTRICT")
    )
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairOrder(Base):
    __tablename__ = "repair_orders"
    __table_args__ = (
        CheckConstraint("status IN ('INCOMPLETE', 'COMPLETED')", name="ck_repair_orders_status"),
        CheckConstraint(
            "warehouse_return_quantity > 0", name="ck_repair_orders_warehouse_positive"
        ),
        CheckConstraint(
            "repaired_quantity >= 0 AND scrapped_quantity >= 0 AND returned_quantity >= 0",
            name="ck_repair_orders_return_counts_nonnegative",
        ),
        CheckConstraint(
            "returned_quantity = repaired_quantity + scrapped_quantity",
            name="ck_repair_orders_return_sum",
        ),
        CheckConstraint(
            "returned_quantity <= warehouse_return_quantity",
            name="ck_repair_orders_return_not_exceeded",
        ),
        UniqueConstraint("repair_no", name="uq_repair_orders_no"),
        UniqueConstraint("source_sha256", name="uq_repair_orders_source_sha256"),
        Index("ix_repair_orders_list", "status", "return_date", "repair_id"),
        Index("ix_repair_orders_factory", "factory_id", "status", "return_date"),
    )

    repair_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repair_no: Mapped[str] = mapped_column(String(32), nullable=False)
    factory_id: Mapped[str] = mapped_column(
        ForeignKey("factories.factory_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    warehouse_return_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    repaired_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    scrapped_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    returned_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    original_file_id: Mapped[int] = mapped_column(
        ForeignKey("stored_files.file_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    archived_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairInspectionLine(Base):
    __tablename__ = "repair_inspection_lines"
    __table_args__ = (
        CheckConstraint(
            "warehouse_return_quantity > 0",
            name="ck_repair_inspection_lines_quantity_positive",
        ),
        UniqueConstraint("repair_id", "source_order", name="uq_repair_inspection_lines_order"),
        UniqueConstraint(
            "repair_id", "source_sheet", "source_row", name="uq_repair_inspection_lines_source_row"
        ),
        Index("ix_repair_inspection_lines_repair", "repair_id", "source_order"),
    )

    inspection_line_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    repair_id: Mapped[str] = mapped_column(
        ForeignKey("repair_orders.repair_id", ondelete="RESTRICT"), nullable=False
    )
    source_sheet: Mapped[str] = mapped_column(String(100), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    box_number: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[str] = mapped_column(
        ForeignKey("product_variants.variant_id", ondelete="RESTRICT"), nullable=False
    )
    source_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    properties_value: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_return_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairReturnBatch(Base):
    __tablename__ = "repair_return_batches"
    __table_args__ = (
        UniqueConstraint(
            "submitted_by",
            "idempotency_key",
            name="uq_repair_return_batches_submitter_key",
        ),
        Index(
            "ix_repair_return_batches_repair",
            "repair_id",
            "submitted_at",
            "batch_id",
        ),
    )

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repair_id: Mapped[str] = mapped_column(
        ForeignKey("repair_orders.repair_id", ondelete="RESTRICT"), nullable=False
    )
    submitted_by: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairReturnLine(Base):
    __tablename__ = "repair_return_lines"
    __table_args__ = (
        CheckConstraint(
            "repaired_quantity >= 0 AND scrapped_quantity >= 0",
            name="ck_repair_return_lines_nonnegative",
        ),
        CheckConstraint(
            "repaired_quantity + scrapped_quantity > 0",
            name="ck_repair_return_lines_positive_total",
        ),
        UniqueConstraint("batch_id", "line_order", name="uq_repair_return_lines_order"),
        UniqueConstraint("batch_id", "variant_id", name="uq_repair_return_lines_variant"),
        Index("ix_repair_return_lines_batch", "batch_id", "line_order"),
    )

    return_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("repair_return_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    line_order: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_id: Mapped[str] = mapped_column(
        ForeignKey("product_variants.variant_id", ondelete="RESTRICT"), nullable=False
    )
    repaired_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    scrapped_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RepairNumberCounter(Base):
    __tablename__ = "repair_number_counters"
    __table_args__ = (
        CheckConstraint("next_sequence > 0", name="ck_repair_number_counters_positive"),
    )

    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="in_progress")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "dedupe_key", name="uq_background_job_type_dedupe"),
        Index("ix_background_jobs_claim", "status", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_dedupe_key"),
        Index(
            "ix_outbox_messages_claim", "message_kind", "status", "available_at", "id"
        ),
        Index("ix_outbox_messages_recipient", "recipient_id", "channel", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    message_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="business_event"
    )
    channel: Mapped[str | None] = mapped_column(String(32))
    recipient_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_summary: Mapped[str | None] = mapped_column(String(500))
    failed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0"
    )
    alert_status: Mapped[str | None] = mapped_column(String(32))
    alert_error_code: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class NotificationAuthorization(Base):
    __tablename__ = "notification_authorizations"
    __table_args__ = (
        CheckConstraint(
            "result IN ('accepted', 'rejected', 'closed')",
            name="ck_notification_authorizations_result",
        ),
        Index(
            "ix_notification_authorizations_available",
            "user_id",
            "template_key",
            "result",
            "consumed_at",
            "authorization_id",
        ),
    )

    authorization_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_id", "dedupe_key", name="uq_notifications_recipient_dedupe"
        ),
        Index(
            "ix_notifications_recipient_created",
            "recipient_id",
            "created_at",
            "notification_id",
        ),
        Index(
            "ix_notifications_recipient_unread",
            "recipient_id",
            "read_at",
            "created_at",
            "notification_id",
        ),
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(191), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    target_path: Mapped[str] = mapped_column(String(500), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_request_id", "request_id"),
        Index("ix_audit_logs_target_created", "target_type", "target_id", "created_at", "id"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at", "id"),
        Index("ix_audit_logs_terminal_created", "source_terminal", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    source_terminal: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
