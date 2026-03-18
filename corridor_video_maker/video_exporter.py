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
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
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
                 corridor_points,        # list of (x, y, bearing_deg)
                 buffer_map_units,       # half-width of corridor view
                 video_path,
                 fps=25,
                 video_width=1920,
                 video_height=1080,
                 total_distance_m=0.0,   # total route length in metres
                 start_label='',         # label shown at bar left end
                 end_label='',           # label shown at bar right end
                 layer_crs=None,          # QgsCoordinateReferenceSystem of the corridor
                 # ── split-view options ────────────────────────────────
                 split_enabled=False,
                 left_layer_ids=None,    # list of QGIS layer IDs for left panel
                 right_layer_ids=None,   # list of QGIS layer IDs for right panel
                 split_ratio=0.5,        # fraction of frame width for left panel
                 div_color=(255,255,255),# BGR colour of divider line; None = hidden
                 div_width=3,            # pixel width of divider line
                 left_panel_label='',    # text drawn in upper-left of left panel
                 right_panel_label='',   # text drawn in upper-left of right panel
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

        # Build coordinate transform to WGS84 for lat/lon display
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        src_crs = layer_crs if (layer_crs and layer_crs.isValid()) else \
                  self._canvas.mapSettings().destinationCrs()
        try:
            self._to_wgs84 = QgsCoordinateTransform(
                src_crs, wgs84, QgsProject.instance()
            )
        except Exception:
            self._to_wgs84 = None

        self._split_enabled    = split_enabled
        self._left_layer_ids   = left_layer_ids  or []
        self._right_layer_ids  = right_layer_ids or []
        self._split_ratio      = max(0.1, min(0.9, split_ratio))
        self._div_color        = div_color
        self._div_width        = div_width
        self._left_panel_label = left_panel_label
        self._right_panel_label= right_panel_label
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

            if self._split_enabled:
                frame_bgr = self._render_split_frame(
                    base_settings, cx, cy, bearing, cv2, np
                )
                if frame_bgr is None:
                    continue
            else:
                img = self._render_frame(base_settings, cx, cy, bearing)
                if img is None:
                    continue

                # Convert QImage (RGB888) -> numpy (H x W x 3) -> BGR for OpenCV
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
                    cx, cy,
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
                           start_label, end_label, cx, cy, cv2, np):
        """
        Draw a semi-transparent distance progress bar at the bottom of *frame*.

        Layout (bottom strip of the frame)
        ───────────────────────────────────
        [START_NAME]   ━━━━━━━━━●──────   [END_NAME]
                           1.25 km
                    12.345678°N  98.765432°E
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

        # ── Lat / Lon display (PIL for Unicode ° symbol) ─────────────────
        try:
            if self._to_wgs84 is not None:
                pt = self._to_wgs84.transform(QgsPointXY(cx, cy))
                lat, lon = pt.y(), pt.x()
            else:
                lat, lon = cy, cx   # already geographic

            def _to_dms(value, pos_ch, neg_ch):
                ch = pos_ch if value >= 0 else neg_ch
                v  = abs(value)
                d  = int(v)
                m  = int((v - d) * 60)
                s  = (v - d - m / 60.0) * 3600.0
                return f"{d}\u00b0{m:02d}'{s:05.2f}\" {ch}"

            coord_txt = f"Lat: {_to_dms(lat, 'N', 'S')}    Lon: {_to_dms(lon, 'E', 'W')}"

            font_size_px = max(14, int(bar_h * 0.22))
            cy_txt = track_y + dot_r + max(10, bar_h // 10)

            self._put_unicode_text(frame, coord_txt,
                                   cy_txt, font_size_px,
                                   (180, 230, 180), np)
        except Exception:
            pass   # never crash the render loop over coord display

    # ------------------------------------------------------------------
    def _put_unicode_text(self, frame, text, y, font_size_px, color_bgr, np):
        """Draw *text* (may contain Unicode like °) onto *frame* in-place.

        Uses PIL/Pillow for full Unicode support.  Falls back to cv2 with
        ASCII replacements (° → d) when PIL is unavailable.

        Parameters
        ----------
        frame       : numpy BGR uint8 array  (modified in-place)
        text        : str  — the string to render (may contain °, ′, ″ …)
        y           : int  — baseline y coordinate in pixels
        font_size_px: int  — approximate font height in pixels
        color_bgr   : tuple (B, G, R) — text colour
        np          : the numpy module reference from the caller
        """
        import cv2 as _cv2
        try:
            from PIL import Image, ImageDraw, ImageFont

            h, w = frame.shape[:2]
            color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])

            # Convert the full frame to PIL (RGB)
            pil_img = Image.fromarray(_cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)

            # Load a system TTF that supports the degree glyph
            font_loaded = None
            for path in ("arial.ttf",
                         "C:/Windows/Fonts/arial.ttf",
                         "C:/Windows/Fonts/calibri.ttf",
                         "C:/Windows/Fonts/segoeui.ttf"):
                try:
                    font_loaded = ImageFont.truetype(path, font_size_px)
                    break
                except Exception:
                    continue
            if font_loaded is None:
                # PIL default bitmap font — very small, but always available
                font_loaded = ImageFont.load_default()

            # Measure text to centre it horizontally
            bbox = draw.textbbox((0, 0), text, font=font_loaded)
            tw = bbox[2] - bbox[0]
            tx = (w - tw) // 2

            # Drop-shadow (black, 1 px offset)
            draw.text((tx + 1, y + 1), text, font=font_loaded, fill=(0, 0, 0))
            # Main text
            draw.text((tx, y), text, font=font_loaded, fill=color_rgb)

            # Write back to frame in-place
            frame[:] = _cv2.cvtColor(np.array(pil_img), _cv2.COLOR_RGB2BGR)

        except Exception:
            # PIL not available — fall back to cv2 ASCII rendering (° → d)
            font = _cv2.FONT_HERSHEY_SIMPLEX
            fallback = text.replace('\u00b0', 'd') \
                           .replace('\u2032', "'") \
                           .replace('\u2033', '"')
            h, w = frame.shape[:2]
            c_scale = max(0.38, font_size_px / 40.0)
            c_thick = max(1, int(c_scale * 1.5))
            (cw, _), _ = _cv2.getTextSize(fallback, font, c_scale, c_thick)
            tx = (w - cw) // 2
            _cv2.putText(frame, fallback, (tx + 1, y + 1), font,
                         c_scale, (0, 0, 0), c_thick + 1, _cv2.LINE_AA)
            _cv2.putText(frame, fallback, (tx, y), font,
                         c_scale, color_bgr, c_thick, _cv2.LINE_AA)

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

    # ------------------------------------------------------------------
    # Split-view rendering
    # ------------------------------------------------------------------

    def _qimage_to_bgr(self, img, cv2, np):
        """Convert a QImage to a BGR numpy array at the image's native size."""
        img = img.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        try:
            ptr = img.bits()
            ptr.setsize(h * w * 3)
            arr = bytes(ptr)
        except AttributeError:
            arr = img.bits().tobytes()
        frame = np.frombuffer(arr, dtype=np.uint8).reshape(h, w, 3)
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def _layer_objects_for_ids(self, base_settings, layer_ids):
        """
        Return a list of QgsMapLayer objects that are currently in
        *base_settings* and whose id() is in *layer_ids*.
        If *layer_ids* is empty, returns the full layer list (all visible).
        """
        all_layers = base_settings.layers()
        if not layer_ids:
            return all_layers
        id_set = set(layer_ids)
        return [lyr for lyr in all_layers if lyr.id() in id_set]

    def _settings_for_panel(self, base_settings, cx, cy, bearing,
                             panel_w, panel_h, layer_ids):
        """
        Build a QgsMapSettings for one split panel.

        The extent and rotation are the same as the main frame; only the
        output size and layer list differ.
        """
        settings = QgsMapSettings(base_settings)
        settings.setOutputSize(QSize(panel_w, panel_h))

        # Keep the same geographic extent centre + bearing
        aspect  = panel_h / panel_w
        half_w  = self._buffer
        half_h  = self._buffer * aspect
        extent  = QgsRectangle(cx - half_w, cy - half_h,
                               cx + half_w, cy + half_h)
        settings.setExtent(extent)

        rotation = -bearing
        if rotation <= -180:
            rotation += 360
        settings.setRotation(rotation)

        layers = self._layer_objects_for_ids(base_settings, layer_ids)
        if layers:
            settings.setLayers(layers)
        return settings

    def _draw_panel_label(self, frame, text, cv2):
        """Draw a small semi-transparent label in the upper-left corner."""
        if not text:
            return
        font    = cv2.FONT_HERSHEY_SIMPLEX
        scale   = max(0.55, self._height / 1000.0)
        thick   = max(1, int(scale * 1.8))
        pad     = max(8, int(self._height * 0.012))
        (tw, th), bl = cv2.getTextSize(text, font, scale, thick)
        # Background pill
        x0, y0 = pad, pad
        x1, y1 = x0 + tw + pad, y0 + th + bl + pad
        import numpy as np
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0 - 4, y0 - 4), (x1 + 4, y1 + 4),
                      (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        # Text
        cv2.putText(frame, text, (x0, y0 + th),
                    font, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(frame, text, (x0, y0 + th),
                    font, scale, (230, 230, 230), thick, cv2.LINE_AA)

    def _render_split_frame(self, base_settings, cx, cy, bearing, cv2, np):
        """
        Render left and right panels independently and composite them
        side-by-side into a single (self._width x self._height) BGR frame.
        """
        left_w  = max(1, int(self._width * self._split_ratio))
        right_w = max(1, self._width - left_w)
        h       = self._height

        # Render each panel
        left_settings  = self._settings_for_panel(
            base_settings, cx, cy, bearing, left_w,  h, self._left_layer_ids)
        right_settings = self._settings_for_panel(
            base_settings, cx, cy, bearing, right_w, h, self._right_layer_ids)

        left_job  = QgsMapRendererSequentialJob(left_settings)
        right_job = QgsMapRendererSequentialJob(right_settings)

        left_job.start()
        left_job.waitForFinished()
        right_job.start()
        right_job.waitForFinished()

        left_img  = left_job.renderedImage()
        right_img = right_job.renderedImage()

        if left_img is None or right_img is None:
            return None

        left_bgr  = self._qimage_to_bgr(left_img,  cv2, np)
        right_bgr = self._qimage_to_bgr(right_img, cv2, np)

        # Ensure exact pixel dimensions (renderer may round)
        if left_bgr.shape[:2] != (h, left_w):
            left_bgr  = cv2.resize(left_bgr,  (left_w,  h), interpolation=cv2.INTER_LANCZOS4)
        if right_bgr.shape[:2] != (h, right_w):
            right_bgr = cv2.resize(right_bgr, (right_w, h), interpolation=cv2.INTER_LANCZOS4)

        # Draw per-panel labels
        self._draw_panel_label(left_bgr,  self._left_panel_label,  cv2)
        self._draw_panel_label(right_bgr, self._right_panel_label, cv2)

        # Composite side by side
        frame = np.hstack([left_bgr, right_bgr])

        # Draw divider line
        if self._div_color is not None and self._div_width > 0:
            dw   = max(1, self._div_width)
            half = dw // 2
            x    = left_w
            cv2.line(frame, (x - half, 0), (x - half, h - 1),
                     self._div_color, dw, cv2.LINE_AA)

        return frame
