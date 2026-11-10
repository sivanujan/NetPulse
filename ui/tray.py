"""System tray icon with dynamic status badge and full management menu for NetPulse."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from core.config import Config
from core.instance import AutostartManager
from core.storage import NetRecord, SpeedRecord

STATUS_COLORS = {
    "OK": QColor(34, 197, 94),      # Green
    "AMBER": QColor(245, 158, 11),  # Amber
    "BAD": QColor(239, 68, 68),     # Red
    "DOWN": QColor(107, 114, 128),  # Grey
}


def create_tray_icon(status: str = "OK") -> QIcon:
    """Generate a crisp high-DPI dynamic tray icon with status-colored pulse badge."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # 1. Dark circular background
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(24, 24, 28))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 14, 14)

    # 2. Draw subtle border
    painter.setPen(QPen(QColor(255, 255, 255, 30), 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 14, 14)

    # 3. Draw stylized pulse line (wave)
    status_color = STATUS_COLORS.get(status, STATUS_COLORS["OK"])
    path = QPainterPath()
    mid_y = size / 2.0
    path.moveTo(12, mid_y)
    path.lineTo(22, mid_y)
    path.lineTo(28, mid_y - 14)
    path.lineTo(36, mid_y + 14)
    path.lineTo(42, mid_y - 6)
    path.lineTo(46, mid_y)
    path.lineTo(52, mid_y)

    pen = QPen(status_color, 4.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(path)

    # 4. Draw Status Indicator Dot at top-right
    dot_color = status_color
    painter.setPen(QPen(QColor(24, 24, 28), 2))
    painter.setBrush(dot_color)
    painter.drawEllipse(QPointF(size - 13, 13), 6.5, 6.5)

    painter.end()
    return QIcon(pixmap)


class NetPulseTrayIcon(QSystemTrayIcon):
    """System tray icon controller for NetPulse."""

    open_dashboard_requested = Signal()
    run_speed_test_requested = Signal()
    create_report_requested = Signal()
    toggle_widget_requested = Signal(bool)
    pause_requested = Signal(object)  # None for indefinite, or float seconds
    resume_requested = Signal()
    data_saver_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(
        self,
        config: Config,
        base_dir: str = ".",
        settings_path: str = "netpulse_settings.json",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.base_dir = os.path.abspath(base_dir)
        self.settings_path = settings_path

        self.current_status: str = "OK"
        self._init_menu()
        self.update_status("OK", None)

        self.activated.connect(self._on_activated)

    def _init_menu(self) -> None:
        """Build the tray context menu."""
        menu = QMenu()
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1e1e24;
                color: #f3f4f6;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 5px 22px 5px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
            }
            QMenu::separator {
                height: 1px;
                background-color: #374151;
                margin: 4px 8px;
            }
            """
        )

        # 1. Open Dashboard
        self.act_dashboard = menu.addAction("Open Dashboard")
        dash_font = self.act_dashboard.font()
        dash_font.setBold(True)
        self.act_dashboard.setFont(dash_font)
        self.act_dashboard.triggered.connect(self.open_dashboard_requested.emit)

        menu.addSeparator()

        # 2. Run speed test now
        self.act_speed_test = menu.addAction("Run Speed Test Now")
        self.act_speed_test.triggered.connect(self.run_speed_test_requested.emit)

        # 2b. Create Report
        self.act_report = menu.addAction("Create Report (PDF / PNG / CSV)…")
        self.act_report.triggered.connect(self.create_report_requested.emit)

        # 3. Show / Hide Mini Widget
        self.act_widget_toggle = menu.addAction("Show Mini Widget")
        self.act_widget_toggle.setCheckable(True)
        self.act_widget_toggle.setChecked(self.config.widget_visible)
        self.act_widget_toggle.triggered.connect(self._on_widget_toggle)

        # 4. Pause monitoring submenu
        self.pause_menu = menu.addMenu("Pause Monitoring")
        self.act_p15 = self.pause_menu.addAction("Pause for 15 Minutes")
        self.act_p15.triggered.connect(lambda: self.pause_requested.emit(15 * 60))

        self.act_p1h = self.pause_menu.addAction("Pause for 1 Hour")
        self.act_p1h.triggered.connect(lambda: self.pause_requested.emit(60 * 60))

        self.act_p_indef = self.pause_menu.addAction("Pause Until Resumed")
        self.act_p_indef.triggered.connect(lambda: self.pause_requested.emit(None))

        self.pause_menu.addSeparator()
        self.act_resume = self.pause_menu.addAction("Resume Monitoring")
        self.act_resume.triggered.connect(self.resume_requested.emit)
        self.act_resume.setEnabled(False)

        # 5. Data-saver mode
        self.act_data_saver = menu.addAction("Data-Saver Mode (No Speed Tests)")
        self.act_data_saver.setCheckable(True)
        self.act_data_saver.setChecked(self.config.data_saver)
        self.act_data_saver.triggered.connect(self._on_data_saver_toggle)

        # 6. Do Not Disturb
        self.act_dnd = menu.addAction("Do Not Disturb (Mute Toast Alerts)")
        self.act_dnd.setCheckable(True)
        self.act_dnd.setChecked(self.config.do_not_disturb)
        self.act_dnd.triggered.connect(self._on_dnd_toggle)

        menu.addSeparator()

        # 7. Start with Windows
        self.act_autostart = menu.addAction("Start with Windows")
        self.act_autostart.setCheckable(True)
        is_auto = AutostartManager.is_autostart_enabled()
        self.act_autostart.setChecked(is_auto)
        self.act_autostart.triggered.connect(self._on_autostart_toggle)

        # 8. Open data folder
        self.act_data_folder = menu.addAction("Open Data Folder")
        self.act_data_folder.triggered.connect(self._open_data_folder)

        menu.addSeparator()

        # 9. Quit
        self.act_quit = menu.addAction("Quit NetPulse")
        self.act_quit.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(menu)
        self._last_toast_action = None
        self.messageClicked.connect(self._on_message_clicked)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Trigger dashboard on left click or double click."""
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            self.open_dashboard_requested.emit()

    def update_status(self, status: str, record: Optional[NetRecord]) -> None:
        """Update tray icon color and tooltip."""
        self.current_status = status
        self.setIcon(create_tray_icon(status))

        if record:
            lat = f"{record.latency_ms:.0f} ms" if record.latency_ms is not None else "---"
            tip = (
                f"NetPulse: {status} ({lat}, {record.loss_pct:.0f}% loss)\n"
                f"{record.network} via {record.conn}"
            )
        else:
            tip = f"NetPulse Network Monitor ({status})"
        self.setToolTip(tip)

    def set_paused_state(self, is_paused: bool) -> None:
        """Update pause menu actions based on engine state."""
        self.act_resume.setEnabled(is_paused)
        self.act_p15.setEnabled(not is_paused)
        self.act_p1h.setEnabled(not is_paused)
        self.act_p_indef.setEnabled(not is_paused)
        if is_paused:
            self.setToolTip("NetPulse: Monitoring Paused")

    def sync_widget_visibility(self, visible: bool) -> None:
        """Sync checkmark state when widget is hidden/shown elsewhere."""
        self.act_widget_toggle.setChecked(visible)

    def _on_dnd_toggle(self, checked: bool) -> None:
        self.config.do_not_disturb = checked
        self.config.save(self.settings_path)

    def _on_message_clicked(self) -> None:
        """Trigger action associated with last toast notification if any."""
        if self._last_toast_action:
            action = self._last_toast_action
            self._last_toast_action = None
            try:
                action()
            except Exception:
                pass
        else:
            self.open_dashboard_requested.emit()

    def show_toast(
        self,
        kind: str,
        title: str,
        message: str,
        on_click: Optional[Callable[[], None]] = None,
    ) -> None:
        """Display native Windows toast notification via system tray with crash-protection guards."""
        if self.config.do_not_disturb:
            return

        try:
            if not self.isVisible():
                return

            icon_map = {
                "down": QSystemTrayIcon.MessageIcon.Critical,
                "restored": QSystemTrayIcon.MessageIcon.Information,
                "bad": QSystemTrayIcon.MessageIcon.Warning,
                "network_change": QSystemTrayIcon.MessageIcon.Information,
                "high_upload": QSystemTrayIcon.MessageIcon.Warning,
            }
            msg_icon = icon_map.get(kind, QSystemTrayIcon.MessageIcon.Information)
            self._last_toast_action = on_click
            self.showMessage(str(title), str(message), msg_icon, 5000)
        except Exception:
            pass

    def _on_widget_toggle(self, checked: bool) -> None:
        self.config.widget_visible = checked
        self.config.save(self.settings_path)
        self.toggle_widget_requested.emit(checked)

    def _on_data_saver_toggle(self, checked: bool) -> None:
        self.config.data_saver = checked
        self.config.save(self.settings_path)
        self.data_saver_toggled.emit(checked)

    def _on_autostart_toggle(self, checked: bool) -> None:
        AutostartManager.set_autostart(checked)
        self.config.start_with_windows = checked
        self.config.save(self.settings_path)

    def _open_data_folder(self) -> None:
        """Open the data directory in Windows Explorer."""
        if os.path.exists(self.base_dir):
            if sys.platform.startswith("win"):
                os.startfile(self.base_dir)
            else:
                subprocess.Popen(["xdg-open", self.base_dir])

