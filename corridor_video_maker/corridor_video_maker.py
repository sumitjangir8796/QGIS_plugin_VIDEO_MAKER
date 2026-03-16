# -*- coding: utf-8 -*-
"""
Corridor Video Maker – main plugin class.
Registers the menu action and toolbar button.
"""

import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .corridor_video_maker_dialog import CorridorVideoMakerDialog


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
