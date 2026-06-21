from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def heartbeat(
    enabled: bool,
    label: str,
    interval_seconds: float = 10.0,
    writer: Callable[[str], None] = print,
) -> Iterator[None]:
    """Print periodic progress without exposing hidden model reasoning."""
    if not enabled:
        yield
        return

    stop = threading.Event()
    started = time.monotonic()

    def report() -> None:
        while not stop.wait(interval_seconds):
            elapsed = round(time.monotonic() - started)
            writer(f"[진행] {label} · {elapsed}초 경과 · 응답 대기 상태 정상")

    worker = threading.Thread(target=report, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1)
        elapsed = round(time.monotonic() - started, 1)
        writer(f"[완료] {label} 처리 시간: {elapsed}초")
