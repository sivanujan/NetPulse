"""Historical analysis dashboard page with date/network filters and 4 interactive synced charts."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QDate, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import DEFAULT_BUSY_KBPS
from core.downsample import downsample_series
from core.perf import log_timing
from core.stats import find_gaps, find_outages, summarize
from core.storage import NetRecord, SpeedRecord, Storage
from ui.async_worker import AsyncWorker


class HistoryPage(QWidget):
    """History page with date/provider filters, summary stats, and 4 synced charts."""

    def __init__(self, storage: Storage, parent: Optional[QWidget] = None, sync: bool = False) -> None:
        super().__init__(parent)
        self.storage = storage
        self._region_items: List[pg.LinearRegionItem] = []

        # Performance & Caching
        self._cache_key: Optional[Tuple[Any, ...]] = None
        self._cache_time: float = 0.0
        self._cache_data: Optional[Dict[str, Any]] = None
        self._query_id: int = 0
        self._is_loading: bool = False

        # Filter Debounce Timer (300 ms)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._do_apply_filter)
        self._worker: Optional[AsyncWorker] = None

        self._init_ui()
        self.populate_filter_dropdowns()
        self.apply_filter(sync=sync)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # 1. Filter Control Bar Frame
        filter_frame = QFrame()
        filter_frame.setStyleSheet(
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
            QComboBox, QDateEdit {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
            }
            """
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(10)

        # Preset Selector
        filter_layout.addWidget(QLabel("Range:"))
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(
            [
                "Last 24 Hours",
                "Today",
                "Yesterday",
                "Last 7 Days",
                "Last 30 Days",
                "All Time",
                "Custom",
            ]
        )
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        filter_layout.addWidget(self.combo_preset)

        # Date Pickers
        filter_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-1))
        self.date_from.setEnabled(False)
        self.date_from.dateChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.date_from)

        filter_layout.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setEnabled(False)
        self.date_to.dateChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.date_to)

        # Provider Filter
        filter_layout.addWidget(QLabel("Provider:"))
        self.combo_provider = QComboBox()
        self.combo_provider.addItem("All Providers")
        self.combo_provider.currentIndexChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.combo_provider)

        # Connection Filter
        filter_layout.addWidget(QLabel("Connection:"))
        self.combo_conn = QComboBox()
        self.combo_conn.addItem("All Connections")
        self.combo_conn.currentIndexChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.combo_conn)

        # Apply Button
        self.btn_apply = QPushButton("Apply Filter")
        self.btn_apply.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.btn_apply.clicked.connect(self.apply_filter)
        filter_layout.addWidget(self.btn_apply)

        main_layout.addWidget(filter_frame)

        # 2. Filter Summary Banner
        self.summary_banner = QFrame()
        self.summary_banner.setStyleSheet(
            """
            QFrame {
                background-color: #1a1b21;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 8px;
            }
            QLabel {
                font-size: 11px;
                color: #f3f4f6;
            }
            """
        )
        banner_layout = QHBoxLayout(self.summary_banner)
        banner_layout.setContentsMargins(14, 8, 14, 8)

        self.lbl_sum_checks = QLabel("Checks: 0")
        self.lbl_sum_uptime = QLabel("Uptime: 0%")
        self.lbl_sum_good = QLabel("Good: 0%")
        self.lbl_sum_ping = QLabel("Median Ping: ---")
        self.lbl_sum_speed = QLabel("Avg Speed: ---")
        self.lbl_sum_outages = QLabel("Outages: 0")
        self.lbl_loading = QLabel("")
        self.lbl_loading.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")

        banner_layout.addWidget(self.lbl_sum_checks)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_sum_uptime)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_sum_good)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_sum_ping)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_sum_speed)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_sum_outages)
        banner_layout.addStretch()
        banner_layout.addWidget(self.lbl_loading)

        main_layout.addWidget(self.summary_banner)

        # 3. 4 Stacked Synced Charts
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
        charts_layout.setContentsMargins(8, 8, 8, 8)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#1e1f25")

        # Plot 1: Speed (Mbps)
        axis_date1 = pg.DateAxisItem(orientation="bottom")
        self.p_speed = self.glw.addPlot(row=0, col=0, axisItems={"bottom": axis_date1}, title="Download Speed (Mbps)")
        self.p_speed.setLabel("left", "Mbps", color="#A0A4AE")
        self.p_speed.showGrid(x=True, y=True, alpha=0.15)
        self.p_speed.setDownsampling(auto=True, mode="peak")
        self.p_speed.setClipToView(True)
        self.curve_speed = self.p_speed.plot(
            pen=pg.mkPen(color="#3b82f6", width=1.5),
            symbol="o",
            symbolSize=5,
            symbolBrush="#3b82f6",
            name="Speed",
        )

        # Plot 2: Ping (ms)
        axis_date2 = pg.DateAxisItem(orientation="bottom")
        self.p_ping = self.glw.addPlot(row=1, col=0, axisItems={"bottom": axis_date2}, title="Ping Latency (ms)")
        self.p_ping.setLabel("left", "ms", color="#A0A4AE")
        self.p_ping.showGrid(x=True, y=True, alpha=0.15)
        self.p_ping.setXLink(self.p_speed)
        self.p_ping.setDownsampling(auto=True, mode="peak")
        self.p_ping.setClipToView(True)
        guide_150 = pg.InfiniteLine(pos=150, angle=0, pen=pg.mkPen(color="#f59e0b", style=Qt.DashLine, width=1.2))
        self.p_ping.addItem(guide_150)
        self.curve_ping = self.p_ping.plot(pen=pg.mkPen(color="#22c55e", width=1.5), name="Ping")

        # Plot 3: Loss (%)
        axis_date3 = pg.DateAxisItem(orientation="bottom")
        self.p_loss = self.glw.addPlot(row=2, col=0, axisItems={"bottom": axis_date3}, title="Packet Loss (%)")
        self.p_loss.setLabel("left", "%", color="#A0A4AE")
        self.p_loss.setYRange(0, 105, padding=0.0)
        self.p_loss.showGrid(x=True, y=True, alpha=0.15)
        self.p_loss.setXLink(self.p_speed)
        self.p_loss.setDownsampling(auto=True, mode="peak")
        self.p_loss.setClipToView(True)
        self.curve_loss = self.p_loss.plot(
            pen=pg.mkPen(color="#ef4444", width=1.2),
            fillLevel=0,
            brush=pg.mkBrush(239, 68, 68, 65),
            name="Loss",
        )

        # Plot 4: PC Usage (kbps)
        axis_date4 = pg.DateAxisItem(orientation="bottom")
        self.p_pc = self.glw.addPlot(row=3, col=0, axisItems={"bottom": axis_date4}, title="PC Internet Use (kbps)")
        self.p_pc.setLabel("left", "kbps", color="#A0A4AE")
        self.p_pc.showGrid(x=True, y=True, alpha=0.15)
        self.p_pc.setXLink(self.p_speed)
        self.p_pc.setDownsampling(auto=True, mode="peak")
        self.p_pc.setClipToView(True)
        guide_busy = pg.InfiniteLine(
            pos=DEFAULT_BUSY_KBPS, angle=0, pen=pg.mkPen(color="#71717a", style=Qt.DotLine, width=1.0)
        )
        self.p_pc.addItem(guide_busy)
        self.curve_pc_down = self.p_pc.plot(pen=pg.mkPen(color="#38bdf8", width=1.2), name="PC Down")
        self.curve_pc_up = self.p_pc.plot(pen=pg.mkPen(color="#f97316", width=1.2), name="PC Up")

        charts_layout.addWidget(self.glw)
        main_layout.addWidget(charts_frame, 1)

    def populate_filter_dropdowns(self) -> None:
        """Populate provider and connection filter dropdowns from historical data."""
        seen = self.storage.get_networks_seen()
        providers = sorted({s["network"] for s in seen if s["network"] and s["network"] != "unknown"})
        conns = sorted({s["conn"] for s in seen if s["conn"] and s["conn"] != "unknown"})

        self.combo_provider.blockSignals(True)
        cur_p = self.combo_provider.currentText()
        self.combo_provider.clear()
        self.combo_provider.addItem("All Providers")
        for p in providers:
            self.combo_provider.addItem(p)
        idx_p = self.combo_provider.findText(cur_p)
        if idx_p >= 0:
            self.combo_provider.setCurrentIndex(idx_p)
        self.combo_provider.blockSignals(False)

        self.combo_conn.blockSignals(True)
        cur_c = self.combo_conn.currentText()
        self.combo_conn.clear()
        self.combo_conn.addItem("All Connections")
        for c in conns:
            self.combo_conn.addItem(c)
        idx_c = self.combo_conn.findText(cur_c)
        if idx_c >= 0:
            self.combo_conn.setCurrentIndex(idx_c)
        self.combo_conn.blockSignals(False)

    def _queue_filter_change(self) -> None:
        """Debounce rapid filter dropdown and date edits (300 ms)."""
        self._debounce_timer.stop()
        self._debounce_timer.start(300)

    def _on_preset_changed(self, index: int) -> None:
        """Update date pickers based on selected preset and queue query."""
        preset = self.combo_preset.currentText()
        is_custom = preset == "Custom"
        self.date_from.setEnabled(is_custom)
        self.date_to.setEnabled(is_custom)

        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        if preset == "Last 24 Hours":
            self.date_from.setDate(QDate.currentDate().addDays(-1))
            self.date_to.setDate(QDate.currentDate())
        elif preset == "Today":
            self.date_from.setDate(QDate.currentDate())
            self.date_to.setDate(QDate.currentDate())
        elif preset == "Yesterday":
            self.date_from.setDate(QDate.currentDate().addDays(-1))
            self.date_to.setDate(QDate.currentDate().addDays(-1))
        elif preset == "Last 7 Days":
            self.date_from.setDate(QDate.currentDate().addDays(-7))
            self.date_to.setDate(QDate.currentDate())
        elif preset == "Last 30 Days":
            self.date_from.setDate(QDate.currentDate().addDays(-30))
            self.date_to.setDate(QDate.currentDate())
        elif preset == "All Time":
            self.date_from.setDate(QDate(2020, 1, 1))
            self.date_to.setDate(QDate.currentDate())
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)

        self._queue_filter_change()

    def apply_filter(self, sync: bool = False) -> None:
        """Filter application with optional synchronous execution."""
        self._debounce_timer.stop()
        self._do_apply_filter(sync=sync)

    def _get_filter_params(self) -> Tuple[str, Optional[str], Optional[str], Optional[datetime], Optional[datetime]]:
        """Extract sanitized filter parameters."""
        preset = self.combo_preset.currentText()
        prov_text = self.combo_provider.currentText()
        conn_text = self.combo_conn.currentText()

        selected_prov = None if prov_text == "All Providers" else prov_text
        selected_conn = None if conn_text == "All Connections" else conn_text

        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None

        if preset == "Last 24 Hours":
            start_dt = datetime.now() - timedelta(hours=24)
        elif preset == "All Time":
            start_dt = None
            end_dt = None
        else:
            q_from = self.date_from.date()
            q_to = self.date_to.date()
            start_dt = datetime(q_from.year(), q_from.month(), q_from.day(), 0, 0, 0)
            end_dt = datetime(q_to.year(), q_to.month(), q_to.day(), 23, 59, 59)

        return preset, selected_prov, selected_conn, start_dt, end_dt

    def _do_apply_filter(self, sync: bool = False) -> None:
        """Check cache and launch background worker or synchronous execution."""
        preset, prov, conn, start_dt, end_dt = self._get_filter_params()
        key = (preset, prov, conn, str(start_dt), str(end_dt))

        now_time = time.time()
        if (
            self._cache_data is not None
            and self._cache_key == key
            and (now_time - self._cache_time) < 60.0
        ):
            # Instant UI restoration from cache
            self._render_history_data(self._cache_data)
            return

        self._query_id += 1
        query_id = self._query_id
        self.lbl_loading.setText("Loading…")

        def background_fetch() -> Dict[str, Any]:
            with log_timing(f"History data fetch ({preset}, {prov})"):
                net_recs = self.storage.get_net_records(
                    start_dt=start_dt, end_dt=end_dt, network=prov, conn_type=conn
                )
                spd_recs = self.storage.get_speed_records(
                    start_dt=start_dt, end_dt=end_dt, network=prov, conn_type=conn
                )
                stats = summarize(net_recs, spd_recs)
                outages = find_outages(net_recs)
                gaps = find_gaps(net_recs, gap_limit_sec=180)

                # Prepare raw time-series
                t_net: List[float] = []
                lats: List[float] = []
                losses: List[float] = []
                down_traffic: List[float] = []
                up_traffic: List[float] = []

                for r in net_recs:
                    if not r.dt:
                        continue
                    ts = r.dt.timestamp()
                    t_net.append(ts)
                    lats.append(r.latency_ms if r.latency_ms is not None else float("nan"))
                    losses.append(r.loss_pct)
                    down_traffic.append(r.pc_down_kbps if r.pc_down_kbps is not None else 0.0)
                    up_traffic.append(r.pc_up_kbps if r.pc_up_kbps is not None else 0.0)

                t_speed: List[float] = []
                speeds: List[float] = []
                for s in spd_recs:
                    if not s.dt or s.download_mbps is None:
                        continue
                    t_speed.append(s.dt.timestamp())
                    speeds.append(s.download_mbps)

                # Downsample dense time-series to <= 2000 points
                t_ping_ds, lats_ds = downsample_series(t_net, lats, max_points=2000)
                _, losses_ds = downsample_series(t_net, losses, max_points=2000)
                _, down_ds = downsample_series(t_net, down_traffic, max_points=2000)
                _, up_ds = downsample_series(t_net, up_traffic, max_points=2000)
                t_spd_ds, spd_ds = downsample_series(t_speed, speeds, max_points=1000, gap_limit_sec=3600.0)

                # Extract top 15 longest outages and gaps for shaded background highlights
                top_outages = sorted(outages, key=lambda o: -o.duration_sec)[:15]
                top_gaps = sorted(gaps, key=lambda g: -g.duration_sec)[:15]

                return {
                    "query_id": query_id,
                    "key": key,
                    "stats": stats,
                    "outages_count": len(outages),
                    "t_spd": t_spd_ds,
                    "spd": spd_ds,
                    "t_ping": t_ping_ds,
                    "lats": lats_ds,
                    "losses": losses_ds,
                    "down": down_ds,
                    "up": up_ds,
                    "top_outages": [
                        (o.start_time.timestamp(), o.end_time.timestamp()) for o in top_outages
                    ],
                    "top_gaps": [
                        (g.start_time.timestamp(), g.end_time.timestamp()) for g in top_gaps
                    ],
                    "first_t": t_net[0] if t_net else None,
                    "last_t": t_net[-1] if t_net else None,
                }

        if sync:
            res = background_fetch()
            self._on_data_ready(res)
        else:
            worker = AsyncWorker(background_fetch)
            self._worker = worker
            worker.signals.finished.connect(self._on_data_ready)
            worker.signals.error.connect(self._on_data_error)
            QThreadPool.globalInstance().start(worker)

    def _on_data_ready(self, data: Dict[str, Any]) -> None:
        """Handle worker completion on main UI thread."""
        self._worker = None
        if data.get("query_id") != self._query_id:
            return  # Discard obsolete result

        self._cache_key = data["key"]
        self._cache_time = time.time()
        self._cache_data = data
        self.lbl_loading.setText("")
        self._render_history_data(data)

    def _on_data_error(self, err: str) -> None:
        """Handle background fetch failure."""
        self._worker = None
        self.lbl_loading.setText("Error loading data")

    def _render_history_data(self, data: Dict[str, Any]) -> None:
        """Render parsed and downsampled data to UI and pyqtgraph curves."""
        with log_timing("History chart render"):
            stats = data["stats"]
            outages_count = data["outages_count"]

            self.lbl_sum_checks.setText(f"Checks: {stats.checks} ({stats.hours:.1f} hrs)")
            self.lbl_sum_uptime.setText(f"Uptime: {stats.uptime_pct:.1f}%")
            self.lbl_sum_good.setText(f"Good: {stats.good_pct:.0f}%")
            med_str = f"{stats.ping_median:.0f} ms" if stats.ping_median is not None else "---"
            self.lbl_sum_ping.setText(f"Median Ping: {med_str}")
            spd_str = f"{stats.speed_avg:.1f} Mbps" if stats.speed_avg is not None else "---"
            self.lbl_sum_speed.setText(f"Avg Speed: {spd_str}")
            self.lbl_sum_outages.setText(f"Outages: {outages_count}")

            # Update Plot Curves
            self.curve_speed.setData(data["t_spd"], data["spd"])
            self.curve_ping.setData(data["t_ping"], data["lats"])
            self.curve_loss.setData(data["t_ping"], data["losses"])
            self.curve_pc_down.setData(data["t_ping"], data["down"])
            self.curve_pc_up.setData(data["t_ping"], data["up"])

            # Highlight significant outages and gaps (bounded to avoid lagging Qt scene graph)
            self._clear_regions()
            for start_ts, end_ts in data["top_outages"]:
                self._add_shaded_region(start_ts, end_ts, color="#ef4444", alpha=50)

            for start_ts, end_ts in data["top_gaps"]:
                self._add_shaded_region(start_ts, end_ts, color="#6b7280", alpha=35)

            # Auto-range to data bounds
            first_t = data.get("first_t")
            last_t = data.get("last_t")
            if first_t and last_t and first_t < last_t:
                self.p_speed.setXRange(first_t, last_t, padding=0.02)

    def _clear_regions(self) -> None:
        """Remove previously added outage and gap region items."""
        for plot in [self.p_speed, self.p_ping, self.p_loss, self.p_pc]:
            for r in self._region_items:
                plot.removeItem(r)
        self._region_items.clear()

    def _add_shaded_region(self, start_ts: float, end_ts: float, color: str, alpha: int) -> None:
        """Add a non-movable vertical shaded region spanning the anchor plot."""
        c = pg.mkColor(color)
        c.setAlpha(alpha)
        region = pg.LinearRegionItem([start_ts, max(end_ts, start_ts + 30.0)], movable=False, brush=c, pen=pg.mkPen(None))
        self.p_ping.addItem(region)
        self._region_items.append(region)
