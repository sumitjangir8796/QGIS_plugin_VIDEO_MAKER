# Run this script once from the QGIS Python Console to create icon.png
# In QGIS: Plugins → Python Console → paste and run this script.
#
# It creates a 32×32 blue PNG with a white play triangle.

import os

from qgis.PyQt.QtGui import QImage, QColor, QPainter, QPolygon
from qgis.PyQt.QtCore import Qt, QPoint

ICON_SIZE = 32
OUT_PATH = os.path.join(os.path.dirname(__file__), "corridor_video_maker", "icon.png")

img = QImage(ICON_SIZE, ICON_SIZE, QImage.Format_ARGB32)
img.fill(QColor(41, 128, 185))          # steel blue background

p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setPen(Qt.NoPen)
p.setBrush(QColor(255, 255, 255, 230))  # white, slightly transparent

# Play triangle (pointing right = forward / travel direction)
tri = QPolygon([QPoint(10, 7), QPoint(10, 25), QPoint(26, 16)])
p.drawPolygon(tri)
p.end()

img.save(OUT_PATH)
print(f"Icon saved → {OUT_PATH}")
