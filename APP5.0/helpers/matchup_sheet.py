"""
matchup_sheet.py — downloadable matchup one-pager (HTML).

Built on the SHARED print chrome ([[helpers.printouts]]), like every other
hand-out. It used to hand-roll its own 720px stylesheet with no masthead, no
footer and its own gold brand bar, which is why it was the one printable that
did not look like the others — and why an ink or layout fix landed everywhere
except here. Contents come from the predictor + simulation outputs the War Room
matchup tab already shows. The artifact a coach texts to an AD or prints for the
locker room. Streamlit-free.
"""
from __future__ import annotations

import html as _html


def matchup_html(pred: dict, sim: dict | None = None, n_sims: int = 0,
                 home_label: str = "Neutral floor", generated: str = "") -> str:
    """Render the matchup sheet. ``pred`` = helpers/predictor.predict_game()
    output; ``sim`` = helpers/simulation.simulate_game() output (optional)."""
    import helpers.printouts as PO
    e = _html.escape
    a, b = e(pred["a_name"]), e(pred["b_name"])
    wa, wb = pred["win_prob_a"] * 100, pred["win_prob_b"] * 100
    fav = e(pred["a_name"] if pred["favorite"] == pred["team_a"]
            else pred["b_name"])

    comp_rows = "".join(
        f"<tr><td>{e(c['label'])}</td>"
        f"<td class='num'>{c['value']:+.1f}</td>"
        f"<td class='note'>{e(c['note'])}</td></tr>"
        for c in pred["components"])

    sim_block = ""
    if sim:
        sim_block = (
            f"<h2>Simulation — {n_sims:,} games</h2>"
            f"<p>{a} wins <b>{sim['win_a'] * 100:.0f}%</b> of simulations · "
            f"mean margin {sim['mean_margin']:+.1f} · 90% of outcomes land "
            f"between {sim['p05']:+.0f} and {sim['p95']:+.0f}.</p>")

    tracked_block = ""
    if pred.get("tracked"):
        tk = pred["tracked"]
        tracked_block = (
            "<h2>Possession projection</h2>"
            f"<p>Pace {tk['pace']:.0f} · {a} {tk['pf_a']:.0f} pts "
            f"(ORtg {tk['ortg_a']:.0f}) · {b} {tk['pf_b']:.0f} pts "
            f"(ORtg {tk['ortg_b']:.0f}).</p>")

    meta_line = e(home_label) + (f" · {e(generated)}" if generated else "")

    chips = (PO.chip("Spread", f"{fav} −{pred['spread']:.1f}")
             + PO.chip("Total", f"{pred['total']:.0f}")
             + PO.chip(e(pred["confidence"])))
    band = PO.band("Matchup Sheet", f"{a} vs {b}", meta_line, chips)

    score = (
        "<table class='score'><tr>"
        f"<td><div class='nm'>{a}</div>"
        f"<div class='pts'>{pred['pf_a']:.0f}</div>"
        f"<div class='wp'>{wa:.0f}% win</div></td>"
        f"<td class='mid'>projected<br>total {pred['total']:.0f}</td>"
        f"<td><div class='nm'>{b}</div>"
        f"<div class='pts'>{pred['pf_b']:.0f}</div>"
        f"<div class='wp'>{wb:.0f}% win</div></td>"
        "</tr></table>")

    # Only what the shared chrome does not already cover — the projected-score
    # block. Outlined, not filled: this used to be a solid panel behind two
    # 40px numbers, and the numbers are the thing, not the panel.
    css = """
/* Page size and wrap width come from the shared chrome — portrait Letter at
   .4in, 7.7in of printable width. Only this sheet's own block is below.
   Table, not flexbox — xhtml2pdf (the PDF engine) has no flex support. */
table.score{width:100%;border:1px solid #999;border-radius:9px;
  border-collapse:separate;margin:12px 0}
table.score td{border:none;padding:12px 20px;text-align:center;
  vertical-align:middle}
.score .nm{font-size:14px;font-weight:700}
.score .pts{font-size:38px;font-weight:900;line-height:1.1}
.score .wp{font-size:12px;color:#444}
.score .mid{color:#555;font-size:13px}
td.note{color:#444;font-size:12px}
p{font-size:13px;line-height:1.5}
"""
    body = (f"{band}<div class='wrap'>{score}"
            "<h2>Where the margin comes from</h2>"
            f"<table>{comp_rows}</table>"
            f"{sim_block}{tracked_block}"
            "<p class='note'>Opponent-adjusted ratings · home court as labelled "
            "in the header.</p></div>")
    return PO.doc(f"{a} vs {b} — matchup sheet", body, extra_css=css)
