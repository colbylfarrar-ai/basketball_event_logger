"""
Smoke test for helpers/pdf_export.py + the table-based print HTML builders.
No DB needed. Run: python tracker/test_pdf_export.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.matchup_sheet as MS                 # noqa: E402
from helpers.pdf_export import html_to_pdf        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


pred = {
    "a_name": "Home & Co", "b_name": "Away HS", "team_a": 1, "team_b": 2,
    "favorite": 1, "pf_a": 54.2, "pf_b": 48.9, "total": 103.1, "spread": 5.3,
    "win_prob_a": 0.68, "win_prob_b": 0.32, "confidence": "Solid",
    "components": [{"label": "Adjusted-net edge", "value": 4.0,
                    "note": "rating gap <raw>"},
                   {"label": "Home court", "value": 3.0, "note": "+3.0"}],
    "tracked": {"pace": 62.0, "pf_a": 55.0, "pf_b": 49.0,
                "ortg_a": 88.0, "ortg_b": 79.0},
}
sim = {"win_a": 0.67, "mean_margin": 5.1, "p05": -8.0, "p95": 18.0}

html_doc = MS.matchup_html(pred, sim=sim, n_sims=20000,
                           home_label="Home court: Home & Co",
                           generated="June 12, 2026")
ok("&amp;" in html_doc and "&lt;raw&gt;" in html_doc, "names + notes escaped")
ok("display: flex" not in html_doc and "display:flex" not in html_doc,
   "matchup sheet is flex-free (xhtml2pdf-safe)")

pdf = html_to_pdf(html_doc)
ok(pdf is not None, "a PDF engine is available")
ok(pdf[:4] == b"%PDF", "matchup sheet renders to a real PDF")
ok(len(pdf) > 1000, f"PDF is non-trivial ({len(pdf)} bytes)")

# The other two builders must be flex-free too (their data needs a DB, so just
# inspect the templates).
scout_src = Path("helpers/scout.py").read_text(encoding="utf-8")
reports_src = Path("helpers/reports.py").read_text(encoding="utf-8")
for name, src in (("scout.py", scout_src), ("reports.py", reports_src)):
    ok("display:flex" not in src and "display: flex" not in src,
       f"{name} template is flex-free (xhtml2pdf-safe)")

print(f"\nALL {PASS} CHECKS PASSED")
