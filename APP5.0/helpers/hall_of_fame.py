"""
hall_of_fame.py — pure engines for the Hall of Fame page's single-game
records and records watch (backlog item 20).

No Streamlit, no DB: the page assembles {pid: {gid: box}} from
stats.player_game_boxes + manual_player_box rows (same combined pool as the
career sums, identity handled by the caller) and feeds plain dicts in, so
both functions run under a script test on synthetic boxes.
"""
from __future__ import annotations

SG_STATS = ("PTS", "TRB", "AST", "STL", "BLK")


def single_game_records(boxes, meta, game_meta, *, stats=SG_STATS, top_n=10):
    """Top single-game nights per stat, all seasons pooled.

    boxes:     {pid: {gid: box}} — box carries the SG_STATS keys
    meta:      {pid: {"name","number","team"}} (players missing here are
               skipped — mirrors the page's gender scoping)
    game_meta: {gid: {"date","matchup","season"}}

    → {stat: [{pid, name, number, team, value, date, matchup, season, gid}]}
    sorted best-first; ties break to the older date (first to do it holds
    the line above the equal, later night)."""
    out = {s: [] for s in stats}
    for pid, per in boxes.items():
        m = meta.get(pid)
        if not m:
            continue
        for gid, b in per.items():
            gm = game_meta.get(gid, {})
            for s in stats:
                v = b.get(s, 0) or 0
                if v <= 0:
                    continue
                out[s].append({
                    "pid": pid, "name": m.get("name", pid),
                    "number": m.get("number"), "team": m.get("team", ""),
                    "value": v, "date": gm.get("date", ""),
                    "matchup": gm.get("matchup", ""),
                    "season": gm.get("season", ""), "gid": gid})
    for s in stats:
        out[s].sort(key=lambda r: (-r["value"], r["date"] or "9999"))
        out[s] = out[s][:top_n]
    return out


def records_watch(careers, *, stats=("PTS", "TRB", "AST"), top_n=10,
                  horizon_games=5, min_gp=5, board_min_gp=0):
    """Active players in striking distance of a career top-10 rung.

    careers: {identity_key: {"name","team","gp","active", PTS, TRB, AST}}
    For each stat, the board is the career top-`top_n`. An ACTIVE player is
    "on watch" when, at their own career per-game pace, they'd pass the next
    rung above them within `horizon_games` more games. Players with fewer
    than `min_gp` career games have no trustworthy pace — skipped.

    → [{name, team, stat, total, target, target_holder, need, games_needed,
        entering (True = would enter the board, False = climbing it)}]
    sorted soonest-first."""
    out = []
    rows = [c for c in careers.values() if (c.get("gp") or 0) > 0]
    # the board mirrors the DISPLAYED career leaders (page passes its
    # CAREER_MIN_GP), so a chip never chases a rung the page doesn't show
    board_rows = [c for c in rows if (c.get("gp") or 0) >= board_min_gp]
    for s in stats:
        board = sorted(board_rows, key=lambda c: -(c.get(s) or 0))[:top_n]
        if not board:
            continue
        cutoff = board[-1].get(s) or 0
        for c in rows:
            if not c.get("active") or (c.get("gp") or 0) < min_gp:
                continue
            total = c.get(s) or 0
            # the next rung strictly above this player's total
            above = [b for b in board if (b.get(s) or 0) > total]
            if not above:
                continue                    # already holds the top line
            target_row = above[-1]          # smallest rung still above them
            target = target_row.get(s) or 0
            pace = total / c["gp"]
            if pace <= 0:
                continue
            need = target - total + 1       # pass, not tie
            games_needed = need / pace
            if games_needed <= horizon_games:
                out.append({
                    "name": c.get("name", "?"), "team": c.get("team", ""),
                    "stat": s, "total": total, "target": target,
                    "target_holder": target_row.get("name", "?"),
                    "need": need, "games_needed": games_needed,
                    "entering": total < cutoff or len(board) < top_n})
    out.sort(key=lambda r: r["games_needed"])
    return out
