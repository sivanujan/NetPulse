"""Unit tests for Phase 3 Dashboard: window shell, Live page, Today page, and History page."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

from PySide6.QtCore import QDate
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from core.config import Config
from core.storage import NetRecord, SpeedRecord, Storage
from ui.dashboard import DashboardWindow, HistoryPage, LivePage, TodayPage

app = QApplication.instance() or QApplication([])


class TestPhase3Dashboard(unittest.TestCase):
    """Test suite for Phase 3 Dashboard pages and window."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = Storage(base_dir=self.tmp_dir)
        self.config = Config()

        # Seed sample data for testing
        base_t = datetime.now() - timedelta(hours=2)
        for i in range(20):
            t = base_t + timedelta(minutes=i * 5)
            self.storage.append_net_record(
                NetRecord(
                    time=t.strftime("%Y-%m-%d %H:%M:%S"),
                    latency_ms=55.0 + (i % 5) * 10,
                    loss_pct=0.0 if i != 3 else 10.0,
                    dns_ms=5.0,
                    status="OK",
                    network="Dialog" if i < 10 else "Mobitel",
                    conn="iPhone USB",
                    pc_down_kbps=1200.0,
                    pc_up_kbps=300.0,
                    dt=t,
                )
            )
        self.storage.append_speed_record(
            SpeedRecord(
                time=(base_t + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                download_mbps=11.5,
                network="Dialog",
                conn="iPhone USB",
                dt=base_t + timedelta(minutes=30),
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        app.processEvents()

    def test_live_page_update(self) -> None:
        """Verify LivePage vitals cards and plot updates."""
        page = LivePage()
        try:
            rec = NetRecord(
                time="2026-11-08 22:00:00",
                latency_ms=64.0,
                loss_pct=0.0,
                dns_ms=4.0,
                status="OK",
                network="Dialog",
                conn="iPhone USB",
                pc_down_kbps=1800.0,
                pc_up_kbps=400.0,
                dt=datetime(2026, 11, 8, 22, 0, 0),
            )
            page.update_sample(rec)

            self.assertIn("64", page.val_ping.text())
            self.assertEqual(page.val_loss.text(), "0.0%")
            self.assertEqual(page.val_net.text(), "Dialog")
            self.assertIn("1.8 Mbps", page.val_traffic.text())
            self.assertEqual(len(page._ping_values), 1)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_today_page_calculation(self) -> None:
        """Verify TodayPage summary calculations and hourly chart population."""
        page = TodayPage(storage=self.storage, sync=True)
        try:
            page.refresh_data(sync=True)

            self.assertIsNotNone(page.val_uptime.text())
            self.assertNotEqual(page.val_uptime.text(), "No data")
            self.assertIsNotNone(page.val_good.text())
            self.assertIsNotNone(page.val_ping.text())
            self.assertIsNotNone(page.bar_item)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_history_page_filter(self) -> None:
        """Verify HistoryPage preset handling, dropdowns, and chart population."""
        page = HistoryPage(storage=self.storage, sync=True)
        try:
            # Dropdowns should include discovered networks
            self.assertIn("All Providers", [page.combo_provider.itemText(i) for i in range(page.combo_provider.count())])
            self.assertIn("Dialog", [page.combo_provider.itemText(i) for i in range(page.combo_provider.count())])

            # Test filter application
            page.combo_preset.setCurrentText("All Time")
            page.apply_filter(sync=True)

            self.assertIn("Checks: 20", page.lbl_sum_checks.text())
            self.assertIn("Uptime: 100", page.lbl_sum_uptime.text())
        finally:
            page.deleteLater()
            app.processEvents()

    def test_dashboard_window_navigation_and_close(self) -> None:
        """Verify DashboardWindow sidebar navigation and minimize-to-tray close behavior."""
        dash = DashboardWindow(storage=self.storage, config=self.config)
        try:
            # Default is page 0 (Live)
            self.assertEqual(dash.stack.currentIndex(), 0)

            # Switch to Today (page 1)
            dash._select_nav(1)
            self.assertEqual(dash.stack.currentIndex(), 1)

            # Switch to History (page 2)
            dash._select_nav(2)
            self.assertEqual(dash.stack.currentIndex(), 2)

            # Close event should hide window without exiting
            dash.show()
            close_event = QCloseEvent()
            dash.closeEvent(close_event)
            self.assertTrue(close_event.isAccepted() is False)
            self.assertFalse(dash.isVisible())
        finally:
            dash.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
