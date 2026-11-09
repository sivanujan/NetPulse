"""Main Dashboard window with Windows 11 styling, sidebar navigation, and stacked pages."""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import Config
from core.storage import NetRecord, Storage
from ui.dashboard.compare_page import CompareNetworksPage
from ui.dashboard.history_page import HistoryPage
from ui.dashboard.live_page import LivePage
from ui.dashboard.outages_page import OutagesPage
from ui.dashboard.settings_page import SettingsPage
from ui.dashboard.today_page import TodayPage
from ui.report_dialog import ReportDialog
from ui.tray import create_tray_icon


class DashboardWindow(QMainWindow):
    """Modern Windows 11 style dashboard window for NetPulse."""

    settings_applied = Signal()

    def __init__(
        self,
        storage: Storage,
        config: Config,
        settings_path: str = "netpulse_settings.json",
        base_dir: str = ".",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.config = config
        self.settings_path = settings_path
        self.base_dir = base_dir

        self._nav_buttons: List[QPushButton] = []
        self._init_window()
        self._init_ui()

    def _init_window(self) -> None:
        self.setWindowTitle("NetPulse — Dashboard")
        self.setWindowIcon(create_tray_icon("OK"))
        self.resize(1080, 740)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #16171b;
                color: #f3f4f6;
                font-family: 'Segoe UI Variable', 'Segoe UI', -apple-system, sans-serif;
            }
            """
        )

    def _init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Left Sidebar Navigation (~200 px)
        sidebar = QFrame()
        sidebar.setFixedWidth(205)
        sidebar.setStyleSheet(
            """
            QFrame {
                background-color: #191a20;
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }
            """
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 18, 12, 18)
        sidebar_layout.setSpacing(6)

        # App Brand Header
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(8)
        brand_icon = QLabel("⚡")
        brand_icon.setStyleSheet("font-size: 18px; color: #3b82f6;")
        brand_layout.addWidget(brand_icon)

        brand_title = QLabel("NetPulse")
        brand_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f3f4f6; letter-spacing: -0.3px;")
        brand_layout.addWidget(brand_title)
        brand_layout.addStretch()
        sidebar_layout.addLayout(brand_layout)

        sidebar_layout.addSpacing(16)

        # Section Label 1: Main Pages
        lbl_pages = QLabel("DASHBOARD")
        lbl_pages.setStyleSheet("color: #71717a; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; margin-left: 6px;")
        sidebar_layout.addWidget(lbl_pages)

        self.btn_live = self._create_nav_button("⚡  Live Monitor", 0)
        self.btn_today = self._create_nav_button("📅  Today", 1)
        self.btn_history = self._create_nav_button("📈  History", 2)

        sidebar_layout.addWidget(self.btn_live)
        sidebar_layout.addWidget(self.btn_today)
        sidebar_layout.addWidget(self.btn_history)

        sidebar_layout.addSpacing(16)

        # Section Label 2: Analytics
        lbl_analytics = QLabel("ANALYTICS")
        lbl_analytics.setStyleSheet("color: #71717a; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; margin-left: 6px;")
        sidebar_layout.addWidget(lbl_analytics)

        self.btn_compare = self._create_nav_button("⚖  Compare Networks", 3)
        self.btn_outages = self._create_nav_button("🚨  Outages Log", 4)
        self.btn_settings = self._create_nav_button("⚙  Settings", 5)

        sidebar_layout.addWidget(self.btn_compare)
        sidebar_layout.addWidget(self.btn_outages)
        sidebar_layout.addWidget(self.btn_settings)

        sidebar_layout.addSpacing(16)

        # Section Label 3: Actions / Reports
        lbl_actions = QLabel("ACTIONS")
        lbl_actions.setStyleSheet("color: #71717a; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; margin-left: 6px;")
        sidebar_layout.addWidget(lbl_actions)

        btn_report = QPushButton("📄  Create Report")
        btn_report.setCursor(Qt.PointingHandCursor)
        btn_report.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 8px 12px;
                border: 1px solid rgba(59, 130, 246, 0.3);
                border-radius: 8px;
                color: #38bdf8;
                font-size: 12px;
                font-weight: 700;
                background-color: rgba(59, 130, 246, 0.1);
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 0.2);
                color: #ffffff;
            }
            """
        )
        btn_report.clicked.connect(self.open_report_dialog)
        sidebar_layout.addWidget(btn_report)

        sidebar_layout.addStretch()

        # Status Footer in Sidebar
        self.status_footer = QLabel("● Active")
        self.status_footer.setStyleSheet("color: #22c55e; font-size: 11px; font-weight: 600; padding: 6px;")
        sidebar_layout.addWidget(self.status_footer)

        root_layout.addWidget(sidebar)

        # 2. Right Content Area (Stacked Pages)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #16171b;")

        # Page 0: Live Page
        self.page_live = LivePage()
        self.stack.addWidget(self.page_live)

        # Page 1: Today Page
        self.page_today = TodayPage(storage=self.storage)
        self.stack.addWidget(self.page_today)

        # Page 2: History Page
        self.page_history = HistoryPage(storage=self.storage)
        self.stack.addWidget(self.page_history)

        # Page 3: Compare Networks Page
        self.page_compare = CompareNetworksPage(storage=self.storage)
        self.stack.addWidget(self.page_compare)

        # Page 4: Outages Page
        self.page_outages = OutagesPage(storage=self.storage)
        self.stack.addWidget(self.page_outages)

        # Page 5: Settings Page
        self.page_settings = SettingsPage(
            config=self.config,
            settings_path=self.settings_path,
            base_dir=self.base_dir,
        )
        self.page_settings.settings_applied.connect(self.settings_applied)
        self.stack.addWidget(self.page_settings)

        root_layout.addWidget(self.stack, 1)

        # Select Live page initially
        self._select_nav(0)

    def _create_nav_button(
        self, text: str, page_index: int, disabled_text: Optional[str] = None
    ) -> QPushButton:
        """Create a styled sidebar navigation button."""
        display_text = text if not disabled_text else f"{text} ({disabled_text})"
        btn = QPushButton(display_text)
        btn.setCheckable(page_index >= 0)
        btn.setEnabled(page_index >= 0)
        btn.setCursor(Qt.PointingHandCursor if page_index >= 0 else Qt.ForbiddenCursor)

        if page_index >= 0:
            btn.clicked.connect(lambda: self._select_nav(page_index))
            self._nav_buttons.append(btn)

        btn.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 8px 12px;
                border: none;
                border-radius: 8px;
                color: #A0A4AE;
                font-size: 12px;
                font-weight: 600;
                background-color: transparent;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.06);
                color: #f3f4f6;
            }
            QPushButton:checked {
                background-color: #272a34;
                color: #38bdf8;
                font-weight: 700;
            }
            QPushButton:disabled {
                color: #52525b;
            }
            """
        )
        return btn

    def _select_nav(self, index: int) -> None:
        """Switch stacked page and update button highlight states."""
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

        # Trigger data refresh when entering pages
        if index == 1:
            self.page_today.refresh_data()
        elif index == 2:
            self.page_history.populate_filter_dropdowns()
            self.page_history.apply_filter()
        elif index == 3:
            self.page_compare.refresh_data()
        elif index == 4:
            self.page_outages.populate_providers()
            self.page_outages.refresh_data()
        elif index == 5:
            self.page_settings.load_values_from_config()

    def open_report_dialog(self) -> None:
        """Open the complaint and diagnostic report creation dialog."""
        dlg = ReportDialog(
            storage=self.storage,
            config=self.config,
            base_dir=self.base_dir,
            parent=self,
        )
        dlg.exec()

    def update_sample(self, record: NetRecord) -> None:
        """Route live sample to LivePage and update sidebar status."""
        self.page_live.update_sample(record)
        self.status_footer.setText(f"● {record.network} ({record.status})")
        color = "#22c55e" if record.status == "OK" else ("#f59e0b" if record.status == "BAD" else "#ef4444")
        self.status_footer.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600; padding: 6px;")

    def seed_live_history(self, records: List[NetRecord]) -> None:
        """Seed rolling 1-hour live chart with existing records."""
        self.page_live.seed_history(records)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Minimize to tray when window is closed instead of quitting the application."""
        event.ignore()
        self.hide()
