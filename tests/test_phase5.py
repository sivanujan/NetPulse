"""Unit tests for Phase 5: Settings page, complaint reports, CSV exports, and data directory."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from core.config import Config
from core.data_dir import get_default_data_dir, migrate_existing_data_if_needed
from core.report_gen import export_filtered_csv, generate_complaint_report
from core.storage import NetRecord, SpeedRecord, Storage
from ui.dashboard.settings_page import SettingsPage


class TestPhase5(unittest.TestCase):
    """Test suite for Phase 5 features."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="netpulse_p5_test_")
        self.settings_path = os.path.join(self.temp_dir, "netpulse_settings.json")
        self.config = Config(
            user_name="Test User",
            user_address="123 Test Lane, Colombo",
            speed_interval_sec=3600,
        )
        self.storage = Storage(base_dir=self.temp_dir)

    def tearDown(self) -> None:
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settings_page_load_and_save(self) -> None:
        """Verify SettingsPage populates from config, edits fields, and emits settings_applied."""
        page = SettingsPage(
            config=self.config,
            settings_path=self.settings_path,
            base_dir=self.temp_dir,
        )
        try:
            self.assertEqual(page.edit_user_name.text(), "Test User")
            self.assertEqual(page.edit_user_address.text(), "123 Test Lane, Colombo")
            self.assertEqual(page.combo_speed_interval.currentText(), "1 hour (default)")

            # Modify settings
            page.edit_user_name.setText("Updated Subscriber")
            page.combo_speed_interval.setCurrentText("30 minutes")
            page.spin_alert_ping.setValue(350)

            applied_called = []
            page.settings_applied.connect(lambda: applied_called.append(True))

            page.save_and_apply()

            self.assertTrue(applied_called)
            self.assertEqual(self.config.user_name, "Updated Subscriber")
            self.assertEqual(self.config.speed_interval_sec, 1800)
            self.assertEqual(self.config.alert_latency_ms, 350.0)

            # Check that settings saved to disk
            reloaded = Config.load(self.settings_path)
            self.assertEqual(reloaded.user_name, "Updated Subscriber")
            self.assertEqual(reloaded.speed_interval_sec, 1800)
        finally:
            page.deleteLater()
            self.app.processEvents()

    def test_report_generation_pdf_and_png(self) -> None:
        """Verify generate_complaint_report produces readable PDF and PNG files."""
        t0 = datetime(2026, 11, 8, 10, 0, 0)
        net_records = []
        for i in range(30):
            t = t0 + timedelta(minutes=i * 2)
            is_down = 10 <= i <= 12
            net_records.append(
                NetRecord(
                    time=t.strftime("%Y-%m-%d %H:%M:%S"),
                    latency_ms=None if is_down else (75.0 + i),
                    loss_pct=100.0 if is_down else 0.0,
                    dns_ms=None if is_down else 10.0,
                    status="DOWN" if is_down else "OK",
                    network="Dialog",
                    conn="iPhone USB",
                    dt=t,
                )
            )

        speed_records = [
            SpeedRecord(
                time=(t0 + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
                download_mbps=12.5,
                network="Dialog",
                conn="iPhone USB",
                dt=t0 + timedelta(minutes=15),
            )
        ]

        pdf_path = os.path.join(self.temp_dir, "report.pdf")
        png_path = os.path.join(self.temp_dir, "report.png")

        out_pdf, out_png = generate_complaint_report(
            net_records=net_records,
            speed_records=speed_records,
            config=self.config,
            out_pdf_path=pdf_path,
            out_png_path=png_path,
            date_label="Test Run",
            provider_filter="Dialog",
        )

        self.assertTrue(os.path.exists(out_pdf))
        self.assertTrue(os.path.exists(out_png))
        self.assertGreater(os.path.getsize(out_pdf), 1000)
        self.assertGreater(os.path.getsize(out_png), 1000)

    def test_export_filtered_csv(self) -> None:
        """Verify export_filtered_csv outputs valid CSV with exact headers."""
        t0 = datetime(2026, 11, 8, 12, 0, 0)
        records = [
            NetRecord(
                time=t0.strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=55.0,
                loss_pct=0.0,
                dns_ms=5.0,
                status="OK",
                network="Mobitel",
                conn="WiFi",
                dt=t0,
            )
        ]
        csv_path = os.path.join(self.temp_dir, "export.csv")
        export_filtered_csv(records, csv_path)

        self.assertTrue(os.path.exists(csv_path))
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Header + 1 record
            self.assertIn("latency_ms", lines[0])
            self.assertIn("Mobitel", lines[1])

    def test_data_dir_migration(self) -> None:
        """Verify migrate_existing_data_if_needed copies files safely when target is empty."""
        src_dir = os.path.join(self.temp_dir, "source")
        target_dir = os.path.join(self.temp_dir, "target")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(target_dir, exist_ok=True)

        # Create source net_log.csv
        src_net = os.path.join(src_dir, "net_log.csv")
        with open(src_net, "w") as f:
            f.write("time,latency_ms\n2026-11-08 10:00:00,50.0\n")

        copied = migrate_existing_data_if_needed(target_dir=target_dir, source_dir=src_dir)
        self.assertIn("net_log.csv", copied)
        self.assertTrue(os.path.exists(os.path.join(target_dir, "net_log.csv")))
        # Source must NOT be deleted
        self.assertTrue(os.path.exists(src_net))

    def test_report_dialog_async_generation(self) -> None:
        """Verify ReportDialog generates reports in thread without crashing or GC issues."""
        from ui.report_dialog import ReportDialog
        from PySide6.QtCore import QThreadPool

        # Add records to storage
        t0 = datetime.now() - timedelta(hours=2)
        self.storage.append_net_record(
            NetRecord(
                time=t0.strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=65.0,
                loss_pct=0.0,
                dns_ms=8.0,
                status="OK",
                network="Dialog",
                conn="iPhone USB",
                dt=t0,
            )
        )

        dlg = ReportDialog(self.storage, self.config, self.temp_dir)
        try:
            # Mock prompt so modal dialog is not raised during test
            prompt_called = []
            dlg._prompt_open_file = lambda p, is_dir=False: prompt_called.append(p)

            dlg._generate_report()
            # Wait for thread pool
            QThreadPool.globalInstance().waitForDone(5000)
            self.app.processEvents()

            self.assertEqual(len(prompt_called), 1)
            self.assertTrue(os.path.exists(prompt_called[0]))
        finally:
            dlg.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

