"""
social_cards.py — premade share graphics for social media (PNG, 1080×1080).

Coach-facing "post this" cards rendered with matplotlib Agg (the court_png.py
engine — zero new dependencies, renders identically on the VPS): a branded dark
canvas in the app palette with the numbers dropped in. Three cards:

  game_result_png(game_id, team_id …)  — head-to-head score, ranks, quarters
  season_record_png(team_id, gender …) — record, power/class rank, wins, players
  games_png(team_id, gender, ids …)    — a selected set: record, margin, results

Every card takes an optional `bg` background colour; the palette
(_theme) adapts text / panel / accent contrast to it.

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
import helpers.seasons as SEAS

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


def _mix(c1, c2, t):
    """Blend hex `c1` → `c2` by fraction `t` (0..1)."""
    a = c1.lstrip("#")
    b = c2.lstrip("#")
    r = tuple(round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t)
              for i in (0, 2, 4))
    return "#%02x%02x%02x" % r


def _theme(bg):
    """A card palette derived from the chosen background colour so text and panels
    keep their contrast on any bg (dark → light text, light → dark text). Brand
    gold is kept as-is. Returns bg/fg/grey/panel/edge."""
    bg = _norm_hex(bg, BG)
    ink = _ink(bg)                              # near-white or near-black
    dark = ink == "#ffffff"                     # bg is dark → light text
    fg = "#f0f6fc" if dark else "#0d1117"
    return {
        "bg": bg,
        "fg": fg,
        "grey": _mix(fg, bg, 0.42),             # secondary text
        "panel": _mix(bg, fg, 0.09),            # subtly raised card
        "edge": _mix(bg, fg, 0.22),
        # brand gold reads on dark; on a light bg darken it so the data accents
        # (record, ranks, section headers) don't wash out gold-on-light.
        "accent": GOLD if dark else "#9a6400",
    }


def _fig(bg=BG):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(_W, _W), dpi=100)
    fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.set_facecolor(bg)
    return fig, ax


def _brand(ax, kicker, bg=BG, grey=GREY):
    """Top brand bar: ball mark + wordmark left, card kicker right, gold rule.
    `bg` fills the mark cut-outs so it reads on any card background."""
    from matplotlib.patches import Circle
    # the "tracked path → ball" mark, simplified for raster
    pts = [(4.2, 93.4), (5.9, 95.0), (7.3, 93.9)]
    for i in range(len(pts) - 1):
        ax.plot([pts[i][0], pts[i + 1][0]], [pts[i][1], pts[i + 1][1]],
                color=GOLD, lw=2.4, solid_capstyle="round", zorder=3)
    for p in pts:
        ax.add_patch(Circle(p, 0.42, facecolor=bg, edgecolor=GOLD, lw=1.6, zorder=4))
    ball = Circle((9.4, 94.4), 1.15, facecolor=GOLD, edgecolor=GOLD, zorder=4)
    ax.add_patch(ball)
    ax.plot([8.25, 10.55], [94.4, 94.4], color=bg, lw=1.1, zorder=5)
    ax.plot([9.4, 9.4], [93.25, 95.55], color=bg, lw=1.1, zorder=5)
    ax.text(11.5, 94.4, "HOOPTRACKS", color=GOLD, fontsize=21,
            fontweight="bold", va="center", ha="left")
    ax.text(96, 94.4, kicker.upper(), color=grey, fontsize=14,
            va="center", ha="right", fontweight="bold")
    ax.plot([4, 96], [91.2, 91.2], color=GOLD, lw=2.5)


def _foot(ax, grey=GREY, edge=EDGE):
    ax.plot([4, 96], [5.4, 5.4], color=edge, lw=1.2)
    ax.text(50, 3.2, "app.hooptracks.com", color=grey, fontsize=12,
            ha="center", va="center")


def _panel(ax, x, y, w, h, panel=PANEL, edge=EDGE):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.4",
        facecolor=panel, edgecolor=edge, lw=1.2, zorder=1))


def _place_logo(ax, img_bytes, cx, cy, max_w, max_h, zorder=5):
    """Draw a coach-uploaded logo centred at (cx, cy), fit inside a max_w × max_h
    data-unit box with aspect preserved. Silently no-ops on a bad image. The
    bytes are used in-memory only — nothing is written to disk."""
    if not img_bytes:
        return
    try:
        import numpy as np
        from PIL import Image
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        im = Image.open(io.BytesIO(img_bytes))
        im.thumbnail((600, 600))                 # cap work for big uploads
        im = im.convert("RGBA")
    except Exception:
        return
    iw, ih = im.size
    if not iw or not ih:
        return
    ppu = 1080 / 100.0                            # px per data unit (1080px / 100)
    zoom = min(max_w * ppu / iw, max_h * ppu / ih)
    oi = OffsetImage(np.asarray(im), zoom=zoom)
    ax.add_artist(AnnotationBbox(
        oi, (cx, cy), frameon=False, box_alignment=(0.5, 0.5),
        pad=0, zorder=zorder))


def _tile(ax, cx, cy, label, value, color=FG, vsize=27):
    ax.text(cx, cy + 2.4, str(value), color=color, fontsize=vsize,
            fontweight="bold", ha="center", va="center", zorder=2)
    ax.text(cx, cy - 3.0, label.upper(), color=GREY, fontsize=11.5,
            ha="center", va="center", zorder=2)


def _fit(name, limit=26):
    n = str(name)
    return n if len(n) <= limit else n[:limit - 1] + "…"


def _team_label(name, base_fs, fit_chars):
    """(text, fontsize) for a team name that ALWAYS shows in full — never an
    ellipsis. Fits at `base_fs` when short enough; a long name first drops its
    redundant ' Girls'/' Boys' suffix (every team carries it), then shrinks the
    font as a last resort so the whole name still fits the width."""
    s = str(name)
    if len(s) <= fit_chars:
        return s, base_fs
    for suf in (" Girls", " Boys"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    if len(s) <= fit_chars:
        return s, base_fs
    return s, max(base_fs * fit_chars / len(s), base_fs * 0.55)


def _shrink(text, base_fs, fit_chars, floor=0.5):
    """Font size that keeps a freeform string (a coach's card headline) fully on
    the card — shrinks past `fit_chars`, never truncates. Text stays unchanged."""
    n = len(str(text))
    return base_fs if n <= fit_chars else max(base_fs * fit_chars / n,
                                              base_fs * floor)


def _row_name(prefix, name, base_fs, fit_chars):
    """(text, fontsize) for a 'prefix + team name' list row that always shows in
    full: drops the redundant gender suffix if the combined line is too long,
    then shrinks the font — never an ellipsis."""
    full = prefix + str(name)
    if len(full) <= fit_chars:
        return full, base_fs
    nm = str(name)
    for suf in (" Girls", " Boys"):
        if nm.endswith(suf):
            nm = nm[:-len(suf)]
            break
    full = prefix + nm
    if len(full) <= fit_chars:
        return full, base_fs
    return full, max(base_fs * fit_chars / len(full), base_fs * 0.55)


def _png(fig):
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    # honour the figure's own background (set per card by _fig(bg))
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), dpi=100)
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
                    show_quarters=False, gender=None, title=None, bg=None,
                    logo_a=None, logo_b=None, season="Current", manual=None):
    """Head-to-head final-score card: two team-colour panels (same treatment for
    both), the score, each team's Power/record/class-rank line, an optional
    coach headline (`title`, e.g. "Region Championship") and an optional
    quarter-by-quarter line. `team_id` is the dashboard team → shown on top;
    `color_a`/`color_b` are its / the opponent's panel colours (defaults derived
    from team id); `bg` sets the card background (default dark). `logo_a`/`logo_b`
    are optional in-memory image bytes drawn on each panel (never persisted).
    None if game not finished.

    `manual` — build the card from coach-typed values instead of a DB game:
    {"b_id", "a_pts", "b_pts", "date", "location"(opt)} with `team_id` = team A
    (top panel). No quarter line (there are no events), rank chips still come
    from the season's ratings. game_id is ignored (pass 0)."""
    from matplotlib.patches import FancyBboxPatch
    T = _theme(bg or BG)
    _BG, FG, GREY, PANEL, EDGE, GOLD = (T["bg"], T["fg"], T["grey"],
                                        T["panel"], T["edge"], T["accent"])
    scored = TR.score_ratings(gender=gender, season=season) if gender else {}
    if manual is not None:
        show_quarters = False                       # no events behind the score
        a_id, b_id = team_id, manual["b_id"]
        _nm = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM teams WHERE id IN (?,?)", (a_id, b_id))}
        a_name = _nm.get(a_id, f"#{a_id}")
        b_name = _nm.get(b_id, f"#{b_id}")
        a_pts, b_pts = int(manual["a_pts"]), int(manual["b_pts"])
        sub = str(manual.get("date") or "")
        if manual.get("location"):
            sub = f"{sub} · {manual['location']}" if sub else manual["location"]
    else:
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
        sub = g["date"] or ""
        if g.get("location"):
            sub = f"{sub} · {g['location']}" if sub else g["location"]
    ca = _norm_hex(color_a, default_team_color(a_id))
    cb = _norm_hex(color_b, default_team_color(b_id))

    fig, ax = _fig(_BG)
    _brand(ax, "final score", bg=_BG, grey=GREY)
    # coach headline (optional) rides above the date; both centred at the top
    title = (title or "").strip()
    if title:
        ax.text(50, 88, title, color=GOLD, fontsize=_shrink(title, 16, 34),
                fontweight="bold", ha="center", va="center")
        if sub:
            ax.text(50, 83.4, sub, color=GREY, fontsize=12.5, ha="center",
                    va="center")
    elif sub:
        ax.text(50, 87.5, sub, color=GREY, fontsize=13, ha="center", va="center")

    a_line = rank_line(scored, a_id)
    b_line = rank_line(scored, b_id)

    # two team panels — identical geometry, each filled in its team colour so
    # the card reads the same for either side.
    def _team_panel(y, h, name, pts, color, winner, subline, logo):
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
        # optional coach-uploaded logo on the left; the name slides right for it
        name_x, fit = 13, 22
        if logo:
            _place_logo(ax, logo, 18, y + h / 2, max_w=15, max_h=h * 0.64)
            name_x, fit = 28, 16
        # name sits a touch high so Power/record/class rank rides beneath it
        _ny = y + h / 2 + (2.6 if subline else 0)
        _nm, _nfs = _team_label(name, 26, fit)
        ax.text(name_x, _ny, _nm, color=ink, fontsize=_nfs,
                fontweight="bold", ha="left", va="center", zorder=3)
        if subline:
            ax.text(name_x, _ny - 5.0, subline, color=ink, fontsize=12.5,
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
    _team_panel(a_top, ph, a_name, a_pts, ca, a_pts > b_pts, a_line, logo_a)
    _team_panel(a_top - ph - gap, ph, b_name, b_pts, cb, b_pts > a_pts, b_line,
                logo_b)

    if show_quarters:
        per, qs = _quarter_points(game_id)
        if qs:
            _panel(ax, 7, 9.5, 86, 21, panel=PANEL, edge=EDGE)
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
                _qnm, _qfs = _team_label(nm, 13, 16)
                ax.text(13, row_y, _qnm, color=FG, fontsize=_qfs,
                        fontweight="bold", ha="left", va="center", zorder=2)
                for x, q in zip(xs, cols):
                    ax.text(x, row_y, str(per.get(tid, {}).get(q, 0)), color=FG,
                            fontsize=14, ha="center", va="center", zorder=2)
                ax.text(xs[-1], row_y, str(tot), color=GOLD, fontsize=14,
                        fontweight="bold", ha="center", va="center", zorder=2)
    _foot(ax, grey=GREY, edge=EDGE)
    return _png(fig)


# ── card 2: season record ────────────────────────────────────────────────────
def season_record_png(team_id, gender, bg=None, season="Current"):
    """Season-to-date card: record, power + class rank, streak, margin, the
    marquee wins and the top-3 players. `bg` sets the card background (defaults
    to the team's colour, resolved by the caller). `season` scopes the whole
    card — record, ranks, wins and player table — to one season (archive views
    make a past-season card, e.g. a program's history post)."""
    T = _theme(bg or default_team_color(team_id))
    _BG, FG, GREY, PANEL, EDGE, GOLD = (T["bg"], T["fg"], T["grey"],
                                        T["panel"], T["edge"], T["accent"])
    scored = TR.score_ratings(gender=gender, season=season)
    s = scored.get(team_id)
    if not s:
        return None
    games = _team_games(team_id, season=season)
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

    fig, ax = _fig(_BG)
    _brand(ax, "season report", bg=_BG, grey=GREY)
    _hn, _hfs = _team_label(s["name"], 28, 30)
    ax.text(50, 86.5, _hn, color=FG, fontsize=_hfs, fontweight="bold",
            ha="center", va="center")
    _szn_lbl = ("Season to date" if SEAS.is_current(season)
                else f"{season} season")
    ax.text(50, 81.5, f"Class {s.get('class', 'N/A')} · {_szn_lbl}",
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

    # ── top 3 players — OVERALL (fallback: scoring) ──────────────────────────
    # the player table reads the season's tracked pool (None = current default)
    _pgids = (None if SEAS.is_current(season)
              else set(SEAS.game_pool(season, gender=gender, tracked_only=True)))
    table = PR.player_stat_table(gender=gender, min_games=1, game_ids=_pgids)
    mine = [r for r in table.values() if r.get("team_id") == team_id]
    rated = [r for r in mine if r.get("OVERALL") is not None]
    if rated:
        top = sorted(rated, key=lambda r: -r["OVERALL"])[:3]
    else:
        top = sorted(mine, key=lambda r: -(r.get("PPG") or 0))[:3]

    # ── one panel holds both sections (Signature Wins over Top Players), so the
    #    boxes never collide and clear the stat block above. Top edge sits below
    #    the MARGIN/PPG label; a thin rule splits the two halves.
    if ranked_wins or top:
        _panel(ax, 8, 7, 84, 43, panel=PANEL, edge=EDGE)   # 7 → 50
        if ranked_wins:
            ax.text(12, 46, "SIGNATURE WINS", color=GOLD, fontsize=12.5,
                    fontweight="bold", ha="left", va="center", zorder=2)
            y = 40.6
            for gm in ranked_wins:
                # the OPPONENT's identity: their class rank, power rank, date
                orank = gm["_opp_rank"]
                ocr, _ocn = class_rank(scored, gm["opp_id"])
                ocls = scored.get(gm["opp_id"], {}).get("class", "")
                meta = (f"{ocls} #{ocr} · " if ocr else "") + \
                       f"power #{orank} · {gm['date']}"
                _rt, _rfs = _row_name(f"{gm['pf']}–{gm['pa']}  vs ",
                                      gm["opp"], 14.5, 32)
                ax.text(12, y, _rt, color=FG, fontsize=_rfs, fontweight="bold",
                        ha="left", va="center", zorder=2)
                ax.text(88, y, meta, color=GREY, fontsize=12, ha="right",
                        va="center", zorder=2)
                y -= 4.9
        if ranked_wins and top:
            ax.plot([12, 88], [27.6, 27.6], color=EDGE, lw=1, zorder=2)
        if top:
            ax.text(12, 23.5, "TOP PLAYERS", color=GOLD, fontsize=12.5,
                    fontweight="bold", ha="left", va="center", zorder=2)
            y = 18.4
            for r in top:
                _pt, _pfs = _row_name(f"#{r.get('number', '')} ", r["name"],
                                      14.5, 26)
                ax.text(12, y, _pt, color=FG, fontsize=_pfs, fontweight="bold",
                        ha="left", va="center", zorder=2)
                line = (f"{(r.get('PPG') or 0):.1f} PPG · {(r.get('RPG') or 0):.1f} REB · "
                        f"{(r.get('APG') or 0):.1f} AST")
                if r.get("OVERALL") is not None:
                    line += f" · {r['OVERALL']:.0f} OVR"
                ax.text(88, y, line, color=GREY, fontsize=12, ha="right",
                        va="center", zorder=2)
                y -= 4.9
    _foot(ax, grey=GREY, edge=EDGE)
    return _png(fig)


# ── card 3: a selected group of games ────────────────────────────────────────
def games_png(team_id, gender, game_ids=None, n=5, title=None, bg=None,
              season="Current"):
    """Record + margin over a chosen set of games, the full results strip (every
    selected game shown) and the player of the run (top scorer over the TRACKED
    games in the set). `game_ids` = an explicit selection (schedule multiselect);
    None → the last `n`. Newest → oldest in the strip. `bg` sets the card
    background (defaults to the team's colour, resolved by the caller)."""
    T = _theme(bg or default_team_color(team_id))
    _BG, FG, GREY, PANEL, EDGE, GOLD = (T["bg"], T["fg"], T["grey"],
                                        T["panel"], T["edge"], T["accent"])
    games = _team_games(team_id, season=season)
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
    scored = TR.score_ratings(gender=gender, season=season) if gender else {}
    chips = rank_line(scored, team_id, record=False)   # Power + class rank

    fig, ax = _fig(_BG)
    _brand(ax, f"{len(chosen)} games", bg=_BG, grey=GREY)
    _hn, _hfs = _team_label(tname, 28, 30)
    ax.text(50, 88, _hn, color=FG, fontsize=_hfs, fontweight="bold",
            ha="center", va="center")
    if chips:
        ax.text(50, 83.2, chips, color=GREY, fontsize=13, ha="center",
                va="center")
    # the coach's own label for the set (tournament / stretch name), else a count
    _sub = title or f"{len(chosen)} selected games"
    ax.text(50, 78.4, _sub, color=GOLD if title else GREY,
            fontsize=_shrink(_sub, 15, 40) if title else 14,
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
    _panel(ax, 8, 10, 84, ph, panel=PANEL, edge=EDGE)
    top, bot = 51, 13.5
    step = (top - bot) / max(len(rows) - 1, 1) if len(rows) > 1 else 0
    y = top if len(rows) > 1 else (top + bot) / 2
    fs = 15 if len(rows) <= 6 else (13 if len(rows) <= 8 else 12)
    for gm in rows:
        clr = GOOD if gm["won"] else BAD
        ax.text(12, y, "W" if gm["won"] else "L", color=clr, fontsize=fs,
                fontweight="bold", ha="left", va="center", zorder=2)
        _rt, _rfs = _row_name(f"{gm['pf']}–{gm['pa']}  vs ", gm["opp"], fs, 30)
        ax.text(16.5, y, _rt, color=FG, fontsize=_rfs, ha="left", va="center",
                zorder=2)
        # opponent identity on the right: their class rank · power rank · date
        ocr, _ocn = class_rank(scored, gm["opp_id"])
        ocls = scored.get(gm["opp_id"], {}).get("class", "")
        opw = scored.get(gm["opp_id"], {}).get("Rank")
        meta = (f"{ocls} #{ocr} · " if ocr else "") + \
               (f"pwr #{opw} · " if opw else "") + gm["date"]
        ax.text(88, y, meta, color=GREY, fontsize=fs - 2.5, ha="right",
                va="center", zorder=2)
        y -= step
    if len(chosen) > len(rows):
        ax.text(88, bot - 3, f"+{len(chosen) - len(rows)} more", color=GREY,
                fontsize=11, ha="right", va="center", zorder=2)
    _foot(ax, grey=GREY, edge=EDGE)
    return _png(fig)


# ── card 4: player spotlight (career / season / game / stretch) ──────────────
def _pid_game_rows(pid):
    """[{game_id,date,opp,box}] — a player row's TRACKED games, oldest first.
    One players.id = one season (rollover archives rows) — but the default
    event pass only covers season='Current', so an ARCHIVED row must fetch its
    OWN season's tracked games explicitly or it reads zero games."""
    prow = query("SELECT team_id, season FROM players WHERE id=?", (pid,))
    tid = prow[0]["team_id"] if prow else None
    szn = (prow[0]["season"] if prow else None) or "Current"
    season_gids = [r["id"] for r in query(
        "SELECT id FROM games WHERE tracked=1 AND season=?", (szn,))]
    if not season_gids:
        return []
    boxes = S.player_game_boxes(game_ids=season_gids).get(pid, {})
    if not boxes:
        return []
    gids = list(boxes)
    ph = ",".join("?" * len(gids))
    gmeta = {r["id"]: r for r in query(
        f"""SELECT g.id, g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
            FROM games g JOIN teams t1 ON t1.id=g.team1_id
                         JOIN teams t2 ON t2.id=g.team2_id
            WHERE g.id IN ({ph})""", tuple(gids))}
    rows = []
    for gid, b in boxes.items():
        m = gmeta.get(gid)
        if not m:
            continue
        rows.append({"game_id": gid, "date": m["date"],
                     "opp": m["n2"] if m["team1_id"] == tid else m["n1"],
                     "box": b})
    rows.sort(key=lambda r: (r["date"] or "", r["game_id"]))
    return rows


def _sum_boxes(boxes):
    out = {}
    for b in boxes:
        for k, v in b.items():
            if isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + v
    return out


def player_spotlight_png(player_id, mode="season", n=5, game_id=None, bg=None):
    """Player spotlight card. Modes:
      'season'  — this player row's season line (tracked + entered boxes)
      'career'  — the person's identity chain: season-by-season + totals
      'game'    — one tracked game (game_id, default the newest)
      'stretch' — the last `n` tracked games
    Box-stat assembly only (PTS/REB/AST/STL/BLK + shooting) — real numbers,
    no ratings, so it renders for free-tier data too. None when no games."""
    import helpers.identity as ID
    import helpers.manual_box as MB
    p = query("""SELECT p.id, p.name, p.number, p.team_id, p.season,
                        p.identity_id, t.name AS team, t.class AS klass
                 FROM players p JOIN teams t ON t.id=p.team_id
                 WHERE p.id=?""", (player_id,))
    if not p:
        return None
    p = p[0]
    T = _theme(bg or default_team_color(p["team_id"]))
    _BG, FG, GREY, PANEL, EDGE, GOLD = (T["bg"], T["fg"], T["grey"],
                                        T["panel"], T["edge"], T["accent"])
    grows = _pid_game_rows(player_id)

    # ── assemble the headline line + the panel rows per mode ────────────────
    panel_hdr, panel_rows = "", []          # [(left, right)] strings
    big_lbl = "PPG"
    if mode == "career":
        pk = p["identity_id"] or p["id"]
        hist = ID.identity_history(pk) or [dict(p, archived=0)]
        tnames = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
        season_lines = []
        for h in hist:
            ln = MB.combined_player_line(h["id"])
            if ln:
                season_lines.append((h, ln))
        if not season_lines:
            return None
        gp = sum(ln["gp"] for _, ln in season_lines)
        tot = {k: sum(ln.get(k, 0) for _, ln in season_lines)
               for k in ("PTS", "TRB", "AST", "STL", "BLK",
                         "FGM", "FGA", "3PM", "3PA", "FTM", "FTA")}
        line = {"gp": gp,
                "PPG": tot["PTS"] / gp, "RPG": tot["TRB"] / gp,
                "APG": tot["AST"] / gp, "SPG": tot["STL"] / gp,
                "BPG": tot["BLK"] / gp,
                "FG%": 100 * tot["FGM"] / tot["FGA"] if tot["FGA"] else 0,
                "3P%": 100 * tot["3PM"] / tot["3PA"] if tot["3PA"] else 0,
                "FT%": 100 * tot["FTM"] / tot["FTA"] if tot["FTA"] else 0}
        _ns = len(season_lines)
        sub = f"Career · {_ns} season{'s' if _ns != 1 else ''} · {gp} games"
        panel_hdr = "SEASON BY SEASON"
        panel_rows.append((
            "Career totals",
            f"{tot['PTS']} pts · {tot['TRB']} reb · {tot['AST']} ast"))
        for h, ln in season_lines:
            szn = h.get("season") or "Current"
            panel_rows.append((
                f"{szn} · {_fit(tnames.get(h['team_id'], ''), 20)}",
                f"{ln['gp']} GP · {ln['PPG']:.1f} / {ln['RPG']:.1f} / "
                f"{ln['APG']:.1f}"))
    elif mode == "game":
        row = None
        if game_id is not None:
            row = next((r for r in grows if r["game_id"] == game_id), None)
        elif grows:
            row = grows[-1]
        if not row:
            return None
        b = row["box"]
        gp = 1
        line = {"gp": 1, "PPG": b.get("PTS", 0), "RPG": b.get("TRB", 0),
                "APG": b.get("AST", 0), "SPG": b.get("STL", 0),
                "BPG": b.get("BLK", 0), "TOV": b.get("TOV", 0),
                "FG%": 100 * b.get("FGM", 0) / b["FGA"] if b.get("FGA") else 0,
                "3P%": 100 * b.get("3PM", 0) / b["3PA"] if b.get("3PA") else 0,
                "FT%": 100 * b.get("FTM", 0) / b["FTA"] if b.get("FTA") else 0}
        big_lbl = "PTS"
        sub = f"{row['date']} vs {_fit(row['opp'], 24)}"
        panel_hdr = "THE LINE"

        def _shootrow(lbl, m, a):
            pct = f" · {100 * m / a:.0f}%" if a else ""
            return (lbl, f"{m}-{a}{pct}")
        panel_rows = [
            _shootrow("Field goals", b.get("FGM", 0), b.get("FGA", 0)),
            _shootrow("Three-pointers", b.get("3PM", 0), b.get("3PA", 0)),
            _shootrow("Free throws", b.get("FTM", 0), b.get("FTA", 0)),
            ("Rebounds", f"{b.get('TRB', 0)}  ({b.get('ORB', 0)} off · "
                         f"{b.get('DRB', 0)} def)"),
            ("Stocks", f"{b.get('STL', 0)} stl · {b.get('BLK', 0)} blk"),
            ("Turnovers · fouls", f"{b.get('TOV', 0)} · {b.get('PF', 0)}"),
        ]
    else:                                   # season / stretch
        if mode == "stretch":
            sel = grows[-int(n):]
            if not sel:
                return None
            tot = _sum_boxes([r["box"] for r in sel])
            gp = len(sel)
            line = {"gp": gp,
                    "PPG": tot.get("PTS", 0) / gp, "RPG": tot.get("TRB", 0) / gp,
                    "APG": tot.get("AST", 0) / gp, "SPG": tot.get("STL", 0) / gp,
                    "BPG": tot.get("BLK", 0) / gp,
                    "FG%": (100 * tot.get("FGM", 0) / tot["FGA"]
                            if tot.get("FGA") else 0),
                    "3P%": (100 * tot.get("3PM", 0) / tot["3PA"]
                            if tot.get("3PA") else 0),
                    "FT%": (100 * tot.get("FTM", 0) / tot["FTA"]
                            if tot.get("FTA") else 0)}
            sub = f"Last {gp} games"
            show = sel
        else:
            line = MB.combined_player_line(player_id)
            if not line:
                return None
            gp = line["gp"]
            _szn = p["season"]
            sub = (f"{_szn} season" if _szn and not SEAS.is_current(_szn)
                   else "Season to date")
            if line.get("manual_gp"):
                sub += (f" · {line['tracked_gp']} tracked + "
                        f"{line['manual_gp']} entered")
            show = grows[-5:]
        panel_hdr = "RECENT GAMES" if mode == "season" else "THE RUN"
        for r in reversed(show):
            b = r["box"]
            panel_rows.append((
                f"{r['date']}  vs {_fit(r['opp'], 22)}",
                f"{b.get('PTS', 0)} pts · {b.get('TRB', 0)} reb · "
                f"{b.get('AST', 0)} ast"))

    # ── draw — the player-profile banner grammar, card-sized ─────────────────
    from matplotlib.patches import FancyBboxPatch
    fig, ax = _fig(_BG)
    _brand(ax, "player spotlight", bg=_BG, grey=GREY)

    # HERO BANNER: number chip · name + identity · headline stat (profile look)
    _panel(ax, 4, 68.5, 92, 20.5, panel=PANEL, edge=_mix(GOLD, _BG, 0.45))
    # ghost jersey number behind the banner content (the profile watermark)
    ax.text(62, 78.5, f"#{p['number']}", color=FG, alpha=0.05, fontsize=80,
            fontweight="bold", ha="center", va="center", zorder=1)
    # number chip
    ax.add_patch(FancyBboxPatch(
        (7.5, 71.5), 12.5, 14.5, boxstyle="round,pad=0,rounding_size=1.2",
        facecolor=_mix(GOLD, _BG, 0.88), edgecolor=_mix(GOLD, _BG, 0.45),
        lw=1.6, zorder=2))
    ax.text(13.75, 83.2, "NO.", color=GREY, fontsize=10.5, ha="center",
            va="center", zorder=3)
    _numfs = 34 if len(str(p["number"])) <= 2 else 26
    ax.text(13.75, 77.2, f"{p['number']}", color=GOLD, fontsize=_numfs,
            fontweight="bold", ha="center", va="center", zorder=3)
    # name + identity + scope (left-aligned beside the chip)
    _hn, _hfs = _team_label(p["name"], 26, 22)
    ax.text(23, 83.3, _hn, color=FG, fontsize=_hfs, fontweight="bold",
            ha="left", va="center", zorder=3)
    ax.text(23, 78.2, f"{_fit(p['team'], 26)} · Class {p['klass'] or '—'}",
            color=GREY, fontsize=13.5, ha="left", va="center", zorder=3)
    ax.text(23, 73.6, sub.upper(), color=GOLD, fontsize=12,
            fontweight="bold", ha="left", va="center", zorder=3)
    # headline stat, big on the right (the profile's OVERALL slot)
    _one = big_lbl == "PTS"
    ax.text(87, 80.6, f"{line['PPG']:.0f}" if _one else f"{line['PPG']:.1f}",
            color=GOLD, fontsize=46, fontweight="bold", ha="center",
            va="center", zorder=3)
    ax.text(87, 74.2, big_lbl, color=GREY, fontsize=12, ha="center",
            va="center", zorder=3)

    # STAT STRIP — 8 tiles across the full width (two rows of four)
    for i, (lbl, val) in enumerate((
            ("REB", f"{line['RPG']:.0f}" if _one else f"{line['RPG']:.1f}"),
            ("AST", f"{line['APG']:.0f}" if _one else f"{line['APG']:.1f}"),
            ("STL", f"{line['SPG']:.0f}" if _one else f"{line['SPG']:.1f}"),
            ("BLK", f"{line['BPG']:.0f}" if _one else f"{line['BPG']:.1f}"))):
        _tile(ax, 15.5 + i * 23, 62, lbl, val, color=FG, vsize=30)
    # last tile: GP for multi-game scopes, turnovers for a single game
    _last = (("TO", f"{line.get('TOV', 0):.0f}") if _one else ("GP", f"{gp}"))
    for i, (lbl, val) in enumerate((
            ("FG%", f"{line['FG%']:.0f}"), ("3P%", f"{line['3P%']:.0f}"),
            ("FT%", f"{line['FT%']:.0f}"), _last)):
        _tile(ax, 15.5 + i * 23, 52.5, lbl, val, color=FG, vsize=30)

    # BOTTOM PANEL — rows sized to FILL the box (no dead space on short lists)
    if panel_rows:
        _panel(ax, 4, 7, 92, 39.5, panel=PANEL, edge=EDGE)
        ax.text(8, 43, panel_hdr, color=GOLD, fontsize=13,
                fontweight="bold", ha="left", va="center", zorder=2)
        ax.plot([8, 92], [41.2, 41.2], color=EDGE, lw=1.0, zorder=2)
        rows = panel_rows[:7]
        top, bottom = 38.6, 10.5
        # spacing grows on short lists but stays capped; the row block is
        # vertically centered so the panel never reads half-empty
        step = (min(8.0, (top - bottom) / max(len(rows) - 1, 1))
                if len(rows) > 1 else 0)
        band = step * (len(rows) - 1)
        y = top - ((top - bottom) - band) / 2
        # few rows → bigger type, so the box always reads full
        _lfs = 16.5 if len(rows) <= 4 else 14 if len(rows) <= 6 else 13
        _rfs = _lfs - 1
        for left, right in rows:
            ax.text(8, y, left, color=FG, fontsize=_lfs, fontweight="bold",
                    ha="left", va="center", zorder=2)
            ax.text(92, y, right, color=GREY, fontsize=_rfs, ha="right",
                    va="center", zorder=2)
            y -= step
        if len(panel_rows) > 7:
            ax.text(92, 8.6, f"+{len(panel_rows) - 7} more", color=GREY,
                    fontsize=11, ha="right", va="center", zorder=2)
    _foot(ax, grey=GREY, edge=EDGE)
    return _png(fig)
