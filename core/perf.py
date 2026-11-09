"""Performance timing and logging utilities for NetPulse."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import Generator, Optional

logger = logging.getLogger("NetPulse")

# Ensure handler is configured so [PERF] entries always write to netpulse.log
if not logger.handlers:
    logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(
            "netpulse.log", maxBytes=5_000_000, backupCount=1, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception:
        pass


@contextmanager
def log_timing(label: str, threshold_ms: float = 0.0) -> Generator[None, None, None]:
    """Measure elapsed time of a code block and log to netpulse.log.

    Args:
        label: Descriptive name of the operation being measured.
        threshold_ms: Minimum duration in milliseconds to trigger logging (0.0 logs all).
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if dt_ms >= threshold_ms:
            logger.info(f"[PERF] {label} took {dt_ms:.1f} ms")
