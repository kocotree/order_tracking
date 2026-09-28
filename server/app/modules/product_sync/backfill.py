import hashlib
import json
from dataclasses import asdict
from io import BytesIO
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import (
    PrivateFileNotFound,
    PrivateFileStore,
    PrivateFileStoreUnavailable,
)
from app.adapters.product import (
    JstProductSource,
    ProductImageCacheError,
    ProductImageStore,
    ProductSourceError,
)
from app.db.models import AuditLog, Product, ProductVariant
from app.modules.product_sync.service import ProductSyncService


class ProductImageBackfill:
    def __init__(
        self, sessions: sessionmaker[Session], *, source: JstProductSource,
        file_store: PrivateFileStore, image_store: ProductImageStore,
    ) -> None:
        self._sessions = sessions
        self._sync = ProductSyncService(sessions, source=source)
        self._files = file_store
        self._images = image_store

    @staticmethod
    def _state(variant: ProductVariant) -> tuple[Any, ...]:
        return (variant.product_id, variant.source_sku_id, variant.source_modified_at,
                variant.image_source_ref, variant.image_object_key, variant.image_revision,
                variant.image_cache_status, variant.image_cache_error,
                variant.image_source_modified_at)

    def run(
        self, *, request_id: str, expected_digest: str | None = None, actor_id: str | None = None,
    ) -> dict[str, Any]:
        with self._sessions() as session:
            styles = session.scalars(
                select(Product.source_i_id).order_by(Product.source_i_id)
            ).all()
        plans: list[dict[str, Any]] = []
        for style in styles:
            source_error = None
            try:
                records = self._sync.fetch_targeted_records(name=None, i_id=style)
            except ProductSourceError:
                records = ()
                source_error = "product_backfill_source_failed"
            by_sku = {record.sku_id: record for record in records}
            with self._sessions() as session:
                product = session.scalar(select(Product).where(Product.source_i_id == style))
                if product is None:
                    raise ProductSourceError("product_backfill_scope_changed")
                variants = session.scalars(select(ProductVariant).where(
                    ProductVariant.product_id == product.product_id,
                ).order_by(ProductVariant.source_sku_id)).all()
                for variant in variants:
                    record = by_sku.get(variant.source_sku_id)
                    plan: dict[str, Any] = {
                        "variantId": variant.variant_id, "skuId": variant.source_sku_id,
                        "iId": style, "state": self._state(variant),
                        "source": asdict(record) if record else None,
                        "objectKey": None, "action": "unmatched",
                    }
                    if source_error:
                        plan["action"] = "failed"
                        plan["error"] = source_error
                    if record is not None:
                        if record.source_modified_at < max(
                            variant.source_modified_at,
                            variant.image_source_modified_at or variant.source_modified_at,
                        ):
                            plan["action"] = "failed"
                            plan["error"] = "product_backfill_older_source"
                        elif record.pic is None:
                            plan["action"] = "missing"
                        else:
                            # ponytail: 单款内逐 SKU 扫描；超大规格款式再按来源建立索引。
                            keys = [
                                candidate.image_object_key for candidate in [variant, *variants]
                                if candidate.image_source_ref == record.pic
                                and candidate.image_object_key is not None
                            ]
                            if product.image_source_ref == record.pic and product.image_object_key:
                                keys.append(product.image_object_key)
                            plan["action"] = "download"
                            for key in dict.fromkeys(keys):
                                try:
                                    content = self._files.get(object_key=key)
                                    with Image.open(BytesIO(content)) as image:
                                        image.verify()
                                except (PrivateFileNotFound, UnidentifiedImageError, OSError):
                                    continue
                                except PrivateFileStoreUnavailable:
                                    plan["action"] = "failed"
                                    plan["error"] = "product_image_store_unavailable"
                                    break
                                else:
                                    plan["action"] = "reused"
                                    plan["objectKey"] = key
                                    break
                    plans.append(plan)
        digest = hashlib.sha256(json.dumps(
            plans, sort_keys=True, default=str, ensure_ascii=False,
        ).encode()).hexdigest()
        if expected_digest is not None and digest != expected_digest:
            raise ProductSourceError("product_preview_changed")
        result: dict[str, Any] = {
            "digest": digest, "applied": expected_digest is not None, "styles": len(styles),
            "matched": sum(plan["source"] is not None for plan in plans),
            "reused": 0, "download": 0, "downloaded": 0,
            "missing": 0, "failed": 0, "unmatched": 0, "items": [],
        }
        for plan in plans:
            action = plan["action"]
            if expected_digest is not None and (
                action not in {"unmatched", "failed"}
                or plan.get("error") == "product_image_store_unavailable"
            ):
                with self._sessions() as session, session.begin():
                    locked = session.get(ProductVariant, plan["variantId"], with_for_update=True)
                    if locked is None or self._state(locked) != plan["state"]:
                        raise ProductSourceError("product_backfill_state_changed")
                    source_ref = plan["source"]["pic"]
                    object_key = plan["objectKey"]
                    if action == "download":
                        try:
                            cached = self._images.cache(
                                source_ref=source_ref,
                                object_key=f"products/backfill/{uuid4()}",
                            )
                        except ProductImageCacheError:
                            action = "failed"
                            plan["error"] = "product_image_cache_failed"
                        else:
                            action = "downloaded"
                            object_key = cached.object_key
                    if (locked.image_source_ref != source_ref
                            or locked.image_object_key != object_key
                            or locked.image_cache_status != (
                                "failed" if action == "failed" else
                                "missing" if action == "missing" else "cached"
                            )):
                        locked.image_revision = str(uuid4())
                    locked.image_source_ref = source_ref
                    locked.image_source_modified_at = plan["source"]["source_modified_at"]
                    locked.image_object_key = object_key
                    locked.image_cache_status = (
                        "failed" if action == "failed" else
                        "missing" if action == "missing" else "cached"
                    )
                    locked.image_cache_error = plan.get("error")
                    session.add(AuditLog(
                        request_id=request_id, action="product_image.backfilled",
                        target_type="product_variant", target_id=locked.variant_id,
                        changes={"result": action}, source_terminal="internal_cli",
                        actor_id=actor_id,
                    ))
            result[action] += 1
            result["items"].append({
                "iId": plan["iId"], "skuId": plan["skuId"], "action": action,
                **({"error": plan["error"]} if "error" in plan else {}),
            })
        return result
