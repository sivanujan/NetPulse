"""NetPulse User Interface package: desktop widget, system tray, and sparkline."""

from ui.sparkline import SparklineWidget
from ui.tray import NetPulseTrayIcon, create_tray_icon
from ui.widget import DesktopWidget

__all__ = [
    "SparklineWidget",
    "DesktopWidget",
    "NetPulseTrayIcon",
    "create_tray_icon",
]

