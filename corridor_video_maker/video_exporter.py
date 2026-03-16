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
                 corridor_points,      # list of (x, y, bearing_deg)
                 buffer_map_units,     # half-width of corridor view
                 video_path,
                 fps=25,
                 video_width=1920,
                 video_height=1080,
                 total_distance_m=0.0, # total route length in metres
                 start_label='',       # label shown at bar left end
                 end_label='',         # label shown at bar right end
                 parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._points = corridor_points
        self._buffer = buffer_map_units
        self._out_path = video_path
        self._fps = fps
        self._width = video_width
        self._height = video_height
        self._total_dist_m = total_distance_m
        self._start_label = start_label
        self._end_label = end_label
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

            # Draw distance progress bar overlay
            if self._total_dist_m > 0:
                self._draw_distance_bar(
                    frame_bgr, idx, total,
                    self._total_dist_m,
                    self._start_label, self._end_label,
                    cv2, np
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

    def _draw_distance_bar(self, frame, idx, total, total_dist_m,
                           start_label, end_label, cv2, np):
        """
        Draw a semi-transparent distance progress bar at the bottom of *frame*.

        Layout (bottom strip of the frame)
        ───────────────────────────────────
        [START_NAME]   ━━━━━━━━━●──────   [END_NAME]
                           1.25 km
        """
        h, w = frame.shape[:2]

        # ── Geometry ────────────────────────────────────────────────────
        bar_h  = max(80, h // 9)          # height of bar area in pixels
        bar_y0 = h - bar_h                # top of bar area
        margin = int(w * 0.07)            # left/right margin for track
        track_x0 = margin
        track_x1 = w - margin
        track_y  = bar_y0 + int(bar_h * 0.42)   # vertical centre of track
        rail_t   = max(4, bar_h // 16)           # rail thickness
        dot_r    = max(10, bar_h // 7)           # radius of position dot

        # ── Semi-transparent dark background ────────────────────────────
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, bar_y0), (w, h), (15, 15, 15), -1)
        cv2.addWeighted(overlay, 0.70, frame, 0.30, 0, frame)

        # ── Track: background rail ──────────────────────────────────────
        cv2.line(frame,
                 (track_x0, track_y), (track_x1, track_y),
                 (80, 80, 80), rail_t, cv2.LINE_AA)

        # ── Progress fraction & current distance ─────────────────────────
        frac     = idx / max(total - 1, 1)
        cur_x    = int(track_x0 + frac * (track_x1 - track_x0))
        cur_dist = frac * total_dist_m

        # ── Filled rail (white glow effect via two overlaid lines) ───────
        if cur_x > track_x0:
            cv2.line(frame,
                     (track_x0, track_y), (cur_x, track_y),
                     (160, 200, 255), rail_t + 4, cv2.LINE_AA)   # glow
            cv2.line(frame,
                     (track_x0, track_y), (cur_x, track_y),
                     (255, 255, 255), rail_t, cv2.LINE_AA)        # core

        # ── Position dot ────────────────────────────────────────────────
        cv2.circle(frame, (cur_x, track_y),
                   dot_r + 3, (0, 0, 0), -1, cv2.LINE_AA)        # shadow
        cv2.circle(frame, (cur_x, track_y),
                   dot_r, (255, 255, 255), -1, cv2.LINE_AA)       # white fill
        cv2.circle(frame, (cur_x, track_y),
                   int(dot_r * 0.45), (100, 160, 255), -1, cv2.LINE_AA)  # blue core

        # ── Distance label above the dot ────────────────────────────────
        if cur_dist < 1000:
            dist_txt = f"{cur_dist:.0f} m"
        else:
            dist_txt = f"{cur_dist / 1000:.2f} km"

        font       = cv2.FONT_HERSHEY_SIMPLEX
        d_scale    = max(0.55, bar_h / 110.0)
        d_thick    = max(1, int(d_scale * 1.8))
        (tw, th), _ = cv2.getTextSize(dist_txt, font, d_scale, d_thick)

        # Clamp so the text never leaves the track area
        tx = max(track_x0, min(cur_x - tw // 2, track_x1 - tw))
        ty = track_y - dot_r - max(6, bar_h // 14)

        # Draw text with dark outline for legibility on any background
        cv2.putText(frame, dist_txt,
                    (tx + 1, ty + 1), font, d_scale, (0, 0, 0), d_thick + 2,
                    cv2.LINE_AA)
        cv2.putText(frame, dist_txt,
                    (tx, ty), font, d_scale, (255, 255, 255), d_thick,
                    cv2.LINE_AA)

        # ── Total distance (small, near right end of track) ──────────────
        if total_dist_m >= 1000:
            tot_txt = f"/ {total_dist_m / 1000:.2f} km"
        else:
            tot_txt = f"/ {total_dist_m:.0f} m"
        t_scale  = max(0.38, bar_h / 160.0)
        t_thick  = max(1, int(t_scale * 1.5))
        (ttw, _), _ = cv2.getTextSize(tot_txt, font, t_scale, t_thick)
        tot_x = track_x1 - ttw
        tot_y = track_y + dot_r + max(10, bar_h // 10)
        cv2.putText(frame, tot_txt,
                    (tot_x + 1, tot_y + 1), font, t_scale, (0, 0, 0), t_thick + 1,
                    cv2.LINE_AA)
        cv2.putText(frame, tot_txt,
                    (tot_x, tot_y), font, t_scale, (160, 160, 160), t_thick,
                    cv2.LINE_AA)

        # ── Start / End labels ───────────────────────────────────────────
        lbl_scale = max(0.42, bar_h / 155.0)
        lbl_thick = max(1, int(lbl_scale * 1.6))
        lbl_y     = h - max(8, bar_h // 10)    # near bottom of bar

        def _put_label(text, x, align_right=False):
            """Draw a label with shadow, optionally right-aligned."""
            (lw, _), _ = cv2.getTextSize(text, font, lbl_scale, lbl_thick)
            lx = (x - lw) if align_right else x
            lx = max(0, min(lx, w - lw))
            cv2.putText(frame, text,
                        (lx + 1, lbl_y + 1), font, lbl_scale,
                        (0, 0, 0), lbl_thick + 2, cv2.LINE_AA)
            cv2.putText(frame, text,
                        (lx, lbl_y), font, lbl_scale,
                        (210, 210, 210), lbl_thick, cv2.LINE_AA)

        if start_label:
            _put_label(start_label, track_x0)
        if end_label:
            _put_label(end_label, track_x1, align_right=True)

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
