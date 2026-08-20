from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    FactoryApplication,
    FactoryContact,
    User,
    UserSession,
)
from app.modules.identity_access import (
    ApplicationConflict,
    PermissionDenied,
    ResourceNotFound,
    VerificationInvalid,
)


class FactoryConflict(ApplicationConflict):
    pass


class FactoryValidation(VerificationInvalid):
    pass


@dataclass(frozen=True)
class FactoryContactSnapshot:
    name: str
    phone: str
    display_order: int
    is_primary: bool


@dataclass(frozen=True)
class FactorySnapshot:
    factory_id: str
    supplier_number: str
    factory_name: str
    factory_code: str
    legal_name: str | None
    address: str | None
    legal_representative: str | None
    is_enabled: bool
    version: int
    contract_complete: bool
    missing_contract_fields: tuple[str, ...]
    contacts: tuple[FactoryContactSnapshot, ...]
    connected_users: int


@dataclass(frozen=True)
class FactoryApplicationSnapshot:
    application_id: str
    user_id: str
    real_name: str
    phone_masked: str
    position: str
    requested_factory_id: str
    requested_factory_name: str
    bound_factory_id: str | None
    bound_factory_name: str | None
    status: str
    submitted_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    version: int
    factory_contacts: tuple[FactoryContactSnapshot, ...]


@dataclass(frozen=True)
class FactoryUserSnapshot:
    user_id: str
    real_name: str
    phone_masked: str | None
    position: str
    factory_id: str
    factory_name: str
    is_enabled: bool
    version: int


class FactoryAccessService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_factory(
        self,
        *,
        actor_id: str,
        supplier_number: str,
        factory_name: str,
        factory_code: str,
        legal_name: str,
        address: str,
        legal_representative: str,
        contacts: list[tuple[str, str]],
        request_id: str,
    ) -> FactorySnapshot:
        normalized_number = self._required_upper(supplier_number, "supplier number")
        normalized_name = self._required(factory_name, "factory name")
        normalized_code = self._required_upper(factory_code, "factory code")
        normalized_contacts = self._normalize_contacts(contacts)
        factory = Factory(
            factory_id=str(uuid4()),
            supplier_number=normalized_number,
            factory_name=normalized_name,
            factory_code=normalized_code,
            legal_name=self._optional(legal_name),
            address=self._optional(address),
            legal_representative=self._optional(legal_representative),
        )
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                session.add(factory)
                session.flush()
                self._replace_contacts(session, factory.factory_id, normalized_contacts)
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="factory.created",
                        target_type="factory",
                        target_id=factory.factory_id,
                        changes={
                            "supplierNumber": normalized_number,
                            "factoryName": normalized_name,
                            "factoryCode": normalized_code,
                        },
                        actor_id=actor_id,
                        source_terminal="web",
                    )
                )
                session.flush()
                return self._snapshot(session, factory)
        except IntegrityError as error:
            raise FactoryConflict("factory unique field already exists") from error

    def update_factory(
        self,
        *,
        actor_id: str,
        factory_id: str,
        expected_version: int,
        factory_name: str,
        factory_code: str,
        legal_name: str,
        address: str,
        legal_representative: str,
        contacts: list[tuple[str, str]],
        request_id: str,
    ) -> FactorySnapshot:
        normalized_name = self._required(factory_name, "factory name")
        normalized_code = self._required_upper(factory_code, "factory code")
        normalized_contacts = self._normalize_contacts(contacts)
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                factory = session.scalar(
                    select(Factory)
                    .where(Factory.factory_id == factory_id)
                    .with_for_update()
                )
                if factory is None:
                    raise ResourceNotFound("factory was not found")
                if factory.version != expected_version:
                    raise FactoryConflict("factory version conflict")
                before = {
                    "factoryName": factory.factory_name,
                    "factoryCode": factory.factory_code,
                    "version": factory.version,
                }
                factory.factory_name = normalized_name
                factory.factory_code = normalized_code
                factory.legal_name = self._optional(legal_name)
                factory.address = self._optional(address)
                factory.legal_representative = self._optional(legal_representative)
                factory.version += 1
                self._replace_contacts(session, factory.factory_id, normalized_contacts)
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="factory.updated",
                        target_type="factory",
                        target_id=factory.factory_id,
                        changes={
                            "before": before,
                            "after": {
                                "factoryName": factory.factory_name,
                                "factoryCode": factory.factory_code,
                                "version": factory.version,
                            },
                        },
                        actor_id=actor_id,
                        source_terminal="web",
                    )
                )
                session.flush()
                return self._snapshot(session, factory)
        except IntegrityError as error:
            raise FactoryConflict("factory unique field already exists") from error

    def get_factory(self, *, actor_id: str, factory_id: str) -> FactorySnapshot:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            factory = session.get(Factory, factory_id)
            if factory is None:
                raise ResourceNotFound("factory was not found")
            return self._snapshot(session, factory)

    def list_factories(
        self,
        *,
        actor_id: str,
        keyword: str = "",
        contract_status: str = "all",
        access_status: str = "all",
    ) -> list[FactorySnapshot]:
        if contract_status not in {"all", "complete", "incomplete"}:
            raise FactoryValidation("contract status is invalid")
        if access_status not in {"all", "connected", "unconnected"}:
            raise FactoryValidation("access status is invalid")
        normalized_keyword = keyword.strip()
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            statement = select(Factory)
            if normalized_keyword:
                pattern = f"%{normalized_keyword}%"
                statement = (
                    statement.outerjoin(FactoryContact)
                    .where(
                        or_(
                            Factory.supplier_number.like(pattern),
                            Factory.factory_name.like(pattern),
                            Factory.legal_name.like(pattern),
                            FactoryContact.name.like(pattern),
                            FactoryContact.phone.like(pattern),
                        )
                    )
                    .distinct()
                )
            factories = session.scalars(statement.order_by(Factory.supplier_number)).all()
            snapshots = [self._snapshot(session, factory) for factory in factories]
            if contract_status != "all":
                expected = contract_status == "complete"
                snapshots = [item for item in snapshots if item.contract_complete is expected]
            if access_status != "all":
                expected_connected = access_status == "connected"
                snapshots = [
                    item
                    for item in snapshots
                    if bool(self._connected_user_count(session, item.factory_id))
                    is expected_connected
                ]
            return snapshots

    def list_factory_options(self, *, keyword: str = "") -> list[FactorySnapshot]:
        normalized_keyword = keyword.strip()
        with self._session_factory() as session:
            statement = select(Factory).where(Factory.is_enabled.is_(True))
            if normalized_keyword:
                pattern = f"%{normalized_keyword}%"
                statement = statement.where(
                    or_(
                        Factory.supplier_number.like(pattern),
                        Factory.factory_name.like(pattern),
                    )
                )
            factories = session.scalars(statement.order_by(Factory.supplier_number)).all()
            return [self._snapshot(session, factory) for factory in factories]

    def submit_factory_application(
        self,
        *,
        user_id: str,
        real_name: str,
        position: str,
        factory_id: str,
        request_id: str,
    ) -> FactoryApplicationSnapshot:
        normalized_name = self._required(real_name, "real name")
        if len(normalized_name) > 100:
            raise FactoryValidation("real name is too long")
        if position not in {"owner", "employee"}:
            raise FactoryValidation("factory position is invalid")
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            pending = session.scalar(
                select(FactoryApplication).where(
                    FactoryApplication.pending_user_id == user_id
                )
            )
            if pending is not None:
                raise FactoryConflict("a factory application is already pending")
            user = session.get(User, user_id)
            if (
                user is None
                or not user.is_enabled
                or user.role is not None
                or user.phone_encrypted is None
                or user.phone_digest is None
                or user.phone_masked is None
            ):
                raise FactoryValidation("verified factory applicant is required")
            target = session.get(Factory, factory_id)
            if target is None or not target.is_enabled:
                raise FactoryValidation("selected factory is unavailable")
            previous = session.scalar(
                select(FactoryApplication)
                .where(FactoryApplication.user_id == user_id)
                .order_by(FactoryApplication.submitted_at.desc())
                .limit(1)
            )
            application = FactoryApplication(
                application_id=str(uuid4()),
                user_id=user_id,
                pending_user_id=user_id,
                real_name=normalized_name,
                phone_encrypted=user.phone_encrypted,
                phone_digest=user.phone_digest,
                phone_masked=user.phone_masked,
                position=position,
                requested_factory_id=factory_id,
                status="pending",
                submitted_at=now,
                version=1,
                previous_application_id=(
                    previous.application_id if previous is not None else None
                ),
            )
            user.feishu_display_name = normalized_name
            session.add(application)
            session.add(
                AuditLog(
                    request_id=request_id,
                    action=(
                        "factory_application.resubmitted"
                        if previous is not None
                        else "factory_application.submitted"
                    ),
                    target_type="factory_application",
                    target_id=application.application_id,
                    changes={
                        "status": "pending",
                        "factoryId": factory_id,
                        "position": position,
                        "phone": user.phone_masked,
                    },
                    actor_id=user_id,
                    source_terminal="mini",
                )
            )
            session.flush()
            return self._application_snapshot(session, application)

    def get_my_factory_application(
        self, *, user_id: str
    ) -> FactoryApplicationSnapshot | None:
        with self._session_factory() as session:
            application = session.scalar(
                select(FactoryApplication)
                .where(FactoryApplication.user_id == user_id)
                .order_by(FactoryApplication.submitted_at.desc())
                .limit(1)
            )
            return (
                self._application_snapshot(session, application)
                if application is not None
                else None
            )

    def list_factory_applications(
        self, *, actor_id: str, status: str | None = None
    ) -> list[FactoryApplicationSnapshot]:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            statement = select(FactoryApplication)
            if status is not None:
                statement = statement.where(FactoryApplication.status == status)
            applications = session.scalars(
                statement.order_by(FactoryApplication.submitted_at.desc())
            ).all()
            return [
                self._application_snapshot(session, application)
                for application in applications
            ]

    def get_factory_application(
        self, *, actor_id: str, application_id: str
    ) -> FactoryApplicationSnapshot:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            application = session.get(FactoryApplication, application_id)
            if application is None:
                raise ResourceNotFound("factory application was not found")
            return self._application_snapshot(session, application)

    def approve_factory_application(
        self,
        *,
        actor_id: str,
        application_id: str,
        expected_version: int,
        factory_id: str,
        request_id: str,
    ) -> FactoryApplicationSnapshot:
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            application = session.scalar(
                select(FactoryApplication)
                .where(FactoryApplication.application_id == application_id)
                .with_for_update()
            )
            if (
                application is None
                or application.status != "pending"
                or application.version != expected_version
            ):
                raise FactoryConflict("factory application was already processed")
            target = session.get(Factory, factory_id)
            if target is None or not target.is_enabled:
                raise FactoryValidation("selected factory is unavailable")
            user = session.get(User, application.user_id)
            if user is None or user.role is not None:
                raise FactoryConflict("factory applicant role has changed")
            application.status = "approved"
            application.pending_user_id = None
            application.bound_factory_id = factory_id
            application.reviewed_by = actor_id
            application.reviewed_at = now
            application.rejection_reason = None
            application.version += 1
            user.role = "factory"
            user.factory_id = factory_id
            user.factory_position = application.position
            user.is_enabled = True
            user.version += 1
            session.execute(
                update(UserSession)
                .where(
                    UserSession.user_id == user.user_id,
                    UserSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="factory_application.approved",
                    target_type="factory_application",
                    target_id=application.application_id,
                    changes={
                        "before": "pending",
                        "after": "approved",
                        "requestedFactoryId": application.requested_factory_id,
                        "boundFactoryId": factory_id,
                    },
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            session.flush()
            return self._application_snapshot(session, application)

    def reject_factory_application(
        self,
        *,
        actor_id: str,
        application_id: str,
        expected_version: int,
        reason: str,
        request_id: str,
    ) -> FactoryApplicationSnapshot:
        normalized_reason = self._required(reason, "rejection reason")
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            application = session.scalar(
                select(FactoryApplication)
                .where(FactoryApplication.application_id == application_id)
                .with_for_update()
            )
            if (
                application is None
                or application.status != "pending"
                or application.version != expected_version
            ):
                raise FactoryConflict("factory application was already processed")
            application.status = "rejected"
            application.pending_user_id = None
            application.reviewed_by = actor_id
            application.reviewed_at = now
            application.rejection_reason = normalized_reason
            application.version += 1
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="factory_application.rejected",
                    target_type="factory_application",
                    target_id=application.application_id,
                    changes={"before": "pending", "after": "rejected"},
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            session.flush()
            return self._application_snapshot(session, application)

    def get_own_factory(self, *, user_id: str, factory_id: str) -> FactorySnapshot:
        with self._session_factory() as session:
            user = session.get(User, user_id)
            if (
                user is None
                or user.role != "factory"
                or not user.is_enabled
                or user.factory_id != factory_id
            ):
                raise ResourceNotFound("factory resource was not found")
            factory = session.get(Factory, factory_id)
            if factory is None or not factory.is_enabled:
                raise ResourceNotFound("factory resource was not found")
            return self._snapshot(session, factory)

    def list_factory_users(
        self, *, actor_id: str, factory_id: str | None = None
    ) -> list[FactoryUserSnapshot]:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            statement = select(User).where(User.role == "factory")
            if factory_id is not None:
                statement = statement.where(User.factory_id == factory_id)
            users = session.scalars(statement.order_by(User.feishu_display_name)).all()
            return [self._factory_user_snapshot(session, user) for user in users]

    def set_factory_user_enabled(
        self,
        *,
        actor_id: str,
        target_user_id: str,
        enabled: bool,
        expected_version: int,
        request_id: str,
    ) -> FactoryUserSnapshot:
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            user = session.scalar(
                select(User).where(User.user_id == target_user_id).with_for_update()
            )
            if user is None or user.role != "factory" or user.factory_id is None:
                raise ResourceNotFound("factory user was not found")
            if user.version != expected_version:
                raise FactoryConflict("factory user version conflict")
            before = user.is_enabled
            user.is_enabled = enabled
            user.version += 1
            if not enabled:
                session.execute(
                    update(UserSession)
                    .where(
                        UserSession.user_id == user.user_id,
                        UserSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="factory_user.enabled" if enabled else "factory_user.disabled",
                    target_type="user",
                    target_id=user.user_id,
                    changes={"before": before, "after": enabled},
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            session.flush()
            return self._factory_user_snapshot(session, user)

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise FactoryValidation(f"{label} is required")
        return normalized

    @classmethod
    def _required_upper(cls, value: str, label: str) -> str:
        return cls._required(value, label).upper()

    @staticmethod
    def _optional(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _normalize_contacts(cls, contacts: list[tuple[str, str]]) -> list[tuple[str, str]]:
        normalized: list[tuple[str, str]] = []
        for name, phone in contacts:
            clean_name = name.strip()
            clean_phone = phone.strip()
            if not clean_name and not clean_phone:
                continue
            if not clean_name or not clean_phone:
                raise FactoryValidation("contact name and phone must be provided together")
            normalized.append((clean_name, clean_phone))
        return normalized

    @staticmethod
    def _require_admin(session: Session, actor_id: str) -> User:
        actor = session.get(User, actor_id)
        if actor is None or actor.role != "admin" or not actor.is_enabled:
            raise PermissionDenied("administrator permission is required")
        return actor

    @staticmethod
    def _replace_contacts(
        session: Session, factory_id: str, contacts: list[tuple[str, str]]
    ) -> None:
        session.execute(delete(FactoryContact).where(FactoryContact.factory_id == factory_id))
        for index, (name, phone) in enumerate(contacts):
            session.add(
                FactoryContact(
                    factory_id=factory_id,
                    name=name,
                    phone=phone,
                    display_order=index,
                    is_primary=index == 0,
                )
            )

    @classmethod
    def _snapshot(cls, session: Session, factory: Factory) -> FactorySnapshot:
        missing = tuple(
            label
            for value, label in (
                (factory.factory_code, "工厂代码"),
                (factory.legal_name, "单位全称"),
                (factory.address, "单位地址"),
                (factory.legal_representative, "法定代表人"),
            )
            if not value
        )
        contacts = session.scalars(
            select(FactoryContact)
            .where(FactoryContact.factory_id == factory.factory_id)
            .order_by(FactoryContact.display_order)
        ).all()
        return FactorySnapshot(
            factory_id=factory.factory_id,
            supplier_number=factory.supplier_number,
            factory_name=factory.factory_name,
            factory_code=factory.factory_code,
            legal_name=factory.legal_name,
            address=factory.address,
            legal_representative=factory.legal_representative,
            is_enabled=factory.is_enabled,
            version=factory.version,
            contract_complete=not missing,
            missing_contract_fields=missing,
            contacts=tuple(
                FactoryContactSnapshot(
                    name=contact.name,
                    phone=contact.phone,
                    display_order=contact.display_order,
                    is_primary=contact.is_primary,
                )
                for contact in contacts
            ),
            connected_users=cls._connected_user_count(session, factory.factory_id),
        )

    @staticmethod
    def _connected_user_count(session: Session, factory_id: str) -> int:
        return len(
            session.scalars(
                select(User.user_id).where(
                    User.factory_id == factory_id,
                    User.role == "factory",
                    User.is_enabled.is_(True),
                )
            ).all()
        )

    @classmethod
    def _application_snapshot(
        cls, session: Session, application: FactoryApplication
    ) -> FactoryApplicationSnapshot:
        requested = session.get(Factory, application.requested_factory_id)
        bound = (
            session.get(Factory, application.bound_factory_id)
            if application.bound_factory_id is not None
            else None
        )
        if requested is None:
            raise RuntimeError("factory application target disappeared")
        requested_snapshot = cls._snapshot(session, requested)
        return FactoryApplicationSnapshot(
            application_id=application.application_id,
            user_id=application.user_id,
            real_name=application.real_name,
            phone_masked=application.phone_masked,
            position=application.position,
            requested_factory_id=application.requested_factory_id,
            requested_factory_name=requested.factory_name,
            bound_factory_id=application.bound_factory_id,
            bound_factory_name=bound.factory_name if bound is not None else None,
            status=application.status,
            submitted_at=application.submitted_at,
            reviewed_by=application.reviewed_by,
            reviewed_at=application.reviewed_at,
            rejection_reason=application.rejection_reason,
            version=application.version,
            factory_contacts=requested_snapshot.contacts,
        )

    @staticmethod
    def _factory_user_snapshot(session: Session, user: User) -> FactoryUserSnapshot:
        if user.factory_id is None or user.factory_position is None:
            raise RuntimeError("factory user affiliation is incomplete")
        factory = session.get(Factory, user.factory_id)
        if factory is None:
            raise RuntimeError("factory user target disappeared")
        return FactoryUserSnapshot(
            user_id=user.user_id,
            real_name=user.feishu_display_name,
            phone_masked=user.phone_masked,
            position=user.factory_position,
            factory_id=user.factory_id,
            factory_name=factory.factory_name,
            is_enabled=user.is_enabled,
            version=user.version,
        )
