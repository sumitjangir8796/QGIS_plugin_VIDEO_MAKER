# -*- coding: utf-8 -*-
"""
Corridor Video Maker – QGIS Plugin
Generates a fly-through video along a polyline centerline.
The map canvas pans + rotates frame-by-frame so the travel
direction always points straight up in the output video.
"""


def classFactory(iface):
    """Required QGIS entry point."""
    from .corridor_video_maker import CorridorVideoMakerPlugin
    return CorridorVideoMakerPlugin(iface)
