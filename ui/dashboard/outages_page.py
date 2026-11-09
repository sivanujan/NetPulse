"""Outages and degraded performance log page with duration tracking and filtering."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
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
from core.stats import OutageEvent, find_outages
from core.storage import Storage
from ui.async_worker import AsyncWorker
from ui.dashboard.live_page import create_stat_card


def format_duration(seconds: float) -> str:
    """Format duration in seconds into human-readable string."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins >= 60:
        hrs = int(mins // 60)
        rem_m = int(mins % 60)
        return f"{hrs}h {rem_m}m"
    if mins > 0:
        return f"{mins}m {secs:02d}s"
    return f"{secs}s"


class OutagesPage(QWidget):
    """Incident log page for complete downtime and sustained degraded quality."""

    def __init__(self, storage: Storage, parent: Optional[QWidget] = None, sync: bool = False) -> None:
        super().__init__(parent)
        self.storage = storage

        # Caching & Query Tracking
        self._cache_key: Optional[Tuple[str, str, str]] = None
        self._cache_time: float = 0.0
        self._cache_data: Optional[Dict[str, Any]] = None
        self._query_id: int = 0
        self._worker: Optional[AsyncWorker] = None

        # Debounce timer (300 ms)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._do_refresh_data)

        self._init_ui()
        self.populate_providers()
        self.refresh_data(sync=sync)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Incident & Outages Log")
        title_label.setStyleSheet("color: #f3f4f6; font-size: 20px; font-weight: 700;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.lbl_loading = QLabel("")
        self.lbl_loading.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px; margin-right: 8px;")
        header_layout.addWidget(self.lbl_loading)

        self.btn_refresh = QPushButton("Refresh Log")
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

        # 2. Top Summary KPI Cards (4 cards)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.card_outages, _, self.val_outages, self.sub_outages = create_stat_card("Total Outages (DOWN)")
        cards_layout.addWidget(self.card_outages, 1)

        self.card_downtime, _, self.val_downtime, self.sub_downtime = create_stat_card("Total Downtime")
        cards_layout.addWidget(self.card_downtime, 1)

        self.card_longest, _, self.val_longest, self.sub_longest = create_stat_card("Longest Outage")
        cards_layout.addWidget(self.card_longest, 1)

        self.card_bad, _, self.val_bad, self.sub_bad = create_stat_card("Degraded Periods (> 5m)")
        cards_layout.addWidget(self.card_bad, 1)

        main_layout.addLayout(cards_layout)

        # 3. Filter Controls Toolbar
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
            QComboBox {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }
            """
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(12)

        filter_layout.addWidget(QLabel("Time Range:"))
        self.combo_range = QComboBox()
        self.combo_range.addItems(["All Time", "Today", "Last 24 Hours", "Last 7 Days", "Last 30 Days"])
        self.combo_range.currentIndexChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.combo_range)

        filter_layout.addWidget(QLabel("Severity:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["All Incidents", "Outages Only (DOWN)", "Degraded Only (BAD > 5 min)"])
        self.combo_type.currentIndexChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.combo_type)

        filter_layout.addWidget(QLabel("Provider:"))
        self.combo_prov = QComboBox()
        self.combo_prov.addItem("All Providers")
        self.combo_prov.currentIndexChanged.connect(self._queue_filter_change)
        filter_layout.addWidget(self.combo_prov)

        filter_layout.addStretch()
        main_layout.addWidget(filter_frame)

        # 4. Outage Incidents Table
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
        table_layout.setContentsMargins(12, 12, 12, 12)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                "Incident Type",
                "Start Time",
                "End Time",
                "Duration",
                "Network Provider",
                "Connection",
                "Checks Logged",
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
        table_layout.addWidget(self.table)
        main_layout.addWidget(table_frame, 1)

    def populate_providers(self) -> None:
        """Populate provider filter combo box with observed providers."""
        seen = self.storage.get_networks_seen()
        providers = sorted({s["network"] for s in seen if s["network"] and s["network"] != "unknown"})
        self.combo_prov.blockSignals(True)
        cur = self.combo_prov.currentText()
        self.combo_prov.clear()
        self.combo_prov.addItem("All Providers")
        for p in providers:
            self.combo_prov.addItem(p)
        idx = self.combo_prov.findText(cur)
        if idx >= 0:
            self.combo_prov.setCurrentIndex(idx)
        self.combo_prov.blockSignals(False)

    def _queue_filter_change(self) -> None:
        """Debounce filter changes by 300 ms."""
        self._debounce_timer.stop()
        self._debounce_timer.start(300)

    def refresh_data(self, force: bool = False, sync: bool = False) -> None:
        """Immediate refresh or cache check."""
        self._debounce_timer.stop()
        self._do_refresh_data(force=force, sync=sync)

    def _do_refresh_data(self, force: bool = False, sync: bool = False) -> None:
        """Execute async query or restore from cache."""
        range_text = self.combo_range.currentText()
        type_text = self.combo_type.currentText()
        prov_text = self.combo_prov.currentText()
        key = (range_text, type_text, prov_text)

        now_time = time.time()
        if not force and self._cache_data is not None and self._cache_key == key and (now_time - self._cache_time) < 60.0:
            self._render_outages_data(self._cache_data)
            return

        self._query_id += 1
        query_id = self._query_id
        self.lbl_loading.setText("Loading…")

        def background_fetch() -> Dict[str, Any]:
            with log_timing(f"Outages computation ({range_text}, {prov_text})"):
                start_dt: Optional[datetime] = None
                now = datetime.now()
                if range_text == "Today":
                    start_dt = datetime(now.year, now.month, now.day, 0, 0, 0)
                elif range_text == "Last 24 Hours":
                    start_dt = now - timedelta(hours=24)
                elif range_text == "Last 7 Days":
                    start_dt = now - timedelta(days=7)
                elif range_text == "Last 30 Days":
                    start_dt = now - timedelta(days=30)

                prov_filter = None if prov_text == "All Providers" else prov_text
                net_records = self.storage.get_net_records(start_dt=start_dt, network=prov_filter)

                include_bad = "Degraded" in type_text or "All" in type_text
                events = find_outages(
                    net_records,
                    gap_limit_sec=180,
                    check_interval_sec=30,
                    include_bad=include_bad,
                    min_bad_duration_sec=300,
                )

                if type_text == "Outages Only (DOWN)":
                    events = [e for e in events if e.status == "DOWN"]
                elif type_text == "Degraded Only (BAD > 5 min)":
                    events = [e for e in events if e.status == "BAD"]

                events.sort(key=lambda e: e.start_time, reverse=True)

                down_events = [e for e in events if e.status == "DOWN"]
                bad_events = [e for e in events if e.status == "BAD"]
                total_downtime = sum(e.duration_sec for e in down_events)
                longest = max(down_events, key=lambda e: e.duration_sec) if down_events else None

                # Pre-format table items in background thread
                rows_data = []
                for ev in events:
                    is_down = ev.status == "DOWN"
                    status_text = "● OUTAGE (DOWN)" if is_down else "● DEGRADED (BAD)"
                    status_color = "#ef4444" if is_down else "#f59e0b"
                    start_str = ev.start_time.strftime("%Y-%m-%d %H:%M")
                    end_str = ev.end_time.strftime("%H:%M:%S")
                    dur_str = format_duration(ev.duration_sec)
                    rows_data.append(
                        [
                            (status_text, status_color, True),
                            (start_str, "#f3f4f6", False),
                            (end_str, "#f3f4f6", False),
                            (dur_str, status_color, True),
                            (ev.network, "#f3f4f6", False),
                            (ev.conn, "#A0A4AE", False),
                            (f"{ev.checks_count} checks", "#A0A4AE", False),
                        ]
                    )

                return {
                    "query_id": query_id,
                    "key": key,
                    "down_count": len(down_events),
                    "bad_count": len(bad_events),
                    "total_downtime": total_downtime,
                    "longest": longest,
                    "rows_data": rows_data,
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

        self._cache_key = data["key"]
        self._cache_time = time.time()
        self._cache_data = data
        self.lbl_loading.setText("")
        self._render_outages_data(data)

    def _on_data_error(self, err: str) -> None:
        """Handle background fetch error."""
        self._worker = None
        self.lbl_loading.setText("Error loading outages")

    def _render_outages_data(self, data: Dict[str, Any]) -> None:
        """Render parsed outages to UI and incident table."""
        with log_timing("Outages UI render"):
            down_count = data["down_count"]
            bad_count = data["bad_count"]
            total_downtime = data["total_downtime"]
            longest = data["longest"]
            rows_data = data["rows_data"]

            self.val_outages.setText(str(down_count))
            self.val_outages.setStyleSheet("color: #ef4444;" if down_count else "color: #22c55e;")
            self.sub_outages.setText("Complete internet drops")

            self.val_downtime.setText(format_duration(total_downtime))
            self.sub_downtime.setText(f"Across {down_count} incidents" if down_count else "Zero downtime")

            if longest:
                self.val_longest.setText(format_duration(longest.duration_sec))
                self.sub_longest.setText(f"{longest.start_time:%d %b %H:%M} ({longest.network})")
            else:
                self.val_longest.setText("---")
                self.sub_longest.setText("No outages logged")

            self.val_bad.setText(str(bad_count))
            self.val_bad.setStyleSheet("color: #f59e0b;" if bad_count else "color: #A0A4AE;")
            self.sub_bad.setText("Sustained latency > 300ms / loss ≥ 25%")

            # Batch table population
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(rows_data))
            for row_idx, items in enumerate(rows_data):
                for col_idx, (text, color, bold) in enumerate(items):
                    item = QTableWidgetItem(text)
                    item.setForeground(QColor(color))
                    item.setTextAlignment(Qt.AlignCenter if col_idx in (0, 1, 2, 3, 6) else Qt.AlignLeft | Qt.AlignVCenter)
                    if bold:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    self.table.setItem(row_idx, col_idx, item)
            self.table.setUpdatesEnabled(True)
