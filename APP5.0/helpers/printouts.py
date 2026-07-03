"""
printouts.py — shared chrome for the print-to-PDF hand-outs.

Single source of the HoopTracks print look so the scout sheet
([[helpers.scout.printable_html]]) and the player-card / game-recap reports
([[helpers.reports]]) never drift: the gradient `.band` header, the KPI tile
strips, the gold-rule `h2`, the zebra tables and the branded footer all live
here. Zero-dependency HTML/CSS strings a page hands to st.download_button; the
same markup renders in the browser (Print → PDF), the in-app preview, and both
PDF engines (WeasyPrint + the pure-pip xhtml2pdf fallback — see
[[helpers.pdf_export]]). Streamlit-free.

A caller uses the shared base CSS, adds its own class block via ``extra_css`` on
``doc()``, builds a header with ``band()`` and KPI strips with ``kpis()``.
"""
from __future__ import annotations

import datetime
import html as _html

e = _html.escape

# Official HoopTracks mark (baked from assets/logo_mark.svg — self-contained so a
# print sheet never depends on the asset file being on the server). The gold
# "HoopTracks" wordmark beside it always renders even where SVG is dropped (the
# pure-pip xhtml2pdf engine), so the brand survives every print path.
BRAND_MARK = (
    "<svg width='15' height='15' viewBox='0 0 64 64' style='vertical-align:-2px'>"
    "<path d='M12 46 L23 35 L31 43 L41 38' fill='none' stroke='#f0a500' "
    "stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/>"
    "<circle cx='12' cy='46' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='23' cy='35' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='31' cy='43' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='46' cy='35' r='12' fill='#f0a500'/>"
    "<path d='M46 23 L46 47 M34 35 L58 35' stroke='#0d1117' stroke-width='1.8' "
    "stroke-linecap='round'/>"
    "<path d='M40 24 C45 30 45 40 40 46' fill='none' stroke='#0d1117' stroke-width='1.5'/>"
    "<path d='M52 24 C47 30 47 40 52 46' fill='none' stroke='#0d1117' stroke-width='1.5'/>"
    "</svg>")

# Shared base look — the polished player-card style (gradient band, gold-rule h2,
# KPI tiles, zebra tables). Callers append their own classes via doc(extra_css=).
# Kept table-based / flexbox-free so the xhtml2pdf fallback renders it.
BASE_CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:'Segoe UI',-apple-system,Arial,sans-serif;color:#16202c;margin:0;
  font-size:13px;line-height:1.45;background:#fff}
.wrap{max-width:920px;margin:0 auto;padding:0 26px 30px}
.band{background:linear-gradient(120deg,#0d1117 0%,#1b2433 60%,#243049 100%);
  color:#f0f6fc;padding:20px 26px;border-bottom:5px solid #f0a500;margin-bottom:16px}
.band .mark{font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#f0a500;font-weight:800}
.band h1{margin:4px 0 2px;font-size:25px}
.band .meta{color:#aeb9c7;font-size:12.5px}
.chips{margin-top:10px}
.chip{display:inline-block;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);
  border-radius:999px;padding:4px 11px;margin:3px 6px 0 0;font-size:11.5px;color:#dbe4ee}
.chip b{color:#fff}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1.4px;color:#0d1117;
  border-left:4px solid #f0a500;padding-left:9px;margin:18px 0 9px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{text-align:left;font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:#5b6675;
  border-bottom:2px solid #16202c;padding:6px 8px}
td{padding:5px 8px;border-bottom:1px solid #e7ebf0}
tr:nth-child(even) td{background:#f7f9fb}
.num,.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.kpis{width:100%;border-collapse:separate;border-spacing:5px 0;margin:6px 0 4px}
td.kpi{background:#f7f9fb;border:1px solid #e7ebf0;border-radius:9px;
  padding:9px 6px;text-align:center}
.kpi .v{font-size:20px;font-weight:800;color:#16202c;font-variant-numeric:tabular-nums}
.kpi .l{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;color:#5b6675}
.bdg{display:inline-block;font-size:10px;font-weight:700;color:#6b4e00;background:#fff3d6;
  border:1px solid #f0d692;border-radius:5px;padding:2px 7px;margin:3px 5px 0 0}
.foot{margin-top:20px;padding-top:10px;border-top:1px solid #e7ebf0;color:#8a94a2;font-size:11px}
@media print{.break{page-break-before:always}}
.court-img,img.court-img{display:block;margin:8px auto;max-width:100%;height:auto;
  border:1px solid #e7ebf0;border-radius:8px}
"""


def today():
    try:
        d = datetime.date.today()
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except Exception:
        return ""


def doc(title, body, extra_css=""):
    """Full HTML document: shared base CSS (+ any caller ``extra_css``), the
    caller's ``body`` (band + content), and the branded footer."""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{e(title)}</title><style>{BASE_CSS}{extra_css}</style></head>"
            f"<body>{body}"
            f"<div class='wrap'><div class='foot'>Made with "
            f"<b style='color:#f0a500'>HoopTracks</b> · app.hooptracks.com"
            f"{(' · ' + today()) if today() else ''}</div></div></body></html>")


def band(kicker, h1, meta, chips_html=""):
    """The gradient header banner. ``kicker`` = the small caps line beside the
    mark (e.g. 'Player Card', 'Scouting Report'); ``chips_html`` = optional
    pre-built ``chip`` spans."""
    chips = f"<div class='chips'>{chips_html}</div>" if chips_html else ""
    return (f"<div class='band'><div class='mark'>{BRAND_MARK} HoopTracks · "
            f"{e(kicker)}</div><h1>{h1}</h1>"
            f"<div class='meta'>{meta}</div>{chips}</div>")


def chip(label, value=None):
    """One header chip. ``chip('OVR', 78)`` → bold value + label; ``chip('Guard')``
    → a plain tag."""
    if value is None:
        return f"<span class='chip'>{e(str(label))}</span>"
    return f"<span class='chip'><b>{e(str(value))}</b> {e(str(label))}</span>"


def kpi(label, value):
    # A table cell, not a flex child — xhtml2pdf (the PDF engine) has no flexbox.
    return (f"<td class='kpi'><div class='v'>{value}</div>"
            f"<div class='l'>{e(str(label))}</div></td>")


def kpis(cells):
    """Wrap a run of ``kpi()`` cells into one tile row."""
    return f"<table class='kpis'><tr>{cells}</tr></table>"
