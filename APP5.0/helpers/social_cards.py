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
                    "opp_id": r["team2_id"] if home else r["team1_id"],
                    "pf": pf, "pa": pa, "won": pf > pa,
                    "tracked": bool(r["tracked"])})
    return out


# ── colour helpers ───────────────────────────────────────────────────────────
def _norm_hex(c, default):
    """Return a #rrggbb string, or `default` when `c` is missing / malformed."""
    if not c:
        return default
    c = str(c).strip()
    if not c.startswith("#"):
        c = "#" + c
    if len(c) == 4:                       # #abc → #aabbcc
        c = "#" + "".join(ch * 2 for ch in c[1:])
    try:
        int(c[1:], 16)
        return c if len(c) == 7 else default
    except ValueError:
        return default


def _ink(hexc):
    """Readable text colour (near-black or near-white) for a filled panel of
    `hexc`, by W3C relative luminance."""
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def _lin(u):
        return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    return "#0d1117" if lum > 0.42 else "#ffffff"


# palette of distinct defaults so an untinted game still reads two-sided
_DEFAULT_TEAM_COLORS = ["#8b1a2b", "#1b3a6b", "#1f6b3a", "#6b4a1b",
                        "#4a1b6b", "#1b5f6b"]


def default_team_color(team_id):
    """A stable default colour for a team (used until a coach picks one)."""
    return _DEFAULT_TEAM_COLORS[int(team_id) % len(_DEFAULT_TEAM_COLORS)]


def _quarter_points(game_id):
    """{team_id: {q: pts}} scored per quarter (shots + free throws), plus the
    sorted quarter list. Mirrors the game-recap quarter tally so the two agree."""
    g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (game_id,))
    if not g:
        return {}, []
    t1, t2 = g[0]["team1_id"], g[0]["team2_id"]
    per = {t1: {}, t2: {}}
    for ev in S.fetch_events([game_id]):
        if ev.get("shot_result") != "make":
            continue
        et = ev.get("event_type")
        if et == "shot":
            pts = ev.get("shot_type") or 2
        elif et == "free_throw":
            pts = 1
        else:
            continue
        tid = ev.get("shooter_team_id")
        if tid in per:
            q = ev.get("quarter")
            per[tid][q] = per[tid].get(q, 0) + pts
    qs = sorted(q for q in (set(per[t1]) | set(per[t2])) if q)
    return per, qs


def rank_line(scored, team_id, record=True, power=True, cls=True):
    """A compact identity line for a team — 'Power #3 · 29–2 · 3A #2' — from the
    already-computed `scored` table. Empty pieces drop out; '' when unrated."""
    s = scored.get(team_id)
    if not s:
        return ""
    bits = []
    if power and s.get("Rank"):
        bits.append(f"Power #{s['Rank']}")
    if record:
        bits.append(f"{s.get('W', 0)}–{s.get('L', 0)}")
    if cls:
        cr, _cn = class_rank(scored, team_id)
        if cr:
            bits.append(f"{s.get('class', '')} #{cr}")
    return "  ·  ".join(bits)


def class_rank(scored, team_id):
    """(rank, n) of `team_id` among same-class teams by Power (1 = best), or
    (None, 0)."""
    s = scored.get(team_id)
    if not s:
        return None, 0
    cls = s.get("class")
    peers = sorted(((tid, v) for tid, v in scored.items()
                    if v.get("class") == cls),
                   key=lambda kv: -(kv[1].get("Power") or 0))
    for i, (tid, _v) in enumerate(peers, 1):
        if tid == team_id:
            return i, len(peers)
    return None, len(peers)


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


# ── card 1: game result — symmetric head-to-head ─────────────────────────────
def game_result_png(game_id, team_id, color_a=None, color_b=None,
                    show_quarters=False, gender=None):
    """Head-to-head final-score card: two team-colour panels (same treatment for
    both), the score, each team's Power/record/class-rank line, and an optional
    quarter-by-quarter line. `team_id` is the dashboard team → shown on top;
    `color_a`/`color_b` are its / the opponent's panel colours (defaults derived
    from team id). None if game not finished."""
    from matplotlib.patches import FancyBboxPatch
    scored = TR.score_ratings(gender=gender) if gender else {}
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
    a_id = team_id
    b_id = g["team2_id"] if home else g["team1_id"]
    a_name = g["n1"] if home else g["n2"]
    b_name = g["n2"] if home else g["n1"]
    a_pts = g["home_score"] if home else g["away_score"]
    b_pts = g["away_score"] if home else g["home_score"]
    ca = _norm_hex(color_a, default_team_color(a_id))
    cb = _norm_hex(color_b, default_team_color(b_id))

    fig, ax = _fig()
    _brand(ax, "final score")
    sub = g["date"] or ""
    if g.get("location"):
        sub = f"{sub} · {g['location']}" if sub else g["location"]
    if sub:
        ax.text(50, 87.5, sub, color=GREY, fontsize=13, ha="center", va="center")

    a_line = rank_line(scored, a_id)
    b_line = rank_line(scored, b_id)

    # two team panels — identical geometry, each filled in its team colour so
    # the card reads the same for either side.
    def _team_panel(y, h, name, pts, color, winner, subline):
        ink = _ink(color)
        # a faint border so a panel whose colour is near the background (a coach
        # can pick anything) still shows its shape.
        ax.add_patch(FancyBboxPatch(
            (7, y), 86, h, boxstyle="round,pad=0,rounding_size=2",
            facecolor=color, edgecolor=EDGE, lw=1.5, zorder=1))
        # winner badge (gold pip on the left edge)
        if winner:
            ax.add_patch(FancyBboxPatch(
                (7, y), 2.4, h, boxstyle="round,pad=0,rounding_size=1",
                facecolor=GOLD, edgecolor="none", zorder=2))
        # name sits a touch high so Power/record/class rank rides beneath it
        _ny = y + h / 2 + (2.6 if subline else 0)
        ax.text(13, _ny, _fit(name, 22), color=ink, fontsize=26,
                fontweight="bold", ha="left", va="center", zorder=3)
        if subline:
            ax.text(13, _ny - 5.0, subline, color=ink, fontsize=12.5,
                    ha="left", va="center", zorder=3, alpha=0.82)
        ax.text(88, y + h / 2, str(pts), color=ink, fontsize=50,
                fontweight="bold", ha="right", va="center", zorder=3)
        if winner:
            ax.text(88, y + h - 3.4, "WINNER", color=ink, fontsize=10.5,
                    fontweight="bold", ha="right", va="center", zorder=3,
                    alpha=0.82)

    # quarters on → shorter panels up top, leaving the lower third for the line;
    # quarters off → taller panels centred in the open space (no dead gap).
    if show_quarters:
        ph, gap, a_top = 21, 3, 61          # A: 61–82, B: 37–58
    else:
        ph, gap, a_top = 25, 6, 47          # A: 47–72, B: 16–41 (centred ~45)
    _team_panel(a_top, ph, a_name, a_pts, ca, a_pts > b_pts, a_line)
    _team_panel(a_top - ph - gap, ph, b_name, b_pts, cb, b_pts > a_pts, b_line)

    if show_quarters:
        per, qs = _quarter_points(game_id)
        if qs:
            _panel(ax, 7, 9.5, 86, 21)
            cols = qs[:5]                       # Q1–Q4 (+ up to one OT)
            n = len(cols) + 1                   # + total
            x0, x1 = 30, 90
            xs = [x0 + (x1 - x0) * (i + 0.5) / n for i in range(n)]
            hdr = [("Q" + str(q) if q <= 4 else "OT" + str(q - 4)) for q in cols] + ["T"]
            ax.text(11, 26.5, "BY QUARTER", color=GOLD, fontsize=12,
                    fontweight="bold", ha="left", va="center", zorder=2)
            for x, h in zip(xs, hdr):
                ax.text(x, 26.5, h, color=GREY, fontsize=13, fontweight="bold",
                        ha="center", va="center", zorder=2)
            for row_y, tid, nm, tot, clr in (
                    (20.5, a_id, a_name, a_pts, ca),
                    (14, b_id, b_name, b_pts, cb)):
                ax.add_patch(FancyBboxPatch(
                    (9, row_y - 2.4), 1.8, 4.8, boxstyle="round,pad=0,rounding_size=.6",
                    facecolor=clr, edgecolor="none", zorder=2))
                ax.text(13, row_y, _fit(nm, 16), color=FG, fontsize=13,
                        fontweight="bold", ha="left", va="center", zorder=2)
                for x, q in zip(xs, cols):
                    ax.text(x, row_y, str(per.get(tid, {}).get(q, 0)), color=FG,
                            fontsize=14, ha="center", va="center", zorder=2)
                ax.text(xs[-1], row_y, str(tot), color=GOLD, fontsize=14,
                        fontweight="bold", ha="center", va="center", zorder=2)
    _foot(ax)
    return _png(fig)


# ── card 2: season record ────────────────────────────────────────────────────
def season_record_png(team_id, gender):
    """Season-to-date card: record, power + class rank, streak, margin, the
    marquee wins and the top-3 players."""
    scored = TR.score_ratings(gender=gender)
    s = scored.get(team_id)
    if not s:
        return None
    games = _team_games(team_id)
    crank, cn = class_rank(scored, team_id)

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
    ax.text(50, 86.5, _fit(s["name"], 30), color=FG, fontsize=28, fontweight="bold",
            ha="center", va="center")
    ax.text(50, 81.5, f"Class {s.get('class', 'N/A')} · Season to date",
            color=GREY, fontsize=14, ha="center", va="center")

    # record — big, but leave room below for two stacked panels
    ax.text(30, 71, f"{s.get('W', 0)}–{s.get('L', 0)}", color=GOLD, fontsize=60,
            fontweight="bold", ha="center", va="center")
    ax.text(30, 62.5, "RECORD", color=GREY, fontsize=12.5, ha="center", va="center")

    # rank / streak / margin stat block beside the record
    rx = 66
    for i, (lbl, val, clr) in enumerate((
            ("POWER RANK", f"#{s.get('Rank', '—')} of {len(scored)}", GOLD),
            (f"CLASS {s.get('class', '')} RANK",
             f"#{crank} of {cn}" if crank else "—", GOLD),
            ("STREAK", streak or "—",
             GOOD if streak.startswith("W") else (BAD if streak else FG)),
            ("MARGIN / PPG",
             f"{s.get('MOV', 0):+.1f} · {s.get('PPG', 0):.0f}-{s.get('oPPG', 0):.0f}",
             GOOD if (s.get("MOV") or 0) >= 0 else BAD))):
        yy = 75 - i * 6.6
        ax.text(rx, yy, val, color=clr, fontsize=18, fontweight="bold",
                ha="left", va="center")
        ax.text(rx, yy - 3, lbl, color=GREY, fontsize=10, ha="left", va="center")

    # ── marquee wins — the best three by opponent power rank (lower = better) ──
    wins = [gm for gm in games if gm["won"]]
    for gm in wins:
        opp = scored.get(gm["opp_id"], {})
        gm["_opp_rank"] = opp.get("Rank")
    ranked_wins = sorted(
        [gm for gm in wins if gm.get("_opp_rank")],
        key=lambda gm: gm["_opp_rank"])[:3]
    if ranked_wins:
        _panel(ax, 8, 27, 84, 25)           # extends lower so text isn't flush
        ax.text(12, 48.3, "SIGNATURE WINS", color=GOLD, fontsize=12.5,
                fontweight="bold", ha="left", va="center", zorder=2)
        y = 42.5
        for gm in ranked_wins:
            ax.text(12, y, f"{gm['pf']}–{gm['pa']}  vs {_fit(gm['opp'], 24)}",
                    color=FG, fontsize=15, fontweight="bold", ha="left",
                    va="center", zorder=2)
            ax.text(88, y, f"power #{gm['_opp_rank']} · {gm['date']}",
                    color=GREY, fontsize=12.5, ha="right", va="center", zorder=2)
            y -= 5.6

    # ── top 3 players — OVERALL (fallback: scoring) ──────────────────────────
    table = PR.player_stat_table(gender=gender, min_games=1)
    mine = [r for r in table.values() if r.get("team_id") == team_id]
    rated = [r for r in mine if r.get("OVERALL") is not None]
    if rated:
        top = sorted(rated, key=lambda r: -r["OVERALL"])[:3]
    else:
        top = sorted(mine, key=lambda r: -(r.get("PPG") or 0))[:3]
    if top:
        _panel(ax, 8, 6.5, 84, 21.5)        # extends lower so text isn't flush
        ax.text(12, 24.5, "TOP PLAYERS", color=GOLD, fontsize=12.5,
                fontweight="bold", ha="left", va="center", zorder=2)
        y = 19.5
        for r in top:
            ax.text(12, y, f"#{r.get('number', '')} {_fit(r['name'], 22)}",
                    color=FG, fontsize=15, fontweight="bold", ha="left",
                    va="center", zorder=2)
            line = (f"{(r.get('PPG') or 0):.1f} PPG · {(r.get('RPG') or 0):.1f} REB · "
                    f"{(r.get('APG') or 0):.1f} AST")
            if r.get("OVERALL") is not None:
                line += f" · {r['OVERALL']:.0f} OVR"
            ax.text(88, y, line, color=GREY, fontsize=12.5, ha="right",
                    va="center", zorder=2)
            y -= 5.3
    _foot(ax)
    return _png(fig)


# ── card 3: a selected group of games ────────────────────────────────────────
def games_png(team_id, gender, game_ids=None, n=5, title=None):
    """Record + margin over a chosen set of games, the full results strip (every
    selected game shown) and the player of the run (top scorer over the TRACKED
    games in the set). `game_ids` = an explicit selection (schedule multiselect);
    None → the last `n`. Newest → oldest in the strip."""
    games = _team_games(team_id)
    if not games:
        return None
    if game_ids:
        want = set(game_ids)
        chosen = [gm for gm in games if gm["id"] in want]
    else:
        chosen = games[-n:]
    if not chosen:
        return None
    # newest first for the strip; win/margin are order-independent
    chosen = sorted(chosen, key=lambda gm: (gm["date"], gm["id"]), reverse=True)
    w = sum(1 for gm in chosen if gm["won"])
    l = len(chosen) - w
    margin = sum(gm["pf"] - gm["pa"] for gm in chosen) / len(chosen)
    name = query("SELECT name FROM teams WHERE id=?", (team_id,))
    tname = name[0]["name"] if name else f"#{team_id}"
    scored = TR.score_ratings(gender=gender) if gender else {}
    chips = rank_line(scored, team_id, record=False)   # Power + class rank

    fig, ax = _fig()
    _brand(ax, f"{len(chosen)} games")
    ax.text(50, 88, _fit(tname, 30), color=FG, fontsize=28, fontweight="bold",
            ha="center", va="center")
    if chips:
        ax.text(50, 83.2, chips, color=GREY, fontsize=13, ha="center",
                va="center")
    # the coach's own label for the set (tournament / stretch name), else a count
    ax.text(50, 78.4, title or f"{len(chosen)} selected games",
            color=GOLD if title else GREY,
            fontsize=15 if title else 14,
            fontweight="bold" if title else "normal",
            ha="center", va="center")

    ax.text(30, 71.5, f"{w}–{l}", color=GOLD, fontsize=56, fontweight="bold",
            ha="center", va="center")
    ax.text(30, 63, "RECORD", color=GREY, fontsize=12.5, ha="center", va="center")
    ax.text(70, 71.5, f"{margin:+.1f}", color=(GOOD if margin >= 0 else BAD),
            fontsize=56, fontweight="bold", ha="center", va="center")
    ax.text(70, 63, "AVG MARGIN", color=GREY, fontsize=12.5, ha="center",
            va="center")

    # results strip — every selected game (cap 10 rows for legibility), the row
    # height adapting to how many there are so the panel always fills cleanly.
    rows = chosen[:10]
    ph = 45.5                                    # panel height budget
    _panel(ax, 8, 10, 84, ph)
    top, bot = 51, 13.5
    step = (top - bot) / max(len(rows) - 1, 1) if len(rows) > 1 else 0
    y = top if len(rows) > 1 else (top + bot) / 2
    fs = 15 if len(rows) <= 6 else (13 if len(rows) <= 8 else 12)
    for gm in rows:
        clr = GOOD if gm["won"] else BAD
        ax.text(12, y, "W" if gm["won"] else "L", color=clr, fontsize=fs,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.text(16.5, y, f"{gm['pf']}–{gm['pa']}  vs {_fit(gm['opp'], 26)}",
                color=FG, fontsize=fs, ha="left", va="center", zorder=2)
        ax.text(88, y, gm["date"], color=GREY, fontsize=fs - 2, ha="right",
                va="center", zorder=2)
        y -= step
    if len(chosen) > len(rows):
        ax.text(88, bot - 3, f"+{len(chosen) - len(rows)} more", color=GREY,
                fontsize=11, ha="right", va="center", zorder=2)
    _foot(ax)
    return _png(fig)
