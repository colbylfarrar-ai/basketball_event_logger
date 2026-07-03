"""
social_cards.py — premade share graphics for social media (PNG, 1080×1080).

Coach-facing "post this" cards rendered with matplotlib Agg (the court_png.py
engine — zero new dependencies, renders identically on the VPS): a branded dark
canvas in the app palette with the numbers dropped in. Three cards:

  game_result_png(game_id, team_id)   — final score, W/L, top performers
  season_record_png(team_id, gender)  — record, power rank, margin, best player
  last_n_png(team_id, gender, n)      — the stretch: record, margin, hot hand

Display-only assembly of existing engines (score_ratings, player_stat_table,
aggregate_player_boxes) — no new stats, real numbers only. Streamlit-free;
the Team Dashboard Share tab owns caching and download buttons.
"""
from __future__ import annotations

import io

from database.db import query
import helpers.stats as S
import helpers.team_ratings as TR
import helpers.player_ratings as PR

# App palette (mirrors the dashboard dark theme + brand gold).
BG = "#0d1117"
PANEL = "#161b22"
EDGE = "#21262d"
GOLD = "#f0a500"
FG = "#f0f6fc"
GREY = "#8b949e"
GOOD = "#3fb950"
BAD = "#e74c3c"

_W = 10.8      # 1080 px at dpi=100, square


def _fig():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(_W, _W), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.set_facecolor(BG)
    return fig, ax


def _brand(ax, kicker):
    """Top brand bar: ball mark + wordmark left, card kicker right, gold rule."""
    from matplotlib.patches import Circle
    # the "tracked path → ball" mark, simplified for raster
    pts = [(4.2, 93.4), (5.9, 95.0), (7.3, 93.9)]
    for i in range(len(pts) - 1):
        ax.plot([pts[i][0], pts[i + 1][0]], [pts[i][1], pts[i + 1][1]],
                color=GOLD, lw=2.4, solid_capstyle="round", zorder=3)
    for p in pts:
        ax.add_patch(Circle(p, 0.42, facecolor=BG, edgecolor=GOLD, lw=1.6, zorder=4))
    ball = Circle((9.4, 94.4), 1.15, facecolor=GOLD, edgecolor=GOLD, zorder=4)
    ax.add_patch(ball)
    ax.plot([8.25, 10.55], [94.4, 94.4], color=BG, lw=1.1, zorder=5)
    ax.plot([9.4, 9.4], [93.25, 95.55], color=BG, lw=1.1, zorder=5)
    ax.text(11.5, 94.4, "HOOPTRACKS", color=GOLD, fontsize=21,
            fontweight="bold", va="center", ha="left")
    ax.text(96, 94.4, kicker.upper(), color=GREY, fontsize=14,
            va="center", ha="right", fontweight="bold")
    ax.plot([4, 96], [91.2, 91.2], color=GOLD, lw=2.5)


def _foot(ax):
    ax.plot([4, 96], [5.4, 5.4], color=EDGE, lw=1.2)
    ax.text(50, 3.2, "app.hooptracks.com", color=GREY, fontsize=12,
            ha="center", va="center")


def _panel(ax, x, y, w, h):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.4",
        facecolor=PANEL, edgecolor=EDGE, lw=1.2, zorder=1))


def _tile(ax, cx, cy, label, value, color=FG, vsize=27):
    ax.text(cx, cy + 2.4, str(value), color=color, fontsize=vsize,
            fontweight="bold", ha="center", va="center", zorder=2)
    ax.text(cx, cy - 3.0, label.upper(), color=GREY, fontsize=11.5,
            ha="center", va="center", zorder=2)


def _fit(name, limit=26):
    n = str(name)
    return n if len(n) <= limit else n[:limit - 1] + "…"


def _png(fig):
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=100)
    plt.close(fig)
    return buf.getvalue()


def _team_games(team_id, season="Current"):
    """Finished games for one team, oldest→newest, from THIS team's side."""
    rows = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score, g.away_score,
                  g.tracked, t1.name n1, t2.name n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id
           WHERE (g.team1_id=? OR g.team2_id=?)
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
             AND g.season=?
           ORDER BY g.date, g.id""",
        (team_id, team_id, season))
    out = []
    for r in rows:
        home = r["team1_id"] == team_id
        pf = r["home_score"] if home else r["away_score"]
        pa = r["away_score"] if home else r["home_score"]
        out.append({"id": r["id"], "date": r["date"] or "",
                    "opp": r["n2"] if home else r["n1"],
                    "pf": pf, "pa": pa, "won": pf > pa,
                    "tracked": bool(r["tracked"])})
    return out


def _top_performers(game_ids, team_id, limit=3):
    """Top scorers for one team over the given games — [(name, num, pts, reb, ast)]."""
    meta = {r["id"]: r for r in query(
        "SELECT id, name, number, team_id FROM players WHERE team_id=?", (team_id,))}
    boxes = S.aggregate_player_boxes(list(game_ids))
    rows = []
    for pid, b in boxes.items():
        m = meta.get(pid)
        if not m:
            continue
        fb = S.finalize_box(b)
        rows.append((m["name"], m["number"], fb.get("PTS", 0),
                     fb.get("TRB", 0), fb.get("AST", 0)))
    rows.sort(key=lambda r: -r[2])
    return [r for r in rows if r[2] > 0][:limit] or rows[:limit]


# ── card 1: game result ──────────────────────────────────────────────────────
def game_result_png(game_id, team_id):
    """Final-score card from `team_id`'s perspective. None if game not finished."""
    g = query(
        """SELECT g.*, t1.name n1, t2.name n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""",
        (game_id,))
    if not g:
        return None
    g = g[0]
    if g["home_score"] is None or g["away_score"] is None:
        return None
    home = g["team1_id"] == team_id
    me = g["n1"] if home else g["n2"]
    opp = g["n2"] if home else g["n1"]
    pf = g["home_score"] if home else g["away_score"]
    pa = g["away_score"] if home else g["home_score"]
    won = pf > pa

    fig, ax = _fig()
    _brand(ax, "final score")

    ax.text(50, 84, _fit(me, 30), color=FG, fontsize=30, fontweight="bold",
            ha="center", va="center")
    ax.text(50, 78.2, f"vs {_fit(opp, 32)}" + (f" · {g['date']}" if g["date"] else ""),
            color=GREY, fontsize=15, ha="center", va="center")

    # verdict + score, the poster read
    ax.text(50, 68, "WIN" if won else "LOSS", color=(GOLD if won else BAD),
            fontsize=26, fontweight="bold", ha="center", va="center")
    ax.text(50, 56.5, f"{pf} – {pa}", color=FG, fontsize=78, fontweight="bold",
            ha="center", va="center")

    # top performers
    tops = _top_performers([game_id], team_id)
    if tops:
        _panel(ax, 8, 10, 84, 34)
        ax.text(12, 39.5, "TOP PERFORMERS", color=GOLD, fontsize=14,
                fontweight="bold", ha="left", va="center", zorder=2)
        y = 32.5
        for name, num, pts, reb, ast in tops:
            ax.text(12, y, f"#{num} {_fit(name, 22)}", color=FG, fontsize=17,
                    fontweight="bold", ha="left", va="center", zorder=2)
            ax.text(88, y, f"{pts} PTS · {reb} REB · {ast} AST", color=GREY,
                    fontsize=15, ha="right", va="center", zorder=2)
            y -= 8.5
    _foot(ax)
    return _png(fig)


# ── card 2: season record ────────────────────────────────────────────────────
def season_record_png(team_id, gender):
    """Season-to-date card: record, power rank, margin, scoring, best player."""
    scored = TR.score_ratings(gender=gender)
    s = scored.get(team_id)
    if not s:
        return None
    games = _team_games(team_id)

    # current streak off the game list (real results, newest backwards)
    streak = ""
    if games:
        last = games[-1]["won"]
        n = 0
        for gm in reversed(games):
            if gm["won"] == last:
                n += 1
            else:
                break
        streak = f"{'W' if last else 'L'}{n}"

    fig, ax = _fig()
    _brand(ax, "season report")
    ax.text(50, 84, _fit(s["name"], 30), color=FG, fontsize=30, fontweight="bold",
            ha="center", va="center")
    ax.text(50, 78.6, f"Class {s.get('class', 'N/A')} · Season to date",
            color=GREY, fontsize=15, ha="center", va="center")

    ax.text(50, 62, f"{s.get('W', 0)}–{s.get('L', 0)}", color=GOLD, fontsize=88,
            fontweight="bold", ha="center", va="center")
    ax.text(50, 50.5, "RECORD", color=GREY, fontsize=14, ha="center", va="center")

    _panel(ax, 8, 25.5, 84, 17)
    xs = [20.5, 40, 60, 79.5]
    _tile(ax, xs[0], 34, "power rank", f"#{s.get('Rank', '—')}", GOLD)
    _tile(ax, xs[1], 34, "streak", streak or "—",
          GOOD if streak.startswith("W") else (BAD if streak else FG))
    _tile(ax, xs[2], 34, "margin", f"{s.get('MOV', 0):+.1f}",
          GOOD if (s.get("MOV") or 0) >= 0 else BAD)
    _tile(ax, xs[3], 34, "ppg / opp", f"{s.get('PPG', 0):.0f}/{s.get('oPPG', 0):.0f}")

    # best player — top OVERALL on the roster (fallback: scoring leader)
    table = PR.player_stat_table(gender=gender, min_games=1)
    mine = [r for r in table.values() if r.get("team_id") == team_id]
    best = None
    rated = [r for r in mine if r.get("OVERALL") is not None]
    if rated:
        best = max(rated, key=lambda r: r["OVERALL"])
    elif mine:
        best = max(mine, key=lambda r: (r.get("PPG") or 0))
    if best:
        _panel(ax, 8, 10, 84, 12.5)
        ax.text(12, 18.6, "BEST PLAYER", color=GOLD, fontsize=13,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.text(12, 13.6, f"#{best.get('number', '')} {_fit(best['name'], 24)}",
                color=FG, fontsize=18, fontweight="bold", ha="left",
                va="center", zorder=2)
        line = (f"{(best.get('PPG') or 0):.1f} PPG · {(best.get('RPG') or 0):.1f} REB · "
                f"{(best.get('APG') or 0):.1f} AST")
        if best.get("OVERALL") is not None:
            line += f" · {best['OVERALL']:.0f} OVR"
        ax.text(88, 13.6, line, color=GREY, fontsize=14.5, ha="right",
                va="center", zorder=2)
    _foot(ax)
    return _png(fig)


# ── card 3: last N games ─────────────────────────────────────────────────────
def last_n_png(team_id, gender, n=5):
    """The recent stretch: record + margin over the last `n`, the results strip
    and the hottest hand (top scorer across those games)."""
    games = _team_games(team_id)
    if not games:
        return None
    stretch = games[-n:]
    w = sum(1 for gm in stretch if gm["won"])
    l = len(stretch) - w
    margin = sum(gm["pf"] - gm["pa"] for gm in stretch) / len(stretch)
    name = query("SELECT name FROM teams WHERE id=?", (team_id,))
    tname = name[0]["name"] if name else f"#{team_id}"

    fig, ax = _fig()
    _brand(ax, f"last {len(stretch)} games")
    ax.text(50, 84, _fit(tname, 30), color=FG, fontsize=30, fontweight="bold",
            ha="center", va="center")
    ax.text(50, 78.6, f"The last {len(stretch)} games", color=GREY, fontsize=15,
            ha="center", va="center")

    ax.text(50, 65, f"{w}–{l}", color=GOLD, fontsize=80, fontweight="bold",
            ha="center", va="center")
    ax.text(50, 55.5, f"AVG MARGIN {margin:+.1f}", color=(GOOD if margin >= 0 else BAD),
            fontsize=16, fontweight="bold", ha="center", va="center")

    # results strip (oldest → newest)
    _panel(ax, 8, 27.5, 84, 21)
    rows = stretch[-6:]
    y0, y1 = 45.2, 30.6
    step = (y0 - y1) / max(len(rows) - 1, 1)
    y = y0
    for gm in rows:
        clr = GOOD if gm["won"] else BAD
        ax.text(12, y, "W" if gm["won"] else "L", color=clr, fontsize=15,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.text(17, y, f"{gm['pf']}–{gm['pa']}  vs {_fit(gm['opp'], 26)}",
                color=FG, fontsize=14.5, ha="left", va="center", zorder=2)
        ax.text(88, y, gm["date"], color=GREY, fontsize=12.5, ha="right",
                va="center", zorder=2)
        y -= step

    # player of the stretch — top scorer over the window's TRACKED games only
    # (player boxes exist only where events were tracked; dividing by the whole
    # stretch would print a made-up per-game line). No tracked games → no panel.
    _tids = [gm["id"] for gm in stretch if gm["tracked"]]
    tops = _top_performers(_tids, team_id, limit=1) if _tids else []
    if tops:
        nm, num, pts, reb, ast = tops[0]
        gp = len(_tids)
        _panel(ax, 8, 10, 84, 12.5)
        _hdr = ("PLAYER OF THE STRETCH" if gp == len(stretch) else
                f"PLAYER OF THE STRETCH · {gp} TRACKED GAME{'S' if gp != 1 else ''}")
        ax.text(12, 18.6, _hdr, color=GOLD, fontsize=13,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.text(12, 13.6, f"#{num} {_fit(nm, 24)}", color=FG, fontsize=18,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.text(88, 13.6,
                f"{pts / gp:.1f} PPG · {reb / gp:.1f} REB · {ast / gp:.1f} AST",
                color=GREY, fontsize=14.5, ha="right", va="center", zorder=2)
    _foot(ax)
    return _png(fig)
