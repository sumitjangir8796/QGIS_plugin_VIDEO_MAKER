# -*- coding: utf-8 -*-
"""
Dialog for Corridor Video Maker.

Provides the full UI:
  • Centerline layer selector
  • "Pick start point" map-click tool (green = first vertex, red = last)
  • Speed / FPS / buffer / resolution settings
  • Output file browser
  • Progress bar + Generate / Cancel / Close buttons
"""

import os

from qgis.PyQt.QtCore import Qt, QThread, pyqtSlot
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QLineEdit,
    QSpinBox, QDoubleSpinBox, QProgressBar, QFileDialog,
    QSizePolicy, QMessageBox, QApplication,
)
from qgis.core import (
    QgsProject, QgsWkbTypes, QgsMapLayerProxyModel,
    QgsVectorLayer,
)
from qgis.gui import QgsMapLayerComboBox

from .utils import (
    interpolate_corridor_points,
    project_step_to_map_units,
    get_line_endpoints,
)
from .map_tools import EndpointPickerTool
from .video_exporter import VideoExporter


# ---------------------------------------------------------------------------
# Worker thread wrapper
# ---------------------------------------------------------------------------

class _ExporterThread(QThread):
    """Runs VideoExporter.run() on a background thread."""

    def __init__(self, exporter: VideoExporter):
        super().__init__()
        self._exporter = exporter

    def run(self):
        self._exporter.run()


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class CorridorVideoMakerDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()

        self._picker_tool = None
        self._prev_tool = None
        self._start_reversed = False   # False = start at first vertex
        self._exporter = None
        self._worker = None

        self.setWindowTitle("Corridor Video Maker")
        self.setMinimumWidth(480)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Layer group ────────────────────────────────────────────────
        grp_layer = QGroupBox("1. Centerline Layer")
        lay_layer = QVBoxLayout()

        self.cb_layer = QgsMapLayerComboBox()
        self.cb_layer.setFilters(QgsMapLayerProxyModel.LineLayer)
        lay_layer.addWidget(self.cb_layer)

        grp_layer.setLayout(lay_layer)
        root.addWidget(grp_layer)

        # ── Start point group ──────────────────────────────────────────
        grp_start = QGroupBox("2. Start Point  (click map to choose end)")
        lay_start = QVBoxLayout()

        row_btn = QHBoxLayout()
        self.btn_pick = QPushButton("🖱  Pick Start Point from Map")
        self.btn_pick.setToolTip(
            "Click near the vertex you want to START from.\n"
            "Green marker = first vertex, Red = last vertex."
        )
        self.btn_pick.clicked.connect(self._activate_picker)
        row_btn.addWidget(self.btn_pick)

        self.lbl_start = QLabel("No start point selected yet.")
        self.lbl_start.setStyleSheet("color: grey;")
        lay_start.addLayout(row_btn)
        lay_start.addWidget(self.lbl_start)

        grp_start.setLayout(lay_start)
        root.addWidget(grp_start)

        # ── Travel settings ────────────────────────────────────────────
        grp_travel = QGroupBox("3. Travel & Display Settings")
        g = QGridLayout()

        g.addWidget(QLabel("Travel speed (m/s):"), 0, 0)
        self.sb_speed = QDoubleSpinBox()
        self.sb_speed.setRange(0.1, 1000.0)
        self.sb_speed.setValue(10.0)
        self.sb_speed.setSuffix(" m/s")
        g.addWidget(self.sb_speed, 0, 1)

        g.addWidget(QLabel("Frames per second (FPS):"), 1, 0)
        self.sb_fps = QSpinBox()
        self.sb_fps.setRange(1, 120)
        self.sb_fps.setValue(25)
        self.sb_fps.setSuffix(" fps")
        g.addWidget(self.sb_fps, 1, 1)

        g.addWidget(QLabel("Corridor buffer (m):"), 2, 0)
        self.sb_buffer = QDoubleSpinBox()
        self.sb_buffer.setRange(1.0, 100_000.0)
        self.sb_buffer.setValue(100.0)
        self.sb_buffer.setSuffix(" m")
        self.sb_buffer.setToolTip(
            "Half-width of the view on each side of the centerline.\n"
            "Increase for a wider corridor, decrease to zoom in."
        )
        g.addWidget(self.sb_buffer, 2, 1)

        g.addWidget(QLabel("Video width (px):"), 3, 0)
        self.sb_width = QSpinBox()
        self.sb_width.setRange(320, 7680)
        self.sb_width.setValue(1920)
        self.sb_width.setSingleStep(2)
        g.addWidget(self.sb_width, 3, 1)

        g.addWidget(QLabel("Video height (px):"), 4, 0)
        self.sb_height = QSpinBox()
        self.sb_height.setRange(240, 4320)
        self.sb_height.setValue(1080)
        self.sb_height.setSingleStep(2)
        g.addWidget(self.sb_height, 4, 1)

        grp_travel.setLayout(g)
        root.addWidget(grp_travel)

        # ── Output file ────────────────────────────────────────────────
        grp_out = QGroupBox("4. Output Video File")
        lay_out = QHBoxLayout()

        self.le_output = QLineEdit()
        self.le_output.setPlaceholderText("Select output .mp4 file …")
        lay_out.addWidget(self.le_output)

        btn_browse = QPushButton("Browse …")
        btn_browse.clicked.connect(self._browse_output)
        lay_out.addWidget(btn_browse)

        grp_out.setLayout(lay_out)
        root.addWidget(grp_out)

        # ── Progress ───────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.lbl_status)

        # ── Buttons ────────────────────────────────────────────────────
        row_btns = QHBoxLayout()

        self.btn_generate = QPushButton("▶  Generate Video")
        self.btn_generate.setDefault(True)
        self.btn_generate.setFixedHeight(36)
        self.btn_generate.clicked.connect(self._on_generate)
        row_btns.addWidget(self.btn_generate)

        self.btn_cancel = QPushButton("⏹  Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row_btns.addWidget(self.btn_cancel)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        row_btns.addWidget(btn_close)

        root.addLayout(row_btns)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _activate_picker(self):
        layer = self.cb_layer.currentLayer()
        if layer is None or not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(self, "No Layer", "Please select a line layer first.")
            return

        self._prev_tool = self.canvas.mapTool()
        self._picker_tool = EndpointPickerTool(self.canvas, layer, self._prev_tool)
        self._picker_tool.endpointSelected.connect(self._on_endpoint_picked)
        self._picker_tool.cancelled.connect(self._on_pick_cancelled)
        self.canvas.setMapTool(self._picker_tool)

        self.lbl_start.setText("Click on the map near the vertex you want to START from …")
        self.lbl_start.setStyleSheet("color: #0055aa;")

    @pyqtSlot(bool)
    def _on_endpoint_picked(self, reverse: bool):
        self._start_reversed = reverse
        layer = self.cb_layer.currentLayer()
        geom = self._first_geom(layer)
        first, last = get_line_endpoints(geom) if geom else (None, None)

        if reverse:
            pt = last
            label = "Start: Last vertex (line walked in reverse)"
        else:
            pt = first
            label = "Start: First vertex"

        if pt:
            label += f"  [{pt.x():.4f}, {pt.y():.4f}]"

        self.lbl_start.setText(label)
        self.lbl_start.setStyleSheet("color: green; font-weight: bold;")

    @pyqtSlot()
    def _on_pick_cancelled(self):
        self.lbl_start.setText("Pick cancelled.")
        self.lbl_start.setStyleSheet("color: grey;")

    @pyqtSlot()
    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Video As", "", "MP4 Video (*.mp4)"
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.le_output.setText(path)

    @pyqtSlot()
    def _on_generate(self):
        # ── Validate inputs ────────────────────────────────────────────
        layer = self.cb_layer.currentLayer()
        if layer is None:
            QMessageBox.warning(self, "Error", "Select a centerline layer.")
            return

        geom = self._first_geom(layer)
        if geom is None:
            QMessageBox.warning(self, "Error", "The selected layer has no features.")
            return

        out_path = self.le_output.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Error", "Choose an output video file.")
            return

        fps = self.sb_fps.value()
        speed_ms = self.sb_speed.value()
        buffer_m = self.sb_buffer.value()
        vid_w = self.sb_width.value()
        vid_h = self.sb_height.value()

        layer_crs = layer.crs()

        # Step per frame in map units
        step_m_per_frame = speed_ms / fps
        step_map = project_step_to_map_units(step_m_per_frame, layer_crs)
        buffer_map = project_step_to_map_units(buffer_m, layer_crs)

        if step_map <= 0:
            QMessageBox.warning(self, "Error", "Invalid step distance.")
            return

        # ── Build corridor points ──────────────────────────────────────
        self.lbl_status.setText("Interpolating corridor points …")
        QApplication.processEvents()

        points = interpolate_corridor_points(
            geom, step_map, reverse=self._start_reversed,
            layer_crs=layer_crs
        )

        if not points:
            QMessageBox.warning(self, "Error",
                                "Could not interpolate points along the line.\n"
                                "Check that the layer contains a valid polyline.")
            return

        total_frames = len(points)
        duration_s = total_frames / fps
        self.lbl_status.setText(
            f"Rendering {total_frames} frames  "
            f"({duration_s:.1f} s at {fps} fps) …"
        )

        # ── Set up exporter on a worker thread ─────────────────────────
        self._exporter = VideoExporter(
            canvas=self.canvas,
            corridor_points=points,
            buffer_map_units=buffer_map,
            video_path=out_path,
            fps=fps,
            video_width=vid_w,
            video_height=vid_h,
        )
        self._exporter.progressChanged.connect(self._on_progress)
        self._exporter.finished.connect(self._on_finished)
        self._exporter.errorOccurred.connect(self._on_error)

        self._worker = _ExporterThread(self._exporter)
        self._worker.start()

        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)

    @pyqtSlot()
    def _on_cancel(self):
        if self._exporter:
            self._exporter.abort()
        self.lbl_status.setText("Cancelling …")
        self.btn_cancel.setEnabled(False)

    @pyqtSlot(int)
    def _on_progress(self, pct: int):
        self.progress.setValue(pct)

    @pyqtSlot(str)
    def _on_finished(self, path: str):
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(100 if path else 0)

        if path:
            self.lbl_status.setText(f"Done!  Saved: {path}")
            QMessageBox.information(
                self, "Done",
                f"Video saved successfully:\n{path}"
            )
        else:
            self.lbl_status.setText("Cancelled or failed – no video saved.")

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        QMessageBox.critical(self, "Export Error", msg)
        self.lbl_status.setText("Error – see message.")
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _first_geom(self, layer):
        if layer is None:
            return None
        feats = list(layer.getFeatures())
        if not feats:
            return None
        g = feats[0].geometry()
        # Merge multi-part to single part if needed
        if g.isMultipart():
            g = g.mergeLines()
        return g

    def closeEvent(self, event):
        # Abort any running export
        if self._exporter:
            self._exporter.abort()
        if self._worker and self._worker.isRunning():
            self._worker.wait(3000)
        # Restore the previous map tool if picker is still active
        if self._picker_tool and self.canvas.mapTool() is self._picker_tool:
            if self._prev_tool:
                self.canvas.setMapTool(self._prev_tool)
        super().closeEvent(event)
