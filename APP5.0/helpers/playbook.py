"""
playbook.py — saved whiteboard plays: compact store + print-ready SVG.

Engine for the Whiteboard's playbook save (Tier 3 item 24). Three concerns,
all founder-rule shaped (DB = living archive, stays SMALL):

  * compact_ops  — validate + shrink the component's stroke list before it
                   touches the DB: coords rounded to 0.1 ft, unknown op types
                   and junk fields dropped, per-play op cap.
  * save/list/get/delete_play — coach_plays CRUD, ALWAYS filtered by
                   coach_email (the coach_notes privacy model). Upsert by
                   (coach, name); per-coach play cap.
  * play_svg     — a vector rendering of a play (court + strokes) for the
                   printable scout sheet / downloads. Pure string building —
                   regenerated on demand so nothing rendered is ever stored.

No Streamlit. Script-testable end to end on a throwaway DB.
"""
from __future__ import annotations

import json
import math

from database.db import query, execute
import helpers.court_geom as CG

MAX_PLAYS_PER_COACH = 40
MAX_OPS_PER_PLAY = 400
MAX_PEN_POINTS = 400

_HALF_LEN = 42.0          # baseline → midcourt, feet (84 ft HS court)
_MARGIN = 1.5             # out-of-bounds margin the board draws with


# ── compaction / validation ──────────────────────────────────────────────────

def _r(v):
    """Round a coordinate to 0.1 ft (a compact, sub-inch grid)."""
    return round(float(v), 1)


def compact_ops(raw):
    """Sanitize one mode's op list from the component into the stored shape.
    Unknown types / malformed ops are dropped silently (client bugs must never
    corrupt the archive); coords round to 0.1 ft; caps applied."""
    out = []
    for o in (raw or [])[:MAX_OPS_PER_PLAY]:
        if not isinstance(o, dict):
            continue
        t = o.get("t")
        try:
            if t == "pen":
                pts = [[_r(p[0]), _r(p[1])]
                       for p in (o.get("pts") or [])[:MAX_PEN_POINTS]]
                if len(pts) >= 2:
                    out.append({"t": "pen", "c": str(o.get("c", ""))[:9],
                                "pts": pts})
            elif t in ("cut", "pass", "dribble", "screen"):
                out.append({"t": t, "c": str(o.get("c", ""))[:9],
                            "x1": _r(o["x1"]), "y1": _r(o["y1"]),
                            "x2": _r(o["x2"]), "y2": _r(o["y2"])})
            elif t in ("O", "X"):
                out.append({"t": t, "c": str(o.get("c", ""))[:9],
                            "x": _r(o["x"]), "y": _r(o["y"]),
                            "n": int(o.get("n", 1))})
            elif t == "ball":
                out.append({"t": "ball", "x": _r(o["x"]), "y": _r(o["y"])})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


# ── CRUD (always coach-scoped) ───────────────────────────────────────────────

def save_play(coach_email, name, mode, ops):
    """Upsert a named play for one coach. Returns None on success or a
    human-readable error string (cap hit / nothing to save / bad name)."""
    name = (name or "").strip()[:60]
    if not name:
        return "Give the play a name first."
    mode = "full" if mode == "full" else "half"
    clean = compact_ops(ops)
    if not clean:
        return "Nothing on the board to save."
    email = (coach_email or "").strip().lower()
    existing = query("SELECT id FROM coach_plays WHERE coach_email=? AND name=?",
                     (email, name))
    if not existing:
        n = query("SELECT COUNT(*) AS n FROM coach_plays WHERE coach_email=?",
                  (email,))[0]["n"]
        if n >= MAX_PLAYS_PER_COACH:
            return (f"{MAX_PLAYS_PER_COACH} saved plays max — delete one you "
                    "don't run anymore first.")
    blob = json.dumps(clean, separators=(",", ":"))
    if existing:
        execute("UPDATE coach_plays SET mode=?, ops=? WHERE id=?",
                (mode, blob, existing[0]["id"]))
    else:
        execute("INSERT INTO coach_plays (coach_email, name, mode, ops) "
                "VALUES (?,?,?,?)", (email, name, mode, blob))
    return None


def list_plays(coach_email):
    """[{id, name, mode, n_ops, created_at}] for one coach, newest first."""
    rows = query("SELECT id, name, mode, ops, created_at FROM coach_plays "
                 "WHERE coach_email=? ORDER BY id DESC",
                 ((coach_email or "").strip().lower(),))
    out = []
    for r in rows:
        try:
            n_ops = len(json.loads(r["ops"]))
        except Exception:
            n_ops = 0
        out.append({"id": r["id"], "name": r["name"], "mode": r["mode"],
                    "n_ops": n_ops, "created_at": r["created_at"]})
    return out


def get_play(coach_email, play_id):
    """{id, name, mode, ops(list)} or None — never another coach's play."""
    rows = query("SELECT id, name, mode, ops FROM coach_plays "
                 "WHERE id=? AND coach_email=?",
                 (play_id, (coach_email or "").strip().lower()))
    if not rows:
        return None
    r = rows[0]
    try:
        ops = json.loads(r["ops"])
    except Exception:
        ops = []
    return {"id": r["id"], "name": r["name"], "mode": r["mode"], "ops": ops}


def delete_play(coach_email, play_id):
    execute("DELETE FROM coach_plays WHERE id=? AND coach_email=?",
            (play_id, (coach_email or "").strip().lower()))


# ── SVG rendering (print embeds; mirrors the component's renderOp) ───────────

def _svg_arrowhead(x1, y1, x2, y2, color, sw):
    a = math.atan2(y2 - y1, x2 - x1)
    L, w = 1.3, 0.5
    p = ""
    for s in (-w, w):
        p += (f"<line x1='{x2:.2f}' y1='{y2:.2f}' "
              f"x2='{x2 - L * math.cos(a + s):.2f}' "
              f"y2='{y2 - L * math.sin(a + s):.2f}' "
              f"stroke='{color}' stroke-width='{sw}' "
              f"stroke-linecap='round'/>")
    return p


def _half_court_svg(tx):
    """One half court's lines inside transform `tx` (local frame: x across
    -25..25, y = feet from baseline, y UP handled by the caller's transform)."""
    G = CG
    hw = (G.X_MAX - G.X_MIN) / 2
    yj = G.HOOP_Y + G.CBREAK
    tj = math.atan2(G.CBREAK, G.CORNER_X)
    line = "#9aa0aa"
    s = f"<g transform='{tx}' stroke='{line}' fill='none' stroke-width='0.18'>"
    s += (f"<polyline points='-{hw},{_HALF_LEN} -{hw},0 {hw},0 "
          f"{hw},{_HALF_LEN}'/>")
    s += (f"<rect x='-{G.LANE_HW}' y='0' width='{2 * G.LANE_HW}' "
          f"height='{G.LANE_D}'/>")
    s += f"<circle cx='0' cy='{G.LANE_D}' r='{G.FT_R}'/>"
    # restricted arc + corner threes + arc
    s += (f"<path d='M {-G.RA_R} {G.HOOP_Y} A {G.RA_R} {G.RA_R} 0 0 0 "
          f"{G.RA_R} {G.HOOP_Y}'/>")
    s += (f"<line x1='-{G.CORNER_X}' y1='0' x2='-{G.CORNER_X}' y2='{yj:.2f}'/>"
          f"<line x1='{G.CORNER_X}' y1='0' x2='{G.CORNER_X}' y2='{yj:.2f}'/>")
    x0 = G.THREE_R * math.cos(math.pi - tj)
    y0 = G.HOOP_Y + G.THREE_R * math.sin(math.pi - tj)
    x1 = G.THREE_R * math.cos(tj)
    y1 = G.HOOP_Y + G.THREE_R * math.sin(tj)
    s += (f"<path d='M {x0:.2f} {y0:.2f} A {G.THREE_R} {G.THREE_R} 0 0 0 "
          f"{x1:.2f} {y1:.2f}'/>")
    # backboard + rim (gold)
    s += (f"<line x1='-3' y1='{G.HOOP_Y - 1.25}' x2='3' y2='{G.HOOP_Y - 1.25}' "
          f"stroke='#b8860b' stroke-width='0.28'/>")
    s += (f"<circle cx='0' cy='{G.HOOP_Y}' r='0.75' stroke='#b8860b' "
          f"stroke-width='0.22'/>")
    s += "</g>"
    return s


def play_svg(ops, mode="half", *, width_px=460, dark=False):
    """Standalone inline-SVG rendering of a play — court + strokes. Prints
    from the browser/WeasyPrint like the sheet's shot charts (xhtml2pdf just
    omits it, keeping the rest of the sheet). `dark=False` renders on white
    for paper."""
    G = CG
    court_w = G.X_MAX - G.X_MIN
    M = _MARGIN
    if mode == "full":
        w_ft, h_ft = 2 * _HALF_LEN + 2 * M, court_w + 2 * M
    else:
        w_ft, h_ft = court_w + 2 * M, _HALF_LEN + 2 * M
    height_px = int(width_px * h_ft / w_ft)
    bg = "#12141e" if dark else "#ffffff"
    ink = "#e6edf3" if dark else "#1a1e26"

    s = (f"<svg xmlns='http://www.w3.org/2000/svg' "
         f"viewBox='0 0 {w_ft:.1f} {h_ft:.1f}' "
         f"width='{width_px}' height='{height_px}'>"
         f"<rect width='{w_ft:.1f}' height='{h_ft:.1f}' fill='{bg}' rx='1'/>")
    # court: same frames the component uses (see 10_Whiteboard drawCourt)
    if mode == "half":
        # local y (feet up from baseline) → svg y down, baseline at bottom
        s += _half_court_svg(
            f"translate({M + court_w / 2},{M + _HALF_LEN}) scale(1,-1)")
        s += (f"<g stroke='#9aa0aa' fill='none' stroke-width='0.18'>"
              f"<line x1='{M}' y1='{M}' x2='{M + court_w}' y2='{M}'/>"
              f"<path d='M {M + court_w / 2 - G.FT_R} {M} "
              f"A {G.FT_R} {G.FT_R} 0 0 0 {M + court_w / 2 + G.FT_R} {M}'/></g>")
    else:
        cy = M + court_w / 2
        s += _half_court_svg(f"translate({M},{cy}) rotate(90) scale(1,-1)")
        s += _half_court_svg(
            f"translate({M + 2 * _HALF_LEN},{cy}) rotate(90)")
        mx = M + _HALF_LEN
        s += (f"<g stroke='#9aa0aa' fill='none' stroke-width='0.18'>"
              f"<line x1='{mx}' y1='{M}' x2='{mx}' y2='{M + court_w}'/>"
              f"<circle cx='{mx}' cy='{cy}' r='{G.FT_R}'/></g>")

    # strokes (component coords are already in the on-screen frame: feet from
    # the board's top-left including the margin — identical to the svg frame)
    sw = 0.32
    for o in compact_ops(ops):
        c = o.get("c") or ink
        if not str(c).startswith("#"):
            c = ink
        if c.lower() in ("#e6edf3", "#ffffff") and not dark:
            c = ink                          # white strokes need ink on paper
        t = o["t"]
        if t == "pen":
            pts = " ".join(f"{p[0]},{p[1]}" for p in o["pts"])
            s += (f"<polyline points='{pts}' fill='none' stroke='{c}' "
                  f"stroke-width='{sw}' stroke-linecap='round' "
                  f"stroke-linejoin='round'/>")
        elif t in ("O", "X"):
            x, y, r = o["x"], o["y"], 1.15
            if t == "O":
                s += (f"<circle cx='{x}' cy='{y}' r='{r}' fill='none' "
                      f"stroke='{c}' stroke-width='0.28'/>"
                      f"<text x='{x}' y='{y + 0.55}' font-size='1.5' "
                      f"text-anchor='middle' fill='{c}' "
                      f"font-family='sans-serif' font-weight='600'>{o['n']}</text>")
            else:
                d = r * 0.8
                s += (f"<line x1='{x - d}' y1='{y - d}' x2='{x + d}' "
                      f"y2='{y + d}' stroke='{c}' stroke-width='0.28'/>"
                      f"<line x1='{x + d}' y1='{y - d}' x2='{x - d}' "
                      f"y2='{y + d}' stroke='{c}' stroke-width='0.28'/>"
                      f"<text x='{x + r * 1.25}' y='{y - r * 0.5}' "
                      f"font-size='1.05' fill='{c}' font-family='sans-serif' "
                      f"font-weight='600'>{o['n']}</text>")
        elif t == "ball":
            s += (f"<circle cx='{o['x']}' cy='{o['y']}' r='0.75' "
                  f"fill='#e6be64' stroke='{bg}' stroke-width='0.12'/>")
        else:                                # two-point tools
            x1, y1, x2, y2 = o["x1"], o["y1"], o["x2"], o["y2"]
            dx, dy = x2 - x1, y2 - y1
            ln = math.hypot(dx, dy)
            if ln < 0.2:
                continue
            dash = " stroke-dasharray='0.9,0.65'" if t == "pass" else ""
            if t == "dribble":
                ux, uy = dx / ln, dy / ln
                nx, ny = -uy, ux
                amp, wave = 0.55, 1.5
                straight = min(1.2, ln * 0.2)
                pts, d, k = [f"{x1},{y1}"], wave / 2, 0
                while d < ln - straight:
                    sgn = 1 if k % 2 == 0 else -1
                    pts.append(f"{x1 + ux * d + nx * amp * sgn:.2f},"
                               f"{y1 + uy * d + ny * amp * sgn:.2f}")
                    d += wave
                    k += 1
                pts.append(f"{x2},{y2}")
                s += (f"<polyline points='{' '.join(pts)}' fill='none' "
                      f"stroke='{c}' stroke-width='{sw}' "
                      f"stroke-linejoin='round'/>")
                s += _svg_arrowhead(x1, y1, x2, y2, c, sw)
                continue
            s += (f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' "
                  f"stroke='{c}' stroke-width='{sw}' "
                  f"stroke-linecap='round'{dash}/>")
            if t in ("cut", "pass"):
                s += _svg_arrowhead(x1, y1, x2, y2, c, sw)
            if t == "screen":
                ux, uy = dx / ln, dy / ln
                half = 1.1
                s += (f"<line x1='{x2 - uy * half:.2f}' "
                      f"y1='{y2 + ux * half:.2f}' x2='{x2 + uy * half:.2f}' "
                      f"y2='{y2 - ux * half:.2f}' stroke='{c}' "
                      f"stroke-width='{sw}' stroke-linecap='round'/>")
    s += "</svg>"
    return s
