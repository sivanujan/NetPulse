"""Unit tests for NetPulse desktop widget, tray icon, and application lifecycle."""

import os
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.config import Config
from core.instance import check_legacy_monitor_running
from core.storage import NetRecord, SpeedRecord
from ui.sparkline import SparklineWidget
from ui.tray import NetPulseTrayIcon, create_tray_icon
from ui.widget import DesktopWidget, format_traffic_rate, get_status_color, get_status_info

# Ensure a single QApplication instance exists for widget testing
app = QApplication.instance() or QApplication([])


class TestPhase2UI(unittest.TestCase):
    """Test suite for Phase 2 UI components."""

    def setUp(self) -> None:
        self.config = Config(
            widget_visible=True,
            widget_always_on_top=False,
            widget_opacity=0.9,
            widget_compact=False,
            widget_locked=False,
        )

    def tearDown(self) -> None:
        if os.path.exists("temp_settings.json"):
            try:
                os.remove("temp_settings.json")
            except Exception:
                pass
        app.processEvents()

    def test_status_color_and_word_mapping(self) -> None:
        """Verify latency and loss color grading and status word rules."""
        # Green / Good: < 100 ms, 0 loss
        c, w = get_status_info(45.0, 0.0, "OK")
        self.assertEqual(c, "#22c55e")
        self.assertEqual(w, "Good")

        # Amber / Slow: 100-300 ms, loss < 25
        c, w = get_status_info(180.0, 5.0, "OK")
        self.assertEqual(c, "#f59e0b")
        self.assertEqual(w, "Slow")

        # Red / Bad: > 300 ms or loss >= 25%
        c, w = get_status_info(350.0, 0.0, "BAD")
        self.assertEqual(c, "#ef4444")
        self.assertEqual(w, "Bad")

        c, w = get_status_info(80.0, 30.0, "BAD")
        self.assertEqual(c, "#ef4444")
        self.assertEqual(w, "Bad")

        # Grey / Down: DOWN or None
        c, w = get_status_info(None, 100.0, "DOWN")
        self.assertEqual(c, "#A0A4AE")
        self.assertEqual(w, "Down")

    def test_format_traffic_rate(self) -> None:
        """Verify formatting of kbps rates and Mbps scaling."""
        self.assertEqual(format_traffic_rate(0), "0 kbps")
        self.assertEqual(format_traffic_rate(850.4), "850 kbps")
        self.assertEqual(format_traffic_rate(1000.0), "1.0 Mbps")
        self.assertEqual(format_traffic_rate(1500.0), "1.5 Mbps")
        self.assertEqual(format_traffic_rate(12500.0), "12.5 Mbps")

    def test_sparkline_widget(self) -> None:
        """Verify sparkline data setting and bounds calculation."""
        sparkline = SparklineWidget()
        try:
            data = [50.0, 60.0, 75.0, 90.0, 65.0]
            sparkline.set_data(data, status="OK")
            self.assertEqual(len(sparkline.values), 5)
            self.assertEqual(sparkline.status, "OK")
        finally:
            sparkline.deleteLater()
            app.processEvents()

    def test_desktop_widget_sample_update(self) -> None:
        """Verify updating DesktopWidget with a NetRecord updates UI labels."""
        widget = DesktopWidget(config=self.config, settings_path="temp_settings.json")
        try:
            rec = NetRecord(
                time="2026-11-08 21:00:00",
                latency_ms=62.4,
                loss_pct=0.0,
                dns_ms=3.0,
                status="OK",
                conn="iPhone USB",
                network="Dialog",
                isp="Dialog Axiata",
                pc_down_kbps=1500.0,
                pc_up_kbps=250.0,
            )
            widget.update_sample(rec)

            self.assertEqual(widget.ping_value_label.text(), "62")
            self.assertEqual(widget.status_word_label.text(), "Good")
            self.assertIn("Dialog", widget.network_label.text())
            self.assertIn("iPhone USB", widget.network_label.text())
            self.assertIn("1.5 Mbps", widget.traffic_label.text())
            self.assertIn("250 kbps", widget.traffic_label.text())
        finally:
            widget.deleteLater()
            app.processEvents()

    def test_desktop_widget_compact_mode(self) -> None:
        """Verify compact mode toggling."""
        widget = DesktopWidget(config=self.config, settings_path="temp_settings.json")
        try:
            widget.set_compact_mode(True)
            self.assertTrue(self.config.widget_compact)
            self.assertTrue(widget.sparkline.isHidden())

            widget.set_compact_mode(False)
            self.assertFalse(self.config.widget_compact)
            self.assertFalse(widget.sparkline.isHidden())
        finally:
            widget.deleteLater()
            app.processEvents()

    def test_tray_icon_and_status(self) -> None:
        """Verify tray icon generation and status updates."""
        icon = create_tray_icon("OK")
        self.assertFalse(icon.isNull())

        tray = NetPulseTrayIcon(config=self.config, settings_path="temp_settings.json")
        try:
            rec = NetRecord(
                time="2026-11-08 21:00:00",
                latency_ms=80.0,
                loss_pct=0.0,
                dns_ms=5.0,
                status="OK",
                conn="iPhone USB",
                network="Dialog",
            )
            tray.update_status("OK", rec)
            self.assertEqual(tray.current_status, "OK")
            self.assertIn("Dialog", tray.toolTip())
        finally:
            tray.hide()
            tray.deleteLater()
            app.processEvents()

    @patch("core.instance.is_pid_alive", return_value=True)
    def test_legacy_monitor_detection(self, mock_alive: MagicMock) -> None:
        """Verify check_legacy_monitor_running accurately identifies running legacy process."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pid_file = os.path.join(td, "monitor.pid")
            with open(pid_file, "w") as f:
                f.write("12345")
            running, pid = check_legacy_monitor_running(td)
            self.assertTrue(running)
            self.assertEqual(pid, 12345)


if __name__ == "__main__":
    unittest.main()
