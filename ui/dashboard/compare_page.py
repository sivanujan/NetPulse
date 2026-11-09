"""Network comparison dashboard page with provider rankings and 24-hour comparative charts."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.perf import log_timing
from core.stats import compare_networks, hourly_distribution
from core.storage import Storage
from ui.async_worker import AsyncWorker
from ui.dashboard.live_page import create_stat_card


class CompareNetworksPage(QWidget):
    """Compare networks page analyzing Dialog, Mobitel, SLT, and others."""

    def __init__(self, storage: Storage, parent: Optional[QWidget] = None, sync: bool = False) -> None:
        super().__init__(parent)
        self.storage = storage

        # Caching & Query Tracking
        self._cache_time: float = 0.0
        self._cache_data: Optional[Dict[str, Any]] = None
        self._query_id: int = 0
        self._worker: Optional[AsyncWorker] = None

        self.plot_curves: List[Any] = []
        self._init_ui()
        self.refresh_data(sync=sync)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Compare Networks & ISPs")
        title_label.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 700;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.lbl_loading = QLabel("")
        self.lbl_loading.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px; margin-right: 8px;")
        header_layout.addWidget(self.lbl_loading)

        self.btn_refresh = QPushButton("Refresh Comparison")
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

        # 2. Winner Insight KPI Cards
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # Best Overall
        self.card_overall, _, self.val_overall, self.sub_overall = create_stat_card("Best Provider Overall")
        top_row.addWidget(self.card_overall, 1)

        # Best Evening
        self.card_evening, _, self.val_evening, self.sub_evening = create_stat_card("Best in Evening (18–22h)")
        top_row.addWidget(self.card_evening, 1)

        main_layout.addLayout(top_row)

        # Fairness Alert Banner (hidden by default)
        self.warning_card = QFrame()
        self.warning_card.setStyleSheet(
            """
            QFrame {
                background-color: rgba(245, 158, 11, 0.12);
                border: 1px solid rgba(245, 158, 11, 0.4);
                border-radius: 8px;
            }
            """
        )
        warning_layout = QHBoxLayout(self.warning_card)
        warning_layout.setContentsMargins(14, 8, 14, 8)
        self.lbl_warning = QLabel("")
        self.lbl_warning.setStyleSheet("color: #fbbf24; font-size: 11px; font-weight: 600;")
        warning_layout.addWidget(self.lbl_warning)
        self.warning_card.setVisible(False)
        main_layout.addWidget(self.warning_card)

        # 3. Provider Comparison Table
        table_frame = QFrame()
        table_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1f25;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            """
        )
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(12, 10, 12, 10)
        table_layout.setSpacing(6)

        table_header = QLabel("Performance Summary by Provider")
        table_header.setStyleSheet("color: #f3f4f6; font-size: 13px; font-weight: 700;")
        table_layout.addWidget(table_header)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Total Hours",
                "Checks",
                "Uptime %",
                "Good Quality %",
                "Median Ping",
                "Avg Speed",
                "Evening Ping (18–22h)",
                "Evening Good %",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background-color: transparent;
                gridline-color: rgba(255, 255, 255, 0.06);
                border: none;
                color: #f3f4f6;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #272832;
                color: #A0A4AE;
                font-size: 11px;
                font-weight: 700;
                padding: 6px;
                border: none;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            QTableWidget::item {
                padding: 6px;
            }
            """
        )
        self.table.setMaximumHeight(140)
        table_layout.addWidget(self.table)
        main_layout.addWidget(table_frame)

        # 4. Comparative 24-Hour Latency Chart
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

        chart_title = QLabel("24-Hour Comparative Latency by Provider")
        chart_title.setStyleSheet("color: #f3f4f6; font-size: 13px; font-weight: 700;")
        chart_layout.addWidget(chart_title)

        chart_desc = QLabel("Average ping for each hour. Shaded region indicates the 18:00 – 22:00 evening window.")
        chart_desc.setStyleSheet("color: #A0A4AE; font-size: 11px;")
        chart_layout.addWidget(chart_desc)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("#1e1f25")

        self.plot_cmp = self.glw.addPlot()
        self.plot_cmp.showGrid(x=False, y=True, alpha=0.15)
        self.plot_cmp.setLabel("left", "Avg Ping (ms)", color="#A0A4AE")
        self.plot_cmp.setLabel("bottom", "Hour of Day", color="#A0A4AE")
        self.plot_cmp.setXRange(-0.8, 23.8, padding=0.02)
        self.plot_cmp.setDownsampling(auto=True)
        self.plot_cmp.setClipToView(True)

        # Shaded Evening Window
        evening_region = pg.LinearRegionItem(
            [17.5, 21.5],
            movable=False,
            brush=pg.mkBrush(245, 158, 11, 25),
            pen=pg.mkPen(color=pg.mkColor(245, 158, 11, 60), width=1, style=Qt.DashLine),
        )
        self.plot_cmp.addItem(evening_region)

        # 150 ms guide line
        guide_150 = pg.InfiniteLine(pos=150, angle=0, pen=pg.mkPen(color="#f59e0b", style=Qt.DashLine, width=1.2))
        self.plot_cmp.addItem(guide_150)

        chart_layout.addWidget(self.glw)
        main_layout.addWidget(chart_frame, 1)

    def refresh_data(self, force: bool = False, sync: bool = False) -> None:
        """Query storage asynchronously with 60-second caching."""
        now_time = time.time()
        if not force and self._cache_data is not None and (now_time - self._cache_time) < 60.0:
            self._render_compare_data(self._cache_data)
            return

        self._query_id += 1
        query_id = self._query_id
        self.lbl_loading.setText("Comparing…")

        def background_fetch() -> Dict[str, Any]:
            with log_timing("Compare networks computation"):
                net_records = self.storage.get_net_records()
                speed_records = self.storage.get_speed_records()

                if not net_records:
                    return {"query_id": query_id, "empty": True}

                res = compare_networks(net_records, speed_records)
                providers_data = res.get("providers", {})
                best_overall = res.get("best_overall")
                best_evening = res.get("best_evening")
                warning = res.get("warning")

                # Compute hourly distribution per provider for comparative chart
                hourly_by_prov: Dict[str, List[float]] = {}
                for prov in providers_data.keys():
                    sub = [r for r in net_records if r.network == prov]
                    h_dist = hourly_distribution(sub, key="latency_ms")
                    hourly_by_prov[prov] = [h_dist[h]["avg"] if h_dist[h]["avg"] is not None else float("nan") for h in range(24)]

                return {
                    "query_id": query_id,
                    "empty": False,
                    "providers_data": providers_data,
                    "best_overall": best_overall,
                    "best_evening": best_evening,
                    "warning": warning,
                    "hourly_by_prov": hourly_by_prov,
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
        """Handle worker completion on main thread."""
        self._worker = None
        if data.get("query_id") != self._query_id:
            return

        self._cache_time = time.time()
        self._cache_data = data
        self.lbl_loading.setText("")
        self._render_compare_data(data)

    def _on_data_error(self, err: str) -> None:
        """Handle background fetch error."""
        self._worker = None
        self.lbl_loading.setText("Error loading comparison")

    def _render_compare_data(self, data: Dict[str, Any]) -> None:
        """Render results to UI widgets."""
        if data.get("empty"):
            self.val_overall.setText("No data")
            self.val_evening.setText("No data")
            self.warning_card.setVisible(False)
            self.table.setRowCount(0)
            return

        with log_timing("Compare UI render"):
            providers_data = data["providers_data"]
            best_overall = data["best_overall"]
            best_evening = data["best_evening"]
            warning = data["warning"]
            hourly_by_prov = data["hourly_by_prov"]

            # 1. Update Best Overall & Best Evening
            if best_overall and best_overall in providers_data:
                s_ov = providers_data[best_overall]["overall"]
                med_str = f"{s_ov.ping_median:.0f} ms" if s_ov.ping_median is not None else "---"
                self.val_overall.setText(best_overall)
                self.val_overall.setStyleSheet("color: #22c55e; font-size: 24px; font-weight: 700;")
                self.sub_overall.setText(f"{s_ov.good_pct:.0f}% good quality · {med_str} median ping")
            else:
                self.val_overall.setText("---")
                self.sub_overall.setText("Insufficient comparison data")

            if best_evening and best_evening in providers_data:
                s_ev = providers_data[best_evening]["evening"]
                med_str = f"{s_ev.ping_median:.0f} ms" if s_ev.ping_median is not None else "---"
                self.val_evening.setText(best_evening)
                self.val_evening.setStyleSheet("color: #38bdf8; font-size: 24px; font-weight: 700;")
                self.sub_evening.setText(f"{s_ev.good_pct:.0f}% good in evening · {med_str} median ping")
            else:
                self.val_evening.setText("---")
                self.sub_evening.setText("No evening data recorded yet")

            # 2. Show / Hide Fairness Warning
            if warning:
                self.lbl_warning.setText(f"⚠ {warning}")
                self.warning_card.setVisible(True)
            else:
                self.warning_card.setVisible(False)

            # 3. Populate Comparison Table (fast batch update)
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(providers_data))
            for row_idx, (prov, pdata) in enumerate(sorted(providers_data.items(), key=lambda x: -x[1]["overall"].hours)):
                ov = pdata["overall"]
                ev = pdata["evening"]

                med_ping = f"{ov.ping_median:.0f} ms" if ov.ping_median is not None else "---"
                spd_avg = f"{ov.speed_avg:.1f} Mbps" if ov.speed_avg is not None else "---"
                ev_ping = f"{ev.ping_median:.0f} ms" if ev.ping_median is not None else "---"

                items = [
                    (prov, "#f3f4f6", True),
                    (f"{ov.hours:.1f} hrs", "#A0A4AE", False),
                    (str(ov.checks), "#A0A4AE", False),
                    (f"{ov.uptime_pct:.1f}%", "#22c55e" if ov.uptime_pct >= 95 else "#ef4444", True),
                    (f"{ov.good_pct:.0f}%", "#22c55e" if ov.good_pct >= 85 else "#f59e0b", True),
                    (med_ping, "#f3f4f6", False),
                    (spd_avg, "#38bdf8", False),
                    (ev_ping, "#fbbf24" if (ev.ping_median or 0) > 200 else "#f3f4f6", False),
                    (f"{ev.good_pct:.0f}%", "#22c55e" if ev.good_pct >= 80 else "#ef4444", False),
                ]

                for col_idx, (text, color, bold) in enumerate(items):
                    item = QTableWidgetItem(text)
                    item.setForeground(QColor(color))
                    item.setTextAlignment(Qt.AlignCenter if col_idx > 0 else Qt.AlignLeft | Qt.AlignVCenter)
                    if bold:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    self.table.setItem(row_idx, col_idx, item)
            self.table.setUpdatesEnabled(True)

            # 4. Update Comparative 24-Hour Latency Lines
            for c in self.plot_curves:
                self.plot_cmp.removeItem(c)
            self.plot_curves.clear()

            palette = ["#38bdf8", "#22c55e", "#f59e0b", "#ec4899", "#a855f7"]
            hours_x = list(range(24))

            for idx, (prov, y_vals) in enumerate(hourly_by_prov.items()):
                color = palette[idx % len(palette)]
                curve = self.plot_cmp.plot(
                    hours_x,
                    y_vals,
                    pen=pg.mkPen(color=color, width=2.0),
                    symbol="o",
                    symbolSize=6,
                    symbolBrush=color,
                    name=prov,
                )
                self.plot_curves.append(curve)
