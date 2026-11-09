"""Thread pool task worker for non-blocking UI background computations."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

logger = logging.getLogger("netpulse")


class WorkerSignals(QObject):
    """Signals for background async workers."""

    finished = Signal(object)
    error = Signal(str)


class AsyncWorker(QRunnable):
    """QRunnable task executing a function on QThreadPool and signaling results back."""

    _active_workers: set[AsyncWorker] = set()

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)
        AsyncWorker._active_workers.add(self)

    def run(self) -> None:
        """Execute the function in the thread pool."""
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            logger.error(f"[AsyncWorker] Exception in task {self.fn}: {exc}", exc_info=True)
            self.signals.error.emit(str(exc))
        finally:
            AsyncWorker._active_workers.discard(self)
