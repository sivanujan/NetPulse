"""Storage engine for NetPulse: CSV persistence and SQLite query cache."""

from __future__ import annotations

import csv
import glob
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from core.config import NET_HEADER, SPEED_HEADER, TFMT
from core.perf import log_timing


def parse_float(val: Any) -> Optional[float]:
    """Safely parse a float from string or number; return None if empty/invalid."""
    if val is None or val == "" or val == "---":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_dt(val: Any) -> Optional[datetime]:
    """Parse timestamp string into datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.strptime(str(val).strip(), TFMT)
    except Exception:
        # Fallback for ISO format or dates with fractional seconds
        try:
            return datetime.fromisoformat(str(val).strip())
        except Exception:
            return None


@dataclass
class NetRecord:
    """A single network check record."""

    time: str
    latency_ms: Optional[float]
    loss_pct: float
    dns_ms: Optional[float]
    status: str
    conn: str = "unknown"
    network: str = "unknown"
    isp: str = ""
    wifi_signal: Optional[float] = None
    pc_down_kbps: Optional[float] = None
    pc_up_kbps: Optional[float] = None
    local_ip: str = ""
    dt: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.dt is None and self.time:
            self.dt = parse_dt(self.time)

    def to_csv_row(self) -> List[Any]:
        """Format as row for net_log.csv."""
        return [
            self.time,
            "" if self.latency_ms is None else f"{self.latency_ms:.1f}",
            f"{self.loss_pct:.1f}",
            "" if self.dns_ms is None else f"{self.dns_ms:.1f}",
            self.status,
            self.conn,
            self.network,
            self.isp,
            "" if self.wifi_signal is None else f"{self.wifi_signal:.0f}",
            "" if self.pc_down_kbps is None else f"{self.pc_down_kbps:.1f}",
            "" if self.pc_up_kbps is None else f"{self.pc_up_kbps:.1f}",
            self.local_ip,
        ]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> NetRecord:
        """Create from dictionary (CSV DictReader or SQLite row)."""
        t = str(d.get("time", "")).strip()
        return cls(
            time=t,
            latency_ms=parse_float(d.get("latency_ms")),
            loss_pct=parse_float(d.get("loss_pct")) or 0.0,
            dns_ms=parse_float(d.get("dns_ms")),
            status=str(d.get("status", "OK")),
            conn=str(d.get("conn") or "unknown"),
            network=str(d.get("network") or "unknown"),
            isp=str(d.get("isp") or ""),
            wifi_signal=parse_float(d.get("wifi_signal")),
            pc_down_kbps=parse_float(d.get("pc_down_kbps")),
            pc_up_kbps=parse_float(d.get("pc_up_kbps")),
            local_ip=str(d.get("local_ip") or ""),
        )


@dataclass
class SpeedRecord:
    """A single speed test record."""

    time: str
    download_mbps: Optional[float]
    conn: str = "unknown"
    network: str = "unknown"
    isp: str = ""
    dt: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.dt is None and self.time:
            self.dt = parse_dt(self.time)

    def to_csv_row(self) -> List[Any]:
        """Format as row for speed_log.csv."""
        return [
            self.time,
            "" if self.download_mbps is None else f"{self.download_mbps:.3f}",
            self.conn,
            self.network,
            self.isp,
        ]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SpeedRecord:
        """Create from dictionary (CSV DictReader or SQLite row)."""
        t = str(d.get("time", "")).strip()
        return cls(
            time=t,
            download_mbps=parse_float(d.get("download_mbps")),
            conn=str(d.get("conn") or "unknown"),
            network=str(d.get("network") or "unknown"),
            isp=str(d.get("isp") or ""),
        )


class Storage:
    """Persistent storage engine: writes to CSV and caches in SQLite."""

    def __init__(self, base_dir: str = ".", db_path: Optional[str] = None) -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.net_csv_path = os.path.join(self.base_dir, "net_log.csv")
        self.speed_csv_path = os.path.join(self.base_dir, "speed_log.csv")
        self.db_path = db_path if db_path is not None else os.path.join(self.base_dir, "netpulse_cache.db")
        self._lock = threading.Lock()
        self._init_sqlite()

    def _get_connection(self) -> sqlite3.Connection:
        """Open a SQLite connection configured for cache queries."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        """Create cache tables and indexes if they do not exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS net_records (
                        time TEXT PRIMARY KEY,
                        dt_ts REAL,
                        latency_ms REAL,
                        loss_pct REAL,
                        dns_ms REAL,
                        status TEXT,
                        conn TEXT,
                        network TEXT,
                        isp TEXT,
                        wifi_signal REAL,
                        pc_down_kbps REAL,
                        pc_up_kbps REAL,
                        local_ip TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_net_dt ON net_records(dt_ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_net_network ON net_records(network)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_net_conn ON net_records(conn)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_net_time ON net_records(time)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS speed_records (
                        time TEXT PRIMARY KEY,
                        dt_ts REAL,
                        download_mbps REAL,
                        conn TEXT,
                        network TEXT,
                        isp TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_speed_dt ON speed_records(dt_ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_speed_network ON speed_records(network)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_speed_conn ON speed_records(conn)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_speed_time ON speed_records(time)"
                )
                conn.commit()
            finally:
                conn.close()

    def append_net_record(self, record: NetRecord) -> None:
        """Append a record to net_log.csv and the SQLite cache."""
        with self._lock:
            new_file = not os.path.exists(self.net_csv_path) or os.path.getsize(self.net_csv_path) == 0
            with open(self.net_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if new_file:
                    writer.writerow(NET_HEADER)
                writer.writerow(record.to_csv_row())

            # Also insert into SQLite cache
            ts = record.dt.timestamp() if record.dt else 0.0
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO net_records
                    (time, dt_ts, latency_ms, loss_pct, dns_ms, status, conn, network, isp, wifi_signal, pc_down_kbps, pc_up_kbps, local_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.time,
                        ts,
                        record.latency_ms,
                        record.loss_pct,
                        record.dns_ms,
                        record.status,
                        record.conn,
                        record.network,
                        record.isp,
                        record.wifi_signal,
                        record.pc_down_kbps,
                        record.pc_up_kbps,
                        record.local_ip,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def append_speed_record(self, record: SpeedRecord) -> None:
        """Append a record to speed_log.csv and the SQLite cache."""
        with self._lock:
            new_file = not os.path.exists(self.speed_csv_path) or os.path.getsize(self.speed_csv_path) == 0
            with open(self.speed_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if new_file:
                    writer.writerow(SPEED_HEADER)
                writer.writerow(record.to_csv_row())

            ts = record.dt.timestamp() if record.dt else 0.0
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO speed_records
                    (time, dt_ts, download_mbps, conn, network, isp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.time,
                        ts,
                        record.download_mbps,
                        record.conn,
                        record.network,
                        record.isp,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def sync_from_csvs(self) -> Tuple[int, int]:
        """Scan all net_log*.csv and speed_log*.csv (including old/) into SQLite cache."""
        with log_timing("CSV to SQLite sync"):
            net_count = 0
            speed_count = 0

        # Discover all net_log CSV files
        net_patterns = [
            os.path.join(self.base_dir, "net_log*.csv"),
            os.path.join(self.base_dir, "old", "net_log*.csv"),
        ]
        net_files: List[str] = []
        for pat in net_patterns:
            net_files.extend(glob.glob(pat))

        with self._lock:
            conn = self._get_connection()
            try:
                for file_path in net_files:
                    if not os.path.exists(file_path):
                        continue
                    try:
                        with open(file_path, "r", newline="", encoding="utf-8", errors="replace") as f:
                            reader = csv.DictReader(f)
                            rows_to_insert = []
                            for row in reader:
                                rec = NetRecord.from_dict(row)
                                if not rec.time or not rec.dt:
                                    continue
                                rows_to_insert.append(
                                    (
                                        rec.time,
                                        rec.dt.timestamp(),
                                        rec.latency_ms,
                                        rec.loss_pct,
                                        rec.dns_ms,
                                        rec.status,
                                        rec.conn,
                                        rec.network,
                                        rec.isp,
                                        rec.wifi_signal,
                                        rec.pc_down_kbps,
                                        rec.pc_up_kbps,
                                        rec.local_ip,
                                    )
                                )
                            if rows_to_insert:
                                conn.executemany(
                                    """
                                    INSERT OR IGNORE INTO net_records
                                    (time, dt_ts, latency_ms, loss_pct, dns_ms, status, conn, network, isp, wifi_signal, pc_down_kbps, pc_up_kbps, local_ip)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    rows_to_insert,
                                )
                                net_count += len(rows_to_insert)
                    except Exception:
                        pass

                # Discover speed files
                speed_patterns = [
                    os.path.join(self.base_dir, "speed_log*.csv"),
                    os.path.join(self.base_dir, "old", "speed_log*.csv"),
                ]
                speed_files: List[str] = []
                for pat in speed_patterns:
                    speed_files.extend(glob.glob(pat))

                for file_path in speed_files:
                    if not os.path.exists(file_path):
                        continue
                    try:
                        with open(file_path, "r", newline="", encoding="utf-8", errors="replace") as f:
                            reader = csv.DictReader(f)
                            rows_to_insert = []
                            for row in reader:
                                rec = SpeedRecord.from_dict(row)
                                if not rec.time or not rec.dt:
                                    continue
                                rows_to_insert.append(
                                    (
                                        rec.time,
                                        rec.dt.timestamp(),
                                        rec.download_mbps,
                                        rec.conn,
                                        rec.network,
                                        rec.isp,
                                    )
                                )
                            if rows_to_insert:
                                conn.executemany(
                                    """
                                    INSERT OR IGNORE INTO speed_records
                                    (time, dt_ts, download_mbps, conn, network, isp)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    """,
                                    rows_to_insert,
                                )
                                speed_count += len(rows_to_insert)
                    except Exception:
                        pass
                conn.commit()
            finally:
                conn.close()

        return net_count, speed_count

    def get_net_records(
        self,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        network: Optional[str] = None,
        conn_type: Optional[str] = None,
        hours: Optional[float] = None,
        date_str: Optional[str] = None,
    ) -> List[NetRecord]:
        """Query net records from cache with optional filters, sorted by time."""
        if hours is not None and hours > 0:
            start_dt = datetime.now() - timedelta(hours=hours)

        clauses = []
        params: List[Any] = []

        if start_dt is not None:
            clauses.append("dt_ts >= ?")
            params.append(start_dt.timestamp())
        if end_dt is not None:
            clauses.append("dt_ts <= ?")
            params.append(end_dt.timestamp())
        if date_str:
            clauses.append("time LIKE ?")
            params.append(f"{date_str}%")
        if network:
            clauses.append("(LOWER(network) LIKE ? OR LOWER(conn) LIKE ?)")
            pat = f"%{network.lower()}%"
            params.extend([pat, pat])
        if conn_type:
            clauses.append("LOWER(conn) LIKE ?")
            params.append(f"%{conn_type.lower()}%")

        query = "SELECT * FROM net_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY dt_ts ASC"

        conn = self._get_connection()
        try:
            with log_timing("SQLite query net_records", threshold_ms=10.0):
                cursor = conn.execute(query, params)
                return [NetRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_speed_records(
        self,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        network: Optional[str] = None,
        conn_type: Optional[str] = None,
        hours: Optional[float] = None,
        date_str: Optional[str] = None,
    ) -> List[SpeedRecord]:
        """Query speed records from cache with optional filters, sorted by time."""
        if hours is not None and hours > 0:
            start_dt = datetime.now() - timedelta(hours=hours)

        clauses = []
        params: List[Any] = []

        if start_dt is not None:
            clauses.append("dt_ts >= ?")
            params.append(start_dt.timestamp())
        if end_dt is not None:
            clauses.append("dt_ts <= ?")
            params.append(end_dt.timestamp())
        if date_str:
            clauses.append("time LIKE ?")
            params.append(f"{date_str}%")
        if network:
            clauses.append("(LOWER(network) LIKE ? OR LOWER(conn) LIKE ?)")
            pat = f"%{network.lower()}%"
            params.extend([pat, pat])
        if conn_type:
            clauses.append("LOWER(conn) LIKE ?")
            params.append(f"%{conn_type.lower()}%")

        query = "SELECT * FROM speed_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY dt_ts ASC"

        conn = self._get_connection()
        try:
            with log_timing("SQLite query speed_records", threshold_ms=10.0):
                cursor = conn.execute(query, params)
                return [SpeedRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_recent_net_records(self, count: int = 50) -> List[NetRecord]:
        """Fetch the most recent N net records."""
        query = "SELECT * FROM (SELECT * FROM net_records ORDER BY dt_ts DESC LIMIT ?) ORDER BY dt_ts ASC"
        conn = self._get_connection()
        try:
            cursor = conn.execute(query, (count,))
            return [NetRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_latest_speed_record(self) -> Optional[SpeedRecord]:
        """Fetch the most recent speed test record."""
        query = "SELECT * FROM speed_records ORDER BY dt_ts DESC LIMIT 1"
        conn = self._get_connection()
        try:
            row = conn.execute(query).fetchone()
            return SpeedRecord.from_dict(dict(row)) if row else None
        finally:
            conn.close()

    def get_networks_seen(self) -> List[Dict[str, Any]]:
        """List distinct provider and connection combinations with statistics."""
        query = """
            SELECT network, conn, COUNT(*) as count, MIN(dt_ts) as first_ts, MAX(dt_ts) as last_ts
            FROM net_records
            GROUP BY network, conn
            ORDER BY count DESC
        """
        results = []
        conn = self._get_connection()
        try:
            for row in conn.execute(query).fetchall():
                first_dt = datetime.fromtimestamp(row["first_ts"]) if row["first_ts"] else None
                last_dt = datetime.fromtimestamp(row["last_ts"]) if row["last_ts"] else None
                results.append(
                    {
                        "network": row["network"],
                        "conn": row["conn"],
                        "count": row["count"],
                        "first_dt": first_dt,
                        "last_dt": last_dt,
                    }
                )
            return results
        finally:
            conn.close()
