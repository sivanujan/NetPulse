"""Floating desktop mini widget for NetPulse: live ping, loss, sparkline, and PC traffic."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from core.config import (
    LATENCY_AMBER_MAX,
    LATENCY_GREEN_MAX,
    LOSS_AMBER_MAX,
    Config,
)
from core.storage import NetRecord, SpeedRecord
from ui.sparkline import SparklineWidget

# High-contrast colors
COLOR_GREEN = "#22c55e"
COLOR_AMBER = "#f59e0b"
COLOR_RED = "#ef4444"
COLOR_GREY = "#A0A4AE"


def get_status_info(latency_ms: Optional[float], loss_pct: float, status: str) -> Tuple[str, str]:
    """Return (color_hex, status_word) based on quality thresholds."""
    if status == "DOWN" or latency_ms is None:
        return COLOR_GREY, "Down"
    if loss_pct >= LOSS_AMBER_MAX or latency_ms > LATENCY_AMBER_MAX:
        return COLOR_RED, "Bad"
    if latency_ms >= LATENCY_GREEN_MAX:
        return COLOR_AMBER, "Slow"
    return COLOR_GREEN, "Good"


def get_status_color(latency_ms: Optional[float], loss_pct: float, status: str) -> str:
    """Determine UI color based on network quality thresholds."""
    color, _ = get_status_info(latency_ms, loss_pct, status)
    return color


def format_traffic_rate(kbps: Optional[float]) -> str:
    """Format traffic: below 1000 kbps show '850 kbps', from 1000 show '1.0 Mbps'."""
    if kbps is None or kbps < 0:
        return "0 kbps"
    if kbps < 1000.0:
        return f"{kbps:.0f} kbps"
    mbps = kbps / 1000.0
    return f"{mbps:.1f} Mbps" if mbps < 100.0 else f"{mbps:.0f} Mbps"


class DesktopWidget(QWidget):
    """Small, floating, semi-transparent desktop card displaying live network vitals."""

    open_dashboard_requested = Signal()
    run_speed_test_requested = Signal()
    open_data_folder_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        config: Config,
        settings_path: str = "netpulse_settings.json",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.settings_path = settings_path

        self._drag_pos: Optional[QPoint] = None
        self._ping_history: List[Optional[float]] = []
        self._today_uptime: float = 100.0
        self._today_median_ping: Optional[float] = None
        self._today_checks: int = 0
        self._last_speed_record: Optional[SpeedRecord] = None

        self._init_window_flags()
        self._init_ui()
        self._apply_config_options()
        self._restore_position()

    def _init_window_flags(self) -> None:
        """Set frameless, translucent, and tool-window flags."""
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.config.widget_always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def _init_ui(self) -> None:
        """Construct the widget layouts and labels."""
        self.setObjectName("NetPulseWidget")

        # Root Card Frame with rounded border
        self.card = QFrame(self)
        self.card.setObjectName("CardFrame")
        self._update_card_style()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.card)

        # Card Content Layout
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(11, 8, 11, 8)
        self.card_layout.setSpacing(4)

        # --- Row 1: Status Dot, Status Word, Provider & Connection, Last Speed ---
        top_row = QHBoxLayout()
        top_row.setSpacing(5)

        self.dot_label = QLabel("●")
        self.dot_label.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px;")
        top_row.addWidget(self.dot_label)

        self.status_word_label = QLabel("Good")
        self.status_word_label.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px; font-weight: 700; margin-right: 2px;")
        top_row.addWidget(self.status_word_label)

        self.network_label = QLabel("Detecting...")
        self.network_label.setStyleSheet("color: #f3f4f6; font-size: 11px; font-weight: 600;")
        top_row.addWidget(self.network_label, 1)

        self.last_speed_label = QLabel("---")
        self.last_speed_label.setStyleSheet("color: #A0A4AE; font-size: 10px; font-weight: 500;")
        top_row.addWidget(self.last_speed_label)

        self.card_layout.addLayout(top_row)

        # --- Row 2: Big Live Ping + 'ms' unit, Loss %, Sparkline ---
        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)

        # Ping number + unit
        ping_box = QVBoxLayout()
        ping_box.setSpacing(0)

        ping_val_row = QHBoxLayout()
        ping_val_row.setSpacing(3)
        ping_val_row.setAlignment(Qt.AlignLeft | Qt.AlignBottom)

        self.ping_value_label = QLabel("---")
        self.ping_value_label.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 26px; font-weight: 700; line-height: 26px;")
        ping_val_row.addWidget(self.ping_value_label)

        self.ping_unit_label = QLabel("ms")
        self.ping_unit_label.setStyleSheet("color: #A0A4AE; font-size: 11px; font-weight: 600; margin-bottom: 3px;")
        ping_val_row.addWidget(self.ping_unit_label)

        ping_box.addLayout(ping_val_row)

        self.loss_label = QLabel("0% loss")
        self.loss_label.setStyleSheet("color: #A0A4AE; font-size: 10px; font-weight: 500;")
        ping_box.addWidget(self.loss_label)

        mid_row.addLayout(ping_box)

        # Sparkline (last 10 minutes)
        self.sparkline = SparklineWidget(self)
        mid_row.addWidget(self.sparkline, 1)

        self.card_layout.addLayout(mid_row)

        # --- Row 3: PC Traffic (Down/Up formatted) & High Upload Warning ---
        self.bottom_row = QHBoxLayout()
        self.bottom_row.setSpacing(6)

        # Using Segoe UI Variable with tabular figures (no monospace)
        self.traffic_label = QLabel("↓ 0 kbps   ↑ 0 kbps")
        self.traffic_label.setStyleSheet(
            "color: #A0A4AE; font-size: 10px; font-weight: 500; "
            "font-family: 'Segoe UI Variable', 'Segoe UI', -apple-system, sans-serif; "
            "font-feature-settings: 'tnum'; font-variant-numeric: tabular-nums;"
        )
        self.bottom_row.addWidget(self.traffic_label, 1)

        self.upload_warning_label = QLabel("⚠ High Up")
        self.upload_warning_label.setStyleSheet(
            "color: #f59e0b; font-size: 9px; font-weight: 700; background: rgba(245, 158, 11, 0.18); "
            "padding: 1px 5px; border-radius: 4px;"
        )
        self.upload_warning_label.setVisible(False)
        self.bottom_row.addWidget(self.upload_warning_label)

        self.card_layout.addLayout(self.bottom_row)

        # Base dimensions (expanded mode)
        self.resize(265, 112)

    def _update_card_style(self) -> None:
        """Apply semi-transparent dark card CSS with rounded corners."""
        self.card.setStyleSheet(
            f"""
            QFrame#CardFrame {{
                background-color: rgba(22, 23, 27, {self.config.widget_opacity});
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }}
            QLabel {{
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
            }}
            """
        )

    def _apply_config_options(self) -> None:
        """Apply always-on-top, opacity, lock, compact, and click-through options."""
        self.setWindowOpacity(1.0)
        if self.config.widget_compact:
            self.set_compact_mode(True)
        self._apply_click_through(self.config.widget_click_through)

    def _apply_click_through(self, enabled: bool) -> None:
        """Toggle input transparency."""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    def _restore_position(self) -> None:
        """Restore saved window coordinates, ensuring visibility on active monitors."""
        x = self.config.widget_pos_x
        y = self.config.widget_pos_y

        if x >= 0 and y >= 0:
            point = QPoint(x, y)
            for screen in QGuiApplication.screens():
                if screen.geometry().contains(point):
                    self.move(point)
                    return

        primary = QGuiApplication.primaryScreen()
        if primary:
            avail = primary.availableGeometry()
            default_x = avail.right() - 285
            default_y = avail.bottom() - 135
            self.move(default_x, default_y)

    def save_position(self) -> None:
        """Save current position to config and disk."""
        pos = self.pos()
        self.config.widget_pos_x = pos.x()
        self.config.widget_pos_y = pos.y()
        self.config.save(self.settings_path)

    # ================= Live Data Updates =================

    def update_sample(self, record: NetRecord) -> None:
        """Update live ping, loss, provider, connection, traffic, and sparkline."""
        # 1. Colors & Status Word
        color, word = get_status_info(record.latency_ms, record.loss_pct, record.status)
        self.dot_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.status_word_label.setText(word)
        self.status_word_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; margin-right: 2px;")

        # 2. Ping Value
        if record.status == "DOWN" or record.latency_ms is None:
            self.ping_value_label.setText("---")
            self.ping_value_label.setStyleSheet(f"color: {COLOR_GREY}; font-size: 26px; font-weight: 700;")
        else:
            self.ping_value_label.setText(f"{record.latency_ms:.0f}")
            self.ping_value_label.setStyleSheet(f"color: {color}; font-size: 26px; font-weight: 700;")

        # 3. Loss %
        if record.loss_pct > 0:
            self.loss_label.setText(f"{record.loss_pct:.0f}% loss")
            self.loss_label.setStyleSheet(f"color: {COLOR_RED if record.loss_pct >= 25 else COLOR_AMBER}; font-size: 10px; font-weight: 600;")
        else:
            self.loss_label.setText("0% loss")
            self.loss_label.setStyleSheet("color: #A0A4AE; font-size: 10px; font-weight: 500;")

        # 4. Network and Connection Label
        conn_str = record.conn
        if record.wifi_signal is not None and record.conn.startswith("WiFi"):
            conn_str = f"{record.conn} ({record.wifi_signal:.0f}%)"
        self.network_label.setText(f"{record.network} · {conn_str}")

        # 5. PC Traffic (formatted rate: < 1000 kbps as kbps, >= 1000 as Mbps)
        down_str = format_traffic_rate(record.pc_down_kbps)
        up_str = format_traffic_rate(record.pc_up_kbps)
        self.traffic_label.setText(f"↓ {down_str}   ↑ {up_str}")

        # 6. Sparkline
        self._ping_history.append(record.latency_ms)
        if len(self._ping_history) > 20:
            self._ping_history.pop(0)
        self.sparkline.set_data(self._ping_history, status=record.status)

        # 7. Update hover tooltip
        self._update_tooltip()

    def update_speed_sample(self, speed_record: SpeedRecord) -> None:
        """Update last speed test label."""
        self._last_speed_record = speed_record
        if speed_record.download_mbps is not None:
            mbps_str = f"{speed_record.download_mbps:.1f} Mbps"
            diff_min = 0
            if speed_record.dt:
                diff_min = max(0, int((datetime.now() - speed_record.dt).total_seconds() / 60))
            ago_str = f"{diff_min}m ago" if diff_min > 0 else "just now"
            self.last_speed_label.setText(f"{mbps_str} · {ago_str}")
        else:
            self.last_speed_label.setText("---")

    def set_today_summary(self, uptime_pct: float, median_ping: Optional[float], checks: int) -> None:
        """Set today's metrics for hover tooltip."""
        self._today_uptime = uptime_pct
        self._today_median_ping = median_ping
        self._today_checks = checks
        self._update_tooltip()

    def set_high_upload_warning(self, active: bool) -> None:
        """Show or hide high upload alert badge."""
        self.upload_warning_label.setVisible(active)

    def _update_tooltip(self) -> None:
        """Format hover tooltip with today's uptime and median ping."""
        med_str = f"{self._today_median_ping:.0f} ms" if self._today_median_ping is not None else "---"
        tip = (
            f"NetPulse Live Monitor\n"
            f"Today: {self._today_uptime:.1f}% uptime · {med_str} median ping ({self._today_checks} checks)\n"
            f"Double-click to open Dashboard · Right-click for options"
        )
        self.setToolTip(tip)

    # ================= Compact / Expanded Modes =================

    def set_compact_mode(self, compact: bool) -> None:
        """Toggle between compact (~210x65) and expanded (~265x112) mode."""
        self.config.widget_compact = compact
        self.sparkline.setVisible(not compact)
        self.bottom_row.setEnabled(not compact)
        if compact:
            self.resize(210, 65)
        else:
            self.resize(265, 112)
        self.config.save(self.settings_path)

    # ================= Mouse Drag & Context Menu =================

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Initiate window drag on left click unless locked."""
        if event.button() == Qt.LeftButton and not self.config.widget_locked:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move window smoothly with mouse pointer."""
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None and not self.config.widget_locked:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Save position when drag completes."""
        if event.button() == Qt.LeftButton and self._drag_pos is not None:
            self._drag_pos = None
            self.save_position()
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Open dashboard on double click."""
        if event.button() == Qt.LeftButton:
            self.open_dashboard_requested.emit()
            event.accept()

    def contextMenuEvent(self, event: Any) -> None:
        """Show right-click options menu."""
        menu = QMenu(self)
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
                padding: 5px 20px 5px 24px;
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

        act_dash = menu.addAction("Open Dashboard")
        act_dash.triggered.connect(self.open_dashboard_requested.emit)

        act_speed = menu.addAction("Run Speed Test Now")
        act_speed.triggered.connect(self.run_speed_test_requested.emit)

        menu.addSeparator()

        act_ontop = menu.addAction("Always on Top")
        act_ontop.setCheckable(True)
        act_ontop.setChecked(self.config.widget_always_on_top)
        act_ontop.triggered.connect(self._toggle_always_on_top)

        act_lock = menu.addAction("Lock Position")
        act_lock.setCheckable(True)
        act_lock.setChecked(self.config.widget_locked)
        act_lock.triggered.connect(self._toggle_locked)

        act_compact = menu.addAction("Compact Mode")
        act_compact.setCheckable(True)
        act_compact.setChecked(self.config.widget_compact)
        act_compact.triggered.connect(lambda chk: self.set_compact_mode(chk))

        opacity_menu = menu.addMenu("Opacity")
        for op in [1.0, 0.95, 0.85, 0.70]:
            pct = int(op * 100)
            act_op = opacity_menu.addAction(f"{pct}%")
            act_op.setCheckable(True)
            act_op.setChecked(abs(self.config.widget_opacity - op) < 0.03)
            act_op.triggered.connect(lambda _, val=op: self._set_opacity(val))

        act_clickthrough = menu.addAction("Click-Through Mode")
        act_clickthrough.setCheckable(True)
        act_clickthrough.setChecked(self.config.widget_click_through)
        act_clickthrough.triggered.connect(self._toggle_click_through)

        menu.addSeparator()

        act_hide = menu.addAction("Hide Mini Widget")
        act_hide.triggered.connect(self.hide)

        act_folder = menu.addAction("Open Data Folder")
        act_folder.triggered.connect(self.open_data_folder_requested.emit)

        menu.addSeparator()

        act_quit = menu.addAction("Quit NetPulse")
        act_quit.triggered.connect(self.quit_requested.emit)

        menu.exec(QCursor.pos())

    def _toggle_always_on_top(self, checked: bool) -> None:
        self.config.widget_always_on_top = checked
        self.config.save(self.settings_path)
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def _toggle_locked(self, checked: bool) -> None:
        self.config.widget_locked = checked
        self.config.save(self.settings_path)

    def _set_opacity(self, opacity: float) -> None:
        self.config.widget_opacity = opacity
        self.config.save(self.settings_path)
        self._update_card_style()

    def _toggle_click_through(self, checked: bool) -> None:
        self.config.widget_click_through = checked
        self.config.save(self.settings_path)
        self._apply_click_through(checked)
