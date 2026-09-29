import json
from datetime import datetime
from io import StringIO
from types import SimpleNamespace

from app.logging import StructuredLogger
from app.worker.runtime import Worker


def test_worker_failure_logs_identity_and_result_without_payload_or_error_text() -> None:
    class Store:
        def __init__(self) -> None:
            self.claimed = SimpleNamespace(
                id=42, job_type="incoming_diff.recognize", attempts=1,
                payload={"secret": "sensitive workbook text"},
            )

        def claim_next_job(self, *, worker_id: str, now: datetime,
                           job_types: tuple[str, ...]) -> SimpleNamespace:
            assert job_types == ("incoming_diff.recognize",)
            return self.claimed

        def retry_job(self, *, job_id: int, error_code: str,
                      available_at: datetime) -> None:
            assert job_id == 42
            assert error_code == "handler_failed"

    def fail(_payload: dict[str, object]) -> None:
        raise ValueError("token=do-not-log")

    stream = StringIO()
    worker = Worker(store=Store(), worker_id="test-worker",  # type: ignore[arg-type]
                    handlers={"incoming_diff.recognize": fail},
                    retry_limits={"incoming_diff.recognize": 3},
                    event_logger=StructuredLogger(stream=stream))

    assert worker.run_once(now=datetime(2026, 9, 29, 9, 0)) is True
    event = json.loads(stream.getvalue())
    assert event["event"] == "job.failed"
    assert event["jobId"] == 42
    assert event["jobType"] == "incoming_diff.recognize"
    assert event["attempt"] == 1
    assert event["status"] == "pending"
    assert event["exceptionType"] == "ValueError"
    assert "do-not-log" not in stream.getvalue()
    assert "sensitive workbook text" not in stream.getvalue()
