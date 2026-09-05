import hashlib
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    AuditLog,
    ContractExport,
    ContractNumberCounter,
    Factory,
    FactoryContact,
    Order,
    OrderAssignment,
    OrderLine,
    ProcessingContract,
    Product,
    ProductVariant,
    StoredFile,
    User,
)
from app.modules.contracts.workbook import ContractWorkbookRenderer

CONTRACT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ContractError(ValueError):
    pass


class ContractValidationError(ContractError):
    pass


class ContractConflict(ContractError):
    pass


class ContractNotFound(ContractError):
    pass


class ContractPermissionDenied(ContractError):
    pass


class ContractGenerationError(ContractError):
    pass


class ContractExecutionGuard(Protocol):
    def has_valid_shipments(self, *, order_id: str) -> bool: ...


class EmptyContractExecutionGuard:
    def has_valid_shipments(self, *, order_id: str) -> bool:
        return False


@dataclass(frozen=True)
class ContractFactoryStatus:
    factory_id: str
    factory_name: str
    contract_ready: bool
    missing_contract_fields: list[str]
    eligible: bool
    ineligible_reason: str | None
    contract_no: str | None
    signing_date: date | None


@dataclass(frozen=True)
class ContractExportResult:
    export_id: str
    contract_id: str
    contract_no: str
    signing_date: date
    filename: str
    status: str
    object_key: str


class ContractService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        execution_guard: ContractExecutionGuard | None = None,
        workbook_renderer: ContractWorkbookRenderer | None = None,
        file_store: PrivateFileStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        template_version: str = "v1",
    ) -> None:
        self._session_factory = session_factory
        self._execution_guard = execution_guard or EmptyContractExecutionGuard()
        self._workbook_renderer = workbook_renderer
        self._file_store = file_store
        self._clock = clock
        self._template_version = template_version

    def list_for_order(self, *, actor_id: str, order_id: str) -> list[ContractFactoryStatus]:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            order = session.get(Order, order_id)
            if order is None or order.deleted_at is not None:
                raise ContractNotFound("order not found")
            factory_ids = list(
                session.scalars(
                    select(OrderAssignment.factory_id)
                    .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                    .where(OrderLine.order_id == order_id)
                    .distinct()
                    .order_by(OrderAssignment.factory_id)
                )
            )
            has_shipments = self._has_unified_shipments(session, order_id=order_id)
            result: list[ContractFactoryStatus] = []
            for factory_id in factory_ids:
                factory = session.get(Factory, factory_id)
                if factory is None:
                    continue
                missing = self._missing_contract_fields(factory)
                contract = session.scalar(
                    select(ProcessingContract).where(
                        ProcessingContract.order_id == order_id,
                        ProcessingContract.factory_id == factory_id,
                    )
                )
                # Existing contracts use their immutable factory snapshot.
                if contract is not None:
                    missing = []
                reason = self._ineligible_reason(
                    order=order, missing=missing, has_shipments=has_shipments
                )
                result.append(
                    ContractFactoryStatus(
                        factory_id=factory.factory_id,
                        factory_name=factory.factory_name,
                        contract_ready=not missing,
                        missing_contract_fields=missing,
                        eligible=reason is None,
                        ineligible_reason=reason,
                        contract_no=contract.contract_no if contract else None,
                        signing_date=contract.signing_date if contract else None,
                    )
                )
            return result

    def create_export(
        self,
        *,
        actor_id: str,
        order_id: str,
        factory_id: str,
        signing_date: date | None,
        idempotency_key: str,
        request_id: str,
    ) -> ContractExportResult:
        if not idempotency_key.strip():
            raise ContractValidationError("idempotency key is required")
        if self._workbook_renderer is None or self._file_store is None:
            raise ContractGenerationError("contract export is not configured")
        now = self._clock()
        export_id: str
        snapshot: dict[str, Any]
        already_ready = False
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            existing_export = session.scalar(
                select(ContractExport).where(
                    ContractExport.exported_by == actor_id,
                    ContractExport.idempotency_key == idempotency_key,
                )
            )
            if existing_export is not None:
                existing_contract = session.get(ProcessingContract, existing_export.contract_id)
                if (
                    existing_contract is None
                    or existing_contract.order_id != order_id
                    or existing_contract.factory_id != factory_id
                ):
                    raise ContractConflict("idempotency key belongs to another export")
                export_id = existing_export.export_id
                snapshot = dict(existing_export.export_snapshot)
                already_ready = existing_export.status == "READY"
                if not already_ready:
                    existing_export.status = "PENDING"
                    existing_export.error_code = None
                    existing_export.error_message = None
            else:
                factory = session.scalar(
                    select(Factory).where(Factory.factory_id == factory_id).with_for_update()
                )
                order = session.scalar(
                    select(Order).where(Order.order_id == order_id).with_for_update()
                )
                if order is None or order.deleted_at is not None:
                    raise ContractNotFound("order not found")
                if order.lifecycle != "PUBLISHED":
                    raise ContractConflict("only published orders can export contracts")
                if self._has_unified_shipments(session, order_id=order_id):
                    raise ContractConflict("order has valid shipments")
                if factory is None or not self._factory_is_assigned(
                    session, order_id=order_id, factory_id=factory_id
                ):
                    raise ContractNotFound("factory assignment not found")
                contract = session.scalar(
                    select(ProcessingContract)
                    .where(
                        ProcessingContract.order_id == order_id,
                        ProcessingContract.factory_id == factory_id,
                    )
                    .with_for_update()
                )
                if contract is None:
                    missing = self._missing_contract_fields(factory)
                    if missing:
                        raise ContractValidationError(
                            "factory contract fields are incomplete: " + ",".join(missing)
                        )
                    assert factory.factory_code is not None
                    if signing_date is None:
                        raise ContractValidationError("signing date is required")
                    sequence = self._allocate_sequence(
                        session,
                        signing_date=signing_date,
                        factory_id=factory_id,
                        now=now,
                    )
                    contract_no = self._contract_no(
                        signing_date=signing_date,
                        factory_code=factory.factory_code,
                        sequence=sequence,
                    )
                    snapshot = self._build_snapshot(
                        session,
                        order=order,
                        factory=factory,
                        contract_no=contract_no,
                        signing_date=signing_date,
                    )
                    contract = ProcessingContract(
                        contract_id=str(uuid4()),
                        order_id=order_id,
                        factory_id=factory_id,
                        signing_date=signing_date,
                        daily_sequence=sequence,
                        contract_no=contract_no,
                        contract_snapshot=snapshot,
                        template_version=self._template_version,
                        created_by=actor_id,
                        created_at=now,
                    )
                    session.add(contract)
                    session.flush()
                else:
                    if signing_date is not None and signing_date != contract.signing_date:
                        raise ContractValidationError(
                            "signing date cannot change after first export"
                        )
                    snapshot = dict(contract.contract_snapshot)
                export_id = str(uuid4())
                session.add(
                    ContractExport(
                        export_id=export_id,
                        contract_id=contract.contract_id,
                        exported_by=actor_id,
                        idempotency_key=idempotency_key,
                        status="PENDING",
                        export_snapshot=snapshot,
                        template_version=contract.template_version,
                        created_at=now,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="contract.export_requested",
                        target_type="processing_contract",
                        target_id=contract.contract_id,
                        changes={"exportId": export_id, "contractNo": contract.contract_no},
                        actor_id=actor_id,
                        source_terminal="web",
                        created_at=now,
                    )
                )
        if already_ready:
            return self._export_result(export_id)
        object_key = self._object_key(snapshot=snapshot, export_id=export_id)
        uploaded = False
        try:
            content = self._workbook_renderer.render(snapshot)
            self._file_store.put(
                object_key=object_key,
                content=content,
                content_type=CONTRACT_MIME,
            )
            uploaded = True
            completed_at = self._clock()
            with self._session_factory() as session, session.begin():
                export = session.get(ContractExport, export_id)
                if export is None:
                    raise ContractNotFound("contract export not found")
                stored_file = StoredFile(
                    bucket=self._file_store.bucket,
                    object_key=object_key,
                    original_filename=self._filename(snapshot),
                    mime_type=CONTRACT_MIME,
                    size_bytes=len(content),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    uploaded_by=actor_id,
                    idempotency_key=f"contract:{export_id}",
                    created_at=completed_at,
                )
                session.add(stored_file)
                session.flush()
                export.stored_file_id = stored_file.file_id
                export.status = "READY"
                export.completed_at = completed_at
            return self._export_result(export_id)
        except Exception as error:
            if uploaded:
                with suppress(Exception):
                    self._file_store.delete(object_key=object_key)
            with self._session_factory() as session, session.begin():
                export = session.get(ContractExport, export_id)
                if export is not None:
                    export.status = "FAILED"
                    export.error_code = "contract_generation_failed"
                    export.error_message = "contract file could not be generated"
                    export.completed_at = self._clock()
            if isinstance(error, (ContractError, ExternalAdapterUnavailable)):
                raise
            raise ContractGenerationError("contract file could not be generated") from error

    def download(self, *, actor_id: str, export_id: str) -> tuple[str, bytes, str]:
        if self._file_store is None:
            raise ContractGenerationError("contract export is not configured")
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            export = session.get(ContractExport, export_id)
            if export is None or export.status != "READY" or export.stored_file_id is None:
                raise ContractNotFound("contract export not found")
            stored_file = session.get(StoredFile, export.stored_file_id)
            if stored_file is None or stored_file.bucket != self._file_store.bucket:
                raise ContractNotFound("contract file not found")
            content = self._file_store.get(object_key=stored_file.object_key)
            if hashlib.sha256(content).hexdigest() != stored_file.content_sha256:
                raise ContractGenerationError("contract file checksum mismatch")
            return stored_file.original_filename, content, stored_file.mime_type

    def _export_result(self, export_id: str) -> ContractExportResult:
        with self._session_factory() as session:
            export = session.get(ContractExport, export_id)
            if export is None:
                raise ContractNotFound("contract export not found")
            contract = session.get(ProcessingContract, export.contract_id)
            if contract is None:
                raise ContractNotFound("contract not found")
            stored_file = (
                session.get(StoredFile, export.stored_file_id)
                if export.stored_file_id is not None
                else None
            )
            return ContractExportResult(
                export_id=export.export_id,
                contract_id=contract.contract_id,
                contract_no=contract.contract_no,
                signing_date=contract.signing_date,
                filename=(
                    stored_file.original_filename
                    if stored_file is not None
                    else self._filename(dict(export.export_snapshot))
                ),
                status=export.status,
                object_key=stored_file.object_key if stored_file is not None else "",
            )

    @staticmethod
    def _factory_is_assigned(session: Session, *, order_id: str, factory_id: str) -> bool:
        assignment_id = session.scalar(
            select(OrderAssignment.order_assignment_id)
            .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
            .where(
                OrderLine.order_id == order_id,
                OrderAssignment.factory_id == factory_id,
            )
            .limit(1)
        )
        return assignment_id is not None

    @staticmethod
    def _allocate_sequence(
        session: Session,
        *,
        signing_date: date,
        factory_id: str,
        now: datetime,
    ) -> int:
        statement = mysql_insert(ContractNumberCounter).values(
            signing_date=signing_date,
            factory_id=factory_id,
            next_sequence=1,
            updated_at=now,
        )
        statement = statement.on_duplicate_key_update(
            next_sequence=ContractNumberCounter.next_sequence + 1,
            updated_at=now,
        )
        session.execute(statement)
        next_sequence = session.scalar(
            select(ContractNumberCounter.next_sequence).where(
                ContractNumberCounter.signing_date == signing_date,
                ContractNumberCounter.factory_id == factory_id,
            )
        )
        if next_sequence is None:
            raise ContractConflict("contract number allocation failed")
        return next_sequence - 1

    @staticmethod
    def _contract_no(*, signing_date: date, factory_code: str, sequence: int) -> str:
        base = f"{signing_date:%Y%m%d}-KK-{factory_code.strip().upper()}"
        return base if sequence == 0 else f"{base}-{sequence}"

    @staticmethod
    def _build_snapshot(
        session: Session,
        *,
        order: Order,
        factory: Factory,
        contract_no: str,
        signing_date: date,
    ) -> dict[str, Any]:
        rows = session.execute(
            select(OrderLine, OrderAssignment, ProductVariant, Product)
            .join(
                OrderAssignment,
                OrderAssignment.order_line_id == OrderLine.order_line_id,
            )
            .join(
                ProductVariant,
                ProductVariant.variant_id == OrderLine.product_variant_id,
            )
            .join(Product, Product.product_id == ProductVariant.product_id)
            .where(
                OrderLine.order_id == order.order_id,
                OrderAssignment.factory_id == factory.factory_id,
            )
            .order_by(OrderLine.order_line_id, OrderAssignment.order_assignment_id)
        ).all()
        if not rows:
            raise ContractNotFound("factory assignment not found")
        contact = session.scalar(
            select(FactoryContact)
            .where(FactoryContact.factory_id == factory.factory_id)
            .order_by(FactoryContact.is_primary.desc(), FactoryContact.display_order)
            .limit(1)
        )
        return {
            "contractNo": contract_no,
            "signingDate": signing_date.isoformat(),
            "orderId": order.order_id,
            "orderNo": order.order_no,
            "orderDate": order.order_date.isoformat() if order.order_date else None,
            "contractShipDate": order.contract_ship_date.isoformat(),
            "factory": {
                "factoryId": factory.factory_id,
                "factoryCode": factory.factory_code,
                "legalName": factory.legal_name,
                "address": factory.address,
                "legalRepresentative": factory.legal_representative,
                "phone": contact.phone if contact is not None else "",
            },
            "lines": [
                {
                    "productId": product.product_id,
                    "itemNo": product.source_i_id,
                    "productName": line.product_name_snapshot,
                    "propertiesValue": line.properties_value_snapshot,
                    "quantity": assignment.assigned_quantity,
                    "imageObjectKey": line.image_object_key_snapshot,
                }
                for line, assignment, _variant, product in rows
            ],
        }

    def _has_unified_shipments(self, session: Session, *, order_id: str) -> bool:
        initial_quantity = int(
            session.scalar(
                select(func.coalesce(func.sum(OrderAssignment.initial_shipped_quantity), 0))
                .join(
                    OrderLine,
                    OrderLine.order_line_id == OrderAssignment.order_line_id,
                )
                .where(OrderLine.order_id == order_id)
            )
            or 0
        )
        return initial_quantity > 0 or self._execution_guard.has_valid_shipments(order_id=order_id)

    @staticmethod
    def _filename(snapshot: dict[str, Any]) -> str:
        lines = list(snapshot["lines"])
        product_names: list[str] = []
        for line in lines:
            name = str(line["productName"])
            if name not in product_names:
                product_names.append(name)
        suffix = product_names[0]
        if len(product_names) > 1:
            suffix = f"{suffix}等{len(product_names)}款"
        raw = f"{snapshot['contractNo']} {snapshot['orderNo']} {suffix}.xlsx"
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw).strip()
        return safe[:255]

    @staticmethod
    def _object_key(*, snapshot: dict[str, Any], export_id: str) -> str:
        signing_date = date.fromisoformat(str(snapshot["signingDate"]))
        return f"contracts/{signing_date:%Y/%m}/{export_id}.xlsx"

    @staticmethod
    def _missing_contract_fields(factory: Factory) -> list[str]:
        fields = (
            ("factoryCode", factory.factory_code),
            ("legalName", factory.legal_name),
            ("address", factory.address),
            ("legalRepresentative", factory.legal_representative),
        )
        return [name for name, value in fields if not value or not value.strip()]

    @staticmethod
    def _ineligible_reason(*, order: Order, missing: list[str], has_shipments: bool) -> str | None:
        if order.lifecycle != "PUBLISHED":
            return "order_not_published"
        if has_shipments:
            return "order_has_shipments"
        if missing:
            return "factory_contract_incomplete"
        return None

    @staticmethod
    def _require_admin(session: Session, actor_id: str) -> User:
        user = session.get(User, actor_id)
        if user is None or not user.is_enabled or user.role != "admin":
            raise ContractPermissionDenied("administrator role required")
        return user
