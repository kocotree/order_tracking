"""Local-only Issue #76 demo server; never loaded by the production entry point."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.api.identity import SessionResponse, _user_response
from app.db.models import Factory, Product, ProductVariant, RepairOrder, StoredFile, User
from app.db.session import create_database_engine
from app.local_demo import LocalDemoFeishuIdentity, LocalDemoWechatIdentity
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.repairs.confirmation import RepairConfirmationService
from app.modules.repairs.workflow import XLSX_MIME, RepairWorkflowService
from app.settings.config import Settings


def create_demo_app() -> FastAPI:
    settings = Settings()
    url = make_url(settings.database_url)
    if (
        settings.app_env != "local_demo"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "order_tracking_issue76_dev"
    ):
        raise RuntimeError("Demo requires the dedicated local Issue #76 database")
    engine = create_database_engine(settings.database_url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    store = FakePrivateFileStore(bucket="issue76-demo")
    now = datetime.now(UTC).replace(tzinfo=None)
    with sessions() as session, session.begin():
        if session.get(Factory, "demo76-factory") is None:
            session.add(
                Factory(
                    factory_id="demo76-factory",
                    supplier_number="DEMO76",
                    factory_name="返修演示工厂",
                    factory_code="DEMOR",
                    is_enabled=True,
                )
            )
        if session.get(Product, "demo76-product") is None:
            session.add(
                Product(
                    product_id="demo76-product",
                    source_i_id="DEMO76-HAT",
                    name="演示遮阳帽",
                    is_available=True,
                    image_cache_status="missing",
                    source_modified_at=now,
                    first_synced_at=now,
                    last_synced_at=now,
                )
            )
        session.flush()
        for user_id, role in [("demo76-admin", "admin"), ("demo76-worker", "factory")]:
            if session.get(User, user_id) is None:
                session.add(
                    User(
                        user_id=user_id,
                        role=role,
                        is_super_admin=role == "admin",
                        is_enabled=True,
                        factory_id="demo76-factory" if role == "factory" else None,
                        feishu_display_name="返修演示管理员"
                        if role == "admin"
                        else "返修演示工厂用户",
                    )
                )
        for suffix, spec in [("BLUE", "蓝色/M"), ("PINK", "粉色/S")]:
            if session.get(ProductVariant, "demo76-" + suffix) is None:
                session.add(
                    ProductVariant(
                        variant_id="demo76-" + suffix,
                        product_id="demo76-product",
                        source_sku_id="DEMO76-" + suffix,
                        properties_value=spec,
                        is_available=True,
                        source_modified_at=now,
                        first_synced_at=now,
                        last_synced_at=now,
                    )
                )
    workflow = RepairWorkflowService(sessions, file_store=store)
    confirmations = RepairConfirmationService(sessions)
    folder = Path(__file__).resolve().parents[2] / "docs/reference/issue-76-demo"
    for path in sorted(folder.glob("*.xlsx")):
        content = path.read_bytes()
        with sessions() as session:
            existing = session.scalar(
                select(RepairOrder).where(RepairOrder.source_sha256 == sha256(content).hexdigest())
            )
            if existing:
                file = session.get(StoredFile, existing.original_file_id)
                assert file is not None
                store.put(object_key=file.object_key, content=content, content_type=XLSX_MIME)
                continue
        preview = workflow.create_preview(
            content=content, filename=path.name, mime_type=XLSX_MIME, uploaded_by="demo76-admin"
        )
        confirmations.confirm(
            preview_id=preview.preview_id,
            confirmed_by="demo76-admin",
            idempotency_key="demo76-" + path.stem,
        )
    identity = IdentityAccessService(
        sessions,
        feishu_identity=LocalDemoFeishuIdentity(),
        wechat_identity=LocalDemoWechatIdentity(),
        super_admin_subjects={"local-demo-super"},
        token_secret=settings.identity_token_secret.encode(),
        phone_encryption_secret=settings.phone_encryption_secret.encode(),
        phone_digest_secret=settings.phone_digest_secret.encode(),
    )
    router = APIRouter(prefix="/api/v1/local-demo", include_in_schema=False)

    @router.post("/repair-login")
    def login(role: Literal["factory", "admin"]) -> dict[str, object]:
        user_id = "demo76-worker" if role == "factory" else "demo76-admin"
        token = identity.issue_session(user_id=user_id, terminal="mini")
        user = identity.get_user(user_id=user_id)
        return {
            "session": SessionResponse.model_validate(token, from_attributes=True).model_dump(
                by_alias=True, mode="json"
            ),
            "user": _user_response(user).model_dump(by_alias=True, mode="json"),
        }

    return create_app(identity_service=identity, private_file_store=store, extra_routers=[router])
