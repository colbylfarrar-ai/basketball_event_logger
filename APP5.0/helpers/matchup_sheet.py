"""
matchup_sheet.py — downloadable matchup one-pager (HTML).

Same pattern as helpers/scout.py's printable_html: one self-contained HTML
string (inline CSS, print-ready) built from the predictor + simulation outputs
the War Room matchup tab already shows. The artifact a coach texts to an AD or
prints for the locker room. Streamlit-free.
"""
from __future__ import annotations

import html as _html


def matchup_html(pred: dict, sim: dict | None = None, n_sims: int = 0,
                 home_label: str = "Neutral floor", generated: str = "") -> str:
    """Render the matchup sheet. ``pred`` = helpers/predictor.predict_game()
    output; ``sim`` = helpers/simulation.simulate_game() output (optional)."""
    from helpers.scout import _BRAND_MARK   # baked HoopTracks mark (xhtml2pdf-safe)
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

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{a} vs {b} — matchup sheet</title>
<style>
  body {{ font-family: 'Segoe UI', -apple-system, Arial, sans-serif;
          color: #16191d; max-width: 720px; margin: 28px auto; padding: 0 18px; }}
  h1 {{ font-size: 22px; margin: 0 0 2px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
        color: #5a6470; border-bottom: 2px solid #e3e6ea;
        padding-bottom: 4px; margin: 22px 0 8px; }}
  .meta {{ color: #5a6470; font-size: 12px; margin-bottom: 18px; }}
  /* Table, not flexbox — xhtml2pdf (the PDF engine) has no flex support. */
  table.score {{ width: 100%; background: #f4f6f8; border-radius: 10px;
                 border-collapse: separate; margin: 14px 0; }}
  table.score td {{ border: none; padding: 14px 22px; text-align: center;
                    vertical-align: middle; }}
  .score .nm {{ font-size: 14px; font-weight: 700; }}
  .score .pts {{ font-size: 40px; font-weight: 900; line-height: 1.1; }}
  .score .wp {{ font-size: 12px; color: #5a6470; }}
  .score .mid {{ color: #8a94a0; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #edf0f3;
        vertical-align: top; }}
  td.num {{ text-align: right; font-weight: 700; white-space: nowrap; }}
  td.note {{ color: #5a6470; font-size: 12px; }}
  p {{ font-size: 13px; line-height: 1.5; }}
  .foot {{ margin-top: 26px; color: #8a94a0; font-size: 11px; }}
  .brandbar {{ font-weight: 800; font-size: 13px; color: #c8860a;
               letter-spacing: .3px; margin-bottom: 8px; }}
  @media print {{ body {{ margin: 8px auto; }} }}
</style></head>
<body>
  <div class="brandbar">{_BRAND_MARK} HoopTracks</div>
  <h1>{a} vs {b}</h1>
  <div class="meta">{meta_line}</div>

  <table class="score"><tr>
    <td><div class="nm">{a}</div>
      <div class="pts">{pred['pf_a']:.0f}</div>
      <div class="wp">{wa:.0f}% win</div></td>
    <td class="mid">projected<br>total {pred['total']:.0f}</td>
    <td><div class="nm">{b}</div>
      <div class="pts">{pred['pf_b']:.0f}</div>
      <div class="wp">{wb:.0f}% win</div></td>
  </tr></table>

  <p><b>{fav} −{pred['spread']:.1f}</b> · {e(pred['confidence'])}</p>

  <h2>Where the margin comes from</h2>
  <table>{comp_rows}</table>

  {sim_block}
  {tracked_block}

  <div class="foot">Opponent-adjusted ratings · home court as labelled above ·
  Made with <b style="color:#c8860a">HoopTracks</b> · app.hooptracks.com</div>
</body></html>"""
