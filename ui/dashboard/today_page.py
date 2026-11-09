"""Today's network quality summary dashboard page with KPIs and 24-hour distribution."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.perf import log_timing
from core.stats import (
    best_and_worst_hours,
    find_outages,
    hourly_distribution,
    summarize,
)
from core.storage import Storage
from ui.async_worker import AsyncWorker
from ui.dashboard.live_page import create_stat_card


class TodayPage(QWidget):
    """Today page showing summary cards and hour-of-day latency breakdown."""

    def __init__(self, storage: Storage, parent: Optional[QWidget] = None, sync: bool = False) -> None:
        super().__init__(parent)
        self.storage = storage

        # Caching & Query Tracking
        self._cache_time: float = 0.0
        self._cache_date_str: str = ""
        self._cache_data: Optional[Dict[str, Any]] = None
        self._query_id: int = 0
        self._worker: Optional[AsyncWorker] = None

        self.bar_item: Optional[pg.BarGraphItem] = None
        self._init_ui()
        self.refresh_data(sync=sync)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 1. Header
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"Today's Overview — {datetime.now():%A, %d %B %Y}")
        self.title_label.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 700;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.lbl_loading = QLabel("")
        self.lbl_loading.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px; margin-right: 8px;")
        header_layout.addWidget(self.lbl_loading)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setStyleSheet(
            """
            QPushButton {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 5px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #323340;
            }
            """
        )
        self.btn_refresh.clicked.connect(lambda: self.refresh_data(force=True))
        header_layout.addWidget(self.btn_refresh)
        main_layout.addLayout(header_layout)

        # 2. Summary KPI Cards (2 rows x 3 columns)
        grid = QGridLayout()
        grid.setSpacing(12)

        # 1. Uptime
        self.card_uptime, _, self.val_uptime, self.sub_uptime = create_stat_card("Uptime")
        grid.addWidget(self.card_uptime, 0, 0)

        # 2. Good Quality %
        self.card_good, _, self.val_good, self.sub_good = create_stat_card("Good Quality")
        grid.addWidget(self.card_good, 0, 1)

        # 3. Median Ping
        self.card_ping, _, self.val_ping, self.sub_ping = create_stat_card("Median Latency")
        grid.addWidget(self.card_ping, 0, 2)

        # 4. Download Speed
        self.card_speed, _, self.val_speed, self.sub_speed = create_stat_card("Download Speed")
        grid.addWidget(self.card_speed, 1, 0)

        # 5. Outages & Downtime
        self.card_outages, _, self.val_outages, self.sub_outages = create_stat_card("Outages & Downtime")
        grid.addWidget(self.card_outages, 1, 1)

        # 6. Peak Hours (Best / Worst)
        self.card_peaks, _, self.val_peaks, self.sub_peaks = create_stat_card("Best & Worst Hours")
        grid.addWidget(self.card_peaks, 1, 2)

        main_layout.addLayout(grid)

        # 3. 24-Hour Latency Distribution Chart
        chart_frame = QFrame()
        chart_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1f25;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            """
        )
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(12, 10, 12, 10)
        chart_layout.setSpacing(6)

        chart_title = QLabel("24-Hour Latency Distribution (Hour-of-Day)")
        chart_title.setStyleSheet("color: #f3f4f6; font-size: 13px; font-weight: 700;")
        chart_layout.addWidget(chart_title)

        chart_desc = QLabel("Average ping for each hour. Bars colored by quality: Green < 100 ms, Amber 100–300 ms, Red > 300 ms. Shading highlights evening peak (18:00–22:00).")
        chart_desc.setStyleSheet("color: #A0A4AE; font-size: 11px;")
        chart_layout.addWidget(chart_desc)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#1e1f25")

        self.plot_hourly = self.glw.addPlot()
        self.plot_hourly.showGrid(x=False, y=True, alpha=0.15)
        self.plot_hourly.setLabel("left", "Avg Ping (ms)", color="#A0A4AE")
        self.plot_hourly.setLabel("bottom", "Hour of Day (00:00 – 23:00)", color="#A0A4AE")
        self.plot_hourly.setXRange(-0.8, 23.8, padding=0.02)
        self.plot_hourly.setDownsampling(auto=True)
        self.plot_hourly.setClipToView(True)

        # Shaded Evening Window (18:00 – 22:00)
        self.evening_region = pg.LinearRegionItem(
            [17.5, 21.5],
            movable=False,
            brush=pg.mkBrush(245, 158, 11, 20),
            pen=pg.mkPen(color=pg.mkColor(245, 158, 11, 70), width=1, style=Qt.DashLine),
        )
        self.plot_hourly.addItem(self.evening_region)

        # 150 ms guide line
        guide_150 = pg.InfiniteLine(pos=150, angle=0, pen=pg.mkPen(color="#f59e0b", style=Qt.DashLine, width=1.2))
        self.plot_hourly.addItem(guide_150)

        chart_layout.addWidget(self.glw)
        main_layout.addWidget(chart_frame, 1)

    def refresh_data(self, force: bool = False, sync: bool = False) -> None:
        """Fetch today's records asynchronously with 60-second caching."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        now_time = time.time()

        if (
            not force
            and self._cache_data is not None
            and self._cache_date_str == today_str
            and (now_time - self._cache_time) < 60.0
        ):
            # Already up-to-date within 60s
            self._render_today_data(self._cache_data)
            return

        self._query_id += 1
        query_id = self._query_id
        self.title_label.setText(f"Today's Overview — {datetime.now():%A, %d %B %Y}")
        self.lbl_loading.setText("Loading…")

        def background_fetch() -> Dict[str, Any]:
            with log_timing("Today stats computation"):
                net_recs = self.storage.get_net_records(date_str=today_str)
                spd_recs = self.storage.get_speed_records(date_str=today_str)

                if not net_recs:
                    return {"query_id": query_id, "empty": True, "date_str": today_str}

                stats = summarize(net_recs, spd_recs)
                outages = find_outages(net_recs)
                best, worst = best_and_worst_hours(net_recs, key="latency_ms")
                dist = hourly_distribution(net_recs, key="latency_ms")

                return {
                    "query_id": query_id,
                    "empty": False,
                    "date_str": today_str,
                    "stats": stats,
                    "outages": outages,
                    "best": best,
                    "worst": worst,
                    "dist": dist,
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
        """Handle completion of background calculation."""
        self._worker = None
        if data.get("query_id") != self._query_id:
            return  # Obsolete result

        self._cache_time = time.time()
        self._cache_date_str = data["date_str"]
        self._cache_data = data
        self.lbl_loading.setText("")
        self._render_today_data(data)

    def _on_data_error(self, err: str) -> None:
        """Handle calculation error."""
        self._worker = None
        self.lbl_loading.setText("Error loading data")

    def _render_today_data(self, data: Dict[str, Any]) -> None:
        """Render data to KPI cards and hourly chart."""
        if data.get("empty"):
            self.val_uptime.setText("No data")
            self.val_good.setText("No data")
            self.val_ping.setText("---")
            self.val_speed.setText("---")
            self.val_outages.setText("0")
            self.val_peaks.setText("---")
            return

        with log_timing("Today UI render"):
            stats = data["stats"]
            outages = data["outages"]
            best = data["best"]
            worst = data["worst"]
            dist = data["dist"]

            # Uptime
            uptime_color = "#22c55e" if stats.uptime_pct >= 99.0 else ("#f59e0b" if stats.uptime_pct >= 95.0 else "#ef4444")
            self.val_uptime.setText(f"{stats.uptime_pct:.1f}%")
            self.val_uptime.setStyleSheet(f"color: {uptime_color}; font-size: 24px; font-weight: 700;")
            self.sub_uptime.setText(f"{stats.checks - stats.down_count} of {stats.checks} checks connected ({stats.hours:.1f} hrs)")

            # Good %
            good_color = "#22c55e" if stats.good_pct >= 90.0 else ("#f59e0b" if stats.good_pct >= 75.0 else "#ef4444")
            self.val_good.setText(f"{stats.good_pct:.0f}%")
            self.val_good.setStyleSheet(f"color: {good_color}; font-size: 24px; font-weight: 700;")
            self.sub_good.setText("ping < 300 ms & loss < 25%")

            # Median Ping
            if stats.ping_median is not None:
                self.val_ping.setText(f"{stats.ping_median:.0f} ms")
                self.sub_ping.setText(f"avg {stats.ping_avg:.0f} ms · loss {stats.loss_avg:.1f}%")
            else:
                self.val_ping.setText("---")
                self.sub_ping.setText("No valid samples")

            # Download Speed
            if stats.speed_avg is not None:
                self.val_speed.setText(f"{stats.speed_avg:.1f} Mbps")
                self.sub_speed.setText(f"best {stats.speed_max:.1f} · worst {stats.speed_min:.1f} ({stats.speed_count} tests)")
            else:
                self.val_speed.setText("---")
                self.sub_speed.setText("No speed tests today")

            # Outages
            total_downtime_sec = sum(o.duration_sec for o in outages)
            down_mins = round(total_downtime_sec / 60.0, 1)
            self.val_outages.setText(f"{len(outages)}")
            self.val_outages.setStyleSheet("color: #ef4444;" if outages else "color: #22c55e;")
            self.sub_outages.setText(f"{down_mins:.1f} min total downtime" if outages else "Zero downtime today")

            # Best / Worst Hours
            if best and worst and best[0] != worst[0]:
                self.val_peaks.setText(f"Best: {best[0]:02d}:00")
                self.sub_peaks.setText(f"Worst: {worst[0]:02d}:00 ({worst[1]:.0f} ms)")
            elif best:
                self.val_peaks.setText(f"{best[0]:02d}:00")
                self.sub_peaks.setText(f"avg {best[1]:.0f} ms")
            else:
                self.val_peaks.setText("---")
                self.sub_peaks.setText("Insufficient data")

            # Hourly Bar Chart
            x_vals: List[float] = []
            y_vals: List[float] = []
            brushes = []

            for h in range(24):
                avg_val = dist[h]["avg"]
                x_vals.append(h)
                if avg_val is not None:
                    y_vals.append(avg_val)
                    if avg_val < 100.0:
                        brushes.append(pg.mkBrush("#22c55e"))  # Green < 100 ms
                    elif avg_val <= 300.0:
                        brushes.append(pg.mkBrush("#f59e0b"))  # Amber 100-300 ms
                    else:
                        brushes.append(pg.mkBrush("#ef4444"))  # Red > 300 ms
                else:
                    y_vals.append(0.0)
                    brushes.append(pg.mkBrush("#374151"))

            if self.bar_item:
                self.plot_hourly.removeItem(self.bar_item)

            self.bar_item = pg.BarGraphItem(x=x_vals, height=y_vals, width=0.68, brushes=brushes)
            self.plot_hourly.addItem(self.bar_item)

            max_y = max(y_vals) if y_vals else 100.0
            self.plot_hourly.setYRange(0, max(180.0, max_y * 1.15), padding=0.05)
