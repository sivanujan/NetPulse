"""NetPulse Core Module: configuration, measurement, storage, and statistics."""

from typing import Any

from core.config import Config, DEFAULT_BUSY_KBPS, DEFAULT_CHECK_INTERVAL_SEC, TFMT
from core.stats import (
    GapEvent,
    OutageEvent,
    SummaryStats,
    best_and_worst_hours,
    busy_vs_idle,
    compare_networks,
    find_gaps,
    find_outages,
    hourly_distribution,
    summarize,
)
from core.storage import NetRecord, SpeedRecord, Storage


def __getattr__(name: str) -> Any:
    """Lazy-load monitor objects to prevent runpy circular import warnings."""
    if name in {
        "MonitorEngine",
        "TrafficTracker",
        "dns_lookup_time",
        "get_adapter_connection",
        "get_local_ip",
        "get_wifi_info",
        "lookup_isp_from_ip",
        "ping_host",
        "ping_multiple",
        "run_speed_test",
    }:
        import core.monitor as m

        return getattr(m, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "Config",
    "DEFAULT_BUSY_KBPS",
    "DEFAULT_CHECK_INTERVAL_SEC",
    "TFMT",
    "Storage",
    "NetRecord",
    "SpeedRecord",
    "MonitorEngine",
    "TrafficTracker",
    "ping_host",
    "ping_multiple",
    "dns_lookup_time",
    "get_local_ip",
    "get_wifi_info",
    "get_adapter_connection",
    "lookup_isp_from_ip",
    "run_speed_test",
    "SummaryStats",
    "OutageEvent",
    "GapEvent",
    "summarize",
    "find_outages",
    "find_gaps",
    "hourly_distribution",
    "best_and_worst_hours",
    "compare_networks",
    "busy_vs_idle",
]
