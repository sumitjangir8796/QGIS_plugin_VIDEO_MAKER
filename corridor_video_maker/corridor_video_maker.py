# -*- coding: utf-8 -*-
"""
Corridor Video Maker – main plugin class.
Registers the menu action and toolbar button.
Auto-installs opencv-python + numpy on first enable.
"""

import os
import sys
import subprocess

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis

from .corridor_video_maker_dialog import CorridorVideoMakerDialog


# ---------------------------------------------------------------------------
# Dependency auto-installer
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = {
    "cv2": "opencv-python",
    "numpy": "numpy",
}


def _ensure_dependencies(iface):
    """
    Check for required packages; install any that are missing using the
    same Python interpreter that QGIS is running.  Shows a QGIS message-bar
    notification while installing so the user knows what's happening.
    """
    missing = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return True   # all good

    # Notify user via message bar
    if iface:
        iface.messageBar().pushMessage(
            "Corridor Video Maker",
            f"Installing required packages: {', '.join(missing)} – please wait …",
            level=Qgis.Info,
            duration=0,
        )
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()

    python_exe = sys.executable
    try:
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "--user"] + missing,
            capture_output=True,
            text=True,
            timeout=300,
        )
        success = result.returncode == 0

        if iface:
            iface.messageBar().clearWidgets()

        if success:
            # Force Python to see the newly-installed packages
            import importlib
            import site
            # Reload site to pick up user site-packages if not yet on path
            if site.getusersitepackages() not in sys.path:
                sys.path.insert(0, site.getusersitepackages())
            for module in REQUIRED_PACKAGES:
                try:
                    importlib.import_module(module)
                except ImportError:
                    pass   # will be caught when actually used
            if iface:
                iface.messageBar().pushMessage(
                    "Corridor Video Maker",
                    "Dependencies installed successfully. Ready to use!",
                    level=Qgis.Success,
                    duration=5,
                )
            return True
        else:
            err = result.stderr[-800:] if result.stderr else "unknown error"
            QMessageBox.critical(
                None,
                "Corridor Video Maker – Install Failed",
                f"Could not install {', '.join(missing)}.\n\n"
                f"Run install_deps.bat from the plugin folder as administrator.\n\n"
                f"Details:\n{err}",
            )
            return False

    except Exception as exc:
        if iface:
            iface.messageBar().clearWidgets()
        QMessageBox.critical(
            None,
            "Corridor Video Maker – Install Error",
            f"Auto-install failed: {exc}\n\n"
            f"Run install_deps.bat from the plugin folder.",
        )
        return False


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
