"""Network measurement engine for NetPulse: ping, loss, DNS, adapter, ISP, traffic, and speed test."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.config import (
    DEFAULT_ADAPTER_INTERVAL_SEC,
    DEFAULT_BUSY_KBPS,
    DEFAULT_CHECK_INTERVAL_SEC,
    DEFAULT_DNS_TEST_HOST,
    DEFAULT_HIGH_UPLOAD_DURATION_SEC,
    DEFAULT_HIGH_UPLOAD_KBPS,
    DEFAULT_ISP_INTERVAL_SEC,
    DEFAULT_PING_COUNT,
    DEFAULT_PING_HOSTS,
    DEFAULT_SPEED_FAST_MAX_BYTES,
    DEFAULT_SPEED_FAST_THRESHOLD_MBPS,
    DEFAULT_SPEED_INTERVAL_SEC,
    DEFAULT_SPEED_MAX_SEC,
    DEFAULT_SPEED_URL,
    TFMT,
    Config,
)
from core.storage import NetRecord, SpeedRecord, Storage

IS_WIN = sys.platform.startswith("win")
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

logger = logging.getLogger("NetPulse")


def setup_logger(log_file_path: str = "netpulse.log") -> logging.Logger:
    """Configure rotating file logger (max 5 MB)."""
    log = logging.getLogger("NetPulse")
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = RotatingFileHandler(
            log_file_path, maxBytes=5_000_000, backupCount=1, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log


def run_command(cmd: List[str], timeout: float = 15.0) -> str:
    """Execute a system command without showing a console window."""
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return res.stdout
    except Exception as e:
        logger.debug(f"Command {' '.join(cmd)} failed: {e}")
        return ""


# ================= Measurements =================


def ping_host(
    host: str, count: int = DEFAULT_PING_COUNT, timeout_ms: int = 2000
) -> Tuple[Optional[float], float]:
    """Ping a single host. Return (avg_latency_ms or None, loss_percent)."""
    if IS_WIN:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), host]

    out = run_command(cmd, timeout=count * 3 + 5)
    times = [float(t) for t in re.findall(r"time[=<]\s*([\d.]+)\s*ms", out, re.I)]
    loss = 100.0 * (count - len(times)) / count
    avg_lat = (sum(times) / len(times)) if times else None
    return avg_lat, loss


def ping_multiple(
    hosts: List[str], count: int = DEFAULT_PING_COUNT, timeout_ms: int = 2000
) -> Dict[str, Any]:
    """Ping multiple hosts (e.g. 8.8.8.8 and 1.1.1.1).

    Loss = the BETTER host's loss (so one blocked host does not fake 50% loss).
    Latency = average of reachable hosts.
    Status = DOWN if loss >= 100%, BAD if loss >= 25% or latency > 300 ms, else OK.
    """
    if not hosts:
        hosts = list(DEFAULT_PING_HOSTS)

    latencies: List[float] = []
    losses: List[float] = []
    per_host: Dict[str, Dict[str, Any]] = {}

    for h in hosts:
        lat, loss = ping_host(h, count=count, timeout_ms=timeout_ms)
        per_host[h] = {"latency_ms": lat, "loss_pct": loss}
        if lat is not None:
            latencies.append(lat)
        losses.append(loss)

    # Better host's loss
    better_loss = min(losses) if losses else 100.0
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else None

    if better_loss >= 100.0 or not latencies:
        status = "DOWN"
    elif better_loss >= 25.0 or (avg_lat is not None and avg_lat > 300.0):
        status = "BAD"
    else:
        status = "OK"

    return {
        "latency_ms": avg_lat,
        "loss_pct": better_loss,
        "status": status,
        "per_host": per_host,
    }


def dns_lookup_time(
    test_host: str = DEFAULT_DNS_TEST_HOST, timeout: float = 5.0
) -> Optional[float]:
    """Measure DNS resolution duration in milliseconds."""
    t0 = time.perf_counter()
    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(test_host)
        socket.setdefaulttimeout(old_timeout)
        return round((time.perf_counter() - t0) * 1000.0, 1)
    except Exception:
        return None


# ================= Connection & Provider =================


def get_local_ip() -> str:
    """Determine the local IP of the adapter routing to the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def get_wifi_info() -> Tuple[str, str]:
    """Query connected Wi-Fi (SSID, signal%) on Windows."""
    if not IS_WIN:
        return "", ""
    out = run_command(["netsh", "wlan", "show", "interfaces"], timeout=8)
    ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    sig_match = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M)
    ssid = ssid_match.group(1).strip() if ssid_match else ""
    signal = sig_match.group(1).strip() if sig_match else ""
    return ssid, signal


def get_adapter_connection(ip: str) -> str:
    """Return adapter type label: 'iPhone USB', 'Android USB', 'WiFi: SSID', or 'Ethernet'."""
    if not ip:
        return "no connection"
    if not IS_WIN:
        return "unknown"

    ps_script = (
        f"Get-NetIPAddress -IPAddress '{ip}' -ErrorAction SilentlyContinue | Get-NetAdapter | "
        f"Select-Object -First 1 Name,InterfaceDescription,PhysicalMediaType | ConvertTo-Json"
    )
    out = run_command(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        timeout=20,
    )
    info: Dict[str, Any] = {}
    try:
        info = json.loads(out)
    except Exception:
        pass

    desc = f"{info.get('Name', '')} {info.get('InterfaceDescription', '')}".lower()
    media = str(info.get("PhysicalMediaType", "")).lower()

    if "apple mobile device" in desc:
        return "iPhone USB"
    if "rndis" in desc or "remote ndis" in desc:
        return "Android USB"
    if any(k in media or k in desc for k in ["802.11", "wi-fi", "wireless", "wlan"]):
        ssid, _ = get_wifi_info()
        return f"WiFi: {ssid}" if ssid else "WiFi"
    if info:
        return "Ethernet"
    return "unknown"


def clean_provider_name(org: str) -> str:
    """Map raw ISP/AS organization string to clean provider name."""
    o = org.lower()
    mapping = [
        ("dialog", "Dialog"),
        ("mobitel", "Mobitel"),
        ("hutch", "Hutch"),
        ("airtel", "Airtel"),
        ("bharti", "Airtel"),
        ("sri lanka telecom", "SLT"),
        ("slt", "SLT"),
        ("lanka bell", "Lanka Bell"),
        ("starlink", "Starlink"),
        ("spacex", "Starlink"),
    ]
    for key, clean_name in mapping:
        if key in o:
            return clean_name
    return re.sub(r"^AS\d+\s+", "", org).strip()[:30] or "unknown"


def lookup_isp_from_ip() -> Optional[Tuple[str, str]]:
    """Query public IP org from ipinfo.io. Return (short_provider, full_org)."""
    try:
        req = urllib.request.Request(
            "https://ipinfo.io/json", headers={"User-Agent": "NetPulse"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            org = data.get("org", "")
            return clean_provider_name(org), org
    except Exception as e:
        logger.debug(f"ISP lookup error: {e}")
        return None


# ================= PC Traffic Measurement =================


class TrafficTracker:
    """Measures PC's upload and download traffic rate on the active adapter."""

    def __init__(self) -> None:
        self.prev_rx: Optional[int] = None
        self.prev_tx: Optional[int] = None
        self.prev_time: float = time.time()
        self.last_ip: str = ""
        self._psutil_available: bool = False
        self._check_psutil()

    def _check_psutil(self) -> None:
        try:
            import psutil  # noqa: F401

            self._psutil_available = True
        except ImportError:
            self._psutil_available = False

    def _get_bytes(self, active_ip: str) -> Optional[Tuple[int, int]]:
        """Fetch total (bytes_recv, bytes_sent) for active adapter or global fallback."""
        if self._psutil_available:
            try:
                import psutil

                # Per-NIC match by active IP
                if active_ip:
                    addrs = psutil.net_if_addrs()
                    for nic_name, nic_addrs in addrs.items():
                        for addr in nic_addrs:
                            if addr.address == active_ip:
                                pernic = psutil.net_io_counters(pernic=True)
                                if nic_name in pernic:
                                    cnt = pernic[nic_name]
                                    return cnt.bytes_recv, cnt.bytes_sent
                # Global fallback
                c = psutil.net_io_counters()
                return c.bytes_recv, c.bytes_sent
            except Exception:
                pass

        # Windows netstat -e fallback
        if IS_WIN:
            out = run_command(["netstat", "-e"], timeout=8)
            m = re.search(r"^\s*Bytes\s+(\d+)\s+(\d+)", out, re.M)
            if m:
                return int(m.group(1)), int(m.group(2))

        return None

    def update(
        self, active_ip: str, speed_test_bytes: int = 0
    ) -> Tuple[Optional[float], Optional[float]]:
        """Calculate (down_kbps, up_kbps) since last update.

        Protects against counter resets, negative rates, and spikes > 1 Gbps.
        Subtracts speed test bytes from rx to avoid self-counting.
        """
        now = time.time()
        cur_bytes = self._get_bytes(active_ip)
        if not cur_bytes:
            self.prev_rx = None
            self.prev_tx = None
            self.prev_time = now
            return None, None

        cur_rx, cur_tx = cur_bytes
        down_kbps: Optional[float] = None
        up_kbps: Optional[float] = None

        # Reset baseline on adapter change or initial tick
        if self.prev_rx is not None and self.prev_tx is not None and active_ip == self.last_ip:
            elapsed = max(now - self.prev_time, 0.5)
            delta_rx = cur_rx - self.prev_rx - speed_test_bytes
            delta_tx = cur_tx - self.prev_tx

            # Sanity checks: ignore negative counter wraps or > 1 Gbps spikes
            max_bytes_per_sec = 125_000_000  # 1 Gbps in bytes/sec
            if 0 <= delta_rx <= (max_bytes_per_sec * elapsed):
                down_kbps = round(delta_rx * 8.0 / elapsed / 1000.0, 1)
            if 0 <= delta_tx <= (max_bytes_per_sec * elapsed):
                up_kbps = round(delta_tx * 8.0 / elapsed / 1000.0, 1)

        self.prev_rx = cur_rx
        self.prev_tx = cur_tx
        self.prev_time = now
        self.last_ip = active_ip
        return down_kbps, up_kbps


# ================= Speed Test =================


def run_speed_test(
    url: str = DEFAULT_SPEED_URL,
    max_sec: int = DEFAULT_SPEED_MAX_SEC,
    max_bytes: int = 5_000_000,
    last_mbps: Optional[float] = None,
) -> Tuple[float, int]:
    """Download chunks from speed test URL.

    Returns (Mbps, total_bytes_downloaded).
    If last_mbps > 10 Mbps, allows a larger download payload.
    """
    effective_url = url
    effective_max_bytes = max_bytes
    if (
        last_mbps is not None
        and last_mbps > DEFAULT_SPEED_FAST_THRESHOLD_MBPS
        and "speed.cloudflare.com" in url
    ):
        effective_max_bytes = max(max_bytes, DEFAULT_SPEED_FAST_MAX_BYTES)
        effective_url = f"https://speed.cloudflare.com/__down?bytes={effective_max_bytes}"

    req = urllib.request.Request(
        effective_url, headers={"User-Agent": "NetPulse-SpeedTest"}
    )
    downloaded = 0
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            while True:
                chunk = resp.read(32 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded >= effective_max_bytes:
                    break
                if (time.perf_counter() - t0) > max_sec:
                    break
    except Exception as e:
        logger.debug(f"Speed test error: {e}")

    elapsed = max(time.perf_counter() - t0, 0.001)
    mbps = round(downloaded * 8.0 / elapsed / 1_000_000.0, 3)
    return mbps, downloaded


# ================= Monitoring Engine =================


class MonitorEngine:
    """Background monitoring service coordinating checks, state tracking, and persistence."""

    def __init__(
        self,
        storage: Optional[Storage] = None,
        config: Optional[Config] = None,
        log_path: str = "netpulse.log",
    ) -> None:
        self.storage = storage
        self.config = config or Config()
        self.log_path = log_path
        setup_logger(self.log_path)

        self.traffic = TrafficTracker()
        self._running = False
        self._paused_until: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Cached state
        self.current_ip: str = ""
        self.current_conn: str = "unknown"
        self.current_network: str = "unknown"
        self.current_isp: str = ""
        self.wifi_signal: Optional[float] = None
        self.last_status: str = "OK"
        self.last_check_record: Optional[NetRecord] = None
        self.last_speed_record: Optional[SpeedRecord] = None

        self._t_adapter: float = 0.0
        self._t_isp: float = 0.0
        self._t_speed: float = 0.0
        self._speed_bytes_last_interval: int = 0

        # High upload tracking
        self._high_upload_start: Optional[float] = None

        # Event callbacks
        self.on_net_tick: Optional[Callable[[NetRecord], None]] = None
        self.on_speed_tick: Optional[Callable[[SpeedRecord], None]] = None
        self.on_status_change: Optional[
            Callable[[str, str, NetRecord], None]
        ] = None
        self.on_network_change: Optional[
            Callable[[str, str, NetRecord], None]
        ] = None
        self.on_high_upload_alert: Optional[
            Callable[[float, float], None]
        ] = None

    def start(self) -> None:
        """Start the background monitoring thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop, name="NetPulseMonitor", daemon=True
            )
            self._thread.start()
            logger.info("Monitoring engine started.")

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Monitoring engine stopped.")

    def pause(self, duration_sec: Optional[float] = None) -> None:
        """Pause monitoring for duration_sec, or indefinitely until resume() if None."""
        with self._lock:
            if duration_sec is None:
                self._paused_until = float("inf")
            else:
                self._paused_until = time.time() + duration_sec
        logger.info(f"Monitoring paused (duration={duration_sec}s).")

    def resume(self) -> None:
        """Resume monitoring immediately."""
        with self._lock:
            self._paused_until = None
        logger.info("Monitoring resumed.")

    def is_paused(self) -> bool:
        """Check if monitoring is currently paused."""
        with self._lock:
            if self._paused_until is None:
                return False
            if time.time() < self._paused_until:
                return True
            self._paused_until = None
            return False

    def trigger_speed_test(self) -> Optional[SpeedRecord]:
        """Manually trigger a speed test immediately."""
        if self.last_status == "DOWN":
            logger.warning("Cannot run speed test: network is DOWN.")
            return None

        last_mbps = (
            self.last_speed_record.download_mbps
            if self.last_speed_record
            else None
        )
        mbps, got_bytes = run_speed_test(
            url=DEFAULT_SPEED_URL,
            max_sec=self.config.speed_max_sec,
            max_bytes=self.config.speed_max_bytes,
            last_mbps=last_mbps,
        )
        self._speed_bytes_last_interval += got_bytes
        record = SpeedRecord(
            time=datetime.now().strftime(TFMT),
            download_mbps=mbps,
            conn=self.current_conn,
            network=self.current_network,
            isp=self.current_isp,
        )
        self.last_speed_record = record
        if self.storage is not None:
            self.storage.append_speed_record(record)
        self._t_speed = time.time()
        logger.info(f"Manual speed test completed: {mbps} Mbps")

        if self.on_speed_tick:
            try:
                self.on_speed_tick(record)
            except Exception as e:
                logger.error(f"Error in on_speed_tick callback: {e}")

        return record

    def run_single_check(self, write_storage: bool = True) -> NetRecord:
        """Execute one complete network measurement cycle synchronously.

        Set write_storage=False for one-shot CLI checks that should not touch CSVs.
        """
        now_dt = datetime.now()
        now_str = now_dt.strftime(TFMT)
        now_ts = time.time()

        # 1. Connection & Adapter detection
        ip = get_local_ip()
        ip_changed = ip != self.current_ip
        old_conn = self.current_conn
        if (
            ip_changed
            or (now_ts - self._t_adapter) > DEFAULT_ADAPTER_INTERVAL_SEC
        ):
            self.current_conn = get_adapter_connection(ip)
            self._t_adapter = now_ts
            self.current_ip = ip

        if self.current_conn.startswith("WiFi"):
            _, sig_str = get_wifi_info()
            try:
                self.wifi_signal = float(sig_str) if sig_str else None
            except ValueError:
                self.wifi_signal = None
        else:
            self.wifi_signal = None

        # 2. Ping & Loss
        ping_res = ping_multiple(
            hosts=self.config.ping_hosts,
            count=self.config.ping_count,
        )
        avg_lat = ping_res["latency_ms"]
        loss_pct = ping_res["loss_pct"]
        status = ping_res["status"]

        # 3. DNS Lookup
        dns_ms = dns_lookup_time(DEFAULT_DNS_TEST_HOST)

        # 4. Provider Lookup
        # Immediately re-checks on IP change, adapter/connection change, or status recovery from DOWN;
        # otherwise re-checks at least every 2 minutes (120 s).
        conn_changed = self.current_conn != old_conn
        old_network = self.current_network
        if status != "DOWN" and (
            ip_changed
            or conn_changed
            or self.last_status == "DOWN"
            or (now_ts - self._t_isp) > DEFAULT_ISP_INTERVAL_SEC
        ):
            isp_res = lookup_isp_from_ip()
            if isp_res:
                self.current_network, self.current_isp = isp_res
                self._t_isp = now_ts

        # 5. Traffic calculation
        down_kbps, up_kbps = self.traffic.update(
            ip, speed_test_bytes=self._speed_bytes_last_interval
        )
        self._speed_bytes_last_interval = 0

        # Check for persistent high upload
        if (
            up_kbps is not None
            and up_kbps >= self.config.high_upload_kbps
        ):
            if self._high_upload_start is None:
                self._high_upload_start = now_ts
            elif (
                now_ts - self._high_upload_start
            ) >= DEFAULT_HIGH_UPLOAD_DURATION_SEC:
                if self.on_high_upload_alert:
                    try:
                        self.on_high_upload_alert(
                            up_kbps, now_ts - self._high_upload_start
                        )
                    except Exception as e:
                        logger.error(f"Error in on_high_upload callback: {e}")
        else:
            self._high_upload_start = None

        # 6. Build and store NetRecord (if storage is enabled and write_storage=True)
        record = NetRecord(
            time=now_str,
            latency_ms=avg_lat,
            loss_pct=loss_pct,
            dns_ms=dns_ms,
            status=status,
            conn=self.current_conn,
            network=self.current_network,
            isp=self.current_isp,
            wifi_signal=self.wifi_signal,
            pc_down_kbps=down_kbps,
            pc_up_kbps=up_kbps,
            local_ip=ip,
            dt=now_dt,
        )
        if write_storage and self.storage is not None:
            self.storage.append_net_record(record)
        self.last_check_record = record

        # 7. Check for status or network changes
        if status != self.last_status:
            old_s = self.last_status
            self.last_status = status
            if self.on_status_change:
                try:
                    self.on_status_change(old_s, status, record)
                except Exception as e:
                    logger.error(f"Error in on_status_change callback: {e}")
        else:
            self.last_status = status

        if old_network != self.current_network and old_network != "unknown":
            if self.on_network_change:
                try:
                    self.on_network_change(
                        old_network, self.current_network, record
                    )
                except Exception as e:
                    logger.error(f"Error in on_network_change callback: {e}")

        # 8. Check if scheduled speed test is due
        if (
            not self.config.data_saver
            and status != "DOWN"
            and (now_ts - self._t_speed) >= self.config.speed_interval_sec
        ):
            self.trigger_speed_test()

        # 9. Emit tick
        if self.on_net_tick:
            try:
                self.on_net_tick(record)
            except Exception as e:
                logger.error(f"Error in on_net_tick callback: {e}")

        return record

    def _run_loop(self) -> None:
        """Internal worker loop executing checks at check_interval_sec."""
        logger.info(
            f"NetPulse monitor loop active (interval={self.config.check_interval_sec}s)."
        )
        while self._running:
            if not self.is_paused():
                start = time.time()
                try:
                    self.run_single_check()
                except Exception as e:
                    logger.exception(f"Unexpected error in monitor cycle: {e}")
                elapsed = time.time() - start
                sleep_time = max(0.5, self.config.check_interval_sec - elapsed)
            else:
                sleep_time = 1.0

            # Sleep in small slices to allow prompt exit on stop()
            wake_target = time.time() + sleep_time
            while self._running and time.time() < wake_target:
                time.sleep(0.5)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NetPulse network measurement tool")
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Run a single live check and print results without writing to CSVs (read-only/dry-run)",
    )
    args = parser.parse_args()

    # Create monitor engine in read-only mode (storage=None, write_storage=False)
    engine = MonitorEngine(storage=None)
    rec = engine.run_single_check(write_storage=False)

    lat_str = f"{rec.latency_ms:.1f}" if rec.latency_ms is not None else "---"
    down_str = f"{rec.pc_down_kbps:.1f}" if rec.pc_down_kbps is not None else "---"
    up_str = f"{rec.pc_up_kbps:.1f}" if rec.pc_up_kbps is not None else "---"
    sig_str = f" ({rec.wifi_signal:.0f}%)" if rec.wifi_signal is not None else ""

    print(
        f"{rec.time}  [{rec.status:4}] ping={lat_str} ms loss={rec.loss_pct:.1f}%  "
        f"{rec.network} via {rec.conn}{sig_str}  PC down/up={down_str}/{up_str} kbps (dry-run, 0 CSV writes)"
    )

