"""Unit tests for NetPulse storage engine and CSV/SQLite synchronization."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime

from core.storage import NetRecord, SpeedRecord, Storage


class TestNetPulseStorage(unittest.TestCase):
    """Test suite for Storage engine operations."""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.storage = Storage(base_dir=self.test_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_append_and_query_net_record(self) -> None:
        """Verify appending NetRecord writes to CSV and caches in SQLite."""
        now_dt = datetime(2026, 11, 8, 15, 30, 0)
        rec = NetRecord(
            time="2026-11-08 15:30:00",
            latency_ms=64.2,
            loss_pct=0.0,
            dns_ms=3.4,
            status="OK",
            conn="iPhone USB",
            network="Dialog",
            isp="AS8544 Dialog Axiata PLC",
            wifi_signal=None,
            pc_down_kbps=1240.5,
            pc_up_kbps=310.2,
            local_ip="172.20.10.2",
            dt=now_dt,
        )
        self.storage.append_net_record(rec)

        # Confirm CSV exists and has data
        self.assertTrue(os.path.exists(self.storage.net_csv_path))

        # Query back
        records = self.storage.get_net_records(network="Dialog")
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.time, "2026-11-08 15:30:00")
        self.assertEqual(r.latency_ms, 64.2)
        self.assertEqual(r.network, "Dialog")
        self.assertEqual(r.conn, "iPhone USB")
        self.assertEqual(r.pc_down_kbps, 1240.5)

    def test_append_and_query_speed_record(self) -> None:
        """Verify appending SpeedRecord writes to CSV and caches in SQLite."""
        rec = SpeedRecord(
            time="2026-11-08 15:35:00",
            download_mbps=14.521,
            conn="iPhone USB",
            network="Dialog",
            isp="AS8544 Dialog Axiata PLC",
            dt=datetime(2026, 11, 8, 15, 35, 0),
        )
        self.storage.append_speed_record(rec)

        self.assertTrue(os.path.exists(self.storage.speed_csv_path))
        latest = self.storage.get_latest_speed_record()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.download_mbps, 14.521)
        self.assertEqual(latest.network, "Dialog")

    def test_sync_legacy_csv_format(self) -> None:
        """Verify loading older logs with fewer columns (e.g. from old/ folder)."""
        old_dir = os.path.join(self.test_dir, "old")
        os.makedirs(old_dir, exist_ok=True)
        old_net_csv = os.path.join(old_dir, "net_log.csv")

        # Old header had only 5 columns
        with open(old_net_csv, "w", encoding="utf-8") as f:
            f.write("time,latency_ms,loss_pct,dns_ms,status\n")
            f.write("2026-11-05 21:20:29,126.5,0.0,9.3,OK\n")
            f.write("2026-11-05 21:20:58,124.8,0.0,0.4,OK\n")

        net_count, _ = self.storage.sync_from_csvs()
        self.assertEqual(net_count, 2)

        records = self.storage.get_net_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].time, "2026-11-05 21:20:29")
        self.assertEqual(records[0].latency_ms, 126.5)
        # Defaults filled for missing columns
        self.assertEqual(records[0].network, "unknown")
        self.assertEqual(records[0].conn, "unknown")


if __name__ == "__main__":
    unittest.main()

