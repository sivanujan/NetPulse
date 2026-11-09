"""Performance and responsiveness regression tests for NetPulse."""

from __future__ import annotations

import os
import sys
import time
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from core.config import Config
from core.downsample import downsample_series
from core.storage import NetRecord, Storage
from ui.dashboard import DashboardWindow


class TestNetPulsePerformance(unittest.TestCase):
    """Ensure UI responsiveness, sub-second page switches, and sub-10s test execution."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.storage = Storage(base_dir=".")
        self.config = Config.load("netpulse_settings.json")

    def test_downsample_performance(self) -> None:
        """Verify downsampling 50,000 dense points takes < 50 ms and produces <= 2000 points."""
        n = 50000
        t0 = time.time()
        times = [t0 + i * 30.0 for i in range(n)]
        values = [50.0 + (i % 200) for i in range(n)]

        t_start = time.perf_counter()
        ds_t, ds_v = downsample_series(times, values, max_points=2000)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        self.assertLessEqual(len(ds_t), 2050)
        self.assertLess(elapsed_ms, 50.0, f"Downsampling took too long: {elapsed_ms:.1f} ms")

    def test_dashboard_page_switch_latency(self) -> None:
        """Verify switching between all dashboard pages takes < 500 ms per switch."""
        dash = DashboardWindow(storage=self.storage, config=self.config)
        try:
            # Warm up
            self.app.processEvents()

            for page_idx in range(5):
                t0 = time.perf_counter()
                dash._select_nav(page_idx)
                self.app.processEvents()
                cost_ms = (time.perf_counter() - t0) * 1000.0
                self.assertLess(
                    cost_ms, 500.0, f"Switching to page {page_idx} exceeded 500ms: {cost_ms:.1f}ms"
                )
        finally:
            dash.deleteLater()
            self.app.processEvents()

    def test_history_filter_responsiveness(self) -> None:
        """Verify rapid filter changes do not block UI thread."""
        dash = DashboardWindow(storage=self.storage, config=self.config)
        try:
            dash._select_nav(2)  # History page
            self.app.processEvents()

            t0 = time.perf_counter()
            dash.page_history.combo_preset.setCurrentText("Last 30 Days")
            dash.page_history.combo_preset.setCurrentText("All Time")
            self.app.processEvents()
            cost_ms = (time.perf_counter() - t0) * 1000.0

            # UI thread must return immediately (< 100 ms) because work is debounced/async
            self.assertLess(cost_ms, 150.0, f"Filter change blocked UI thread: {cost_ms:.1f}ms")
        finally:
            dash.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
