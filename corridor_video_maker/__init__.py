# -*- coding: utf-8 -*-
"""
Corridor Video Maker – QGIS Plugin
Generates a fly-through video along a polyline centerline.
The map canvas pans + rotates frame-by-frame so the travel
direction always points straight up in the output video.
"""

import sys
import importlib

# Force all sub-modules to reload every time this package is (re)loaded.
# This ensures Plugin Reloader in QGIS always picks up the latest code.
_SUBMODULES = [
    "corridor_video_maker.utils",
    "corridor_video_maker.map_tools",
    "corridor_video_maker.video_exporter",
    "corridor_video_maker.corridor_video_maker_dialog",
    "corridor_video_maker.corridor_video_maker",
]
for _mod in _SUBMODULES:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])


def classFactory(iface):
    """Required QGIS entry point."""
    from .corridor_video_maker import CorridorVideoMakerPlugin
    return CorridorVideoMakerPlugin(iface)
