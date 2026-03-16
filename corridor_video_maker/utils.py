# -*- coding: utf-8 -*-
"""
Geometry utility functions for Corridor Video Maker.

Key functions
-------------
interpolate_corridor_points()
    Walk along a QgsGeometry polyline at a fixed step and return a list of
    (x, y, bearing_degrees) tuples. Bearing is measured clockwise from North
    and represents the travel direction at that sample.

get_line_endpoints()
    Return the two QgsPointXY endpoints of a polyline geometry so that the
    user can click the nearest one to choose the start direction.
"""

import math
import numpy as np
from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_line_endpoints(geom: QgsGeometry):
    """
    Return (first_point, last_point) as QgsPointXY for a line geometry.
    Works for single-part and multi-part linestrings.
    """
    verts = list(geom.vertices())
    if len(verts) < 2:
        return None, None
    return QgsPointXY(verts[0].x(), verts[0].y()), \
           QgsPointXY(verts[-1].x(), verts[-1].y())


def interpolate_corridor_points(geom: QgsGeometry,
                                step_m: float,
                                reverse: bool = False,
                                layer_crs=None,
                                smooth_window: int = 40):
    """
    Interpolate evenly-spaced sample points along *geom* (a line geometry).

    Parameters
    ----------
    geom          : QgsGeometry  – the centerline (any CRS)
    step_m        : float        – distance between samples in map units.
    reverse       : bool         – if True, walk from last vertex to first.
    layer_crs     : QgsCoordinateReferenceSystem or None
    smooth_window : int          – Gaussian smoothing window (frames).
                                   Larger = smoother turns but more lag.
                                   0 or 1 = no smoothing.

    Returns
    -------
    list of (x, y, bearing) tuples
        x, y    – coordinates in the layer CRS
        bearing – travel direction at that sample, degrees clockwise from North
    """
    if reverse:
        geom = _reverse_geometry(geom)

    total_length = geom.length()
    if total_length == 0 or step_m <= 0:
        return []

    xs, ys, bearings = [], [], []
    d = 0.0

    while d <= total_length:
        pt = geom.interpolate(d).asPoint()
        bearing = _bearing_at_distance(geom, d, step_m, total_length)
        xs.append(pt.x())
        ys.append(pt.y())
        bearings.append(bearing)
        d += step_m

    # Always include the exact end point
    last_pt = geom.interpolate(total_length).asPoint()
    xs.append(last_pt.x())
    ys.append(last_pt.y())
    bearings.append(bearings[-1] if bearings else 0.0)

    # ── Smooth bearings so turns rotate gradually over many frames ────
    if smooth_window > 1 and len(bearings) > 1:
        bearings = _smooth_bearings_circular(bearings, smooth_window)

    return list(zip(xs, ys, bearings))


def project_step_to_map_units(step_m: float, layer_crs) -> float:
    """
    Convert a distance in *metres* to the layer's map units.
    For projected CRS (metres) this is 1:1.
    For geographic CRS (degrees) we use a rough equatorial approximation
    (good enough for corridor mapping; use a proper geodesic calculation
    for very long lines near the poles).
    """
    if layer_crs is None:
        return step_m  # assume metres

    from qgis.core import QgsUnitTypes
    unit = layer_crs.mapUnits()
    if unit == QgsUnitTypes.DistanceDegrees:
        # ~111,320 metres per degree (equatorial)
        return step_m / 111_320.0
    elif unit == QgsUnitTypes.DistanceFeet:
        return step_m * 3.28084
    elif unit == QgsUnitTypes.DistanceYards:
        return step_m * 1.09361
    else:
        return step_m  # metres (most projected CRS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _smooth_bearings_circular(bearings: list, window: int) -> list:
    """
    Apply a Gaussian-weighted circular moving average to *bearings*.

    Handles the 0°/360° wrap-around correctly using unit-vector averaging
    (sum of sin/cos components), so a turn from 350° → 10° smooths through
    360° rather than jumping back through 180°.

    Parameters
    ----------
    bearings : list of float  – raw bearings, degrees clockwise from North
    window   : int            – total Gaussian window width in samples

    Returns
    -------
    list of float – smoothed bearings
    """
    n = len(bearings)
    if n <= 1 or window <= 1:
        return bearings

    arr = np.array(bearings, dtype=np.float64)
    half = window // 2
    sigma = window / 4.0          # 1 sigma = quarter of the window

    # Build normalised Gaussian kernel
    x = np.arange(-half, half + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()

    # Convert to unit vectors on the circle
    rads = np.radians(arr)
    sin_v = np.sin(rads)          # shape: (n,)
    cos_v = np.cos(rads)

    # Convolve each component separately (reflect padding avoids edge jumps)
    sin_smooth = np.convolve(sin_v, kernel, mode='same')
    cos_smooth = np.convolve(cos_v, kernel, mode='same')

    # Reconstruct angle and normalise to [0, 360)
    smoothed = np.degrees(np.arctan2(sin_smooth, cos_smooth)) % 360.0
    return smoothed.tolist()


def _bearing_at_distance(geom: QgsGeometry, d: float,
                         step: float, total_length: float) -> float:
    """
    Compute the travel bearing (degrees clockwise from North) at distance *d*
    along *geom* by using a short look-ahead segment.
    """
    look = max(step * 0.05, min(step * 0.5, 5.0))  # small look-ahead
    d2 = min(d + look, total_length)
    d1 = max(d2 - look, 0.0)

    p1 = geom.interpolate(d1).asPoint()
    p2 = geom.interpolate(d2).asPoint()

    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()

    if dx == 0 and dy == 0:
        return 0.0

    # atan2 gives angle from East, ccw → convert to bearing (clockwise from N)
    angle_rad = math.atan2(dx, dy)
    bearing = math.degrees(angle_rad)
    if bearing < 0:
        bearing += 360.0
    return bearing


def _reverse_geometry(geom: QgsGeometry) -> QgsGeometry:
    """Return a new geometry with vertex order reversed."""
    verts = list(geom.vertices())
    if not verts:
        return geom
    from qgis.core import QgsLineString
    xs = [v.x() for v in reversed(verts)]
    ys = [v.y() for v in reversed(verts)]
    return QgsGeometry(QgsLineString(xs, ys))


def nearest_endpoint(click_point: QgsPointXY, geom: QgsGeometry):
    """
    Return 'first' or 'last' indicating which endpoint of *geom*
    is closer to *click_point*.
    """
    first, last = get_line_endpoints(geom)
    if first is None:
        return 'first'
    d_first = click_point.distance(first)
    d_last = click_point.distance(last)
    return 'first' if d_first <= d_last else 'last'
