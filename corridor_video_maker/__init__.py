# -*- coding: utf-8 -*-
"""
Corridor Video Maker – QGIS Plugin
Generates a fly-through video along a polyline centerline.
"""


def classFactory(iface):
    """Required QGIS entry point."""
    from .corridor_video_maker import CorridorVideoMakerPlugin
    return CorridorVideoMakerPlugin(iface)
