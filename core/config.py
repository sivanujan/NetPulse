"""Configuration and settings management for NetPulse."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

# Default network measurement constants
DEFAULT_PING_HOSTS: List[str] = ["8.8.8.8", "1.1.1.1"]
DEFAULT_PING_COUNT: int = 4
DEFAULT_CHECK_INTERVAL_SEC: int = 30
DEFAULT_SPEED_INTERVAL_SEC: int = 60 * 60  # Default speed-test interval = 60 minutes
DEFAULT_SPEED_URL: str = "https://speed.cloudflare.com/__down?bytes=5000000"
DEFAULT_SPEED_MAX_SEC: int = 10
DEFAULT_SPEED_FAST_THRESHOLD_MBPS: float = 10.0
DEFAULT_SPEED_FAST_MAX_BYTES: int = 10_000_000  # Cap fast-link download at 10 MB
DEFAULT_ISP_INTERVAL_SEC: int = 120
DEFAULT_ADAPTER_INTERVAL_SEC: int = 300
DEFAULT_DNS_TEST_HOST: str = "www.google.com"

# Traffic classification thresholds
DEFAULT_BUSY_KBPS: float = 300.0
DEFAULT_HIGH_UPLOAD_KBPS: float = 500.0
DEFAULT_HIGH_UPLOAD_DURATION_SEC: int = 300

# Ping latency quality thresholds (ms)
LATENCY_GREEN_MAX: float = 100.0
LATENCY_AMBER_MAX: float = 300.0
LOSS_AMBER_MAX: float = 25.0

# Notification rate limits (seconds)
TOAST_DOWN_DELAY_SEC: int = 60
TOAST_BAD_DELAY_SEC: int = 300
TOAST_RATE_LIMIT_SEC: int = 900

# CSV file headers
NET_HEADER: List[str] = [
    "time",
    "latency_ms",
    "loss_pct",
    "dns_ms",
    "status",
    "conn",
    "network",
    "isp",
    "wifi_signal",
    "pc_down_kbps",
    "pc_up_kbps",
    "local_ip",
]

SPEED_HEADER: List[str] = [
    "time",
    "download_mbps",
    "conn",
    "network",
    "isp",
]

TFMT: str = "%Y-%m-%d %H:%M:%S"


@dataclass
class Config:
    """User-configurable settings for NetPulse."""

    ping_hosts: List[str] = field(default_factory=lambda: list(DEFAULT_PING_HOSTS))
    ping_count: int = DEFAULT_PING_COUNT
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC
    speed_interval_sec: int = DEFAULT_SPEED_INTERVAL_SEC
    speed_max_bytes: int = 5_000_000
    speed_max_sec: int = DEFAULT_SPEED_MAX_SEC
    data_saver: bool = False
    busy_kbps: float = DEFAULT_BUSY_KBPS
    high_upload_kbps: float = DEFAULT_HIGH_UPLOAD_KBPS
    theme: str = "dark"
    start_with_windows: bool = False
    widget_visible: bool = True
    widget_always_on_top: bool = True
    widget_opacity: float = 0.95
    widget_locked: bool = False
    widget_compact: bool = False
    widget_click_through: bool = False
    widget_pos_x: int = -1
    widget_pos_y: int = -1
    user_name: str = ""
    user_address: str = ""
    data_folder: str = ""
    do_not_disturb: bool = False
    alert_latency_ms: float = 300.0
    alert_loss_pct: float = 25.0
    alert_degraded_min: int = 5

    @classmethod
    def load(cls, file_path: str) -> Config:
        """Load settings from JSON file, falling back to defaults if not found."""
        if not os.path.exists(file_path):
            return cls()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Filter out unknown keys for forward compatibility
            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**filtered)
        except Exception:
            return cls()

    def save(self, file_path: str) -> None:
        """Save settings to JSON file."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception:
            pass

