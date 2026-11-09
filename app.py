"""NetPulse: Modern Windows Network Monitor desktop application."""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from core.config import Config
from core.data_dir import get_default_data_dir, migrate_existing_data_if_needed
from core.instance import SingleInstanceLock, check_legacy_monitor_running
from core.monitor import MonitorEngine
from core.notifier import NotificationManager
from core.stats import summarize
from core.storage import NetRecord, SpeedRecord, Storage
from ui.async_worker import AsyncWorker
from ui.dashboard import DashboardWindow
from ui.tray import NetPulseTrayIcon, create_tray_icon
from ui.widget import DesktopWidget


class EngineBridge(QObject):
    """Thread-safe Qt signal bridge between background MonitorEngine and UI widgets."""

    sig_net_sample = Signal(object)
    sig_speed_sample = Signal(object)
    sig_status_change = Signal(str, str, object)
    sig_network_change = Signal(str, str, object)
    sig_high_upload = Signal(float, float)


class NetPulseApp:
    """Main application controller orchestrating engine, desktop widget, and system tray."""

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.settings_path = os.path.join(self.base_dir, "netpulse_settings.json")
        self.config = Config.load(self.settings_path)

        # 1. Thread-safe Qt Signal Bridge
        self.bridge = EngineBridge()

        # 2. Storage & Engine
        self.storage = Storage(base_dir=self.base_dir)
        self.engine = MonitorEngine(
            storage=self.storage,
            config=self.config,
            log_path=os.path.join(self.base_dir, "netpulse.log"),
        )
        self._wire_engine_callbacks()

        # 3. Desktop Mini Widget
        self.widget = DesktopWidget(
            config=self.config,
            settings_path=self.settings_path,
        )

        # 4. System Tray Icon
        self.tray = NetPulseTrayIcon(
            config=self.config,
            base_dir=self.base_dir,
            settings_path=self.settings_path,
        )

        # 5. Dashboard Window (Live, Today, History, Compare, Outages, Settings)
        self.dashboard = DashboardWindow(
            storage=self.storage,
            config=self.config,
            settings_path=self.settings_path,
            base_dir=self.base_dir,
        )

        # 6. Windows Toast Notifications Manager
        self.notifier = NotificationManager(
            config=self.config,
            show_toast_callback=self._show_toast_alert,
        )

        self._last_summary_time: float = 0.0
        self._summary_worker: Optional[AsyncWorker] = None
        self._watchdog_timer: Optional[QTimer] = None

        self._wire_ui_signals()
        self._seed_initial_data()
        self._start_background_sync()

    def _start_background_sync(self) -> None:
        """Scan all CSV files into SQLite cache ONCE in a background thread."""
        def worker() -> None:
            self.storage.sync_from_csvs()
            QTimer.singleShot(0, lambda: self._refresh_today_summary(force=True))

        t = threading.Thread(target=worker, daemon=True, name="StartupCSVSyncThread")
        t.start()

    def _wire_engine_callbacks(self) -> None:
        """Route engine callbacks across threads into Qt signals."""
        self.engine.on_net_tick = lambda rec: self.bridge.sig_net_sample.emit(rec)
        self.engine.on_speed_tick = lambda rec: self.bridge.sig_speed_sample.emit(rec)
        self.engine.on_status_change = lambda o, n, r: self.bridge.sig_status_change.emit(o, n, r)
        self.engine.on_network_change = lambda o, n, r: self.bridge.sig_network_change.emit(o, n, r)
        self.engine.on_high_upload_alert = lambda rate, dur: self.bridge.sig_high_upload.emit(rate, dur)

    def _wire_ui_signals(self) -> None:
        """Connect Qt signals to UI update routines."""
        # Engine events -> UI updates
        self.bridge.sig_net_sample.connect(self._on_net_sample)
        self.bridge.sig_speed_sample.connect(self._on_speed_sample)
        self.bridge.sig_status_change.connect(self._on_status_change)
        self.bridge.sig_high_upload.connect(lambda r, d: self.widget.set_high_upload_warning(True))

        # Widget events
        self.widget.open_dashboard_requested.connect(self._show_dashboard)
        self.widget.run_speed_test_requested.connect(self._trigger_speed_test_async)
        self.widget.quit_requested.connect(self.quit)

        # Tray events
        self.tray.open_dashboard_requested.connect(self._show_dashboard)
        self.tray.run_speed_test_requested.connect(self._trigger_speed_test_async)
        self.tray.create_report_requested.connect(self.dashboard.open_report_dialog)
        self.tray.toggle_widget_requested.connect(self._toggle_widget)
        self.tray.pause_requested.connect(self._pause_monitoring)
        self.tray.resume_requested.connect(self._resume_monitoring)
        self.tray.data_saver_toggled.connect(self._set_data_saver)
        self.tray.quit_requested.connect(self.quit)

        # Dashboard settings applied
        self.dashboard.settings_applied.connect(self._on_settings_applied)

    def _on_settings_applied(self) -> None:
        """Apply newly saved settings immediately to running engine and UI widgets."""
        # 1. Update Engine
        self.engine.ping_hosts = list(self.config.ping_hosts)
        self.engine.check_interval_sec = self.config.check_interval_sec
        self.engine.speed_interval_sec = self.config.speed_interval_sec
        self.engine.speed_max_bytes = self.config.speed_max_bytes
        self.engine.data_saver = self.config.data_saver

        # 2. Update Desktop Widget
        self.widget.set_always_on_top(self.config.widget_always_on_top)
        self.widget.set_opacity(self.config.widget_opacity)
        self.widget.set_compact_mode(self.config.widget_compact)
        self.widget.set_locked(self.config.widget_locked)
        self.widget.set_click_through(self.config.widget_click_through)

        # 3. Update Tray
        self.tray.act_data_saver.setChecked(self.config.data_saver)
        self.tray.act_dnd.setChecked(self.config.do_not_disturb)

    def _seed_initial_data(self) -> None:
        """Populate widget and dashboard with the most recent sample from storage on startup."""
        recent = self.storage.get_recent_net_records(120)
        if recent:
            self._on_net_sample(recent[-1])
            self.dashboard.seed_live_history(recent)

        latest_speed = self.storage.get_latest_speed_record()
        if latest_speed:
            self.widget.update_speed_sample(latest_speed)

        # Populate today's summary for tooltip
        self._refresh_today_summary()

    def _on_net_sample(self, record: NetRecord) -> None:
        """Update widget, tray, and dashboard on each ping/network sample."""
        self.widget.update_sample(record)
        self.tray.update_status(record.status, record)
        self.dashboard.update_sample(record)
        self.notifier.evaluate_sample(record)

        # Reset high upload warning if current upload is normal
        if (record.pc_up_kbps or 0.0) < self.config.high_upload_kbps:
            self.widget.set_high_upload_warning(False)

        # Periodic refresh of today's uptime & median ping
        self._refresh_today_summary()

    def _show_toast_alert(
        self,
        kind: str,
        title: str,
        message: str,
        on_click: Optional[Callable[[], None]],
    ) -> None:
        """Route notification to system tray Windows toast."""
        self.tray.show_toast(kind, title, message, on_click)

    def _on_speed_sample(self, record: SpeedRecord) -> None:
        """Update widget on completed speed test."""
        self.widget.update_speed_sample(record)

    def _on_status_change(self, old_status: str, new_status: str, record: NetRecord) -> None:
        """Handle status transitions."""
        self.tray.update_status(new_status, record)

    def _refresh_today_summary(self, force: bool = False) -> None:
        """Calculate and set today's uptime % and median ping for widget tooltip asynchronously."""
        import time
        now = time.time()
        if not force and (now - self._last_summary_time) < 300.0:
            return  # Throttle to once every 5 minutes
        self._last_summary_time = now

        today_str = datetime.now().strftime("%Y-%m-%d")

        def background_calc() -> Optional[Any]:
            today_records = self.storage.get_net_records(date_str=today_str)
            return summarize(today_records) if today_records else None

        def on_done(stats: Optional[Any]) -> None:
            self._summary_worker = None
            if stats:
                self.widget.set_today_summary(
                    uptime_pct=stats.uptime_pct,
                    median_ping=stats.ping_median,
                    checks=stats.checks,
                )

        def on_error(err: str) -> None:
            self._summary_worker = None

        worker = AsyncWorker(background_calc)
        self._summary_worker = worker
        worker.signals.finished.connect(on_done)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)

    def _trigger_speed_test_async(self) -> None:
        """Run manual speed test in a worker thread so UI never freezes."""
        if self.engine.last_status == "DOWN":
            self.tray.showMessage(
                "NetPulse Speed Test",
                "Cannot run speed test: network is currently DOWN.",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )
            return

        def worker() -> None:
            self.engine.trigger_speed_test()

        threading.Thread(target=worker, daemon=True, name="ManualSpeedTest").start()

    def _toggle_widget(self, visible: bool) -> None:
        """Show or hide the desktop mini widget."""
        self.config.widget_visible = visible
        self.config.save(self.settings_path)
        if visible:
            self.widget.show_widget()
        else:
            self.widget.hide_widget()
        self.tray.sync_widget_visibility(visible)

    def _pause_monitoring(self, duration_sec: Optional[float]) -> None:
        """Pause monitoring for a duration or indefinitely."""
        self.engine.pause(duration_sec)
        self.tray.set_paused_state(True)

    def _resume_monitoring(self) -> None:
        """Resume active monitoring."""
        self.engine.resume()
        self.tray.set_paused_state(False)

    def _set_data_saver(self, enabled: bool) -> None:
        """Enable or disable data-saver mode."""
        self.config.data_saver = enabled
        self.engine.config.data_saver = enabled
        self.config.save(self.settings_path)

    def _show_dashboard(self) -> None:
        """Display the main Dashboard window."""
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def start(self) -> None:
        """Show UI and start background monitoring with auto-visibility watchdog."""
        self.tray.show()
        if self.config.widget_visible:
            self.widget.show_widget()
        self.engine.start()

        # Watchdog to guarantee desktop widget is never involuntarily hidden by Windows
        self._watchdog_timer = QTimer()
        self._watchdog_timer.setInterval(10000)  # Check every 10 seconds
        self._watchdog_timer.timeout.connect(self._watchdog_check)
        self._watchdog_timer.start()

    def _watchdog_check(self) -> None:
        """Keep desktop widget visible and raised if enabled in config."""
        if self.config.widget_visible:
            if not self.widget.isVisible() or self.widget.isMinimized():
                self.widget.show()
                self.widget.raise_()

    def quit(self) -> None:
        """Clean shutdown: save settings, stop engine, and exit."""
        self.widget.save_position()
        self.config.save(self.settings_path)
        self.engine.stop()
        QApplication.instance().quit()


def main() -> int:
    """Application entrypoint with single-instance lock and legacy monitor detection."""
    # 1. Enforce single-instance lock for NetPulse
    lock = SingleInstanceLock()
    if not lock.acquire():
        print("[NetPulse] Another instance of NetPulse is already running. Exiting.")
        return 0

    # 2. Determine data directory and perform safe first-run migration if needed
    base_dir = get_default_data_dir()
    migrate_existing_data_if_needed(target_dir=base_dir, source_dir=os.path.dirname(os.path.abspath(__file__)))

    # 3. Safe explicit migration check: refuse to run if old net_monitor.py is active
    legacy_running, legacy_pid = check_legacy_monitor_running(base_dir)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NetPulse")
    app.setWindowIcon(create_tray_icon("OK"))
    app.setQuitOnLastWindowClosed(False)  # Tray keeps app running

    if legacy_running:
        msg = (
            f"NetPulse cannot start monitoring because the legacy net_monitor.py "
            f"is currently running (PID {legacy_pid}).\n\n"
            f"To prevent conflicting CSV writes, please stop the legacy monitor first by running:\n\n"
            f"    python net_monitor.py stop\n"
            f"    python net_monitor.py autostart off\n\n"
            f"Then launch NetPulse again."
        )
        print(f"\n{'='*75}\n[MIGRATION REQUIRED]\n{msg}\n{'='*75}\n")
        QMessageBox.critical(
            None,
            "NetPulse — Legacy Monitor Active",
            msg,
        )
        lock.release()
        return 1

    # 3. Launch NetPulse app
    netpulse = NetPulseApp(base_dir=base_dir)
    netpulse.start()

    exit_code = app.exec()
    lock.release()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
