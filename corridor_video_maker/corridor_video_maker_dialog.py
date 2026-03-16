# -*- coding: utf-8 -*-
"""
Dialog for Corridor Video Maker.

Provides the full UI split across two tabs:

Tab 1 - Standard
    * Centerline layer selector
    * "Pick start point" map-click tool
    * Speed / FPS / buffer / resolution / smooth settings
    * Distance bar overlay labels
    * Output file browser

Tab 2 - Advanced Frame Designer
    * Enable / disable split view
    * Divider position slider (10-90 %)
    * Divider line colour & width
    * Per-panel labels (shown in the video)
    * Two mirrored layer-tree pickers (Left panel / Right panel)
      with check-boxes for every layer and group in the project
    * Refresh button to re-scan layers after project changes
"""

import os

from qgis.PyQt.QtCore import Qt, QThread, pyqtSlot
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QLineEdit,
    QSpinBox, QDoubleSpinBox, QProgressBar, QFileDialog,
    QSizePolicy, QMessageBox, QApplication,
    QTabWidget, QWidget, QTreeWidget, QTreeWidgetItem,
    QSlider, QScrollArea, QCheckBox, QFrame,
)
from qgis.core import (
    QgsProject, QgsWkbTypes, QgsMapLayerProxyModel,
    QgsVectorLayer, QgsLayerTreeGroup, QgsLayerTreeLayer,
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
# Colour presets for the divider line  (stored as BGR tuples for OpenCV)
# ---------------------------------------------------------------------------
_DIV_COLOURS = {
    "White":      (255, 255, 255),
    "Light Grey": (180, 180, 180),
    "Dark Grey":  (80,  80,  80),
    "Black":      (0,   0,   0),
    "Yellow":     (0,   255, 255),
    "Red":        (0,   0,   255),
    "None":       None,
}


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
        self._start_reversed = False
        self._exporter = None
        self._worker = None

        self.setWindowTitle("Corridor Video Maker")
        self.setMinimumWidth(580)
        self.setMinimumHeight(540)
        self._build_ui()

    # ======================================================================
    # UI Construction
    # ======================================================================

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 6)
        main.setSpacing(6)

        # Tab container
        self._tabs = QTabWidget()
        main.addWidget(self._tabs, 1)

        # Tab 1: Standard settings
        std_scroll = QScrollArea()
        std_scroll.setWidgetResizable(True)
        std_scroll.setFrameShape(QFrame.NoFrame)
        std_widget = QWidget()
        std_scroll.setWidget(std_widget)
        root = QVBoxLayout(std_widget)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)
        self._build_standard_tab(root)
        root.addStretch(1)
        self._tabs.addTab(std_scroll, "Standard")

        # Tab 2: Advanced Frame Designer
        adv_scroll = QScrollArea()
        adv_scroll.setWidgetResizable(True)
        adv_scroll.setFrameShape(QFrame.NoFrame)
        adv_widget = QWidget()
        adv_scroll.setWidget(adv_widget)
        self._build_advanced_tab(adv_widget)
        self._tabs.addTab(adv_scroll, "Advanced - Frame Designer")

        # Tab 3: Help & About
        help_widget = QWidget()
        self._build_help_tab(help_widget)
        self._tabs.addTab(help_widget, "Help & About")

        # Progress bar (always visible, outside tabs)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        main.addWidget(self.lbl_status)

        # Buttons (always visible)
        row_btns = QHBoxLayout()

        self.btn_generate = QPushButton("Play  Generate Video")
        self.btn_generate.setDefault(True)
        self.btn_generate.setFixedHeight(36)
        self.btn_generate.clicked.connect(self._on_generate)
        row_btns.addWidget(self.btn_generate)

        self.btn_cancel = QPushButton("Stop  Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row_btns.addWidget(self.btn_cancel)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        row_btns.addWidget(btn_close)

        main.addLayout(row_btns)

    # ------------------------------------------------------------------
    # Tab 1: Standard
    # ------------------------------------------------------------------

    def _build_standard_tab(self, root):
        """Add all Standard-tab widgets to root (a QVBoxLayout)."""

        # Layer group
        grp_layer = QGroupBox("1. Centerline Layer")
        lay_layer = QVBoxLayout()
        self.cb_layer = QgsMapLayerComboBox()
        self.cb_layer.setFilters(QgsMapLayerProxyModel.LineLayer)
        lay_layer.addWidget(self.cb_layer)
        grp_layer.setLayout(lay_layer)
        root.addWidget(grp_layer)

        # Start point group
        grp_start = QGroupBox("2. Start Point  (click map to choose end)")
        lay_start = QVBoxLayout()
        row_btn = QHBoxLayout()
        self.btn_pick = QPushButton("Pick Start Point from Map")
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

        # Travel & Display Settings
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
        self.sb_buffer.setRange(1.0, 100000.0)
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

        g.addWidget(QLabel("Turn smoothing (frames):"), 5, 0)
        self.sb_smooth = QSpinBox()
        self.sb_smooth.setRange(0, 500)
        self.sb_smooth.setValue(40)
        self.sb_smooth.setSuffix(" frames")
        self.sb_smooth.setToolTip(
            "Number of frames over which a turn eases in/out.\n"
            "0 = instant rotation (hard cuts on turns).\n"
            "40 = smooth ~1.6 s ease at 25 fps (recommended).\n"
            "Higher values = more gradual but more lag into a turn."
        )
        g.addWidget(self.sb_smooth, 5, 1)

        grp_travel.setLayout(g)
        root.addWidget(grp_travel)

        # Distance Bar Overlay
        grp_bar = QGroupBox("4. Distance Bar Overlay")
        gb = QGridLayout()

        gb.addWidget(QLabel("Start point name:"), 0, 0)
        self.le_start_name = QLineEdit()
        self.le_start_name.setPlaceholderText("e.g.  Village A  (optional)")
        gb.addWidget(self.le_start_name, 0, 1)

        gb.addWidget(QLabel("End point name:"), 1, 0)
        self.le_end_name = QLineEdit()
        self.le_end_name.setPlaceholderText("e.g.  Village B  (optional)")
        gb.addWidget(self.le_end_name, 1, 1)

        grp_bar.setLayout(gb)
        root.addWidget(grp_bar)

        # Output Video File
        grp_out = QGroupBox("5. Output Video File")
        lay_out = QHBoxLayout()
        self.le_output = QLineEdit()
        self.le_output.setPlaceholderText("Select output .mp4 file ...")
        lay_out.addWidget(self.le_output)
        btn_browse = QPushButton("Browse ...")
        btn_browse.clicked.connect(self._browse_output)
        lay_out.addWidget(btn_browse)
        grp_out.setLayout(lay_out)
        root.addWidget(grp_out)

    # ------------------------------------------------------------------
    # Tab 2: Advanced Frame Designer
    # ------------------------------------------------------------------

    def _build_advanced_tab(self, widget):
        """Build the Advanced tab content inside widget."""
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        info = QLabel(
            "<b>Frame Designer</b>  - optionally split the video frame into a "
            "<b>left</b> and a <b>right</b> panel, each rendering different layers."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        # Enable split view group
        grp_split = QGroupBox("Split View")
        grp_split_lay = QVBoxLayout(grp_split)

        self.chk_split = QCheckBox("Enable split view  (left panel  |  right panel)")
        self.chk_split.setChecked(False)
        self.chk_split.toggled.connect(self._on_split_enabled_toggled)
        grp_split_lay.addWidget(self.chk_split)

        # Designer container - shown only when split is enabled
        self._split_designer = QWidget()
        self._split_designer.setVisible(False)
        grp_split_lay.addWidget(self._split_designer)

        sd = QVBoxLayout(self._split_designer)
        sd.setContentsMargins(0, 6, 0, 0)
        sd.setSpacing(8)

        # Divider position
        div_pos_grp = QGroupBox("Divider Position")
        div_pos_lay = QHBoxLayout(div_pos_grp)
        div_pos_lay.addWidget(QLabel("Left width:"))
        self.sl_ratio = QSlider(Qt.Horizontal)
        self.sl_ratio.setRange(10, 90)
        self.sl_ratio.setValue(50)
        self.sl_ratio.setTickPosition(QSlider.TicksBelow)
        self.sl_ratio.setTickInterval(10)
        self.sl_ratio.valueChanged.connect(self._on_ratio_changed)
        div_pos_lay.addWidget(self.sl_ratio)
        self.lbl_ratio = QLabel("50 %  |  50 %")
        self.lbl_ratio.setMinimumWidth(90)
        self.lbl_ratio.setAlignment(Qt.AlignCenter)
        div_pos_lay.addWidget(self.lbl_ratio)
        sd.addWidget(div_pos_grp)

        # Divider line style
        div_line_grp = QGroupBox("Divider Line Style")
        div_line_lay = QHBoxLayout(div_line_grp)
        div_line_lay.addWidget(QLabel("Colour:"))
        self.cb_div_color = QComboBox()
        for name in _DIV_COLOURS:
            self.cb_div_color.addItem(name)
        self.cb_div_color.setCurrentIndex(0)
        div_line_lay.addWidget(self.cb_div_color)
        div_line_lay.addSpacing(14)
        div_line_lay.addWidget(QLabel("Width:"))
        self.sb_div_w = QSpinBox()
        self.sb_div_w.setRange(0, 20)
        self.sb_div_w.setValue(3)
        self.sb_div_w.setSuffix(" px")
        div_line_lay.addWidget(self.sb_div_w)
        div_line_lay.addStretch()
        sd.addWidget(div_line_grp)

        # Panel overlay labels
        lbl_grp = QGroupBox("Panel Labels  (shown in video, upper-left of each panel)")
        lbl_grid = QGridLayout(lbl_grp)
        lbl_grid.addWidget(QLabel("Left panel label:"), 0, 0)
        self.le_left_label = QLineEdit()
        self.le_left_label.setPlaceholderText("e.g.  Satellite  (optional)")
        lbl_grid.addWidget(self.le_left_label, 0, 1)
        lbl_grid.addWidget(QLabel("Right panel label:"), 1, 0)
        self.le_right_label = QLineEdit()
        self.le_right_label.setPlaceholderText("e.g.  Topographic  (optional)")
        lbl_grid.addWidget(self.le_right_label, 1, 1)
        sd.addWidget(lbl_grp)

        # Layer picker trees
        trees_grp = QGroupBox("Layer / Group Visibility per Panel")
        trees_lay = QVBoxLayout(trees_grp)

        hint = QLabel(
            "Check the layers you want visible in each panel.\n"
            "Unchecked layers are hidden for that panel during rendering."
        )
        hint.setWordWrap(True)
        trees_lay.addWidget(hint)

        btn_refresh = QPushButton("Refresh  Refresh layer list from project")
        btn_refresh.setToolTip("Re-scan all layers/groups from the current QGIS project.")
        btn_refresh.clicked.connect(self._populate_split_trees)
        trees_lay.addWidget(btn_refresh)

        trees_cols = QHBoxLayout()

        # Left tree
        left_box = QGroupBox("Left Panel")
        left_box_lay = QVBoxLayout(left_box)
        self.tree_left = QTreeWidget()
        self.tree_left.setHeaderLabel("Layer / Group")
        self.tree_left.setColumnCount(1)
        self.tree_left.setAlternatingRowColors(True)
        self.tree_left.setMinimumHeight(200)
        left_box_lay.addWidget(self.tree_left)
        lq = QHBoxLayout()
        btn_lall  = QPushButton("All")
        btn_lnone = QPushButton("None")
        btn_lall.setFixedHeight(22)
        btn_lnone.setFixedHeight(22)
        btn_lall.clicked.connect(lambda: self._set_all_check(self.tree_left, Qt.Checked))
        btn_lnone.clicked.connect(lambda: self._set_all_check(self.tree_left, Qt.Unchecked))
        lq.addWidget(btn_lall)
        lq.addWidget(btn_lnone)
        lq.addStretch()
        left_box_lay.addLayout(lq)
        trees_cols.addWidget(left_box)

        # Right tree
        right_box = QGroupBox("Right Panel")
        right_box_lay = QVBoxLayout(right_box)
        self.tree_right = QTreeWidget()
        self.tree_right.setHeaderLabel("Layer / Group")
        self.tree_right.setColumnCount(1)
        self.tree_right.setAlternatingRowColors(True)
        self.tree_right.setMinimumHeight(200)
        right_box_lay.addWidget(self.tree_right)
        rq = QHBoxLayout()
        btn_rall  = QPushButton("All")
        btn_rnone = QPushButton("None")
        btn_rall.setFixedHeight(22)
        btn_rnone.setFixedHeight(22)
        btn_rall.clicked.connect(lambda: self._set_all_check(self.tree_right, Qt.Checked))
        btn_rnone.clicked.connect(lambda: self._set_all_check(self.tree_right, Qt.Unchecked))
        rq.addWidget(btn_rall)
        rq.addWidget(btn_rnone)
        rq.addStretch()
        right_box_lay.addLayout(rq)
        trees_cols.addWidget(right_box)

        trees_lay.addLayout(trees_cols)
        sd.addWidget(trees_grp, 1)

        layout.addWidget(grp_split, 1)

    # ------------------------------------------------------------------
    # Tab 3: Help & About
    # ------------------------------------------------------------------

    def _build_help_tab(self, widget):
        """Build the Help & About tab."""
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Plugin title ───────────────────────────────────────────────
        title = QLabel("<h2>Corridor Video Maker</h2>")
        title.setAlignment(Qt.AlignCenter)
        title.setTextFormat(Qt.RichText)
        layout.addWidget(title)

        subtitle = QLabel(
            "<i>Generate fly-through MP4 videos along any polyline corridor in QGIS.</i>"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setTextFormat(Qt.RichText)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep1)

        # ── Author ─────────────────────────────────────────────────────
        grp_author = QGroupBox("Author")
        g_author = QGridLayout(grp_author)
        g_author.setSpacing(6)

        g_author.addWidget(QLabel("<b>Name:</b>"), 0, 0)
        g_author.addWidget(QLabel("Sumit Jangir"), 0, 1)

        g_author.addWidget(QLabel("<b>Email:</b>"), 1, 0)
        email_lbl = QLabel('<a href="mailto:sumitjangir8796@gmail.com">sumitjangir8796@gmail.com</a>')
        email_lbl.setTextFormat(Qt.RichText)
        email_lbl.setOpenExternalLinks(True)
        g_author.addWidget(email_lbl, 1, 1)

        g_author.addWidget(QLabel("<b>GitHub:</b>"), 2, 0)
        gh_lbl = QLabel('<a href="https://github.com/sumitjangir8796">github.com/sumitjangir8796</a>')
        gh_lbl.setTextFormat(Qt.RichText)
        gh_lbl.setOpenExternalLinks(True)
        g_author.addWidget(gh_lbl, 2, 1)

        g_author.addWidget(QLabel("<b>Plugin repo:</b>"), 3, 0)
        repo_lbl = QLabel('<a href="https://github.com/sumitjangir8796/QGIS_plugin_VIDEO_MAKER">QGIS_plugin_VIDEO_MAKER</a>')
        repo_lbl.setTextFormat(Qt.RichText)
        repo_lbl.setOpenExternalLinks(True)
        g_author.addWidget(repo_lbl, 3, 1)

        layout.addWidget(grp_author)

        # ── Quick-use guide ────────────────────────────────────────────
        grp_how = QGroupBox("Quick Guide")
        how_lay = QVBoxLayout(grp_how)
        help_text = QLabel(
            "<ol>"
            "<li>Load a <b>line / polyline</b> vector layer into QGIS.</li>"
            "<li>Open the plugin: <i>Vector &rarr; Corridor Video Maker &rarr; Generate Corridor Video</i>.</li>"
            "<li>Select the <b>centerline layer</b> from the dropdown.</li>"
            "<li>Click <b>Pick Start Point from Map</b> and click near the vertex you want to start from.<br>"
            "&nbsp;&nbsp;&nbsp; Green marker = first vertex &nbsp;|&nbsp; Red marker = last vertex.</li>"
            "<li>Configure <b>Travel &amp; Display Settings</b> (speed, FPS, buffer, resolution, smoothing).</li>"
            "<li>Optionally fill in <b>Distance Bar</b> start/end labels.</li>"
            "<li>For a <b>split-screen</b> view, switch to the <i>Advanced &ndash; Frame Designer</i> tab,<br>"
            "&nbsp;&nbsp;&nbsp; enable Split View, and choose layers for each panel.</li>"
            "<li>Choose an output <b>.mp4 file</b> and click <b>Generate Video</b>.</li>"
            "</ol>"
        )
        help_text.setTextFormat(Qt.RichText)
        help_text.setWordWrap(True)
        how_lay.addWidget(help_text)
        layout.addWidget(grp_how)

        # ── Tips ───────────────────────────────────────────────────────
        grp_tips = QGroupBox("Tips")
        tips_lay = QVBoxLayout(grp_tips)
        tips_lbl = QLabel(
            "<ul>"
            "<li>Use a <b>projected CRS</b> (e.g. UTM) for accurate metre-based distances.</li>"
            "<li>Reduce buffer &amp; resolution for a fast preview, then increase for the final render.</li>"
            "<li>Higher <b>Turn Smoothing</b> values give smoother curves but add a slight directional lag.</li>"
            "<li>The plugin renders all <b>currently visible</b> map layers &mdash; style your map before generating.</li>"
            "<li>For very long lines the export can take several minutes; lower FPS or speed for quicker results.</li>"
            "</ul>"
        )
        tips_lbl.setTextFormat(Qt.RichText)
        tips_lbl.setWordWrap(True)
        tips_lay.addWidget(tips_lbl)
        layout.addWidget(grp_tips)

        # ── Version / licence ──────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        footer = QLabel("Version 1.0.0  &nbsp;|&nbsp;  MIT Licence  &nbsp;|&nbsp;  QGIS 3.20+")
        footer.setAlignment(Qt.AlignCenter)
        footer.setTextFormat(Qt.RichText)
        footer.setStyleSheet("color: grey; font-size: 10px;")
        layout.addWidget(footer)

        layout.addStretch(1)

    # ======================================================================
    # Slots
    # ======================================================================

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

        self.lbl_start.setText("Click on the map near the vertex you want to START from ...")
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

    @pyqtSlot(bool)
    def _on_split_enabled_toggled(self, checked: bool):
        self._split_designer.setVisible(checked)
        if checked and self.tree_left.topLevelItemCount() == 0:
            self._populate_split_trees()

    @pyqtSlot(int)
    def _on_ratio_changed(self, value: int):
        self.lbl_ratio.setText(f"{value} %  |  {100 - value} %")

    @pyqtSlot()
    def _on_generate(self):
        # Validate inputs
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

        fps       = self.sb_fps.value()
        speed_ms  = self.sb_speed.value()
        buffer_m  = self.sb_buffer.value()
        vid_w     = self.sb_width.value()
        vid_h     = self.sb_height.value()
        layer_crs = layer.crs()

        step_m_per_frame = speed_ms / fps
        step_map   = project_step_to_map_units(step_m_per_frame, layer_crs)
        buffer_map = project_step_to_map_units(buffer_m, layer_crs)

        start_label = self.le_start_name.text().strip()
        end_label   = self.le_end_name.text().strip()

        if step_map <= 0:
            QMessageBox.warning(self, "Error", "Invalid step distance.")
            return

        # Build corridor points
        self.lbl_status.setText("Interpolating corridor points ...")
        QApplication.processEvents()

        smooth_window = self.sb_smooth.value()
        points = interpolate_corridor_points(
            geom, step_map, reverse=self._start_reversed,
            layer_crs=layer_crs, smooth_window=smooth_window
        )

        if not points:
            QMessageBox.warning(self, "Error",
                                "Could not interpolate points along the line.\n"
                                "Check that the layer contains a valid polyline.")
            return

        total_frames     = len(points)
        duration_s       = total_frames / fps
        total_distance_m = step_m_per_frame * max(total_frames - 1, 1)
        self.lbl_status.setText(
            f"Rendering {total_frames} frames  ({duration_s:.1f} s at {fps} fps) ..."
        )

        # Collect split-view settings
        split_enabled     = self.chk_split.isChecked()
        left_layer_ids    = []
        right_layer_ids   = []
        split_ratio       = 0.5
        div_color         = (255, 255, 255)
        div_width         = 3
        left_panel_label  = ""
        right_panel_label = ""

        if split_enabled:
            left_layer_ids    = self._get_checked_layer_ids(self.tree_left)
            right_layer_ids   = self._get_checked_layer_ids(self.tree_right)
            split_ratio       = self.sl_ratio.value() / 100.0
            colour_name       = self.cb_div_color.currentText()
            div_color         = _DIV_COLOURS.get(colour_name, (255, 255, 255))
            div_width         = self.sb_div_w.value()
            left_panel_label  = self.le_left_label.text().strip()
            right_panel_label = self.le_right_label.text().strip()

            if not left_layer_ids and not right_layer_ids:
                reply = QMessageBox.question(
                    self, "No Layers Selected",
                    "No layers are checked for either panel.\n"
                    "Both panels will render all visible layers.\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    self.lbl_status.setText("")
                    return

        # Create exporter
        self._exporter = VideoExporter(
            canvas=self.canvas,
            corridor_points=points,
            buffer_map_units=buffer_map,
            video_path=out_path,
            fps=fps,
            video_width=vid_w,
            video_height=vid_h,
            total_distance_m=total_distance_m,
            start_label=start_label,
            end_label=end_label,
            split_enabled=split_enabled,
            left_layer_ids=left_layer_ids,
            right_layer_ids=right_layer_ids,
            split_ratio=split_ratio,
            div_color=div_color,
            div_width=div_width,
            left_panel_label=left_panel_label,
            right_panel_label=right_panel_label,
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
        self.lbl_status.setText("Cancelling ...")
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
            QMessageBox.information(self, "Done", f"Video saved successfully:\n{path}")
        else:
            self.lbl_status.setText("Cancelled or failed - no video saved.")

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        QMessageBox.critical(self, "Export Error", msg)
        self.lbl_status.setText("Error - see message.")
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    # ======================================================================
    # Advanced tab helpers
    # ======================================================================

    @pyqtSlot()
    def _populate_split_trees(self):
        """Re-populate both layer trees from the current QGIS project."""
        prev_left  = self._save_check_states(self.tree_left)
        prev_right = self._save_check_states(self.tree_right)

        self.tree_left.clear()
        self.tree_right.clear()

        root_node = QgsProject.instance().layerTreeRoot()
        self._fill_tree(self.tree_left,  self.tree_left.invisibleRootItem(),
                        root_node, prev_left,  default=Qt.Checked)
        self._fill_tree(self.tree_right, self.tree_right.invisibleRootItem(),
                        root_node, prev_right, default=Qt.Checked)

        self.tree_left.expandAll()
        self.tree_right.expandAll()

    def _fill_tree(self, tree_widget, parent_item, tree_node,
                   prev_states: dict, default):
        """Recursively mirror the QGIS layer tree into tree_widget."""
        for child in tree_node.children():
            if isinstance(child, QgsLayerTreeGroup):
                grp_item = QTreeWidgetItem(parent_item, [child.name()])
                grp_item.setFlags(
                    grp_item.flags()
                    | Qt.ItemIsUserCheckable
                    | Qt.ItemIsAutoTristate
                )
                grp_item.setCheckState(0, Qt.Checked)
                grp_item.setData(0, Qt.UserRole, None)
                self._fill_tree(tree_widget, grp_item, child, prev_states, default)

            elif isinstance(child, QgsLayerTreeLayer):
                lyr = child.layer()
                if lyr is None:
                    continue
                lyr_item = QTreeWidgetItem(parent_item, [lyr.name()])
                lyr_item.setFlags(lyr_item.flags() | Qt.ItemIsUserCheckable)
                state = prev_states.get(lyr.id(), default)
                lyr_item.setCheckState(0, state)
                lyr_item.setData(0, Qt.UserRole, lyr.id())

    @staticmethod
    def _save_check_states(tree_widget) -> dict:
        """Return {layer_id: Qt.CheckState} for all leaf items."""
        states = {}

        def traverse(item):
            lid = item.data(0, Qt.UserRole)
            if lid is not None:
                states[lid] = item.checkState(0)
            for i in range(item.childCount()):
                traverse(item.child(i))

        root = tree_widget.invisibleRootItem()
        for i in range(root.childCount()):
            traverse(root.child(i))
        return states

    @staticmethod
    def _get_checked_layer_ids(tree_widget) -> list:
        """Return list of layer IDs for all checked leaf items."""
        ids = []

        def traverse(item):
            lid = item.data(0, Qt.UserRole)
            if lid is not None:
                if item.checkState(0) == Qt.Checked:
                    ids.append(lid)
            for i in range(item.childCount()):
                traverse(item.child(i))

        root = tree_widget.invisibleRootItem()
        for i in range(root.childCount()):
            traverse(root.child(i))
        return ids

    @staticmethod
    def _set_all_check(tree_widget, state):
        """Set all items in tree_widget to state."""
        def traverse(item):
            item.setCheckState(0, state)
            for i in range(item.childCount()):
                traverse(item.child(i))

        root = tree_widget.invisibleRootItem()
        for i in range(root.childCount()):
            traverse(root.child(i))

    # ======================================================================
    # Helpers
    # ======================================================================

    def _first_geom(self, layer):
        if layer is None:
            return None
        feats = list(layer.getFeatures())
        if not feats:
            return None
        g = feats[0].geometry()
        if g.isMultipart():
            g = g.mergeLines()
        return g

    def closeEvent(self, event):
        if self._exporter:
            self._exporter.abort()
        if self._worker and self._worker.isRunning():
            self._worker.wait(3000)
        if self._picker_tool and self.canvas.mapTool() is self._picker_tool:
            if self._prev_tool:
                self.canvas.setMapTool(self._prev_tool)
        super().closeEvent(event)
