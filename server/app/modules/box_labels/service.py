import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    BoxLabelExport,
    Factory,
    Order,
    OrderAssignment,
    OrderDetail,
    OrderLine,
    Product,
    ProductVariant,
    StoredFile,
    User,
)
from app.modules.box_labels.workbook import BoxLabelWorkbookRenderer
from app.modules.contracts.service import CONTRACT_MIME
from app.modules.product_sync.color import extract_color as extract_product_color


class BoxLabelError(ValueError):
    pass


class BoxLabelNotFound(BoxLabelError):
    pass


class BoxLabelPermissionDenied(BoxLabelError):
    pass


class BoxLabelGenerationError(BoxLabelError):
    pass


@dataclass(frozen=True)
class BoxLabelGroup:
    group_id: str
    factory_id: str
    factory_name: str
    product_id: str | None
    product_name: str
    item_no: str
    color: str
    eligible: bool
    ineligible_reason: str | None
    variants: tuple[ProductVariant, ...] = ()


def extract_color(properties: str | None) -> str | None:
    value = (properties or "").strip()
    # 旧聚水潭样本中的 120/60 整体为尺码，公共规则单独按分隔符解析会截错。
    match = re.fullmatch(r"(.+?[\u4e00-\u9fff])\d{2,3}/\d{2,3}[A-Z]?", value)
    if match:
        return match.group(1)
    return extract_product_color(value)


def group_id(factory_id: str, product_id: str, color: str) -> str:
    return hashlib.sha256(f"{factory_id}\0{product_id}\0{color}".encode()).hexdigest()


class BoxLabelService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        renderer: BoxLabelWorkbookRenderer,
        file_store: PrivateFileStore,
    ) -> None:
        self._sessions = session_factory
        self._renderer = renderer
        self._files = file_store

    @staticmethod
    def _require_admin(session: Session, actor_id: str) -> None:
        user = session.get(User, actor_id)
        if user is None or user.role != "admin" or not user.is_enabled:
            raise BoxLabelPermissionDenied("administrator role required")

    @staticmethod
    def _order(session: Session, order_id: str, *, lock: bool = False) -> Order:
        query = select(Order).where(Order.order_id == order_id)
        order = session.scalar(query.with_for_update() if lock else query)
        if order is None or order.deleted_at is not None:
            raise BoxLabelNotFound("order not found")
        return order

    def list_for_order(self, *, actor_id: str, order_id: str) -> list[BoxLabelGroup]:
        with self._sessions() as session:
            self._require_admin(session, actor_id)
            order = self._order(session, order_id)
            return self._groups(session, order)

    def _groups(self, session: Session, order: Order) -> list[BoxLabelGroup]:
        if order.detail_mode:
            rows = session.execute(
                select(OrderDetail, Factory, ProductVariant, Product)
                .join(Factory, Factory.factory_id == OrderDetail.matched_factory_id)
                .outerjoin(
                    ProductVariant, ProductVariant.variant_id == OrderDetail.matched_variant_id
                )
                .outerjoin(Product, Product.product_id == ProductVariant.product_id)
                .where(OrderDetail.order_id == order.order_id)
                .order_by(OrderDetail.sort_order, OrderDetail.detail_id)
            ).all()
            source = [
                (
                    factory, product, variant, detail.product_name or "",
                    detail.properties_value or (variant.properties_value if variant else None),
                )
                for detail, factory, variant, product in rows
            ]
        else:
            query = (
                select(OrderAssignment, OrderLine, Factory, ProductVariant, Product)
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .join(Factory, Factory.factory_id == OrderAssignment.factory_id)
                .join(ProductVariant, ProductVariant.variant_id == OrderLine.product_variant_id)
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(OrderLine.order_id == order.order_id)
                .order_by(OrderLine.order_line_id, OrderAssignment.order_assignment_id)
            )
            if order.lifecycle != "DRAFT":
                query = query.where(OrderAssignment.is_active.is_(True))
            source = [
                (
                    factory, product, variant,
                    line.product_name_snapshot, line.properties_value_snapshot,
                )
                for _assignment, line, factory, variant, product in session.execute(query)
            ]
        grouped: dict[str, BoxLabelGroup] = {}
        for index, (factory, product, variant, source_name, properties) in enumerate(source):
            color = extract_color(properties)
            reason = "产品未匹配" if product is None else "颜色无法确定" if not color else None
            key = (
                group_id(factory.factory_id, product.product_id, color)
                if product is not None and color else f"unmatched-{index}"
            )
            prior = grouped.get(key)
            variants = (variant,) if variant is not None else ()
            if prior is not None:
                grouped[key] = BoxLabelGroup(
                    **{**prior.__dict__, "variants": prior.variants + variants}
                )
                continue
            grouped[key] = BoxLabelGroup(
                group_id=key,
                factory_id=factory.factory_id,
                factory_name=factory.factory_name,
                product_id=product.product_id if product else None,
                product_name=product.name if product else source_name or "—",
                item_no=product.source_i_id if product else "",
                color=color or "—",
                eligible=reason is None,
                ineligible_reason=reason,
                variants=variants,
            )
        for saved in session.scalars(
            select(BoxLabelExport).where(BoxLabelExport.order_id == order.order_id)
        ):
            snapshot = saved.snapshot
            grouped[saved.group_id] = BoxLabelGroup(
                group_id=saved.group_id,
                factory_id=saved.factory_id,
                factory_name=str(snapshot["factory"]),
                product_id=saved.product_id,
                product_name=str(snapshot["productName"]),
                item_no=str(snapshot["itemNo"]),
                color=saved.color,
                eligible=True,
                ineligible_reason=None,
            )
        return list(grouped.values())

    def export(self, *, actor_id: str, order_id: str, selected_group_id: str) -> tuple[str, str]:
        object_key: str | None = None
        uploaded = False
        try:
            with self._sessions() as session, session.begin():
                self._require_admin(session, actor_id)
                # ponytail: 订单行锁串行化同订单首次导出；吞吐受 OSS 时延限制。
                order = self._order(session, order_id, lock=True)
                saved = session.scalar(
                    select(BoxLabelExport).where(
                        BoxLabelExport.order_id == order_id,
                        BoxLabelExport.group_id == selected_group_id,
                    ).with_for_update()
                )
                if saved is not None:
                    return saved.export_id, self._stored_file(session, saved).original_filename
                group = next(
                    (item for item in self._groups(session, order)
                     if item.group_id == selected_group_id), None
                )
                if group is None:
                    raise BoxLabelNotFound("box label group not found")
                if not group.eligible or group.product_id is None:
                    raise BoxLabelError(group.ineligible_reason or "box label group is incomplete")
                image: bytes | None = None
                unavailable_image = False
                for variant in sorted(
                    group.variants, key=lambda item: (item.source_sku_id, item.variant_id)
                ):
                    if variant.cached_image_key:
                        image = self._files.get(object_key=variant.cached_image_key)
                        break
                    if variant.image_source_ref:
                        unavailable_image = True
                if image is None and unavailable_image:
                    raise BoxLabelGenerationError("SKU 图片尚未可用，请稍后重试")
                values = {
                    "factory": group.factory_name,
                    "itemNo": group.item_no,
                    "productName": group.product_name,
                    "color": group.color,
                }
                filename = self._filename(order.order_no, values)
                content = self._renderer.render(values, image)
                export_id = str(uuid4())
                object_key = f"box-labels/{export_id}.xlsx"
                self._files.put(object_key=object_key, content=content, content_type=CONTRACT_MIME)
                uploaded = True
                now = datetime.now(UTC)
                stored = StoredFile(
                    bucket=self._files.bucket,
                    object_key=object_key,
                    original_filename=filename,
                    mime_type=CONTRACT_MIME,
                    size_bytes=len(content),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    uploaded_by=actor_id,
                    idempotency_key=f"box-label:{export_id}",
                    created_at=now,
                )
                session.add(stored)
                session.flush()
                session.add(BoxLabelExport(
                    export_id=export_id,
                    order_id=order_id,
                    group_id=selected_group_id,
                    factory_id=group.factory_id,
                    product_id=group.product_id,
                    color=group.color,
                    snapshot=values,
                    template_version="v1",
                    stored_file_id=stored.file_id,
                    created_by=actor_id,
                    created_at=now,
                ))
            return export_id, filename
        except Exception:
            if uploaded and object_key is not None:
                self._files.delete(object_key=object_key)
            raise

    def download(self, *, actor_id: str, export_id: str) -> tuple[str, bytes, str]:
        with self._sessions() as session:
            self._require_admin(session, actor_id)
            saved = session.get(BoxLabelExport, export_id)
            if saved is None:
                raise BoxLabelNotFound("box label export not found")
            stored = self._stored_file(session, saved)
            content = self._files.get(object_key=stored.object_key)
            if hashlib.sha256(content).hexdigest() != stored.content_sha256:
                raise BoxLabelGenerationError("box label checksum mismatch")
            return stored.original_filename, content, stored.mime_type

    def _stored_file(self, session: Session, saved: BoxLabelExport) -> StoredFile:
        stored = session.scalar(
            select(StoredFile).where(StoredFile.file_id == saved.stored_file_id).with_for_update()
        )
        if stored is None or stored.bucket != self._files.bucket:
            raise BoxLabelNotFound("box label file not found")
        return stored

    @staticmethod
    def _filename(order_no: str, values: dict[str, str]) -> str:
        raw = f"{order_no}_{values['factory']}_{values['productName']}_{values['color']}"
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw).strip(" .")
        return safe[:250].rstrip(" .") + ".xlsx"
