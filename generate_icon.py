"""Generate a crisp, multi-size application icon for NetPulse."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


def create_netpulse_icon(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    scale = size / 256.0

    # 1. Background rounded rectangle with deep dark gradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#1e1b4b"))  # Deep indigo
    grad.setColorAt(1.0, QColor("#0f172a"))  # Slate dark

    bg_path = QPainterPath()
    margin = 12 * scale
    bg_rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    bg_path.addRoundedRect(bg_rect, 52 * scale, 52 * scale)

    p.fillPath(bg_path, QBrush(grad))

    # Border glow
    p.setPen(QPen(QColor(59, 130, 246, 120), 3 * scale))
    p.drawPath(bg_path)

    # 2. Pulse / Heartbeat Wave
    wave_path = QPainterPath()
    pts = [
        (40, 138),
        (85, 138),
        (105, 95),
        (125, 180),
        (148, 65),
        (170, 160),
        (185, 138),
        (216, 138),
    ]
    wave_path.moveTo(pts[0][0] * scale, pts[0][1] * scale)
    for x, y in pts[1:]:
        wave_path.lineTo(x * scale, y * scale)

    # Glow under wave
    p.setPen(QPen(QColor(56, 189, 248, 80), 10 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(wave_path)

    # Main vibrant wave
    wave_pen = QPen(QColor("#38bdf8"), 5 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(wave_pen)
    p.drawPath(wave_path)

    # 3. Leading Pulse Dot (Emerald Green glow)
    dot_center = QPointF(216 * scale, 138 * scale)
    # Glow halo
    p.setBrush(QColor(34, 197, 94, 90))
    p.setPen(Qt.NoPen)
    p.drawEllipse(dot_center, 12 * scale, 12 * scale)
    # Solid dot
    p.setBrush(QColor("#22c55e"))
    p.drawEllipse(dot_center, 6 * scale, 6 * scale)

    p.end()
    return img


def main():
    img256 = create_netpulse_icon(256)
    img256.save("netpulse.ico", "ICO")
    print("netpulse.ico generated successfully.")


if __name__ == "__main__":
    main()
