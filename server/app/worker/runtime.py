from collections.abc import Callable, Mapping
from datetime import datetime
from threading import Event
from typing import Any

from app.modules.infrastructure import InfrastructureStore, utc_now

JobHandler = Callable[[dict[str, Any]], None]


class Worker:
    def __init__(
        self,
        *,
        store: InfrastructureStore,
        worker_id: str,
        handlers: Mapping[str, JobHandler],
    ) -> None:
        self._store = store
        self._worker_id = worker_id
        self._handlers = handlers

    def run_once(self, *, now: datetime | None = None) -> bool:
        claimed = self._store.claim_next_job(worker_id=self._worker_id, now=now or utc_now())
        if claimed is None:
            return False
        handler = self._handlers.get(claimed.job_type)
        if handler is None:
            self._store.fail_job(job_id=claimed.id, error_code="handler_not_registered")
            return True
        try:
            handler(claimed.payload)
        except Exception:
            self._store.fail_job(job_id=claimed.id, error_code="handler_failed")
            return True
        self._store.complete_job(job_id=claimed.id)
        return True

    def run(self, *, stop_event: Event, poll_interval: float = 1.0) -> int:
        processed = 0
        while not stop_event.is_set():
            if self.run_once():
                processed += 1
                continue
            stop_event.wait(poll_interval)
        return processed
