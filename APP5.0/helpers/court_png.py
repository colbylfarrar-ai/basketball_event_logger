"""
court_png.py — base64-PNG half-court for the printable scout sheet.

Why PNG, not inline SVG: the print sheet must render identically in the browser
(Print → PDF), the in-app preview, AND both PDF engines. WeasyPrint draws SVG but
the pure-pip xhtml2pdf fallback ([[pdf_export]]) does not — it only rasterises
<img> PNG/JPEG. So the scout charts ship as base64-PNG <img> tags: the same
picture everywhere, so a downloaded PDF carries the same information as the sheet.

A light-theme half-court is rendered once per width via matplotlib (lru_cached —
the only costly step), then shots are overlaid with PIL per call (cheap), mirroring
court_geom.court_image / court_image_with_marker. Light lines on white print
ink-friendly. Streamlit-free.
"""
from __future__ import annotations

import base64
import io
import math
from functools import lru_cache

import helpers.court_geom as CG


@lru_cache(maxsize=8)
def _light_court(width=340):
    """White-background, dark-line half-court as a PIL image (width × aspect).
    Cached per width — matplotlib is the only expensive step, so every chart at a
    given width reuses one render and just overlays dots."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Arc, Circle, Rectangle
    from PIL import Image

    h = CG.image_height(width)
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(CG.X_MIN, CG.X_MAX)
    ax.set_ylim(CG.Y_MIN, CG.Y_MAX)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    LINE, lw, RIM = "#444444", 1.3, "#b8860b"
    ax.plot([CG.X_MIN, CG.X_MAX], [0, 0], color=LINE, lw=lw)              # baseline
    ax.plot([CG.X_MIN, CG.X_MIN], [0, CG.Y_MAX], color=LINE, lw=lw)       # sidelines
    ax.plot([CG.X_MAX, CG.X_MAX], [0, CG.Y_MAX], color=LINE, lw=lw)
    ax.plot([CG.X_MIN, CG.X_MAX], [CG.Y_MAX, CG.Y_MAX], color=LINE, lw=lw)  # half-court
    ax.add_patch(Rectangle((-CG.LANE_HW, 0), 2 * CG.LANE_HW, CG.LANE_D,
                           fill=False, edgecolor=LINE, lw=lw))            # paint
    ax.add_patch(Arc((0, CG.LANE_D), 2 * CG.FT_R, 2 * CG.FT_R, theta1=0,
                     theta2=360, edgecolor=LINE, lw=lw))                  # FT circle
    ax.add_patch(Arc((0, CG.HOOP_Y), 2 * CG.RA_R, 2 * CG.RA_R, theta1=0,
                     theta2=180, edgecolor=LINE, lw=1))                   # restricted
    ax.plot([-3, 3], [CG.HOOP_Y - 1.25, CG.HOOP_Y - 1.25], color=RIM, lw=2.2)  # backboard
    ax.add_patch(Circle((0, CG.HOOP_Y), 0.75, fill=False, edgecolor=RIM, lw=1.6))  # rim
    yj = CG.HOOP_Y + CG.CBREAK
    ax.plot([-CG.CORNER_X, -CG.CORNER_X], [0, yj], color=LINE, lw=lw)     # corner-3s
    ax.plot([CG.CORNER_X, CG.CORNER_X], [0, yj], color=LINE, lw=lw)
    tj = math.degrees(math.atan2(CG.CBREAK, CG.CORNER_X))
    ax.add_patch(Arc((0, CG.HOOP_Y), 2 * CG.THREE_R, 2 * CG.THREE_R,
                     theta1=tj, theta2=180 - tj, edgecolor=LINE, lw=lw))  # 3-pt arc

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if img.size != (width, h):
        img = img.resize((width, h))
    return img


def _img_tag(img, width, h):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b = base64.b64encode(buf.getvalue()).decode("ascii")
    return (f"<img class='court-img' width='{width}' height='{h}' "
            f"src='data:image/png;base64,{b}'/>")


@lru_cache(maxsize=8)
def blank_halfcourt_png(width=160):
    """A blank light half-court as a base64-PNG <img> tag (for hand-drawn plays).
    Cached per width — the blank courts are identical every render."""
    h = CG.image_height(width)
    return _img_tag(_light_court(width), width, h)


def shot_chart_png(shots, width=340, dot_r=None):
    """Light half-court with green-dot makes / red-× misses overlaid via PIL, as a
    base64-PNG <img> tag. `shots` = helpers.stats.located_shots() dicts (x, y feet,
    `make` bool). Misses first so makes paint on top."""
    from PIL import ImageDraw
    img = _light_court(width).copy()
    w, h = img.size
    d = ImageDraw.Draw(img)
    r = dot_r if dot_r else max(3, int(round(w * 0.019)))
    for s in shots:
        if s.get("make"):
            continue
        px, py = CG.px_from_feet(s["x"], s["y"], w, h)
        d.line([px - r, py - r, px + r, py + r], fill="#cf222e", width=2)
        d.line([px - r, py + r, px + r, py - r], fill="#cf222e", width=2)
    for s in shots:
        if not s.get("make"):
            continue
        px, py = CG.px_from_feet(s["x"], s["y"], w, h)
        d.ellipse([px - r, py - r, px + r, py + r], fill="#1a7f37")
    return _img_tag(img, w, h)
