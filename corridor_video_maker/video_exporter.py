# -*- coding: utf-8 -*-
"""
Video Exporter – off-screen renderer for Corridor Video Maker.

Renders each corridor frame using QgsMapRendererSequentialJob so the
live QGIS canvas is never disturbed.  Frames are written to an MP4 file
via OpenCV (cv2).

Usage (called from the dialog)
-------------------------------
    exporter = VideoExporter(
        canvas          = iface.mapCanvas(),
        corridor_points = [(x, y, bearing), ...],      # from utils.py
        buffer_map_units= 150,                          # half-width of view
        video_path      = r"C:\out\corridor.mp4",
        fps             = 25,
        video_width     = 1920,
        video_height    = 1080,
        progress_cb     = lambda pct: ...,              # 0-100
        cancelled_cb    = lambda: False,                # return True to stop
        finished_cb     = lambda: ...,
    )
    exporter.run()      # blocking (call from a worker thread or with QgsTask)
"""

import math
import os

from qgis.PyQt.QtCore import QSize, QTimer, pyqtSignal, QObject
from qgis.PyQt.QtGui import QImage
from qgis.core import (
    QgsMapSettings,
    QgsRectangle,
    QgsMapRendererSequentialJob,
    QgsApplication,
)


class VideoExporter(QObject):
    """
    Off-screen corridor video renderer.

    Signals
    -------
    progressChanged(int)   0-100 percent
    finished(str)          path of output video (empty string on error)
    errorOccurred(str)     human-readable error message
    """

    progressChanged = pyqtSignal(int)
    finished = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def __init__(self,
                 canvas,
                 corridor_points,    # list of (x, y, bearing_deg)
                 buffer_map_units,   # half-width of corridor view
                 video_path,
                 fps=25,
                 video_width=1920,
                 video_height=1080,
                 parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._points = corridor_points
        self._buffer = buffer_map_units
        self._out_path = video_path
        self._fps = fps
        self._width = video_width
        self._height = video_height
        self._abort = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def abort(self):
        """Call from the main thread to stop rendering early."""
        self._abort = True

    def run(self):
        """
        Main rendering loop.  This is blocking – run inside a QgsTask or
        a regular Python thread.  All Qt signals are queued and safe to
        emit from a worker thread in QGIS.
        """
        try:
            import cv2
        except ImportError:
            self.errorOccurred.emit(
                "OpenCV (cv2) is not installed.\n"
                "Open the QGIS Python console and run:\n"
                "  import pip; pip.main(['install', 'opencv-python'])\n"
                "or run 'install_deps.bat' from the plugin folder."
            )
            self.finished.emit("")
            return

        import numpy as np

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            self._out_path, fourcc, float(self._fps),
            (self._width, self._height)
        )
        if not writer.isOpened():
            self.errorOccurred.emit(
                f"Could not open output video for writing:\n{self._out_path}"
            )
            self.finished.emit("")
            return

        base_settings = QgsMapSettings(self._canvas.mapSettings())
        total = len(self._points)

        for idx, (cx, cy, bearing) in enumerate(self._points):
            if self._abort:
                break

            img = self._render_frame(base_settings, cx, cy, bearing)
            if img is None:
                continue

            # Convert QImage (RGB888) → numpy (H×W×3) → BGR for OpenCV
            img = img.convertToFormat(QImage.Format_RGB888)
            w, h = img.width(), img.height()
            try:
                ptr = img.bits()
                ptr.setsize(h * w * 3)          # PyQt5 voidptr
                arr = bytes(ptr)
            except AttributeError:
                arr = img.bits().tobytes()      # PyQt6 fallback

            frame = np.frombuffer(arr, dtype=np.uint8).reshape(h, w, 3)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # Resize to target dimensions if needed
            if (w, h) != (self._width, self._height):
                frame_bgr = cv2.resize(
                    frame_bgr, (self._width, self._height),
                    interpolation=cv2.INTER_LANCZOS4
                )

            writer.write(frame_bgr)
            pct = int((idx + 1) / total * 100)
            self.progressChanged.emit(pct)

        writer.release()

        if self._abort:
            # Remove partial file
            try:
                os.remove(self._out_path)
            except OSError:
                pass
            self.finished.emit("")
        else:
            self.finished.emit(self._out_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_frame(self, base_settings: QgsMapSettings,
                      cx: float, cy: float, bearing: float):
        """
        Render one frame off-screen and return a QImage.

        The extent is a rectangle centred at (cx, cy) with half-width =
        self._buffer map units.  The rotation is set to -bearing so that
        the travel direction always faces the top of the image.
        """
        settings = QgsMapSettings(base_settings)
        settings.setOutputSize(QSize(self._width, self._height))

        # Build a north-aligned rectangle; QGIS will apply the rotation
        # around the centre automatically.
        aspect = self._height / self._width
        half_w = self._buffer
        half_h = self._buffer * aspect
        extent = QgsRectangle(cx - half_w, cy - half_h,
                              cx + half_w, cy + half_h)
        settings.setExtent(extent)

        # Rotate: QGIS rotates clockwise, so -bearing makes travel dir "up"
        rotation = -bearing
        # Normalise to (-180, 180]
        if rotation <= -180:
            rotation += 360
        settings.setRotation(rotation)

        job = QgsMapRendererSequentialJob(settings)
        job.start()
        job.waitForFinished()
        return job.renderedImage()
