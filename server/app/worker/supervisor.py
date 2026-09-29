import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from threading import Event

from app.logging import StructuredLogger

STOP_GRACE_SECONDS = 30


def supervise(roles: Sequence[str], *, grace_seconds: float = STOP_GRACE_SECONDS) -> int:
    logger = StructuredLogger()
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopping.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stopping.set())
    children: dict[str, subprocess.Popen[bytes]] = {}
    failure = False
    try:
        for role in roles:
            children[role] = subprocess.Popen(
                [sys.executable, "-m", "app.worker", "--role", role]
            )
            logger.event("worker.child_started", fields={"role": role,
                                                         "pid": children[role].pid})
        while not stopping.wait(0.1):
            for role, child in children.items():
                code = child.poll()
                if code is not None:
                    logger.event("worker.child_exited", level="ERROR",
                                 fields={"role": role, "exitCode": code})
                    failure = True
                    stopping.set()
                    break
    finally:
        for child in children.values():
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + grace_seconds
        for role, child in children.items():
            while child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            if child.poll() is None:
                logger.event("worker.child_timeout", level="ERROR",
                             fields={"role": role, "pid": child.pid})
                child.kill()
            child.wait()
    return 1 if failure else 0
