"""
court_geom.py — half-court coordinate model + raster court image (engine-safe).

The single source of truth for the shot-location coordinate system that replaces
the 5-zone model. Coordinates are in FEET with the hoop at the origin (0,0), +x
to the right, +y out toward half-court — the same frame helpers/court.py already
draws in, so old zone charts and new x/y maps line up.

This module is Streamlit-FREE (math + an optional matplotlib raster), so the
engine (helpers/stats.py) and the Game Tracker can both import it. matplotlib /
Pillow are imported lazily inside court_image() only, so importing this module
stays cheap.

Migration note: every new tap stores shot_x/shot_y AND a `zone` derived from it
via zone_from_xy(), so all existing zone-based analytics keep working untouched —
x/y is a strict superset of the zone.
"""
from __future__ import annotations

import math

# ── court extent (feet), hoop at origin ─────────────────────────────────────────
X_MIN, X_MAX = -25.0, 25.0      # sidelines (50 ft wide)
Y_MIN, Y_MAX = -1.0, 38.0       # baseline → deep past the arc (~13 ft of room beyond the top of the key for deep shots)
HOOP_Y = 5.25                   # rim centre, 5 ft 3 in from the baseline (real)
THREE_R = 19.75                 # NFHS high-school 3-pt arc — 19 ft 9 in (top of arc)
CORNER_X = 19.0                 # corner-3 straight segment, parallel to the sideline
CBREAK = math.sqrt(max(0.0, THREE_R ** 2 - CORNER_X ** 2))  # rise hoop→arc/corner join (~5.39 ft)
LANE_HW, LANE_D = 6.0, 19.0     # paint: 12 ft wide × 19 ft (baseline → FT line)
FT_R, RA_R = 6.0, 4.0           # free-throw circle (6 ft r), restricted area (4 ft r)

ZONES = ("LC", "LW", "C", "RW", "RC")


# ── derived shot attributes ─────────────────────────────────────────────────────
def shot_distance(x, y):
    """Straight-line distance from the hoop (at (0, HOOP_Y)), in feet."""
    return math.hypot(x, y - HOOP_Y)


def is_three(x, y):
    """True beyond the 3-pt line: the straight corner segments (|x| >= CORNER_X up
    to where they meet the arc) or the arc itself (>= THREE_R from the hoop)."""
    if abs(x) >= CORNER_X and (y - HOOP_Y) <= CBREAK:
        return True
    return shot_distance(x, y) >= THREE_R


def is_corner_three(x, y):
    """A corner 3 — beyond the line via the straight corner segment (not the arc).
    The shortest, highest-value 3 and the signature floor-spacing shot."""
    return abs(x) >= CORNER_X and (y - HOOP_Y) <= CBREAK


def shot_value(x, y):
    """Point value of a make from this spot: 3 beyond the arc, else 2."""
    return 3 if is_three(x, y) else 2


def in_paint(x, y):
    """True inside the painted lane (12 ft wide × baseline→FT line). Anything in
    here is zone 'C' regardless of angle — the lane is too narrow for the angular
    sectors to mean anything, so a wing/corner reading there is just noise."""
    return abs(x) <= LANE_HW and y <= LANE_D


# 5 angular sectors fanning out from the hoop, baseline-left → baseline-right.
_ZONE_BOUNDS = [(-90.0, -54.0, "LC"), (-54.0, -18.0, "LW"), (-18.0, 18.0, "C"),
                (18.0, 54.0, "RW"), (54.0, 90.0, "RC")]


def zone_from_xy(x, y):
    """Collapse a coordinate into one of the 5 legacy zones (LC/LW/C/RW/RC).

    Anything inside the paint is always 'C' (see in_paint). Outside the paint,
    bearing is measured from straight-ahead (toward half-court): 0° = center/top,
    negative = left, positive = right. Behind the baseline maps to the near
    corner by sign. This is what keeps every zone-based stat working on new data.
    """
    if in_paint(x, y):
        return "C"
    deg = math.degrees(math.atan2(x, max(y - HOOP_Y, 1e-4)))
    deg = max(-90.0, min(90.0, deg))
    for lo, hi, z in _ZONE_BOUNDS:
        if lo <= deg < hi:
            return z
    return "RC" if deg >= 0 else "LC"     # deg == 90 edge


# ── pixel ↔ feet (image origin top-left, y grows downward) ───────────────────────
def feet_from_px(px, py, w, h):
    """Map a pixel tapped on a w×h court image to (x, y) feet."""
    x = X_MIN + (px / w) * (X_MAX - X_MIN)
    y = Y_MAX - (py / h) * (Y_MAX - Y_MIN)
    return x, y


def px_from_feet(x, y, w, h):
    """Map (x, y) feet to a pixel on a w×h court image."""
    px = (x - X_MIN) / (X_MAX - X_MIN) * w
    py = (Y_MAX - y) / (Y_MAX - Y_MIN) * h
    return px, py


def image_height(width):
    """Pixel height for a court image of the given pixel width (keeps feet aspect)."""
    return int(round(width * (Y_MAX - Y_MIN) / (X_MAX - X_MIN)))


# ── zone → representative location (bridge for legacy zone-only shots) ───────────
# Lets historical shots that have only a `zone` appear on the new x/y maps, placed
# at the zone's centroid (flagged approximate), until real tap data replaces them.
ZONE_CENTROIDS = {
    ("C", 2): (0.0, 16.0),   ("C", 3): (0.0, 26.0),
    ("LC", 2): (-13.0, 8.0), ("LC", 3): (-19.0, 4.0),
    ("LW", 2): (-12.0, 17.0),("LW", 3): (-17.0, 21.0),
    ("RW", 2): (12.0, 17.0), ("RW", 3): (17.0, 21.0),
    ("RC", 2): (13.0, 8.0),  ("RC", 3): (19.0, 4.0),
}


def zone_centroid(zone, value):
    """Representative (x, y) for a (zone, 2|3) pair, or None if unknown."""
    return ZONE_CENTROIDS.get((zone, 3 if value == 3 else 2))


# ── raster half-court (matplotlib → PIL), for tap capture ───────────────────────
def court_image(width=500):
    """Render the half-court as a PIL RGB image exactly width × image_height(width)
    px, court filling the frame edge-to-edge so feet_from_px() is exact. matplotlib
    + Pillow are imported here so module import stays light."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Arc, Circle, Rectangle
    from PIL import Image

    h = image_height(width)
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])               # full-bleed: data fills the frame
    ax.set_xlim(X_MIN, X_MAX)
    ax.set_ylim(Y_MIN, Y_MAX)
    ax.axis("off")
    bg = "#12141e"
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    LINE, lw, GOLD = "#9aa0aa", 1.5, "#e6be64"
    ax.plot([X_MIN, X_MAX], [0, 0], color=LINE, lw=lw)            # baseline
    ax.plot([X_MIN, X_MIN], [0, Y_MAX], color=LINE, lw=lw)        # sidelines
    ax.plot([X_MAX, X_MAX], [0, Y_MAX], color=LINE, lw=lw)
    ax.plot([X_MIN, X_MAX], [Y_MAX, Y_MAX], color=LINE, lw=lw)    # half-court line
    ax.add_patch(Rectangle((-LANE_HW, 0), 2 * LANE_HW, LANE_D, fill=False,
                           edgecolor=LINE, lw=lw))                # paint
    ax.add_patch(Arc((0, LANE_D), 2 * FT_R, 2 * FT_R, theta1=0, theta2=360,
                     edgecolor=LINE, lw=lw))                      # FT circle
    ax.add_patch(Arc((0, HOOP_Y), 2 * RA_R, 2 * RA_R, theta1=0, theta2=180,
                     edgecolor=LINE, lw=1))                       # restricted area
    ax.plot([-3, 3], [HOOP_Y - 1.25, HOOP_Y - 1.25], color=GOLD, lw=2.4)  # backboard
    ax.add_patch(Circle((0, HOOP_Y), 0.75, fill=False, edgecolor=GOLD, lw=2))  # rim
    yj = HOOP_Y + CBREAK                                          # corner/arc join
    ax.plot([-CORNER_X, -CORNER_X], [0, yj], color=LINE, lw=lw)   # corner-3 straights
    ax.plot([CORNER_X, CORNER_X], [0, yj], color=LINE, lw=lw)
    tj = math.degrees(math.atan2(CBREAK, CORNER_X))
    ax.add_patch(Arc((0, HOOP_Y), 2 * THREE_R, 2 * THREE_R, theta1=tj,
                     theta2=180 - tj, edgecolor=LINE, lw=lw))     # 3-pt arc

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=bg)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if img.size != (width, h):       # force exact dims so feet_from_px stays 1:1
        img = img.resize((width, h))
    return img


def court_image_with_marker(x, y, base=None, width=500, color="#f0a500"):
    """Court image with a dot drawn at (x, y) feet — the just-tapped spot."""
    from PIL import ImageDraw
    img = base.copy() if base is not None else court_image(width)
    w, h = img.size
    px, py = px_from_feet(x, y, w, h)
    d = ImageDraw.Draw(img)
    r = 8
    d.ellipse([px - r, py - r, px + r, py + r], outline="#ffffff", width=2, fill=color)
    return img
