"""
Native Streamlit box score renderer.
Uses st.dataframe + pandas Styler — no raw HTML tables.
Call show_game_box_score() from any page.
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pct(made: int, att: int) -> str:
    return f"{100*made/att:.1f}%" if att else "—"


def _build_traditional_df(rows: list) -> pd.DataFrame:
    out = []
    for r in rows:
        fgm, fga = r.get("FGM", 0), r.get("FGA", 0)
        tpm, tpa = r.get("3PM", 0), r.get("3PA", 0)
        ftm, fta = r.get("FTM", 0), r.get("FTA", 0)
        min_v = r.get("MIN", 0)
        out.append({
            "_totals": r.get("_totals", False),
            "Player": r["Player"],
            "MIN":    f"{min_v:.1f}" if isinstance(min_v, float) else str(min_v),
            "PTS":    r.get("PTS", 0),
            "REB":    r.get("REB", 0),
            "AST":    r.get("AST", 0),
            "STL":    r.get("STL", 0),
            "BLK":    r.get("BLK", 0),
            "TOV":    r.get("TOV", 0),
            "PF":     r.get("PF", 0),
            "FG":     f"{fgm}-{fga}",
            "FG%":    _pct(fgm, fga),
            "3P":     f"{tpm}-{tpa}",
            "3P%":    _pct(tpm, tpa),
            "FT":     f"{ftm}-{fta}",
            "FT%":    _pct(ftm, fta),
            "+/-":    r.get("+/-"),
        })
    return pd.DataFrame(out)


def _build_advanced_df(rows: list) -> pd.DataFrame:
    out = []
    for r in rows:
        efg   = r.get("eFG%")
        ts    = r.get("TS%")
        gs    = r.get("GmSc")
        wpass = r.get("W/Pass%")
        wopass= r.get("W/O%")
        min_v = r.get("MIN", 0)
        out.append({
            "_totals":   r.get("_totals", False),
            "Player":    r["Player"],
            "MIN":       f"{min_v:.1f}" if isinstance(min_v, float) else str(min_v),
            "PTS":       r.get("PTS", 0),
            "eFG%":      f"{efg:.1f}%"   if efg   is not None else "—",
            "TS%":       f"{ts:.1f}%"    if ts    is not None else "—",
            "GmSc":      f"{gs:.1f}"     if gs    is not None else "—",
            "W/Pass%":   f"{wpass:.1f}%" if wpass is not None else "—",
            "W/O%":      f"{wopass:.1f}%" if wopass is not None else "—",
            "OREB":      r.get("OREB", 0),
            "DREB":      r.get("DREB", 0),
            "AST":       r.get("AST", 0),
            "STL":       r.get("STL", 0),
            "BLK":       r.get("BLK", 0),
            "TOV":       r.get("TOV", 0),
            "+/-":       r.get("+/-"),
        })
    return pd.DataFrame(out)


def _style_box(df: pd.DataFrame) -> object:
    """Apply Styler: bold totals row, green/red +/- column."""
    is_tot = df["_totals"].tolist() if "_totals" in df.columns else [False] * len(df)
    display = df.drop(columns=["_totals"], errors="ignore").copy()

    for c in display.columns:
        if display[c].dtype.kind == 'O' or isinstance(display[c].dtype, pd.StringDtype):
            if c != "+/-":
                display[c] = display[c].astype(str)

    def _row_style(row):
        if is_tot[row.name]:
            return ["font-weight:bold; background-color:#1c2b1c"] * len(row)
        return [""] * len(row)

    def _pm_style(val):
        try:
            v = float(val)
            if v > 0:
                return "color:#2ecc71; font-weight:600"
            if v < 0:
                return "color:#e74c3c; font-weight:600"
            return "color:#8b949e"
        except (TypeError, ValueError):
            return "color:#8b949e"

    styled = display.style.apply(_row_style, axis=1)
    if "+/-" in display.columns:
        styled = styled.map(_pm_style, subset=["+/-"])
    return styled


def _show_linescore(q_data: dict, t1name: str, t2name: str,
                    t1id: int, t2id: int) -> None:
    """Quarter-by-quarter linescore as a small styled DataFrame."""
    all_qs = sorted(q_data.keys())

    def q_lbl(q):
        return f"Q{q}" if q <= 4 else f"OT{q - 4}"

    t1tot = sum(q_data[q].get(t1id, 0) for q in all_qs)
    t2tot = sum(q_data[q].get(t2id, 0) for q in all_qs)

    r1 = {"Team": t1name, **{q_lbl(q): q_data[q].get(t1id, 0) for q in all_qs}, "TOT": t1tot}
    r2 = {"Team": t2name, **{q_lbl(q): q_data[q].get(t2id, 0) for q in all_qs}, "TOT": t2tot}

    df_ls = pd.DataFrame([r1, r2])

    def _ls_style(row):
        styles = [""] * len(row)
        styles[-1] = "font-weight:800; font-size:15px"  # TOT column
        return styles

    st.dataframe(
        df_ls.style.apply(_ls_style, axis=1),
        hide_index=True,
        use_container_width=True,
    )


def _show_top_performers(player_rows: list) -> None:
    """6 stat-leader metrics: scorer, rebounder, passer, steal, block, GmSc."""
    if not player_rows:
        return
    top_pts = max(player_rows, key=lambda r: r.get("PTS",  0) or 0)
    top_reb = max(player_rows, key=lambda r: r.get("REB",  0) or 0)
    top_ast = max(player_rows, key=lambda r: r.get("AST",  0) or 0)
    top_stl = max(player_rows, key=lambda r: r.get("STL",  0) or 0)
    top_blk = max(player_rows, key=lambda r: r.get("BLK",  0) or 0)
    top_gsc = max(player_rows, key=lambda r: r.get("GmSc") or 0)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("PTS",  top_pts.get("PTS", 0))
        st.caption(top_pts["Player"])
    with c2:
        st.metric("REB",  top_reb.get("REB", 0))
        st.caption(top_reb["Player"])
    with c3:
        st.metric("AST",  top_ast.get("AST", 0))
        st.caption(top_ast["Player"])
    with c4:
        st.metric("STL",  top_stl.get("STL", 0))
        st.caption(top_stl["Player"])
    with c5:
        st.metric("BLK",  top_blk.get("BLK", 0))
        st.caption(top_blk["Player"])
    with c6:
        gs = top_gsc.get("GmSc")
        st.metric("GmSc", f"{gs:.1f}" if gs is not None else "—")
        st.caption(top_gsc["Player"])


def _show_team_comparison(rows_t1: list, rows_t2: list,
                           t1name: str, t2name: str) -> None:
    """Side-by-side team totals with winner bolded in green."""
    def _get_totals(rows):
        for r in rows:
            if r.get("_totals"):
                return r
        return {}

    t1 = _get_totals(rows_t1)
    t2 = _get_totals(rows_t2)
    if not t1 and not t2:
        return

    t1_fgm, t1_fga = t1.get("FGM", 0), t1.get("FGA", 0)
    t2_fgm, t2_fga = t2.get("FGM", 0), t2.get("FGA", 0)
    t1_tpm, t1_tpa = t1.get("3PM", 0), t1.get("3PA", 0)
    t2_tpm, t2_tpa = t2.get("3PM", 0), t2.get("3PA", 0)
    t1_ftm, t1_fta = t1.get("FTM", 0), t1.get("FTA", 0)
    t2_ftm, t2_fta = t2.get("FTM", 0), t2.get("FTA", 0)

    # (display_v1, display_v2, numeric_n1, numeric_n2, higher_is_better)
    def _fg_n(made, att):
        return made / att if att else 0.0

    rows_data = [
        ("Points",      t1.get("PTS", 0),           t2.get("PTS", 0),           t1.get("PTS", 0),         t2.get("PTS", 0),         True),
        ("FG",          f"{t1_fgm}-{t1_fga}",        f"{t2_fgm}-{t2_fga}",        _fg_n(t1_fgm, t1_fga),    _fg_n(t2_fgm, t2_fga),    True),
        ("FG%",         _pct(t1_fgm, t1_fga),        _pct(t2_fgm, t2_fga),        _fg_n(t1_fgm, t1_fga),    _fg_n(t2_fgm, t2_fga),    True),
        ("3P",          f"{t1_tpm}-{t1_tpa}",        f"{t2_tpm}-{t2_tpa}",        _fg_n(t1_tpm, t1_tpa),    _fg_n(t2_tpm, t2_tpa),    True),
        ("3P%",         _pct(t1_tpm, t1_tpa),        _pct(t2_tpm, t2_tpa),        _fg_n(t1_tpm, t1_tpa),    _fg_n(t2_tpm, t2_tpa),    True),
        ("FT",          f"{t1_ftm}-{t1_fta}",        f"{t2_ftm}-{t2_fta}",        _fg_n(t1_ftm, t1_fta),    _fg_n(t2_ftm, t2_fta),    True),
        ("FT%",         _pct(t1_ftm, t1_fta),        _pct(t2_ftm, t2_fta),        _fg_n(t1_ftm, t1_fta),    _fg_n(t2_ftm, t2_fta),    True),
        ("Rebounds",    t1.get("REB", 0),             t2.get("REB", 0),             t1.get("REB", 0),          t2.get("REB", 0),          True),
        ("Off Reb",     t1.get("OREB", 0),            t2.get("OREB", 0),            t1.get("OREB", 0),         t2.get("OREB", 0),         True),
        ("Def Reb",     t1.get("DREB", 0),            t2.get("DREB", 0),            t1.get("DREB", 0),         t2.get("DREB", 0),         True),
        ("Assists",     t1.get("AST", 0),             t2.get("AST", 0),             t1.get("AST", 0),          t2.get("AST", 0),          True),
        ("Turnovers",   t1.get("TOV", 0),             t2.get("TOV", 0),             t1.get("TOV", 0),          t2.get("TOV", 0),          False),
        ("Steals",      t1.get("STL", 0),             t2.get("STL", 0),             t1.get("STL", 0),          t2.get("STL", 0),          True),
        ("Blocks",      t1.get("BLK", 0),             t2.get("BLK", 0),             t1.get("BLK", 0),          t2.get("BLK", 0),          True),
        ("Fouls",       t1.get("PF", 0),              t2.get("PF", 0),              t1.get("PF", 0),           t2.get("PF", 0),           False),
    ]

    # Determine winner per row
    winners = []
    df_rows = []
    for label, v1, v2, n1, n2, higher_better in rows_data:
        if n1 == n2:
            winners.append(0)
        elif (n1 > n2) == higher_better:
            winners.append(-1)  # t1 wins
        else:
            winners.append(1)   # t2 wins
        df_rows.append({t1name: v1, "Stat": label, t2name: v2})

    df = pd.DataFrame(df_rows)
    t1col, t2col = t1name, t2name

    def _style_row(row):
        base = pd.Series("", index=row.index)
        w = winners[row.name]
        if w == -1:
            base[t1col] = "font-weight:700; color:#2ecc71"
        elif w == 1:
            base[t2col] = "font-weight:700; color:#2ecc71"
        base["Stat"] = "color:#8b949e; text-align:center; font-size:11px"
        return base

    st.dataframe(
        df.style.apply(_style_row, axis=1),
        hide_index=True,
        use_container_width=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def show_game_box_score(rows_t1: list, rows_t2: list,
                        q_data: dict, game_info: dict, cfg: dict) -> None:
    """
    Renders a complete game box score using native Streamlit components.

    Parameters
    ----------
    rows_t1 / rows_t2 : lists of player-stat dicts from compute_game_box_score()
    q_data            : {quarter: {team_id: pts}} from compute_game_quarter_scores()
                        Pass {} to have this function auto-fetch it.
    game_info         : dict with keys t1id, t2id, t1name, t2name, id
    cfg               : settings dict from get_all_settings()
    """
    t1name  = game_info.get("t1name", "Team 1")
    t2name  = game_info.get("t2name", "Team 2")
    t1id    = game_info.get("t1id")
    t2id    = game_info.get("t2id")
    game_id = game_info.get("id")

    # Score flow chart (lazy import to avoid circular dependency)
    if game_id and t1id and t2id:
        try:
            from helpers.charts import show_score_flow_chart
            show_score_flow_chart(game_id, t1name, t2name, t1id, t2id,
                                  key=f"bs_flow_{game_id}")
        except Exception:
            pass

    # Auto-fetch quarter data if not provided
    if not q_data and game_id:
        try:
            from helpers.stats_players import compute_game_quarter_scores
            q_data = compute_game_quarter_scores(game_id) or {}
        except Exception:
            q_data = {}

    # Quarter linescore
    if q_data and t1id and t2id:
        _show_linescore(q_data, t1name, t2name, t1id, t2id)

    st.divider()

    # Team stats comparison
    st.markdown("**Team Stats**")
    _show_team_comparison(rows_t1, rows_t2, t1name, t2name)

    st.divider()

    # ── Per-team tabs ─────────────────────────────────────────────────────────
    tab_t1, tab_t2 = st.tabs([t1name, t2name])

    for _tab, _rows, _tname in [
        (tab_t1, rows_t1, t1name),
        (tab_t2, rows_t2, t2name),
    ]:
        with _tab:
            player_rows = [r for r in _rows if not r.get("_totals")]
            if not player_rows:
                st.info(f"No stats logged for {_tname}.")
                continue

            # Stat leaders (6 categories)
            _show_top_performers(player_rows)
            st.divider()

            # ── Traditional | Advanced inner tabs ─────────────────────────
            _tt, _ta = st.tabs(["📋 Traditional", "📈 Advanced"])

            with _tt:
                st.dataframe(
                    _style_box(_build_traditional_df(_rows)),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "FG / 3P / FT = Made-Attempted  ·  "
                    "FG% / 3P% / FT% = shooting %  ·  "
                    "+/- = net points while on court"
                )

            with _ta:
                st.dataframe(
                    _style_box(_build_advanced_df(_rows)),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "eFG% = (FGM + 0.5·3PM) / FGA  ·  "
                    "TS% = PTS / (2·(FGA + 0.44·FTA))  ·  "
                    "GmSc = Hollinger Game Score  ·  "
                    "W/Pass% = assisted FGM / FGA  ·  "
                    "W/O% = unassisted FGM / FGA"
                )
