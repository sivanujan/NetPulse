"""Unit tests for Phase 4: NotificationManager, CompareNetworksPage, and OutagesPage."""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from core.config import Config
from core.notifier import NotificationManager
from core.storage import NetRecord, SpeedRecord, Storage
from ui.dashboard import CompareNetworksPage, OutagesPage

app = QApplication.instance() or QApplication([])


class TestPhase4(unittest.TestCase):
    """Test suite for Phase 4 components."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = Storage(base_dir=self.tmp_dir)
        self.config = Config(do_not_disturb=False, high_upload_kbps=500.0)
        self.toast_mock = MagicMock()
        self.notifier = NotificationManager(
            config=self.config,
            show_toast_callback=self.toast_mock,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        app.processEvents()

    def test_notification_down_after_60s(self) -> None:
        """Verify toast is sent only when DOWN exceeds 60s."""
        rec_down = NetRecord(
            time="2026-11-08 22:00:00",
            latency_ms=None,
            loss_pct=100.0,
            dns_ms=None,
            status="DOWN",
            network="Dialog",
            conn="iPhone USB",
        )
        # First tick at t=0
        with unittest.mock.patch("time.time", return_value=1000.0):
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 0)

        # After 30s: still down, but < 60s
        with unittest.mock.patch("time.time", return_value=1030.0):
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 0)

        # After 70s (> 60s threshold): DOWN alert must trigger
        with unittest.mock.patch("time.time", return_value=1070.0):
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 1)
            kind, title, msg, _ = self.toast_mock.call_args[0]
            self.assertEqual(kind, "down")
            self.assertIn("Down", title)

    def test_notification_restored_after_downtime(self) -> None:
        """Verify toast is sent when connection restores, reporting downtime duration."""
        rec_down = NetRecord(time="2026-11-08 22:00:00", latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB")
        rec_ok = NetRecord(time="2026-11-08 22:02:30", latency_ms=65.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB")

        # Down at t=1000, trigger alert at t=1070
        with unittest.mock.patch("time.time", return_value=1000.0):
            self.notifier.evaluate_sample(rec_down)
        with unittest.mock.patch("time.time", return_value=1070.0):
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 1)

        # Restored at t=1150 (150s = 2m 30s downtime)
        with unittest.mock.patch("time.time", return_value=1150.0):
            self.notifier.evaluate_sample(rec_ok)
            self.assertEqual(self.toast_mock.call_count, 2)
            kind, title, msg, _ = self.toast_mock.call_args[0]
            self.assertEqual(kind, "restored")
            self.assertIn("Restored", title)
            self.assertIn("2m 30s", msg)

    def test_notification_network_changed(self) -> None:
        """Verify toast when provider changes."""
        rec_dialog = NetRecord(time="2026-11-08 22:00:00", latency_ms=65.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB")
        rec_mobitel = NetRecord(time="2026-11-08 22:01:00", latency_ms=75.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Mobitel", conn="iPhone USB")

        with unittest.mock.patch("time.time", return_value=1000.0):
            self.notifier.evaluate_sample(rec_dialog)
            self.assertEqual(self.toast_mock.call_count, 0)

        with unittest.mock.patch("time.time", return_value=1060.0):
            self.notifier.evaluate_sample(rec_mobitel)
            self.assertEqual(self.toast_mock.call_count, 1)
            kind, title, msg, _ = self.toast_mock.call_args[0]
            self.assertEqual(kind, "network_change")
            self.assertIn("Mobitel", msg)

    def test_notification_rate_limit_and_dnd(self) -> None:
        """Verify 15-minute rate limit and Do Not Disturb suppression."""
        rec_down = NetRecord(time="2026-11-08 22:00:00", latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB")

        # Initial down alert at t=1070
        with unittest.mock.patch("time.time", return_value=1000.0):
            self.notifier.evaluate_sample(rec_down)
        with unittest.mock.patch("time.time", return_value=1070.0):
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 1)

        # Still down at t=1200 (within 15 min / 900s limit): rate-limited
        with unittest.mock.patch("time.time", return_value=1200.0):
            self.notifier.down_alert_sent = False  # Reset flag to test rate limit
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 1)

        # Do Not Disturb active
        self.config.do_not_disturb = True
        with unittest.mock.patch("time.time", return_value=3000.0):
            self.notifier.down_alert_sent = False
            self.notifier.evaluate_sample(rec_down)
            self.assertEqual(self.toast_mock.call_count, 1, "DND must suppress alerts")

    def test_compare_networks_page(self) -> None:
        """Verify CompareNetworksPage calculations and winner badges."""
        base_t = datetime(2026, 11, 8, 12, 0, 0)
        # Add daytime checks for Dialog & Mobitel
        for i in range(10):
            t = base_t + timedelta(minutes=i * 5)
            self.storage.append_net_record(
                NetRecord(
                    time=t.strftime("%Y-%m-%d %H:%M:%S"),
                    latency_ms=60.0,
                    loss_pct=0.0,
                    dns_ms=5.0,
                    status="OK",
                    network="Dialog",
                    conn="iPhone USB",
                    dt=t,
                )
            )
        # Add evening checks for Dialog (19:00 - fast) and Mobitel (19:00 - slow)
        eve_t = datetime(2026, 11, 8, 19, 0, 0)
        for i in range(5):
            t_dia = eve_t + timedelta(minutes=i * 5)
            t_mob = t_dia + timedelta(seconds=30)
            self.storage.append_net_record(
                NetRecord(
                    time=t_dia.strftime("%Y-%m-%d %H:%M:%S"),
                    latency_ms=75.0,
                    loss_pct=0.0,
                    dns_ms=5.0,
                    status="OK",
                    network="Dialog",
                    conn="iPhone USB",
                    dt=t_dia,
                )
            )
            self.storage.append_net_record(
                NetRecord(
                    time=t_mob.strftime("%Y-%m-%d %H:%M:%S"),
                    latency_ms=250.0,
                    loss_pct=15.0,
                    dns_ms=20.0,
                    status="BAD",
                    network="Mobitel",
                    conn="iPhone USB",
                    dt=t_mob,
                )
            )

        page = CompareNetworksPage(storage=self.storage, sync=True)
        try:
            page.refresh_data(sync=True)
            self.assertEqual(page.val_overall.text(), "Dialog")
            self.assertEqual(page.val_evening.text(), "Dialog")
            self.assertGreaterEqual(page.table.rowCount(), 2)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_outages_page(self) -> None:
        """Verify OutagesPage identifies DOWN outages and sustained BAD periods."""
        t0 = datetime(2026, 11, 8, 10, 0, 0)
        # DOWN outage (3 contiguous checks = 90s)
        for i in range(3):
            t = t0 + timedelta(seconds=i * 30)
            self.storage.append_net_record(
                NetRecord(time=t.strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB", dt=t)
            )
        # OK gap
        t_ok = t0 + timedelta(minutes=10)
        self.storage.append_net_record(
            NetRecord(time=t_ok.strftime("%Y-%m-%d %H:%M:%S"), latency_ms=50.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=t_ok)
        )
        # Sustained BAD period (> 5 min: 11 checks = 330s)
        t_bad = t_ok + timedelta(minutes=10)
        for i in range(11):
            t = t_bad + timedelta(seconds=i * 30)
            self.storage.append_net_record(
                NetRecord(time=t.strftime("%Y-%m-%d %H:%M:%S"), latency_ms=350.0, loss_pct=10.0, dns_ms=15.0, status="BAD", network="Dialog", conn="iPhone USB", dt=t)
            )

        page = OutagesPage(storage=self.storage, sync=True)
        try:
            page.refresh_data(sync=True)
            self.assertEqual(page.val_outages.text(), "1")
            self.assertEqual(page.val_bad.text(), "1")
            self.assertEqual(page.table.rowCount(), 2)
        finally:
            page.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
