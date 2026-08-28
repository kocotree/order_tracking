from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from app.modules.infrastructure import InfrastructureStore, utc_now
from app.modules.notifications_audit.service import NotificationsAuditService


class NotificationWorkerHandlers:
    def __init__(
        self,
        *,
        service: NotificationsAuditService,
        store: InfrastructureStore,
    ) -> None:
        self._service = service
        self._store = store

    def ensure_due_scan_job(self, *, business_date: date, now: datetime | None = None) -> int:
        return self._store.enqueue_job(
            job_type="notification_due_scan",
            dedupe_key=f"notification-due-scan:{business_date.isoformat()}",
            payload={"businessDate": business_date.isoformat()},
            available_at=now or utc_now(),
        )

    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], None]]:
        return {"notification_due_scan": self.scan_due_reminders}

    def scan_due_reminders(self, payload: dict[str, Any]) -> None:
        business_date = date.fromisoformat(str(payload["businessDate"]))
        self._service.scan_due_reminders(business_date=business_date)
