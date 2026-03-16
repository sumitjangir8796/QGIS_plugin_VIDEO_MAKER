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

# numpy is already bundled inside QGIS – only cv2 may be missing.
REQUIRED_PACKAGES = {
    "cv2": "opencv-python",
}


def _ensure_dependencies(iface):
    """
    Check for cv2; install it if missing using the same Python that QGIS runs.
    Uses --user so no admin rights are needed.
    numpy is intentionally NOT installed here – QGIS ships its own numpy.
    """
    missing = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return True

    if iface:
        try:
            from qgis.core import Qgis
            iface.messageBar().pushMessage(
                "Corridor Video Maker",
                f"Installing required packages: {', '.join(missing)} – please wait …",
                level=Qgis.Info,
                duration=0,
            )
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

    import sys
    import subprocess
    import tempfile
    python_exe = sys.executable
    tmp_dir = tempfile.gettempdir()
    try:
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "--user",
             "--cache-dir", tmp_dir,
             "--no-warn-script-location"] + missing,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmp_dir,          # keep pip's build artefacts away from Documents
        )
        if iface:
            try:
                iface.messageBar().clearWidgets()
            except Exception:
                pass

        if result.returncode == 0:
            import site
            if site.getusersitepackages() not in sys.path:
                sys.path.insert(0, site.getusersitepackages())
            if iface:
                try:
                    from qgis.core import Qgis
                    iface.messageBar().pushMessage(
                        "Corridor Video Maker",
                        "opencv-python installed. Ready to use!",
                        level=Qgis.Success,
                        duration=5,
                    )
                except Exception:
                    pass
            return True
        else:
            from qgis.PyQt.QtWidgets import QMessageBox
            err = result.stderr[-600:] if result.stderr else "unknown error"
            QMessageBox.critical(
                None,
                "Corridor Video Maker – Install Failed",
                f"Could not auto-install opencv-python.\n\n"
                f"Run install_deps.bat from the plugin folder.\n\n{err}",
            )
            return False

    except Exception as exc:
        if iface:
            try:
                iface.messageBar().clearWidgets()
            except Exception:
                pass
        try:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "Corridor Video Maker – Install Error",
                f"Auto-install failed: {exc}\n\nRun install_deps.bat."
            )
        except Exception:
            pass
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
