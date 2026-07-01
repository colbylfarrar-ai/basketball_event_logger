"""
player_edge.py — league-wide PLAYER leaderboards in the tracked-edge metrics.

The "player edge" boards answer scouting questions the box score can't: who makes
the hardest shots, who to force off their hand, who bends games on defense, who
gets buckets in the clutch, who creates their own shot, who is efficient at volume,
who disrupts. Each board is a ranked top-N over the league pool, gated by sample so
a two-shot night can't top it.

Pure data layer (stdlib + engines; no streamlit). Returns board dicts the shared
renderer (helpers/dashboard/player_edge.py) turns into tables, so the Rankings
League Lab and the Players Lab tab draw the SAME boards from one source.
"""
from __future__ import annotations

import helpers.player_ratings as PR
import helpers.stats as S
import helpers.playtypes as PT
import helpers.wpa as WPA

TOP_N = 12


def _rank(table, stat, gate_stat, gate_min, higher=True, cols=None):
    """Top-N rows over the table by ``stat``, gated on ``gate_stat >= gate_min``.
    ``cols`` = list of (column_label, row_key) to project; the sort stat need not
    be one of them. Returns a list of {column_label: value} dicts."""
    elig = [r for r in table.values()
            if r.get(stat) is not None and (r.get(gate_stat) or 0) >= gate_min]
    elig.sort(key=lambda r: r[stat], reverse=higher)
    out = []
    for r in elig[:TOP_N]:
        row = {}
        for label, key in cols:
            v = r.get(key)
            row[label] = v
        out.append(row)
    return out


def edge_boards(gender=None):
    """The full set of player-edge leaderboards for a gender.

    Returns a list of board dicts: {key, title, caption, rows, signed, pct} where
    `rows` is table-ready (list of {col: val}), `signed` = columns to render with a
    +/- sign, `pct` = columns that are already 0-100 percentages. Boards with no
    qualifying players are still returned (empty rows) so the renderer can show a
    graceful 'not enough sample' note in place."""
    table = PR.player_stat_table(gender=gender, min_games=1)

    # ── tracked-edge trio (shot-making over expected · hand split · def WPA) ──
    poe = sorted(
        ({"Player": r["name"], "Team": r.get("team", ""),
          "+pts/shot": round(r["PPS"] - r["xPPS"], 2), "FGA": r.get("FGA")}
         for r in table.values()
         if r.get("PPS") is not None and r.get("xPPS") is not None
         and (r.get("FGA") or 0) >= 20),
        key=lambda d: -d["+pts/shot"])[:TOP_N]

    hand = sorted(
        ({"Player": r["name"], "Team": r.get("team", ""),
          "Strong%": round(r["Dom_FG%"]), "Weak%": round(r["Weak_FG%"]),
          "Gap": round(r["Dom_FG%"] - r["Weak_FG%"])}
         for r in table.values()
         if r.get("Dom_FG%") is not None and r.get("Weak_FG%") is not None
         and (r.get("Dom_FGA") or 0) >= 6 and (r.get("Weak_FGA") or 0) >= 6),
        key=lambda d: -d["Gap"])[:TOP_N]

    try:
        sw = WPA.season_wpa(gender, mode="possession")
    except Exception:
        sw = {}
    dwpa = sorted(
        ({"Player": v.get("name"), "Team": v.get("team", ""),
          "Def WPA": round(v.get("def_wpa") or 0, 2), "GP": v.get("games")}
         for v in sw.values() if (v.get("games") or 0) >= 4),
        key=lambda d: -d["Def WPA"])[:TOP_N]

    return [
        {"key": "shot_makers", "title": "Shot-makers",
         "caption": "Points/shot over expected (FGA ≥ 20)",
         "rows": poe, "signed": ["+pts/shot"], "pct": []},
        {"key": "force_hand", "title": "Force off-hand",
         "caption": "Strong − weak side FG% gap (6+ each)",
         "rows": hand, "signed": [], "pct": ["Strong%", "Weak%", "Gap"]},
        {"key": "def_wpa", "title": "Defensive win value",
         "caption": "Def WPA — wins created on defense (4+ GP)",
         "rows": dwpa, "signed": ["Def WPA"], "pct": []},
        {"key": "clutch", "title": "Clutch scorers",
         "caption": "Fourth-quarter points per game (FGA ≥ 15)",
         "rows": _rank(table, "Q4PPG", "FGA", 15, cols=[
             ("Player", "name"), ("Team", "team"), ("Q4 PPG", "Q4PPG"),
             ("Q4 %", "Q4%")]),
         "signed": [], "pct": ["Q4 %"]},
        {"key": "creators", "title": "Shot creators",
         "caption": "Self-created shot share — low assist dependency (FGA ≥ 20)",
         "rows": _rank(table, "SelfCr%", "FGA", 20, cols=[
             ("Player", "name"), ("Team", "team"), ("Self-cr%", "SelfCr%"),
             ("FGA", "FGA")]),
         "signed": [], "pct": ["Self-cr%"]},
        {"key": "efficient", "title": "Efficient at volume",
         "caption": "True-shooting % on real usage (FGA ≥ 30)",
         "rows": _rank(table, "TS%", "FGA", 30, cols=[
             ("Player", "name"), ("Team", "team"), ("TS%", "TS%"),
             ("PPG", "PPG")]),
         "signed": [], "pct": ["TS%"]},
        {"key": "disruptors", "title": "Disruptors",
         "caption": "Stocks (steals+blocks) per 32 minutes (48+ min)",
         "rows": _rank(table, "STOCKS/32", "MIN", 48, cols=[
             ("Player", "name"), ("Team", "team"), ("Stocks/32", "STOCKS/32"),
             ("SPG", "SPG"), ("BPG", "BPG")]),
         "signed": [], "pct": []},
        {"key": "rim", "title": "Rim finishers",
         "caption": "FG% inside 5 ft on real volume (15+ rim FGA)",
         "rows": _rank(table, "Near_FG%", "Near_FGA", 15, cols=[
             ("Player", "name"), ("Team", "team"), ("Rim FG%", "Near_FG%"),
             ("Rim FGA", "Near_FGA")]),
         "signed": [], "pct": ["Rim FG%"]},
    ]
