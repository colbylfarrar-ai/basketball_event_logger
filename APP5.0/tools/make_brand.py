"""make_brand.py — generate the HoopTracks raster icons from the brand mark
(concept C: motion-tracking nodes sweeping into a basketball).

Single source for every PNG icon the product needs:
  assets/logo_mark.png          web favicon / Streamlit page_icon   (bg #0d1117)
  tracker/static/icon-180.png   iOS apple-touch-icon                (bg #12141e)
  tracker/static/icon-192.png   PWA manifest                        (bg #12141e)
  tracker/static/icon-512.png   PWA manifest / splash               (bg #12141e)

The SVG vector logos (assets/logo_mark.svg, assets/logo_wordmark.svg) are the
in-app source of truth — used directly by st.logo() and the login screen. These
PNGs exist only where a raster is required (browser-tab favicon, phone
home-screen icon). Re-run after any change to the mark geometry below:

    python tools/make_brand.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GOLD = "#f0a500"

# Mark geometry in a 64-unit box — keep in lock-step with assets/logo_mark.svg.
_PATH  = [(12, 46), (23, 35), (31, 43), (41, 38)]   # gold tracking polyline
_NODES = [(12, 46), (23, 35), (31, 43)]             # tracking-point markers
_BALL  = (46, 35, 12)                               # cx, cy, r


def draw_mark(size: int, bg: str, *, rounded: bool = True) -> Image.Image:
    """Render the tracked-path mark on a ``bg`` square of ``size`` px."""
    ss = 4                                  # supersample → smooth edges
    s = size * ss
    f = s / 64.0
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(0.22 * s), fill=bg)
    else:
        d.rectangle([0, 0, s, s], fill=bg)

    def P(p):
        return (p[0] * f, p[1] * f)

    # Tracking path first, so the basketball sits on top of where it ends.
    d.line([P(p) for p in _PATH], fill=GOLD, width=max(1, int(2.6 * f)),
           joint="curve")
    nr = 2.9 * f
    for n in _NODES:
        cx, cy = P(n)
        d.ellipse([cx - nr, cy - nr, cx + nr, cy + nr], fill=bg,
                  outline=GOLD, width=max(1, int(1.7 * f)))

    bx, by, br = _BALL[0] * f, _BALL[1] * f, _BALL[2] * f
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=GOLD)
    seam = max(1, int(1.8 * f))
    d.line([bx, by - br, bx, by + br], fill=bg, width=seam)        # vertical seam
    d.line([bx - br, by, bx + br, by], fill=bg, width=seam)        # horizontal seam
    sw = max(1, int(1.5 * f))
    d.arc([bx - 2.2 * br, by - br, bx - 0.2 * br, by + br], 270, 90, fill=bg, width=sw)
    d.arc([bx + 0.2 * br, by - br, bx + 2.2 * br, by + br], 90, 270, fill=bg, width=sw)

    return img.resize((size, size), Image.LANCZOS)


def write_all() -> None:
    (ROOT / "assets").mkdir(exist_ok=True)
    draw_mark(512, "#0d1117").save(ROOT / "assets" / "logo_mark.png")
    print("wrote assets/logo_mark.png")
    static = ROOT / "tracker" / "static"
    static.mkdir(parents=True, exist_ok=True)
    for sz in (180, 192, 512):
        draw_mark(sz, "#12141e").save(static / f"icon-{sz}.png")
        print(f"wrote tracker/static/icon-{sz}.png")


if __name__ == "__main__":
    write_all()
