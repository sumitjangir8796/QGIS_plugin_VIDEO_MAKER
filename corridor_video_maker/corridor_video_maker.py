# -*- coding: utf-8 -*-
"""
Corridor Video Maker – main plugin class.
Registers the menu action and toolbar button.
Auto-installs opencv-python in a background thread on first enable.
"""

import os
import sys
import subprocess
import tempfile
import threading

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis

from .corridor_video_maker_dialog import CorridorVideoMakerDialog


# ---------------------------------------------------------------------------
# Helper: find the real Python interpreter QGIS is running
# ---------------------------------------------------------------------------

def _find_python():
    """
    Return the path to a working python.exe inside the QGIS installation.

    On some installs sys.executable is qgis.exe / qgis-ltr-bin.exe, not python.
    We use QgsApplication.prefixPath() to find the QGIS root reliably on any PC.
    """
    import sys, os, glob

    # 1. BEST: use QGIS's own API to locate the installation root
    try:
        from qgis.core import QgsApplication
        qgis_root = QgsApplication.prefixPath()   # e.g. C:/Program Files/QGIS 3.40.11
        # prefixPath usually points to QGIS\apps\qgis  – go up to the QGIS root
        # Handle both  …\apps\qgis  and  …\QGIS x.y.z
        for candidate_root in (
            os.path.dirname(qgis_root),             # …\apps\qgis  → …\apps? try parent
            os.path.dirname(os.path.dirname(qgis_root)),  # two levels up
            qgis_root,
        ):
            for pat in [
                os.path.join(candidate_root, "apps", "Python3*", "python.exe"),
                os.path.join(candidate_root, "Python3*", "python.exe"),
            ]:
                hits = sorted(glob.glob(pat), reverse=True)
                if hits:
                    return hits[0]
    except Exception:
        pass

    # 2. sys.executable itself – works when QGIS ships a real python.exe
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if "python" in base:
        return exe

    # 3. Look for python3.exe / python.exe siblings of qgis*.exe
    qgis_bin = os.path.dirname(exe)
    for name in ("python3.exe", "python.exe"):
        candidate = os.path.join(qgis_bin, name)
        if os.path.isfile(candidate):
            return candidate

    # 4. Scan Program Files for any QGIS Python
    qgis_root = os.path.dirname(qgis_bin)
    patterns = [
        os.path.join(qgis_root, "apps", "Python3*", "python.exe"),
        os.path.join(qgis_root, "apps", "Python3*", "python3.exe"),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat), reverse=True)   # newest Python first
        if hits:
            return hits[0]

    # 4. Fall back – will likely fail, but at least gives an informative error
    return exe


# ---------------------------------------------------------------------------
# Dependency auto-installer  (runs in a background thread – never blocks QGIS)
# ---------------------------------------------------------------------------

def _ensure_dependencies(iface):
    """
    Check for cv2; if missing, install it in a background thread so QGIS
    never freezes or times out.  numpy is intentionally skipped – QGIS
    ships its own.
    """
    try:
        import cv2  # noqa: F401
        return  # already installed, nothing to do
    except ImportError:
        pass

    # Show a non-blocking info bar immediately
    try:
        iface.messageBar().pushMessage(
            "Corridor Video Maker",
            "Installing opencv-python in the background … "
            "The plugin will be ready shortly.",
            level=Qgis.Info,
            duration=0,
        )
    except Exception:
        pass

    def _install():
        python_exe = _find_python()
        tmp_dir    = tempfile.gettempdir()
        try:
            result = subprocess.run(
                [
                    python_exe, "-m", "pip", "install",
                    "--user",
                    "--cache-dir", tmp_dir,
                    "--no-warn-script-location",
                    "opencv-python",
                ],
                capture_output=True,
                text=True,
                cwd=tmp_dir,
                # No timeout – let pip finish however long it needs
            )
            _on_install_done(iface, result)
        except Exception as exc:
            _on_install_error(iface, str(exc))

    t = threading.Thread(target=_install, daemon=True)
    t.start()


def _on_install_done(iface, result):
    """Called from the background thread when pip finishes."""
    # Add user site-packages to path so cv2 is importable immediately
    import site, sys
    try:
        usp = site.getusersitepackages()
        if usp not in sys.path:
            sys.path.insert(0, usp)
    except Exception:
        pass

    try:
        iface.messageBar().clearWidgets()
    except Exception:
        pass

    if result.returncode == 0:
        try:
            iface.messageBar().pushMessage(
                "Corridor Video Maker",
                "opencv-python installed successfully.  Open the plugin to generate a video.",
                level=Qgis.Success,
                duration=8,
            )
        except Exception:
            pass
    else:
        err = (result.stderr or result.stdout or "unknown error")[-500:]
        try:
            iface.messageBar().pushMessage(
                "Corridor Video Maker",
                f"opencv-python install failed.  Run install_deps.bat.  Detail: {err}",
                level=Qgis.Critical,
                duration=0,
            )
        except Exception:
            pass


def _on_install_error(iface, exc_str):
    """Called from the background thread on an unexpected exception."""
    try:
        iface.messageBar().clearWidgets()
    except Exception:
        pass
    try:
        iface.messageBar().pushMessage(
            "Corridor Video Maker",
            f"Auto-install error: {exc_str}  –  Run install_deps.bat.",
            level=Qgis.Critical,
            duration=0,
        )
    except Exception:
        pass


class CorridorVideoMakerPlugin:

    PLUGIN_NAME = "Corridor Video Maker"
    MENU_TEXT   = "&Corridor Video Maker"
    ACTION_TEXT = "Generate Corridor Video …"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self._dialog = None
        self._action = None

    # ------------------------------------------------------------------
    # QGIS lifecycle
    # ------------------------------------------------------------------

    def initGui(self):
        # ── Auto-install missing dependencies first ──────────────────────
        _ensure_dependencies(self.iface)

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self._action = QAction(icon, self.ACTION_TEXT, self.iface.mainWindow())
        self._action.setStatusTip(
            "Generate a fly-through MP4 video along a corridor centerline."
        )
        self._action.triggered.connect(self._show_dialog)

        # Add to Vector menu and toolbar
        self.iface.addPluginToVectorMenu(self.MENU_TEXT, self._action)
        self.iface.addToolBarIcon(self._action)

    def unload(self):
        self.iface.removePluginVectorMenu(self.MENU_TEXT, self._action)
        self.iface.removeToolBarIcon(self._action)
        if self._dialog:
            self._dialog.close()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _show_dialog(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = CorridorVideoMakerDialog(
                self.iface, self.iface.mainWindow()
            )
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
