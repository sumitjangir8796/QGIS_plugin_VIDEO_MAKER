# -*- coding: utf-8 -*-
"""
Map tool that lets the user click on the canvas to select the
start endpoint of the corridor centerline.

When the user clicks, the tool:
  1. Finds the active centerline layer's geometry.
  2. Determines which endpoint (first or last vertex) is nearest.
  3. Emits endpointSelected(reverse: bool) where reverse=True means
     the user clicked near the *last* vertex, so we should walk the
     line in reverse order.
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt

from .utils import nearest_endpoint


class EndpointPickerTool(QgsMapTool):
    """
    Click-on-map tool for choosing the start endpoint.

    Signals
    -------
    endpointSelected(reverse: bool)
        Emitted after the user clicks; *reverse* is True when the last
        vertex is the selected start point.
    cancelled()
        Emitted when the user presses Escape.
    """

    endpointSelected = pyqtSignal(bool)   # reverse flag
    cancelled = pyqtSignal()

    def __init__(self, canvas, line_layer, prev_tool=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.line_layer = line_layer
        self.prev_tool = prev_tool

        # Crosshair cursor
        self.setCursor(QCursor(Qt.CrossCursor))

        # Optional rubber-band highlight of both endpoints
        self._rb_first = None
        self._rb_last = None
        self._init_rubber_bands()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def activate(self):
        super().activate()
        self._draw_endpoint_markers()

    def deactivate(self):
        self._clear_rubber_bands()
        super().deactivate()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def canvasReleaseEvent(self, event):
        click_pt = self.toMapCoordinates(event.pos())

        geom = self._get_line_geom()
        if geom is None:
            return

        which = nearest_endpoint(click_pt, geom)
        reverse = (which == 'last')

        # Restore previous map tool, then notify dialog
        if self.prev_tool:
            self.canvas.setMapTool(self.prev_tool)
        self.endpointSelected.emit(reverse)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.prev_tool:
                self.canvas.setMapTool(self.prev_tool)
            self.cancelled.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_line_geom(self):
        if self.line_layer is None:
            return None
        feats = list(self.line_layer.getFeatures())
        if not feats:
            return None
        # Merge all features into one multi-geometry for simplicity,
        # but for corridor work a single-feature layer is normal.
        return feats[0].geometry()

    def _init_rubber_bands(self):
        from qgis.core import QgsWkbTypes
        from qgis.gui import QgsRubberBand

        self._rb_first = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
        self._rb_first.setColor(QColor(0, 200, 0, 200))
        self._rb_first.setIconSize(12)

        self._rb_last = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
        self._rb_last.setColor(QColor(255, 60, 0, 200))
        self._rb_last.setIconSize(12)

    def _draw_endpoint_markers(self):
        from .utils import get_line_endpoints
        geom = self._get_line_geom()
        if geom is None:
            return
        first, last = get_line_endpoints(geom)
        if first:
            from qgis.core import QgsGeometry
            self._rb_first.setToGeometry(QgsGeometry.fromPointXY(first),
                                         self.line_layer.crs())
        if last:
            from qgis.core import QgsGeometry
            self._rb_last.setToGeometry(QgsGeometry.fromPointXY(last),
                                        self.line_layer.crs())
        self.canvas.refresh()

    def _clear_rubber_bands(self):
        if self._rb_first:
            self._rb_first.reset()
        if self._rb_last:
            self._rb_last.reset()
        self.canvas.refresh()
