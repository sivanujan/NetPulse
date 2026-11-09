"""Notification management for NetPulse: rate-limited Windows toast alerts for outages, latency, network shifts, and high upload."""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

from core.config import (
    DEFAULT_HIGH_UPLOAD_DURATION_SEC,
    DEFAULT_HIGH_UPLOAD_KBPS,
    LATENCY_AMBER_MAX,
    LOSS_AMBER_MAX,
    TOAST_BAD_DELAY_SEC,
    TOAST_DOWN_DELAY_SEC,
    TOAST_RATE_LIMIT_SEC,
    Config,
)
from core.storage import NetRecord


class NotificationManager:
    """Evaluates network events and triggers rate-limited Windows toast notifications."""

    def __init__(
        self,
        config: Config,
        show_toast_callback: Callable[[str, str, str, Optional[Callable[[], None]]], None],
    ) -> None:
        self.config = config
        self.show_toast_callback = show_toast_callback

        # State tracking
        self.down_start_ts: Optional[float] = None
        self.down_alert_sent = False

        self.bad_start_ts: Optional[float] = None
        self.bad_alert_sent = False

        self.upload_start_ts: Optional[float] = None
        self.upload_alert_sent = False

        self.last_network: Optional[str] = None
        self.last_conn: Optional[str] = None

        # Rate-limiting: kind -> timestamp of last notification
        self.last_toast_ts: Dict[str, float] = {}

    def _can_send(self, kind: str, now_ts: float) -> bool:
        """Check if notifications are allowed (respects Do Not Disturb and 15-min rate limit)."""
        if self.config.do_not_disturb:
            return False
        last_t = self.last_toast_ts.get(kind, 0.0)
        return (now_ts - last_t) >= TOAST_RATE_LIMIT_SEC

    def _record_sent(self, kind: str, now_ts: float) -> None:
        """Record timestamp of dispatched notification."""
        self.last_toast_ts[kind] = now_ts

    @staticmethod
    def open_resource_monitor() -> None:
        """Launch Windows Resource Monitor (resmon.exe)."""
        if sys.platform.startswith("win"):
            try:
                subprocess.Popen(["resmon.exe"], shell=False)
            except Exception:
                pass

    def evaluate_sample(self, record: NetRecord) -> None:
        """Evaluate network sample and dispatch alerts if thresholds are met."""
        now_ts = time.time()
        status = record.status

        # ---------------- 1. Internet DOWN & Restored ----------------
        if status == "DOWN":
            if self.down_start_ts is None:
                self.down_start_ts = now_ts
                self.down_alert_sent = False
            elif (now_ts - self.down_start_ts) >= TOAST_DOWN_DELAY_SEC and not self.down_alert_sent:
                if self._can_send("down", now_ts):
                    self.show_toast_callback(
                        "down",
                        "Internet Connection Down",
                        f"Internet has been unreachable for > 60s on {record.network} ({record.conn}).",
                        None,
                    )
                    self._record_sent("down", now_ts)
                    self.down_alert_sent = True
        else:
            # Check if recovering from DOWN
            if self.down_start_ts is not None:
                downtime_sec = max(0.0, now_ts - self.down_start_ts)
                if self.down_alert_sent or downtime_sec >= TOAST_DOWN_DELAY_SEC:
                    if self._can_send("restored", now_ts):
                        mins = int(downtime_sec // 60)
                        secs = int(downtime_sec % 60)
                        dur_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
                        self.show_toast_callback(
                            "restored",
                            "Internet Restored",
                            f"Connection restored after {dur_str} downtime on {record.network}.",
                            None,
                        )
                        self._record_sent("restored", now_ts)
                self.down_start_ts = None
                self.down_alert_sent = False

        # ---------------- 2. Degraded / BAD (> 300 ms or loss >= 25% for 5+ min) ----------------
        is_bad = (
            status == "BAD"
            or (record.latency_ms is not None and record.latency_ms > LATENCY_AMBER_MAX)
            or record.loss_pct >= LOSS_AMBER_MAX
        )
        if is_bad and status != "DOWN":
            if self.bad_start_ts is None:
                self.bad_start_ts = now_ts
                self.bad_alert_sent = False
            elif (now_ts - self.bad_start_ts) >= TOAST_BAD_DELAY_SEC and not self.bad_alert_sent:
                if self._can_send("bad", now_ts):
                    lat_str = f"{record.latency_ms:.0f} ms" if record.latency_ms is not None else "---"
                    self.show_toast_callback(
                        "bad",
                        "Network Quality Degraded",
                        f"High latency ({lat_str}) or packet loss ({record.loss_pct:.0f}%) for over 5 minutes.",
                        None,
                    )
                    self._record_sent("bad", now_ts)
                    self.bad_alert_sent = True
        else:
            self.bad_start_ts = None
            self.bad_alert_sent = False

        # ---------------- 3. Provider or Connection Changed ----------------
        if self.last_network is not None and self.last_conn is not None:
            net_changed = record.network != self.last_network and record.network != "unknown"
            conn_changed = record.conn != self.last_conn and record.conn != "unknown"
            if (net_changed or conn_changed) and status != "DOWN":
                if self._can_send("network_change", now_ts):
                    msg = f"Switched to {record.network} via {record.conn}."
                    self.show_toast_callback(
                        "network_change",
                        "Connection Changed",
                        msg,
                        None,
                    )
                    self._record_sent("network_change", now_ts)

        if record.network and record.network != "unknown":
            self.last_network = record.network
        if record.conn and record.conn != "unknown":
            self.last_conn = record.conn

        # ---------------- 4. High PC Upload (> 500 kbps for 5+ min) ----------------
        up_kbps = record.pc_up_kbps or 0.0
        if up_kbps >= self.config.high_upload_kbps:
            if self.upload_start_ts is None:
                self.upload_start_ts = now_ts
                self.upload_alert_sent = False
            elif (now_ts - self.upload_start_ts) >= DEFAULT_HIGH_UPLOAD_DURATION_SEC and not self.upload_alert_sent:
                if self._can_send("high_upload", now_ts):
                    rate_str = f"{up_kbps / 1000.0:.1f} Mbps" if up_kbps >= 1000 else f"{up_kbps:.0f} kbps"
                    self.show_toast_callback(
                        "high_upload",
                        "High Upload Detected",
                        f"Something is uploading ({rate_str}) for 5+ minutes. Click to inspect Resource Monitor.",
                        self.open_resource_monitor,
                    )
                    self._record_sent("high_upload", now_ts)
                    self.upload_alert_sent = True
        else:
            self.upload_start_ts = None
            self.upload_alert_sent = False

