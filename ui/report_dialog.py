"""Interactive dialog for generating TRCSL/ISP complaint reports and CSV exports."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QDate, QThreadPool, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import Config
from core.report_gen import export_filtered_csv, generate_complaint_report
from core.storage import Storage
from ui.async_worker import AsyncWorker


class ReportDialog(QDialog):
    """Dialog allowing user to choose date range and provider to export complaint PDF, PNG, and CSV."""

    def __init__(
        self,
        storage: Storage,
        config: Config,
        base_dir: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.config = config
        self.base_dir = base_dir

        self.reports_dir = os.path.join(self.base_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self._worker: Optional[AsyncWorker] = None

        self._init_ui()
        self._populate_providers()

    def _init_ui(self) -> None:
        self.setWindowTitle("NetPulse — Create Complaint & Diagnostic Report")
        self.resize(520, 360)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #16171b;
                color: #f3f4f6;
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
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
                padding: 6px 10px;
                font-size: 11px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Title
        title = QLabel("Generate Evidence / Complaint Pack")
        title.setStyleSheet("color: #f3f4f6; font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        desc = QLabel(
            "Exports a complete diagnostic pack (PDF, PNG, CSV) with outage lists, latency graphs, "
            "and speed history ready to submit to your ISP or TRCSL."
        )
        desc.setStyleSheet("color: #9ca3af; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Form Frame
        form_frame = QFrame()
        form_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1f25;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            """
        )
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        # Date Preset
        row_preset = QHBoxLayout()
        row_preset.addWidget(QLabel("Date Range:"))
        self.combo_range = QComboBox()
        self.combo_range.addItems(
            ["Last 24 Hours", "Today", "Yesterday", "Last 7 Days", "Last 30 Days", "All Time", "Custom"]
        )
        self.combo_range.currentIndexChanged.connect(self._on_preset_changed)
        row_preset.addWidget(self.combo_range, 1)
        form_layout.addLayout(row_preset)

        # Custom Date Pickers
        self.row_custom = QHBoxLayout()
        self.row_custom.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.setEnabled(False)
        self.row_custom.addWidget(self.date_from, 1)

        self.row_custom.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setEnabled(False)
        self.row_custom.addWidget(self.date_to, 1)
        form_layout.addLayout(self.row_custom)

        # Provider Selector
        row_prov = QHBoxLayout()
        row_prov.addWidget(QLabel("Filter Network:"))
        self.combo_prov = QComboBox()
        self.combo_prov.addItem("All Detected Networks")
        row_prov.addWidget(self.combo_prov, 1)
        form_layout.addLayout(row_prov)

        layout.addWidget(form_frame)

        # Status Label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.lbl_status)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_csv = QPushButton("Export CSV Only")
        self.btn_csv.setStyleSheet(
            """
            QPushButton {
                background-color: #272832;
                color: #f3f4f6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #323340;
            }
            """
        )
        self.btn_csv.clicked.connect(self._export_csv)
        btn_layout.addWidget(self.btn_csv)

        btn_layout.addStretch()

        self.btn_generate = QPushButton("Create PDF && PNG Report")
        self.btn_generate.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: 700;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.btn_generate.clicked.connect(self._generate_report)
        btn_layout.addWidget(self.btn_generate)

        layout.addLayout(btn_layout)

    def _populate_providers(self) -> None:
        """Populate provider dropdown with detected networks."""
        seen = self.storage.get_networks_seen()
        providers = sorted({s["network"] for s in seen if s["network"] and s["network"] != "unknown"})
        for p in providers:
            self.combo_prov.addItem(p)

    def _on_preset_changed(self, idx: int) -> None:
        """Enable custom date pickers when 'Custom' is selected."""
        is_custom = self.combo_range.currentText() == "Custom"
        self.date_from.setEnabled(is_custom)
        self.date_to.setEnabled(is_custom)

    def _get_filter_bounds(self) -> tuple[Optional[datetime], Optional[datetime], Optional[str], str]:
        """Extract start and end datetimes from chosen filter."""
        preset = self.combo_range.currentText()
        now = datetime.now()
        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None

        if preset == "Last 24 Hours":
            start_dt = now - timedelta(hours=24)
        elif preset == "Today":
            start_dt = datetime(now.year, now.month, now.day, 0, 0, 0)
        elif preset == "Yesterday":
            y = now - timedelta(days=1)
            start_dt = datetime(y.year, y.month, y.day, 0, 0, 0)
            end_dt = datetime(y.year, y.month, y.day, 23, 59, 59)
        elif preset == "Last 7 Days":
            start_dt = now - timedelta(days=7)
        elif preset == "Last 30 Days":
            start_dt = now - timedelta(days=30)
        elif preset == "All Time":
            start_dt = None
            end_dt = None
        elif preset == "Custom":
            q_from = self.date_from.date()
            q_to = self.date_to.date()
            start_dt = datetime(q_from.year(), q_from.month(), q_from.day(), 0, 0, 0)
            end_dt = datetime(q_to.year(), q_to.month(), q_to.day(), 23, 59, 59)

        prov = self.combo_prov.currentText()
        prov_filter = None if prov == "All Detected Networks" else prov
        return start_dt, end_dt, prov_filter, preset

    def _export_csv(self) -> None:
        """Export CSV of filtered slice."""
        start_dt, end_dt, prov_filter, preset = self._get_filter_bounds()
        records = self.storage.get_net_records(start_dt=start_dt, end_dt=end_dt, network=prov_filter)
        if not records:
            QMessageBox.warning(self, "No Data", "No network records match the selected filter.")
            return

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"netpulse_export_{ts_str}.csv"
        out_path = os.path.join(self.reports_dir, filename)

        try:
            export_filtered_csv(records, out_path)
            self.lbl_status.setText(f"✓ Exported {len(records):,} records to {filename}")
            self._prompt_open_file(out_path, is_dir=True)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV: {exc}")

    def _generate_report(self) -> None:
        """Run report generation in background thread."""
        start_dt, end_dt, prov_filter, preset = self._get_filter_bounds()
        net_recs = self.storage.get_net_records(start_dt=start_dt, end_dt=end_dt, network=prov_filter)
        spd_recs = self.storage.get_speed_records(start_dt=start_dt, end_dt=end_dt, network=prov_filter)

        if not net_recs:
            QMessageBox.warning(self, "No Data", "No network records match the selected filter.")
            return

        self.btn_generate.setEnabled(False)
        self.btn_csv.setEnabled(False)
        self.lbl_status.setText("Rendering high-res PDF and PNG charts…")

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = os.path.join(self.reports_dir, f"NetPulse_Report_{ts_str}.pdf")
        png_path = os.path.join(self.reports_dir, f"NetPulse_Report_{ts_str}.png")

        def task() -> tuple[str, str]:
            return generate_complaint_report(
                net_records=net_recs,
                speed_records=spd_recs,
                config=self.config,
                out_pdf_path=pdf_path,
                out_png_path=png_path,
                date_label=preset,
                provider_filter=prov_filter,
            )

        def on_done(paths: tuple[str, str]) -> None:
            self._worker = None
            self.btn_generate.setEnabled(True)
            self.btn_csv.setEnabled(True)
            self.lbl_status.setText(f"✓ Created: {os.path.basename(paths[0])}")
            self._prompt_open_file(paths[0])

        def on_error(err: str) -> None:
            self._worker = None
            self.btn_generate.setEnabled(True)
            self.btn_csv.setEnabled(True)
            self.lbl_status.setText("Report generation failed")
            QMessageBox.critical(self, "Generation Error", f"Could not create report:\n{err}")

        worker = AsyncWorker(task)
        self._worker = worker
        worker.signals.finished.connect(on_done)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)

    def _prompt_open_file(self, target_path: str, is_dir: bool = False) -> None:
        """Offer to open the exported file or folder."""
        box = QMessageBox(self)
        box.setWindowTitle("Report Generated Successfully")
        box.setText(f"Evidence report saved to:\n{target_path}")
        btn_open = box.addButton("Open Report" if not is_dir else "Open Folder", QMessageBox.AcceptRole)
        btn_folder = box.addButton("Open Folder", QMessageBox.ActionRole) if not is_dir else None
        btn_close = box.addButton("Close", QMessageBox.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        try:
            if clicked == btn_open and not is_dir:
                if sys.platform.startswith("win"):
                    try:
                        os.startfile(target_path)
                    except Exception:
                        self._open_explorer(self.reports_dir)
                else:
                    subprocess.run(["xdg-open", target_path])
            elif clicked == btn_open and is_dir:
                self._open_explorer(target_path)
            elif btn_folder and clicked == btn_folder:
                self._open_explorer(self.reports_dir)
        except Exception:
            pass

    def _open_explorer(self, path: str) -> None:
        """Open directory in Windows Explorer."""
        try:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            if sys.platform.startswith("win"):
                os.startfile(target)
            else:
                subprocess.run(["xdg-open", target])
        except Exception:
            pass
