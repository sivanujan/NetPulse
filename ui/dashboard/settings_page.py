"""Settings and preferences dashboard page for NetPulse."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config import Config
from core.instance import AutostartManager


class SettingsPage(QWidget):
    """Settings page allowing customization of intervals, alerts, widget, and autostart."""

    settings_applied = Signal()

    def __init__(
        self,
        config: Config,
        settings_path: str,
        base_dir: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.settings_path = settings_path
        self.base_dir = base_dir

        self._init_ui()
        self.load_values_from_config()

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area to handle smaller screens smoothly
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 1. Header
        header_layout = QHBoxLayout()
        title_label = QLabel("NetPulse Settings")
        title_label.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 700;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setStyleSheet("color: #22c55e; font-weight: 600; font-size: 11px;")
        header_layout.addWidget(self.lbl_save_status)

        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.btn_save.clicked.connect(self.save_and_apply)
        header_layout.addWidget(self.btn_save)
        layout.addLayout(header_layout)

        # 2. Section 1: Monitoring & Speed Test
        card_monitor = self._create_card("Network Monitoring & Speed Test")
        card_mon_layout = QGridLayout(card_monitor)
        card_mon_layout.setContentsMargins(16, 14, 16, 14)
        card_mon_layout.setSpacing(10)

        card_mon_layout.addWidget(QLabel("Ping Hosts (comma separated):"), 0, 0)
        self.edit_ping_hosts = QLineEdit()
        self.edit_ping_hosts.setPlaceholderText("8.8.8.8, 1.1.1.1")
        card_mon_layout.addWidget(self.edit_ping_hosts, 0, 1)

        card_mon_layout.addWidget(QLabel("Ping Interval:"), 1, 0)
        self.spin_check_interval = QSpinBox()
        self.spin_check_interval.setRange(5, 300)
        self.spin_check_interval.setSuffix(" seconds")
        card_mon_layout.addWidget(self.spin_check_interval, 1, 1)

        card_mon_layout.addWidget(QLabel("Speed Test Interval:"), 2, 0)
        self.combo_speed_interval = QComboBox()
        self.combo_speed_interval.addItems(
            [
                "15 minutes",
                "30 minutes",
                "1 hour (default)",
                "3 hours",
                "Off (data-saver)",
            ]
        )
        card_mon_layout.addWidget(self.combo_speed_interval, 2, 1)

        card_mon_layout.addWidget(QLabel("Speed Test Max Download:"), 3, 0)
        self.spin_speed_mb = QSpinBox()
        self.spin_speed_mb.setRange(1, 50)
        self.spin_speed_mb.setSuffix(" MB")
        card_mon_layout.addWidget(self.spin_speed_mb, 3, 1)

        self.chk_data_saver = QCheckBox("Data-Saver Mode (no automated speed tests, ping only)")
        self.chk_data_saver.setStyleSheet("color: #f3f4f6; font-size: 11px;")
        card_mon_layout.addWidget(self.chk_data_saver, 4, 0, 1, 2)

        layout.addWidget(card_monitor)

        # 3. Section 2: Alert Thresholds & Notifications
        card_alerts = self._create_card("Quality Thresholds & Notifications")
        card_alerts_layout = QGridLayout(card_alerts)
        card_alerts_layout.setContentsMargins(16, 14, 16, 14)
        card_alerts_layout.setSpacing(10)

        card_alerts_layout.addWidget(QLabel("High Latency Alert:"), 0, 0)
        self.spin_alert_ping = QSpinBox()
        self.spin_alert_ping.setRange(50, 2000)
        self.spin_alert_ping.setSuffix(" ms")
        card_alerts_layout.addWidget(self.spin_alert_ping, 0, 1)

        card_alerts_layout.addWidget(QLabel("Packet Loss Alert:"), 1, 0)
        self.spin_alert_loss = QSpinBox()
        self.spin_alert_loss.setRange(5, 100)
        self.spin_alert_loss.setSuffix(" %")
        card_alerts_layout.addWidget(self.spin_alert_loss, 1, 1)

        card_alerts_layout.addWidget(QLabel("Sustained Degraded Duration:"), 2, 0)
        self.spin_alert_min = QSpinBox()
        self.spin_alert_min.setRange(1, 60)
        self.spin_alert_min.setSuffix(" minutes")
        card_alerts_layout.addWidget(self.spin_alert_min, 2, 1)

        card_alerts_layout.addWidget(QLabel("PC High Upload Warning:"), 3, 0)
        self.spin_upload_kbps = QSpinBox()
        self.spin_upload_kbps.setRange(100, 10000)
        self.spin_upload_kbps.setSuffix(" kbps")
        card_alerts_layout.addWidget(self.spin_upload_kbps, 3, 1)

        self.chk_dnd = QCheckBox("Do Not Disturb (suppress desktop Windows toast notifications)")
        self.chk_dnd.setStyleSheet("color: #f3f4f6; font-size: 11px;")
        card_alerts_layout.addWidget(self.chk_dnd, 4, 0, 1, 2)

        layout.addWidget(card_alerts)

        # 4. Section 3: Desktop Mini Widget & Theme
        card_widget = self._create_card("Desktop Mini Widget & Appearance")
        card_w_layout = QGridLayout(card_widget)
        card_w_layout.setContentsMargins(16, 14, 16, 14)
        card_w_layout.setSpacing(10)

        card_w_layout.addWidget(QLabel("Widget Opacity:"), 0, 0)
        op_layout = QHBoxLayout()
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(30, 100)
        self.lbl_opacity_val = QLabel("95%")
        self.lbl_opacity_val.setStyleSheet("color: #38bdf8; font-weight: 600; min-width: 35px;")
        self.slider_opacity.valueChanged.connect(lambda v: self.lbl_opacity_val.setText(f"{v}%"))
        op_layout.addWidget(self.slider_opacity)
        op_layout.addWidget(self.lbl_opacity_val)
        card_w_layout.addLayout(op_layout, 0, 1)

        self.chk_always_on_top = QCheckBox("Always on top")
        self.chk_compact = QCheckBox("Compact mode (hide sparkline & traffic)")
        self.chk_locked = QCheckBox("Lock position on screen")
        self.chk_click_through = QCheckBox("Click-through (transparent to mouse events)")

        for cb in [self.chk_always_on_top, self.chk_compact, self.chk_locked, self.chk_click_through]:
            cb.setStyleSheet("color: #f3f4f6; font-size: 11px;")

        card_w_layout.addWidget(self.chk_always_on_top, 1, 0)
        card_w_layout.addWidget(self.chk_compact, 1, 1)
        card_w_layout.addWidget(self.chk_locked, 2, 0)
        card_w_layout.addWidget(self.chk_click_through, 2, 1)

        card_w_layout.addWidget(QLabel("Dashboard Theme:"), 3, 0)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Dark (default)", "Light"])
        card_w_layout.addWidget(self.combo_theme, 3, 1)

        layout.addWidget(card_widget)

        # 5. Section 4: System Integration & Data Folder
        card_sys = self._create_card("System Integration & Data")
        card_sys_layout = QGridLayout(card_sys)
        card_sys_layout.setContentsMargins(16, 14, 16, 14)
        card_sys_layout.setSpacing(10)

        self.chk_start_windows = QCheckBox("Start NetPulse with Windows (HKCU Run)")
        self.chk_start_windows.setStyleSheet("color: #f3f4f6; font-size: 11px; font-weight: 600;")
        card_sys_layout.addWidget(self.chk_start_windows, 0, 0, 1, 2)

        card_sys_layout.addWidget(QLabel("Data Directory:"), 1, 0)
        folder_row = QHBoxLayout()
        self.lbl_data_dir = QLabel(self.base_dir)
        self.lbl_data_dir.setStyleSheet("color: #A0A4AE; font-size: 11px; font-family: monospace;")
        folder_row.addWidget(self.lbl_data_dir, 1)

        btn_open_folder = QPushButton("Open Folder")
        btn_open_folder.setStyleSheet(
            """
            QPushButton {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #323340;
            }
            """
        )
        btn_open_folder.clicked.connect(self._open_data_folder)
        folder_row.addWidget(btn_open_folder)
        card_sys_layout.addLayout(folder_row, 1, 1)

        layout.addWidget(card_sys)

        # 6. Section 5: Complaint Report Subscriber Details
        card_rep = self._create_card("Complaint Report Subscriber Details (TRCSL / ISP)")
        card_rep_layout = QGridLayout(card_rep)
        card_rep_layout.setContentsMargins(16, 14, 16, 14)
        card_rep_layout.setSpacing(10)

        card_rep_layout.addWidget(QLabel("Subscriber / Account Name:"), 0, 0)
        self.edit_user_name = QLineEdit()
        self.edit_user_name.setPlaceholderText("e.g. K. Sivanujan")
        card_rep_layout.addWidget(self.edit_user_name, 0, 1)

        card_rep_layout.addWidget(QLabel("Address / Connection Location:"), 1, 0)
        self.edit_user_address = QLineEdit()
        self.edit_user_address.setPlaceholderText("e.g. No. 12, Main Street, Jaffna (Dialog 4G Home Broadband)")
        card_rep_layout.addWidget(self.edit_user_address, 1, 1)

        lbl_rep_hint = QLabel("These details are included in the header of PDF/PNG complaint reports generated for TRCSL or ISP disputes.")
        lbl_rep_hint.setStyleSheet("color: #71717a; font-size: 10px; font-style: italic;")
        card_rep_layout.addWidget(lbl_rep_hint, 2, 0, 1, 2)

        layout.addWidget(card_rep)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def _create_card(self, title: str) -> QFrame:
        """Create styled Windows 11 card container."""
        frame = QFrame()
        frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1f25;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QLabel {
                color: #A0A4AE;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }
            """
        )
        return frame

    def load_values_from_config(self) -> None:
        """Populate input controls with current config values."""
        self.edit_ping_hosts.setText(", ".join(self.config.ping_hosts))
        self.spin_check_interval.setValue(self.config.check_interval_sec)

        # Speed test interval mapping
        sec = self.config.speed_interval_sec
        if self.config.data_saver or sec <= 0:
            self.combo_speed_interval.setCurrentText("Off (data-saver)")
        elif sec <= 900:
            self.combo_speed_interval.setCurrentText("15 minutes")
        elif sec <= 1800:
            self.combo_speed_interval.setCurrentText("30 minutes")
        elif sec <= 3600:
            self.combo_speed_interval.setCurrentText("1 hour (default)")
        else:
            self.combo_speed_interval.setCurrentText("3 hours")

        self.spin_speed_mb.setValue(max(1, int(self.config.speed_max_bytes / 1_000_000)))
        self.chk_data_saver.setChecked(self.config.data_saver)

        # Alerts
        self.spin_alert_ping.setValue(int(self.config.alert_latency_ms))
        self.spin_alert_loss.setValue(int(self.config.alert_loss_pct))
        self.spin_alert_min.setValue(self.config.alert_degraded_min)
        self.spin_upload_kbps.setValue(int(self.config.high_upload_kbps))
        self.chk_dnd.setChecked(self.config.do_not_disturb)

        # Widget
        op_val = int(self.config.widget_opacity * 100)
        self.slider_opacity.setValue(op_val)
        self.lbl_opacity_val.setText(f"{op_val}%")
        self.chk_always_on_top.setChecked(self.config.widget_always_on_top)
        self.chk_compact.setChecked(self.config.widget_compact)
        self.chk_locked.setChecked(self.config.widget_locked)
        self.chk_click_through.setChecked(self.config.widget_click_through)

        theme_text = "Light" if self.config.theme == "light" else "Dark (default)"
        self.combo_theme.setCurrentText(theme_text)

        # System
        self.chk_start_windows.setChecked(self.config.start_with_windows)

        # Report details
        self.edit_user_name.setText(self.config.user_name)
        self.edit_user_address.setText(self.config.user_address)

    def save_and_apply(self) -> None:
        """Apply modified values to active Config object and save to disk."""
        # 1. Monitoring & Speed
        raw_hosts = [h.strip() for h in self.edit_ping_hosts.text().split(",") if h.strip()]
        if raw_hosts:
            self.config.ping_hosts = raw_hosts
        self.config.check_interval_sec = self.spin_check_interval.value()

        # Map interval text to seconds
        txt = self.combo_speed_interval.currentText()
        if "15" in txt:
            self.config.speed_interval_sec = 900
            self.config.data_saver = False
        elif "30" in txt:
            self.config.speed_interval_sec = 1800
            self.config.data_saver = False
        elif "1 hour" in txt:
            self.config.speed_interval_sec = 3600
            self.config.data_saver = False
        elif "3 hours" in txt:
            self.config.speed_interval_sec = 10800
            self.config.data_saver = False
        elif "Off" in txt:
            self.config.data_saver = True

        if self.chk_data_saver.isChecked():
            self.config.data_saver = True

        self.config.speed_max_bytes = self.spin_speed_mb.value() * 1_000_000

        # 2. Alerts
        self.config.alert_latency_ms = float(self.spin_alert_ping.value())
        self.config.alert_loss_pct = float(self.spin_alert_loss.value())
        self.config.alert_degraded_min = self.spin_alert_min.value()
        self.config.high_upload_kbps = float(self.spin_upload_kbps.value())
        self.config.do_not_disturb = self.chk_dnd.isChecked()

        # 3. Widget & Theme
        self.config.widget_opacity = self.slider_opacity.value() / 100.0
        self.config.widget_always_on_top = self.chk_always_on_top.isChecked()
        self.config.widget_compact = self.chk_compact.isChecked()
        self.config.widget_locked = self.chk_locked.isChecked()
        self.config.widget_click_through = self.chk_click_through.isChecked()
        self.config.theme = "light" if "Light" in self.combo_theme.currentText() else "dark"

        # 4. Autostart
        new_autostart = self.chk_start_windows.isChecked()
        if new_autostart != self.config.start_with_windows:
            self.config.start_with_windows = new_autostart
            autostart_mgr = AutostartManager(self.base_dir)
            autostart_mgr.set_autostart(new_autostart)

        # 5. Report details
        self.config.user_name = self.edit_user_name.text().strip()
        self.config.user_address = self.edit_user_address.text().strip()

        # Save to disk
        self.config.save(self.settings_path)

        # Emit signal to update live widget, tray, and engine without restart
        self.settings_applied.emit()

        self.lbl_save_status.setText("✓ Settings saved and applied")
        QTimer.singleShot(3000, lambda: self.lbl_save_status.setText(""))

    def _open_data_folder(self) -> None:
        """Open local data folder in Windows Explorer."""
        folder = os.path.abspath(self.base_dir)
        if sys.platform.startswith("win"):
            os.startfile(folder)
        else:
            subprocess.run(["xdg-open", folder])
