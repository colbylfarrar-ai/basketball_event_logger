"""
printouts.py — shared chrome for the print-to-PDF hand-outs.

Single source of the HoopTracks print look so the scout sheet
([[helpers.scout.printable_html]]), the matchup one-pager
([[helpers.matchup_sheet]]) and the player-card / game-recap reports
([[helpers.reports]]) never drift: the rule-and-type masthead, the outlined KPI
tile strips, the `h2` rule, the hairline tables, the page size and the footer
all live here. The look is deliberately INK-LIGHT — see BASE_CSS for what is
absent and why. Zero-dependency HTML/CSS strings a page hands to
st.download_button; the
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
# print sheet never depends on the asset file being on the server). Drawn as
# OUTLINE, in ink: the solid gold disc behind the ball was the only filled area
# in the whole mark and it printed as a grey blob on a mono laser. The
# "HoopTracks" wordmark beside it always renders even where SVG is dropped (the
# pure-pip xhtml2pdf engine), so the brand survives every print path.
BRAND_MARK = (
    "<svg width='15' height='15' viewBox='0 0 64 64' style='vertical-align:-2px'>"
    "<path d='M12 46 L23 35 L31 43 L41 38' fill='none' stroke='#111' "
    "stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/>"
    "<circle cx='12' cy='46' r='2.9' fill='none' stroke='#111' stroke-width='1.7'/>"
    "<circle cx='23' cy='35' r='2.9' fill='none' stroke='#111' stroke-width='1.7'/>"
    "<circle cx='31' cy='43' r='2.9' fill='none' stroke='#111' stroke-width='1.7'/>"
    "<circle cx='46' cy='35' r='12' fill='none' stroke='#111' stroke-width='1.8'/>"
    "<path d='M46 23 L46 47 M34 35 L58 35' stroke='#111' stroke-width='1.4' "
    "stroke-linecap='round'/>"
    "<path d='M40 24 C45 30 45 40 40 46' fill='none' stroke='#111' stroke-width='1.2'/>"
    "<path d='M52 24 C47 30 47 40 52 46' fill='none' stroke='#111' stroke-width='1.2'/>"
    "</svg>")

# ── Shared base look: INK-LIGHT, greyscale, line-art ─────────────────────────
# These documents are printed, usually on a school printer a coach pays for out
# of their own budget, often a dozen copies for a staff. So the look is line
# work: rules, outlines and type. Specifically NOT here, on purpose:
#
#   * no full-bleed header block. The masthead used to be a dark gradient with a
#     5px gold rule across the full page width — the single most expensive
#     object in any of these documents, repeated on every one of them, and it
#     carried no information a hairline and bold type do not.
#   * no zebra striping. It filled every other row of every table on the sheet
#     to separate rows that a hairline separates for a fraction of the ink.
#   * no filled tiles, badges or cards — outlines say the same thing.
#   * no colour as a CARRIER of meaning. Green/red is invisible on a mono laser
#     and roughly invisible to a red-green colourblind reader on a colour one,
#     so good/bad is carried by a ▲ / ▼ marker and by the words. Colour that
#     survives is incidental, and there is almost none left.
#
# `print-color-adjust:exact` stays: what little is left (the percentile bar
# fill, the court images) is information, and a browser that drops it would be
# dropping data rather than saving ink.
#
# Kept table-based / flexbox-free so the xhtml2pdf fallback renders it.
BASE_CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
/* Every hand-out states its page. Only the scout sheet used to, so the other
   four assumed portrait without choosing it and ran a 920px (9.6in) wrap
   against 7.7in of printable width — shrink-to-fit on every print, with the
   overflow coming out of the content. A caller that wants landscape overrides
   both in its own extra_css. */
@page{size:Letter portrait;margin:.4in}
body{font-family:'Segoe UI',-apple-system,Arial,sans-serif;color:#111;margin:0;
  font-size:13px;line-height:1.45;background:#fff}
.wrap{max-width:7.7in;margin:0 auto;padding:0 20px 24px}
/* The masthead: type and two rules, no block of ink. */
.band{background:#fff;color:#111;padding:12px 20px 8px;
  border-bottom:2px solid #111;margin-bottom:12px}
.band .mark{font-size:9.5px;letter-spacing:3px;text-transform:uppercase;
  color:#444;font-weight:700}
.band h1{margin:3px 0 1px;font-size:23px;letter-spacing:-.2px}
.band .meta{color:#444;font-size:12px}
.chips{margin-top:7px}
.chip{display:inline-block;border:1px solid #999;border-radius:999px;
  padding:2px 9px;margin:2px 5px 0 0;font-size:11px;color:#333}
.chip b{color:#111}
h2{font-size:12px;text-transform:uppercase;letter-spacing:1.4px;color:#111;
  border-left:3px solid #111;padding-left:8px;margin:15px 0 7px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{text-align:left;font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;
  color:#333;border-bottom:1.5px solid #111;padding:5px 8px}
td{padding:4px 8px;border-bottom:1px solid #ccc}
.num,.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.kpis{width:100%;border-collapse:separate;border-spacing:5px 0;margin:6px 0 4px}
td.kpi{border:1px solid #999;border-radius:7px;padding:7px 6px;text-align:center}
.kpi .v{font-size:19px;font-weight:800;color:#111;font-variant-numeric:tabular-nums}
.kpi .l{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;color:#444}
.bdg{display:inline-block;font-size:10px;font-weight:700;color:#111;
  border:1px solid #666;border-radius:4px;padding:1px 6px;margin:2px 4px 0 0}
/* Good / bad without colour: the marker IS the encoding. */
.up:before{content:"\\25B2 "}
.down:before{content:"\\25BC "}
.foot{margin-top:18px;padding-top:8px;border-top:1px solid #ccc;color:#555;
  font-size:10.5px}
@media print{.break{page-break-before:always}}
.court-img,img.court-img{display:block;margin:8px auto;max-width:100%;height:auto;
  border:1px solid #ccc;border-radius:6px}
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
            f"<b>HoopTracks</b> · app.hooptracks.com"
            f"{(' · ' + today()) if today() else ''}</div></div></body></html>")


def band(kicker, h1, meta, chips_html=""):
    """The masthead: type over a rule, not a block of ink. ``kicker`` = the
    small caps line beside the
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
