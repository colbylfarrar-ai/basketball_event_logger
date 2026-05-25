"""
ESPN / NBA.com-style HTML box score renderer.
Used by pages/3_Rankings.py (and optionally other pages) to display
a professional-looking player box score from the output of
helpers.stats_players.compute_game_box_score().
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Shared CSS ────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* ── Box score table ─────────────────────────────── */
.bx-table {
    width: 100%; border-collapse: collapse;
    font-size: 12.5px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.bx-table thead th {
    padding: 8px 11px; text-align: center;
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.8px; color: #8b949e;
    border-bottom: 2px solid #30363d; white-space: nowrap;
}
.bx-table thead th.bx-pl { text-align: left; min-width: 150px; }
.bx-table tbody td {
    padding: 8px 11px; text-align: center;
    color: #e6edf3; border-bottom: 1px solid #21262d; white-space: nowrap;
}
.bx-table tbody td.bx-pl {
    text-align: left; font-weight: 500;
}
.bx-table tbody tr:hover td { background: #161b22 !important; }
.bx-table tbody tr.bx-totals td {
    font-weight: 700; background: #0d1117 !important;
    border-top: 2px solid #30363d; border-bottom: none; color: #f0f6fc;
}
.bx-pts  { font-weight: 700 !important; font-size: 14px !important; }
.bx-pct  { color: #8b949e !important; font-size: 11px !important; }
/* ── Top-performer cards ──────────────────────────── */
.bx-perf-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 10px; margin-bottom: 14px;
}
.bx-perf-card {
    border-radius: 10px; padding: 12px 10px; text-align: center;
}
/* ── Linescore ────────────────────────────────────── */
.ls-table { width: 100%; border-collapse: collapse;
            font-size: 13px; color: #e6edf3;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.ls-table th {
    padding: 6px 14px; font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.8px;
    color: #8b949e; border-bottom: 1px solid #30363d; text-align: center;
}
.ls-table th.ls-team { text-align: left; min-width: 130px; }
.ls-table td { padding: 7px 14px; text-align: center;
               border-bottom: 1px solid #21262d; }
.ls-table td.ls-team { text-align: left; font-weight: 700; color: #f0f6fc; }
</style>
"""


# ── Utility helpers ───────────────────────────────────────────────────────────

def _pct(made: int, att: int) -> str:
    if att == 0:
        return "—"
    return f"{100 * made / att:.1f}"


def _pm_html(val) -> str:
    if val is None or not isinstance(val, (int, float)):
        return "<span style='color:#8b949e'>—</span>"
    color = "#2ecc71" if val > 0 else ("#e74c3c" if val < 0 else "#8b949e")
    sign  = "+" if val > 0 else ""
    return f"<span style='color:{color};font-weight:600'>{sign}{int(val)}</span>"


def _min_str(val) -> str:
    if isinstance(val, float):
        return f"{val:.1f}"
    return str(val) if val else "0.0"


# ── Sub-renderers ─────────────────────────────────────────────────────────────

def _top_performers_html(rows: list, accent: str, bg: str, border: str) -> str:
    """3 hero cards: top scorer · top rebounder · top passer."""
    players = [r for r in rows if not r.get("_totals")]
    if not players:
        return ""

    def _best(key):
        return max(players, key=lambda r: r.get(key, 0) or 0)

    scorer = _best("PTS")
    reb    = _best("REB")
    ast    = _best("AST")

    def _card(row, key, label, icon):
        v    = row.get(key, 0)
        name = row["Player"]
        return (
            f'<div class="bx-perf-card" style="background:{bg};border:1px solid {border}">'
            f'  <div style="font-size:10px;color:#8b949e;text-transform:uppercase;'
            f'letter-spacing:.8px">{icon} {label}</div>'
            f'  <div style="font-size:28px;font-weight:800;color:{accent};'
            f'margin:4px 0;line-height:1.1">{v}</div>'
            f'  <div style="font-size:12px;font-weight:600;color:#f0f6fc">{name}</div>'
            f'</div>'
        )

    cards = _card(scorer, "PTS", "Points", "🏀") \
          + _card(reb,    "REB", "Rebounds", "📊") \
          + _card(ast,    "AST", "Assists", "🎯")
    return f'<div class="bx-perf-grid">{cards}</div>'


def _trad_html(rows: list, accent: str, bg: str, border: str) -> str:
    """Traditional box score: MIN PTS REB AST STL BLK TOV PF FGM-A FG% 3PM-A 3P% FTM-A FT% +/-"""
    players    = [r for r in rows if not r.get("_totals")]
    top_scorer = max((r["PTS"] for r in players), default=0)

    thead = (
        f'<thead><tr>'
        f'<th class="bx-pl">Player</th>'
        f'<th>MIN</th>'
        f'<th style="color:{accent}">PTS</th>'
        f'<th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th><th>PF</th>'
        f'<th>FGM-A</th><th class="bx-pct">FG%</th>'
        f'<th>3PM-A</th><th class="bx-pct">3P%</th>'
        f'<th>FTM-A</th><th class="bx-pct">FT%</th>'
        f'<th>+/-</th>'
        f'</tr></thead>'
    )

    body = []
    for r in rows:
        is_tot = r.get("_totals", False)
        tr_cls = ' class="bx-totals"' if is_tot else ""

        name = r["Player"]
        if not is_tot and r["PTS"] == top_scorer and top_scorer > 0:
            name = f'<span style="color:{accent};font-weight:700">{name}</span>'

        fgm, fga = r.get("FGM", 0), r.get("FGA", 0)
        tpm, tpa = r.get("3PM", 0), r.get("3PA", 0)
        ftm, fta = r.get("FTM", 0), r.get("FTA", 0)
        pm_html  = _pm_html(r.get("+/-")) if not is_tot else "<span style='color:#8b949e'>—</span>"
        pts_cls  = ' class="bx-pts"' if not is_tot else ""

        body.append(
            f'<tr{tr_cls}>'
            f'<td class="bx-pl">{name}</td>'
            f'<td>{_min_str(r.get("MIN", 0))}</td>'
            f'<td{pts_cls}>{r["PTS"]}</td>'
            f'<td>{r.get("REB", 0)}</td>'
            f'<td>{r.get("AST", 0)}</td>'
            f'<td>{r.get("STL", 0)}</td>'
            f'<td>{r.get("BLK", 0)}</td>'
            f'<td>{r.get("TOV", 0)}</td>'
            f'<td>{r.get("PF", 0)}</td>'
            f'<td>{fgm}-{fga}</td><td class="bx-pct">{_pct(fgm, fga)}</td>'
            f'<td>{tpm}-{tpa}</td><td class="bx-pct">{_pct(tpm, tpa)}</td>'
            f'<td>{ftm}-{fta}</td><td class="bx-pct">{_pct(ftm, fta)}</td>'
            f'<td>{pm_html}</td>'
            f'</tr>'
        )

    return (
        f'<div style="overflow-x:auto;border:1px solid {border};'
        f'border-radius:12px;background:{bg}">'
        f'<table class="bx-table">{thead}<tbody>{"".join(body)}</tbody></table>'
        f'</div>'
    )


def _adv_html(rows: list, accent: str, bg: str, border: str) -> str:
    """Advanced box score: MIN PTS eFG% TS% GmSc OREB DREB REB AST STL BLK TOV +/-"""
    players  = [r for r in rows if not r.get("_totals")]
    top_gms  = max((r.get("GmSc") or 0 for r in players), default=0)

    thead = (
        f'<thead><tr>'
        f'<th class="bx-pl">Player</th>'
        f'<th>MIN</th>'
        f'<th style="color:{accent}">PTS</th>'
        f'<th>eFG%</th><th>TS%</th>'
        f'<th style="color:{accent}">GmSc</th>'
        f'<th>OREB</th><th>DREB</th><th>REB</th>'
        f'<th>AST</th><th>STL</th><th>BLK</th><th>TOV</th>'
        f'<th>+/-</th>'
        f'</tr></thead>'
    )

    body = []
    for r in rows:
        is_tot  = r.get("_totals", False)
        tr_cls  = ' class="bx-totals"' if is_tot else ""
        gms     = r.get("GmSc")
        efg     = r.get("eFG%")
        ts      = r.get("TS%")
        gms_str = f"{gms:.1f}" if gms is not None else "—"
        efg_str = f"{efg:.1f}" if efg is not None else "—"
        ts_str  = f"{ts:.1f}"  if ts  is not None else "—"
        pm_html = _pm_html(r.get("+/-")) if not is_tot else "<span style='color:#8b949e'>—</span>"

        # Highlight best game score
        name = r["Player"]
        if not is_tot and gms is not None and abs((gms or 0) - top_gms) < 0.01 and top_gms > 0:
            name = f'<span style="color:{accent};font-weight:700">{name}</span>'

        gms_cell = (
            f'<td style="font-weight:700;color:{accent}">{gms_str}</td>'
            if not is_tot else f'<td>{gms_str}</td>'
        )

        body.append(
            f'<tr{tr_cls}>'
            f'<td class="bx-pl">{name}</td>'
            f'<td>{_min_str(r.get("MIN", 0))}</td>'
            f'<td class="bx-pts">{r["PTS"]}</td>'
            f'<td>{efg_str}</td><td>{ts_str}</td>'
            f'{gms_cell}'
            f'<td>{r.get("OREB", 0)}</td>'
            f'<td>{r.get("DREB", 0)}</td>'
            f'<td>{r.get("REB", 0)}</td>'
            f'<td>{r.get("AST", 0)}</td>'
            f'<td>{r.get("STL", 0)}</td>'
            f'<td>{r.get("BLK", 0)}</td>'
            f'<td>{r.get("TOV", 0)}</td>'
            f'<td>{pm_html}</td>'
            f'</tr>'
        )

    return (
        f'<div style="overflow-x:auto;border:1px solid {border};'
        f'border-radius:12px;background:{bg}">'
        f'<table class="bx-table">{thead}<tbody>{"".join(body)}</tbody></table>'
        f'</div>'
    )


def linescore_html(q_data: dict, t1name: str, t2name: str,
                   t1id: int, t2id: int, accent: str) -> str:
    """Quarter-by-quarter linescore table."""
    if not q_data:
        return ""

    all_qs = sorted(q_data.keys())

    def q_lbl(q):
        return f"Q{q}" if q <= 4 else f"OT{q - 4}"

    q_hdrs   = "".join(f'<th>{q_lbl(q)}</th>' for q in all_qs)
    t1tot    = sum(q_data[q].get(t1id, 0) for q in all_qs)
    t2tot    = sum(q_data[q].get(t2id, 0) for q in all_qs)
    t1_cells = "".join(f'<td>{q_data[q].get(t1id, 0)}</td>' for q in all_qs)
    t2_cells = "".join(f'<td>{q_data[q].get(t2id, 0)}</td>' for q in all_qs)

    t1_tot_style = f"color:{accent};font-weight:800;font-size:17px" if t1tot >= t2tot \
                   else "color:#8b949e;font-weight:700;font-size:17px"
    t2_tot_style = f"color:{accent};font-weight:800;font-size:17px" if t2tot > t1tot \
                   else "color:#8b949e;font-weight:700;font-size:17px"

    return (
        f'<div style="overflow-x:auto;margin:10px 0 20px">'
        f'<table class="ls-table">'
        f'<thead><tr>'
        f'<th class="ls-team">Team</th>{q_hdrs}'
        f'<th style="font-size:11px;color:#8b949e">TOT</th>'
        f'</tr></thead>'
        f'<tbody>'
        f'<tr><td class="ls-team">{t1name}</td>{t1_cells}'
        f'<td style="{t1_tot_style};text-align:center">{t1tot}</td></tr>'
        f'<tr><td class="ls-team">{t2name}</td>{t2_cells}'
        f'<td style="{t2_tot_style};text-align:center">{t2tot}</td></tr>'
        f'</tbody></table></div>'
    )


# ── Public API ────────────────────────────────────────────────────────────────

def render_box_parts(rows_t1: list, rows_t2: list,
                     q_data: dict, game_info: dict, settings: dict) -> dict:
    """
    Build all HTML fragments for a game box score.

    Parameters
    ----------
    rows_t1 / rows_t2  : lists of player-stat dicts from compute_game_box_score()
    q_data             : {quarter: {team_id: pts}} from compute_game_quarter_scores()
    game_info          : dict with keys t1id, t2id, t1name, t2name (from compute_game_box_score)
    settings           : dict from get_all_settings()

    Returns
    -------
    dict with keys: css, linescore, t1_performers, t2_performers,
                    t1_trad, t2_trad, t1_adv, t2_adv
    """
    from helpers.settings_utils import STYLE_PRESETS, DEFAULTS

    style_name = settings.get("app_style", DEFAULTS["app_style"])
    style  = STYLE_PRESETS.get(style_name, STYLE_PRESETS["Dark"])
    accent = settings.get("accent_color", DEFAULTS["accent_color"])
    bg     = style["card_bg"]
    border = style["card_border"]

    t1name = game_info.get("t1name", "Team 1")
    t2name = game_info.get("t2name", "Team 2")
    t1id   = game_info.get("t1id")
    t2id   = game_info.get("t2id")

    return {
        "css":           _CSS,
        "linescore":     linescore_html(q_data, t1name, t2name, t1id, t2id, accent),
        "t1_performers": _top_performers_html(rows_t1, accent, bg, border),
        "t2_performers": _top_performers_html(rows_t2, accent, bg, border),
        "t1_trad":       _trad_html(rows_t1, accent, bg, border),
        "t2_trad":       _trad_html(rows_t2, accent, bg, border),
        "t1_adv":        _adv_html(rows_t1, accent, bg, border),
        "t2_adv":        _adv_html(rows_t2, accent, bg, border),
    }
