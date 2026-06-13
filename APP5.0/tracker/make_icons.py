"""Generate the tracker PWA icons (simple basketball on the app's dark navy).
Run once: python tracker/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "static"
BG, BALL, SEAM = "#12141e", "#e6be64", "#12141e"


def make(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    m = size * 0.14                       # margin
    box = [m, m, size - m, size - m]
    d.ellipse(box, fill=BALL)
    w = max(2, int(size * 0.025))         # seam width
    cx = size / 2
    d.line([cx, m, cx, size - m], fill=SEAM, width=w)            # vertical seam
    d.line([m, cx, size - m, cx], fill=SEAM, width=w)            # horizontal seam
    r = (size - 2 * m) / 2
    d.arc([cx - 2.2 * r, m, cx - 0.2 * r, size - m], 270, 90, fill=SEAM, width=w)
    d.arc([cx + 0.2 * r, m, cx + 2.2 * r, size - m], 90, 270, fill=SEAM, width=w)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for s in (180, 192, 512):
        make(s).save(OUT / f"icon-{s}.png")
        print(f"wrote icon-{s}.png")
