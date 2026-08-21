from collections.abc import Callable, Mapping
from typing import Any

from app.modules.product_sync.service import ProductImageService, ProductSyncService


class ProductWorkerHandlers:
    def __init__(
        self,
        *,
        sync_service: ProductSyncService,
        image_service: ProductImageService | None = None,
        worker_id: str = "product-worker",
    ) -> None:
        self._sync_service = sync_service
        self._image_service = image_service
        self._worker_id = worker_id

    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], None]]:
        handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "product-sync-initial": self._run_initial,
            "product-sync-incremental": self._run_incremental,
        }
        if self._image_service is not None:
            handlers["product-image-cache"] = self._image_service.process
        return handlers

    def _run_initial(self, payload: dict[str, Any]) -> None:
        self._sync_service.run_initial(
            request_id=self._request_id(payload),
            worker_id=self._worker_id,
            actor_id=self._actor_id(payload),
        )

    def _run_incremental(self, payload: dict[str, Any]) -> None:
        self._sync_service.run_incremental(
            request_id=self._request_id(payload),
            worker_id=self._worker_id,
            actor_id=self._actor_id(payload),
        )

    @staticmethod
    def _request_id(payload: dict[str, Any]) -> str:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("product_sync_job_payload_invalid")
        return request_id

    @staticmethod
    def _actor_id(payload: dict[str, Any]) -> str | None:
        actor_id = payload.get("actor_id")
        if actor_id is None:
            return None
        if not isinstance(actor_id, str) or not actor_id:
            raise ValueError("product_sync_job_payload_invalid")
        return actor_id
