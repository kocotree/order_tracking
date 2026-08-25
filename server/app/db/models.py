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
    __table_args__ = (
        UniqueConstraint("source_i_id", name="uq_products_source_i_id"),
        UniqueConstraint("name", name="uq_products_name"),
    )

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
        UniqueConstraint(
            "product_id",
            "properties_value",
            name="uq_product_variants_product_properties",
        ),
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
        Index("ix_outbox_messages_publish", "status", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_request_id", "request_id"),)

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
