"""Dashboard UI components: main window and pages."""

from ui.dashboard.compare_page import CompareNetworksPage
from ui.dashboard.history_page import HistoryPage
from ui.dashboard.live_page import LivePage
from ui.dashboard.outages_page import OutagesPage
from ui.dashboard.today_page import TodayPage
from ui.dashboard.window import DashboardWindow

__all__ = [
    "DashboardWindow",
    "LivePage",
    "TodayPage",
    "HistoryPage",
    "CompareNetworksPage",
    "OutagesPage",
]
