"""Live monitoring dashboard page with real-time gauges and 1-hour rolling pyqtgraph charts."""

from __future__ import annotations

import time
from typing import List, Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.config import (
    DEFAULT_BUSY_KBPS,
    LATENCY_AMBER_MAX,
    LATENCY_GREEN_MAX,
    LOSS_AMBER_MAX,
)
from core.storage import NetRecord
from ui.widget import format_traffic_rate, get_status_info

COLOR_GREEN = "#22c55e"
COLOR_AMBER = "#f59e0b"
COLOR_RED = "#ef4444"
COLOR_GREY = "#A0A4AE"


def create_stat_card(title: str) -> tuple[QFrame, QLabel, QLabel, QLabel]:
    """Helper to build a styled dark card frame with a title, main value, and subtitle."""
    card = QFrame()
    card.setStyleSheet(
        """
        QFrame {
            background-color: #1e1f25;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
        }
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(4)

    title_label = QLabel(title.upper())
    title_label.setStyleSheet("color: #A0A4AE; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;")
    layout.addWidget(title_label)

    val_label = QLabel("---")
    val_label.setStyleSheet("color: #f3f4f6; font-size: 24px; font-weight: 700;")
    layout.addWidget(val_label)

    extra_label = QLabel("")
    extra_label.setStyleSheet("color: #A0A4AE; font-size: 11px; font-weight: 500;")
    layout.addWidget(extra_label)

    return card, title_label, val_label, extra_label


class LivePage(QWidget):
    """Live monitor page showing current vitals and 1-hour rolling charts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ping_times: List[float] = []
        self._ping_values: List[float] = []
        self._loss_values: List[float] = []
        self._traffic_times: List[float] = []
        self._pc_down: List[float] = []
        self._pc_up: List[float] = []
        self._needs_plot_refresh: bool = False

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 1. Page Header
        header_layout = QHBoxLayout()
        page_title = QLabel("Live Network Quality")
        page_title.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 700;")
        header_layout.addWidget(page_title)
        header_layout.addStretch()

        self.last_update_label = QLabel("Waiting for live data...")
        self.last_update_label.setStyleSheet("color: #A0A4AE; font-size: 11px;")
        header_layout.addWidget(self.last_update_label)
        main_layout.addLayout(header_layout)

        # 2. Vitals Cards Grid
        grid = QGridLayout()
        grid.setSpacing(12)

        # Card 1: Ping
        self.card_ping, _, self.val_ping, self.sub_ping = create_stat_card("Latency")
        grid.addWidget(self.card_ping, 0, 0)

        # Card 2: Packet Loss & DNS
        self.card_loss, _, self.val_loss, self.sub_loss = create_stat_card("Packet Loss")
        grid.addWidget(self.card_loss, 0, 1)

        # Card 3: Network & Adapter
        self.card_net, _, self.val_net, self.sub_net = create_stat_card("Active Connection")
        grid.addWidget(self.card_net, 0, 2)

        # Card 4: PC Usage
        self.card_traffic, _, self.val_traffic, self.sub_traffic = create_stat_card("PC Internet Use")
        grid.addWidget(self.card_traffic, 0, 3)

        main_layout.addLayout(grid)

        # 3. pyqtgraph Plots (Last 1 Hour)
        charts_frame = QFrame()
        charts_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1f25;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            """
        )
        charts_layout = QVBoxLayout(charts_frame)
        charts_layout.setContentsMargins(10, 10, 10, 10)
        charts_layout.setSpacing(8)

        # Configure pyqtgraph global colors
        pg.setConfigOption("background", "#1e1f25")
        pg.setConfigOption("foreground", "#A0A4AE")
        pg.setConfigOption("antialias", True)

        # Graphics Layout Widget
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#1e1f25")

        # Top Plot: Ping (ms) & Loss (%)
        date_axis_top = pg.DateAxisItem(orientation="bottom")
        self.plot_ping = self.glw.addPlot(
            row=0, col=0, axisItems={"bottom": date_axis_top}, title="Ping Latency (Last 1 Hour)"
        )
        self.plot_ping.showGrid(x=True, y=True, alpha=0.15)
        self.plot_ping.setDownsampling(auto=True)
        self.plot_ping.setClipToView(True)
        self.plot_ping.setLabel("left", "ms", color="#A0A4AE")
        self.plot_ping.setYRange(0, 200, padding=0.1)

        # 150 ms Guide line
        guide_150 = pg.InfiniteLine(
            pos=150, angle=0, pen=pg.mkPen(color="#f59e0b", style=Qt.DashLine, width=1.2)
        )
        self.plot_ping.addItem(guide_150)

        # Ping Curve
        self.curve_ping = self.plot_ping.plot(
            pen=pg.mkPen(color=COLOR_GREEN, width=2.0),
            name="Ping",
        )

        # Bottom Plot: PC Bandwidth (kbps)
        date_axis_bottom = pg.DateAxisItem(orientation="bottom")
        self.plot_traffic = self.glw.addPlot(
            row=1, col=0, axisItems={"bottom": date_axis_bottom}, title="PC Bandwidth (Last 1 Hour)"
        )
        self.plot_traffic.showGrid(x=True, y=True, alpha=0.15)
        self.plot_traffic.setDownsampling(auto=True)
        self.plot_traffic.setClipToView(True)
        self.plot_traffic.setLabel("left", "kbps", color="#A0A4AE")
        self.plot_traffic.setXLink(self.plot_ping)  # Synchronize zoom/pan

        # 300 kbps Guide line
        guide_300 = pg.InfiniteLine(
            pos=DEFAULT_BUSY_KBPS,
            angle=0,
            pen=pg.mkPen(color="#71717a", style=Qt.DotLine, width=1.0),
        )
        self.plot_traffic.addItem(guide_300)

        # Download Curve (Blue) & Upload Curve (Orange)
        self.curve_down = self.plot_traffic.plot(
            pen=pg.mkPen(color="#38bdf8", width=1.8), name="Download"
        )
        self.curve_up = self.plot_traffic.plot(
            pen=pg.mkPen(color="#f97316", width=1.8), name="Upload"
        )

        charts_layout.addWidget(self.glw)
        main_layout.addWidget(charts_frame, 1)

    def seed_history(self, records: List[NetRecord]) -> None:
        """Seed rolling 1-hour window from recent database records."""
        cutoff = time.time() - 3600.0
        self._ping_times.clear()
        self._ping_values.clear()
        self._loss_values.clear()
        self._traffic_times.clear()
        self._pc_down.clear()
        self._pc_up.clear()

        for r in records:
            if not r.dt:
                continue
            ts = r.dt.timestamp()
            if ts < cutoff:
                continue

            if r.latency_ms is not None:
                self._ping_times.append(ts)
                self._ping_values.append(r.latency_ms)
                self._loss_values.append(r.loss_pct)

            if r.pc_down_kbps is not None and r.pc_up_kbps is not None:
                self._traffic_times.append(ts)
                self._pc_down.append(r.pc_down_kbps)
                self._pc_up.append(r.pc_up_kbps)

        self._refresh_plots()

    def update_sample(self, record: NetRecord) -> None:
        """Update live gauge cards and append to 1-hour rolling charts."""
        # 1. Update Card 1: Ping
        color, word = get_status_info(record.latency_ms, record.loss_pct, record.status)
        if record.status == "DOWN" or record.latency_ms is None:
            self.val_ping.setText("DOWN")
            self.val_ping.setStyleSheet(f"color: {COLOR_GREY}; font-size: 24px; font-weight: 700;")
            self.sub_ping.setText("Internet unreachable")
        else:
            self.val_ping.setText(f"{record.latency_ms:.0f} ms")
            self.val_ping.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 700;")
            self.sub_ping.setText(f"Status: {word} · Quality: {record.status}")

        # 2. Update Card 2: Loss & DNS
        loss_color = COLOR_RED if record.loss_pct >= LOSS_AMBER_MAX else (COLOR_AMBER if record.loss_pct > 0 else "#f3f4f6")
        self.val_loss.setText(f"{record.loss_pct:.1f}%")
        self.val_loss.setStyleSheet(f"color: {loss_color}; font-size: 24px; font-weight: 700;")
        dns_str = f"DNS: {record.dns_ms:.0f} ms" if record.dns_ms is not None else "DNS: ---"
        self.sub_loss.setText(dns_str)

        # 3. Update Card 3: Network
        self.val_net.setText(record.network)
        conn_extra = record.conn
        if record.wifi_signal is not None:
            conn_extra += f" ({record.wifi_signal:.0f}%)"
        self.sub_net.setText(f"{conn_extra} · {record.local_ip}")

        # 4. Update Card 4: PC Usage
        down_str = format_traffic_rate(record.pc_down_kbps)
        up_str = format_traffic_rate(record.pc_up_kbps)
        self.val_traffic.setText(f"↓ {down_str}")
        self.sub_traffic.setText(f"↑ {up_str} upload")

        self.last_update_label.setText(f"Updated: {record.time}")

        # 5. Append to rolling 1-hour arrays
        now_ts = record.dt.timestamp() if record.dt else time.time()
        cutoff = now_ts - 3600.0

        if record.latency_ms is not None:
            self._ping_times.append(now_ts)
            self._ping_values.append(record.latency_ms)
            self._loss_values.append(record.loss_pct)

        if record.pc_down_kbps is not None and record.pc_up_kbps is not None:
            self._traffic_times.append(now_ts)
            self._pc_down.append(record.pc_down_kbps)
            self._pc_up.append(record.pc_up_kbps)

        # Evict data older than 1 hour
        while self._ping_times and self._ping_times[0] < cutoff:
            self._ping_times.pop(0)
            self._ping_values.pop(0)
            self._loss_values.pop(0)

        while self._traffic_times and self._traffic_times[0] < cutoff:
            self._traffic_times.pop(0)
            self._pc_down.pop(0)
            self._pc_up.pop(0)

        if self.isVisible():
            self._refresh_plots()
            self._needs_plot_refresh = False
        else:
            self._needs_plot_refresh = True

    def showEvent(self, event: Any) -> None:
        """Refresh plots when switching back to the Live tab if new samples arrived while hidden."""
        super().showEvent(event)
        if self._needs_plot_refresh:
            self._refresh_plots()
            self._needs_plot_refresh = False

    def _refresh_plots(self) -> None:
        """Update pyqtgraph curves."""
        from core.perf import log_timing

        with log_timing("Live plot update"):
            if self._ping_times:
                self.curve_ping.setData(self._ping_times, self._ping_values)
                max_lat = max(self._ping_values)
                self.plot_ping.setYRange(0, max(200.0, max_lat * 1.15), padding=0.05)

            if self._traffic_times:
                self.curve_down.setData(self._traffic_times, self._pc_down)
                self.curve_up.setData(self._traffic_times, self._pc_up)
                max_traffic = max(max(self._pc_down, default=0), max(self._pc_up, default=0))
                self.plot_traffic.setYRange(0, max(500.0, max_traffic * 1.15), padding=0.05)

