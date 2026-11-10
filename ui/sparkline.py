"""Lightweight custom sparkline QWidget for ping history visualization."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

STATUS_COLORS = {
    "OK": QColor(34, 197, 94),      # Green (#22c55e)
    "AMBER": QColor(245, 158, 11),  # Amber (#f59e0b)
    "BAD": QColor(239, 68, 68),     # Red (#ef4444)
    "DOWN": QColor(107, 114, 128),  # Grey (#6b7280)
}


class SparklineWidget(QWidget):
    """Renders a smooth antialiased sparkline of recent ping latencies."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.values: List[Optional[float]] = []
        self.status: str = "OK"
        self.setMinimumSize(80, 24)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def set_data(self, values: List[Optional[float]], status: str = "OK") -> None:
        """Update sparkline data and trigger repaint."""
        self.values = values[-25:] if len(values) > 25 else list(values)
        self.status = status
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Custom paint routine using QPainter."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)

            width = self.width()
            height = self.height()
            if width <= 0 or height <= 0:
                return

            # Filter numeric values for range calculation
            valid_nums = [v for v in self.values if v is not None and v >= 0]
            if not valid_nums:
                # Draw placeholder baseline
                pen = QPen(QColor(60, 60, 65), 1, Qt.DashLine)
                painter.setPen(pen)
                painter.drawLine(0, height // 2, width, height // 2)
                return

            min_val = max(0.0, min(valid_nums) * 0.8)
            max_val = max(max(valid_nums) * 1.15, min_val + 50.0)
            val_range = max(1.0, max_val - min_val)

            # Base color selection
            line_color = STATUS_COLORS.get(self.status, STATUS_COLORS["OK"])

            # Map points
            n = len(self.values)
            step = width / max(1, n - 1) if n > 1 else width
            points: List[Optional[QPointF]] = []

            for i, val in enumerate(self.values):
                if val is None:
                    points.append(None)
                else:
                    x = i * step
                    # Invert y: higher ping = higher on graph
                    ratio = (val - min_val) / val_range
                    ratio = max(0.0, min(1.0, ratio))
                    y = height - (ratio * (height - 6)) - 3
                    points.append(QPointF(x, y))

            # Build path
            path = QPainterPath()
            first_point = True
            first_valid_x: Optional[float] = None
            last_valid_point: Optional[QPointF] = None

            for pt in points:
                if pt is not None:
                    if first_point:
                        path.moveTo(pt)
                        first_point = False
                        first_valid_x = pt.x()
                    else:
                        path.lineTo(pt)
                    last_valid_point = pt

            if not path.isEmpty() and last_valid_point is not None:
                # Draw gradient fill under line
                fill_path = QPainterPath(path)
                fill_path.lineTo(last_valid_point.x(), height)
                fill_path.lineTo(first_valid_x if first_valid_x is not None else 0.0, height)
                fill_path.closeSubpath()

                grad = QLinearGradient(0, 0, 0, height)
                grad.setColorAt(0.0, QColor(line_color.red(), line_color.green(), line_color.blue(), 55))
                grad.setColorAt(1.0, QColor(line_color.red(), line_color.green(), line_color.blue(), 0))
                painter.fillPath(fill_path, QBrush(grad))

                # Draw the line
                pen = QPen(line_color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(path)

                # Draw glowing end dot at latest value
                # Outer glow
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(line_color.red(), line_color.green(), line_color.blue(), 90))
                painter.drawEllipse(last_valid_point, 4.0, 4.0)
                # Inner dot
                painter.setBrush(line_color)
                painter.drawEllipse(last_valid_point, 2.2, 2.2)

            # Draw tiny "max {val} ms" label at top-right
            if valid_nums:
                peak = max(valid_nums)
                max_label = f"max {peak:.0f} ms"
                font = painter.font()
                font.setFamily("Segoe UI Variable")
                font.setPixelSize(9)
                font.setWeight(QFont.Medium)
                painter.setFont(font)
                painter.setPen(QColor(160, 164, 174))  # #A0A4AE high contrast
                painter.drawText(
                    0,
                    0,
                    width - 2,
                    11,
                    Qt.AlignRight | Qt.AlignTop,
                    max_label,
                )
        finally:
            painter.end()
