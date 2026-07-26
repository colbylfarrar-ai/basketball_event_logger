"""insights_brief.py — the auto-scout board at the top of Insights.

REGISTER, AND WHY IT CHANGED
----------------------------
The first version of this module was written to be readable by someone who had
never seen a basketball game. It glossed every term inline — "PPP (points per
trip down the floor)", "a turnover (losing the ball)" — and it read as
condescending to the only people who will ever open this page. A coach does not
need ORB, TOV, PPS or contested% explained; spelling them out tells them you
think they don't know.

So this is written coach-to-coach: standard shorthand used bare, numbers first,
verdict in the fewest words that carry it. What stays explicit is the thing a
coach genuinely cannot know by looking — WHICH of the numbers actually moved
this team's games, and how firmly each one is measured. That is the value the
page adds. Vocabulary is not.

DENSITY IS THE POINT
--------------------
This is the flagship tab and it is scored on how much true information is on
screen at once. Rules:

  * tiles over paragraphs, bullets over sentences, one line per finding;
  * every number carries its comparison inline (`47% vs 31% lg`) rather than in
    a following clause;
  * reliability rides as a small `r=` chip, not as a sentence of hedging;
  * nothing is capped — if a read fired it is on screen.

Layout vocabulary is the app's own (`.mini-tile`, `.stat-chip`, `.badge`,
`.gloss-card`, `.lab-hdr`), so this tab looks like the player card and the team
card rather than like a new dialect.
"""
from __future__ import annotations

import html
import re

import streamlit as st

import helpers.reliability as REL


def _b(t):
    """Markdown **bold** → <b> for the raw-HTML cards."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def _signed(v, dp=1):
    """Signed number with NEGATIVE ZERO removed. `"%+.1f" % -0.04` is "-0.0",
    which reads as a deficit that is not there — and on a four-term split whose
    whole promise is that the terms add up, a phantom minus is exactly the kind
    of thing that makes a coach stop trusting the page."""
    if abs(v) < 0.5 / (10 ** dp):
        v = 0.0
    return f"{v:+.{dp}f}"


def _hdr(text, sub=None):
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)
    if sub:
        st.markdown(f"<div class='hdr-sub'>{sub}</div>",
                    unsafe_allow_html=True)


def _chips(items):
    """One compact row of stat-chips. `items` = [(label, value)] or strings."""
    out = []
    for it in items:
        if isinstance(it, (tuple, list)):
            out.append(f"<span class='stat-chip'>{html.escape(str(it[0]))} "
                       f"<b>{html.escape(str(it[1]))}</b></span>")
        else:
            out.append(f"<span class='stat-chip'>{it}</span>")
    return ("<div style='display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 10px'>"
            + "".join(out) + "</div>")


def _bullets(items, dense=True):
    """Tight bullet block. `items` = [(badge_or_None, html_line)]."""
    rows = []
    for badge, line in items:
        chip = (f"<span class='badge accent' style='margin-right:6px'>"
                f"{html.escape(str(badge))}</span>" if badge else
                "<span style='color:var(--accent);margin-right:6px'>▸</span>")
        rows.append(f"<div style='margin:{'3px' if dense else '6px'} 0;"
                    f"font-size:12.5px;line-height:1.45'>{chip}{line}</div>")
    return f"<div class='gloss-card'>{''.join(rows)}</div>"


# ── the dense block, and the grid it packs into ──────────────────────────────
# The unit the whole tab is built from. A block is a short uppercase heading
# with its sample size on the right, then either label/value ROWS or one-line
# findings. Blocks are laid 3-5 across, because the thing being optimised is
# how much true information is on one screen — a coach comparing nine players
# should not be scrolling between them.

def block(title, *, rows=None, lines=None, n=None, tone=None):
    """One compact info block (HTML string).

    `rows`  = [(label, value)] or [(label, value, tone)] — the stat-line form.
    `lines` = [html] or [(tag, html)] — the finding form, one per row.
    Both may be given; rows render above lines.
    """
    body = []
    for r in (rows or []):
        k, v = r[0], r[1]
        cls = f" {r[2]}" if len(r) > 2 and r[2] else ""
        body.append(f"<div class='ins-row'><span class='k'>{html.escape(str(k))}"
                    f"</span><span class='v{cls}'>{v}</span></div>")
    for ln in (lines or []):
        if isinstance(ln, (tuple, list)):
            tag = (f"<span class='ins-tag'>{html.escape(str(ln[0]))}</span>"
                   if ln[0] else "")
            body.append(f"<div class='ins-line'>{tag}{ln[1]}</div>")
        else:
            body.append(f"<div class='ins-line'>{ln}</div>")
    nbit = (f"<span class='n'>{html.escape(str(n))}</span>"
            if n not in (None, "") else "")
    cls = f" {tone}" if tone else ""
    return (f"<div class='ins-block{cls}'>"
            f"<div class='ins-hd'><span>{html.escape(str(title))}</span>"
            f"{nbit}</div>{''.join(body)}</div>")


def grid(blocks, cols=4):
    """Lay blocks into `cols` columns, filling COLUMN-WISE so the tallest
    block does not leave a ragged hole beside it. Streamlit columns are
    independent stacks, so distributing round-robin keeps them even."""
    if not blocks:
        return
    cols = max(1, min(cols, len(blocks)))
    buckets = [[] for _ in range(cols)]
    for i, b in enumerate(blocks):
        buckets[i % cols].append(b)
    for col, items in zip(st.columns(cols), buckets):
        col.markdown("".join(items), unsafe_allow_html=True)


def _tile(label, value, sub="", tone=None):
    colour = {"good": "var(--good)", "bad": "var(--bad)"}.get(tone, "var(--text)")
    return (f"<div class='mini-tile' style='text-align:left;padding:10px 12px'>"
            f"<div class='mini-lbl' style='font-size:10px'>"
            f"{html.escape(str(label))}</div>"
            f"<div class='mini-val' style='font-size:20px;color:{colour}'>"
            f"{html.escape(str(value))}</div>"
            + (f"<div class='mini-sub' style='font-size:10px'>{sub}</div>"
               if sub else "") + "</div>")


#: (key, short label) for the four margin terms, largest-first at render time.
_TERMS = (("volume", "Extra shots"), ("quality", "Selection"),
          ("making", "Shot-making"), ("ft_margin", "Free throws"))


def _margin_bar(means):
    """Signed bar per term, scaled to the largest. NOT stacked — the terms can
    oppose each other and a stack would read a +15/−15 wash as a big total."""
    top = max((abs(means.get(k, 0.0)) for k, _l in _TERMS), default=0)
    if top <= 0:
        return ""
    rows = []
    for key, label in _TERMS:
        v = means.get(key, 0.0)
        pct = min(100.0, abs(v) / top * 100.0)
        colour = "var(--good)" if v >= 0 else "var(--bad)"
        side = "left" if v >= 0 else "right"
        rows.append(
            f"<div style='display:flex;align-items:center;gap:8px;"
            f"margin-bottom:4px'>"
            f"<div style='width:84px;font-size:10.5px;color:var(--subtext);"
            f"text-align:right'>{html.escape(label)}</div>"
            f"<div style='flex:1;height:11px;background:var(--card-border);"
            f"border-radius:3px;position:relative'>"
            f"<div style='position:absolute;{side}:50%;width:{pct / 2:.1f}%;"
            f"height:100%;background:{colour};border-radius:3px'></div>"
            f"<div style='position:absolute;left:50%;top:-2px;width:1px;"
            f"height:15px;background:var(--subtext);opacity:.45'></div></div>"
            f"<div style='width:52px;font-size:11.5px;font-weight:800;"
            f"color:{colour}'>{_signed(v)}</div></div>")
    return ("<div class='gloss-card' style='padding:11px 14px'>"
            + "".join(rows) + "</div>")


def _identity(des):
    """The one-line read on what actually decides this team's games.

    Two quantities, and conflating them writes a false sentence. `mean_abs` is
    how hard a term SWINGS game to game — it is what makes a term decisive.
    `signed` is whether the team is ahead or behind on it over the season. A
    term can swing ±8.8 pts/g and net +0.7: that team is not "winning on
    volume", it is being decided by volume and roughly breaking even on it.
    The first version said "Wins on volume" off the ranking alone, and printed
    it over a 3-5 team taking fewer shots than its opponents.
    """
    key, label, mean_abs, signed = des["ranked_terms"][0]
    m = des["means"]
    # is the season-long lean material against how much the term moves?
    lean = ("edge" if signed >= 0 else "problem")
    flat = abs(signed) < max(1.0, 0.30 * mean_abs)
    head = {
        "volume": "Extra shots decide their games",
        "making": "Shot-making decides their games",
        "quality": "Shot selection decides their games",
        "ft_margin": "The free-throw line decides their games",
    }.get(key, f"{label} decides their games")
    if flat:
        tail = (f"±{mean_abs:.1f} pts/g of swing, but it nets only "
                f"{_signed(signed)} — decisive game to game, close to even "
                f"across the season.")
    else:
        tail = (f"±{mean_abs:.1f} pts/g of swing and a {_signed(signed)} season "
                f"lean — their biggest {lean}.")
    detail = {
        "volume": f" FGA {_signed(m['fga_gap'])}/g · "
                  f"ORB {_signed(m['orb_gap'])} · "
                  f"TOV {_signed(m['tov_gap'])}.",
        "making": (" Least repeatable of the four — "
                   + ("record ahead of process."
                      if signed > 0 else "process ahead of record.")),
        "quality": " Look value against the opponent's, before anything drops.",
        "ft_margin": "",
    }.get(key, "")
    return f"**{head}.** {tail}{detail}"


def render(ctx, table, pids, tlines, deep_bundle, fp=None):
    """The auto-scout board. `deep_bundle` carries already-computed engine
    output so nothing here pays for a second event pass (prod is 1 vCPU)."""
    des = (deep_bundle or {}).get("deserved") or {}
    allowed = (deep_bundle or {}).get("allowed") or {}
    anat = (deep_bundle or {}).get("anatomy") or {}

    if not des.get("available") or des.get("games", 0) < 3:
        st.caption("Auto-scout needs 3+ tracked games. Full depth is in the "
                   "other tabs.")
        _team_flags(tlines)
        return

    n = des["games"]
    w, l = des["record"]
    m = des["means"]

    # ── the header strip: record + the four terms as tiles ───────────────────
    _hdr("Auto-scout", f"{n} tracked games · {w}–{l} · "
                       f"{_signed(m['margin'])} margin/g · every point of it split "
                       f"four ways, and the four add up exactly")

    _cols = st.columns(4)
    _ranked = {k: (lbl, a, s) for k, lbl, a, s in des["ranked_terms"]}
    _lead_key = des["ranked_terms"][0][0]
    _subs = {
        "volume": f"ORB {_signed(m['orb_gap'])} · "
                  f"TOV {_signed(m['tov_gap'])}",
        "quality": "look value vs opp",
        "making": "vs what looks were worth",
        "ft_margin": "FT margin",
    }
    for i, (key, label) in enumerate(_TERMS):
        v = m.get(key, 0.0)
        lead = " ★" if key == _lead_key else ""
        _cols[i].markdown(
            _tile(label + lead, _signed(v), _subs.get(key, ""),
                  tone="good" if v >= 0 else "bad"),
            unsafe_allow_html=True)

    st.markdown(_margin_bar(m), unsafe_allow_html=True)

    # ── the identity + deserved-result line ──────────────────────────────────
    _lines = [(None, _b(_identity(des)))]
    if des.get("agree_pct") is not None and des["decided"] >= 3:
        up = des.get("biggest_upset")
        bit = (f"Play matched result <b>{des['agree']}/{des['decided']}</b> "
               f"({des['agree_pct']:.0f}%).")
        if up is not None:
            bit += (f" Widest miss: <b>{up['opp_name']}</b> — "
                    f"{'W' if up['margin'] > 0 else 'L'}"
                    f"{abs(up['margin']):.0f} on {up['xmargin']:+.1f} play.")
        bit += (" Descriptive only — quality does not forecast scoring on "
                "this book.")
        _lines.append(("Deserved", bit))
    st.markdown(_bullets(_lines), unsafe_allow_html=True)

    # ── defense + runs as blocks, packed ─────────────────────────────────────
    blocks = []
    mine = allowed.get("mine") if allowed else None
    if mine and mine.get("n", 0) >= 80:
        contest = mine.get("contest_share")
        lg = allowed.get("league_contest")
        rows = [("Opp FGA", mine["n"]),
                ("Opp PPS", f"{mine['opp_pps']:.2f}"),
                ("Opp 3PA%", f"{mine['three_share'] * 100:.0f}%")]
        dl = []
        if contest is not None and lg is not None:
            sb = REL.measured("team", "contest_share_allowed")
            rows.insert(0, ("Contested", f"{contest * 100:.0f}%",
                            "good" if contest >= lg else "bad"))
            dl.append((
                "Contest",
                f"<b>{contest * 100:.0f}%</b> vs {lg * 100:.0f}% lg · "
                f"r={sb:.2f} — most repeatable team defensive read on the "
                f"book."))
        blocks.append(block("Defense — pressure", rows=rows, lines=dl,
                            n=f"{mine['n']} opp FGA"))

        band = allowed.get("league_band") or {}
        labels = allowed.get("band_labels") or {}
        pps = allowed.get("band_pps") or {}
        drows = []
        for b, lgs in sorted(band.items(),
                             key=lambda kv: -abs(mine["band"].get(kv[0], 0.0)
                                                 - kv[1])):
            share = mine["band"].get(b, 0.0)
            v = pps.get(b)
            drows.append((
                labels.get(b, b),
                f"{share * 100:.0f}% <span style='color:var(--subtext);"
                f"font-weight:600'>vs {lgs * 100:.0f}% "
                f"({(share - lgs) * 100:+.0f})"
                + (f" · {v:.2f}" if v is not None else "") + "</span>"))
        if drows:
            blocks.append(block("Defense — shots allowed", rows=drows,
                                n="share vs league · PPS"))

    if anat:
        import helpers.runs as RN
        for side, lbl in (("own", "Runs made"), ("allowed", "Runs allowed")):
            s = anat.get(side) or {}
            if not s.get("n"):
                continue
            trig = RN._mode_share(s["trigger"])
            dfn = RN._mode_share(s["defense"])
            pts = s.get("points") or {}
            tot = sum(pts.values())
            rows = [("Count", s["n"]),
                    ("Avg", f"{s['avg_pts']:.0f} pts"),
                    ("Length", f"{s['avg_secs'] / 60:.1f} min")]
            if trig:
                rows.append((RN.TRIGGER_LABELS.get(trig[0], trig[0]).lstrip(),
                             f"{trig[1] * 100:.0f}%"))
            if dfn:
                rows.append((str(dfn[0]).replace("_", " "),
                             f"{dfn[1] * 100:.0f}%"))
            if tot:
                top = max(pts.items(), key=lambda kv: kv[1])
                rows.append(("FT" if top[0] == "ft"
                             else RN._band_phrase(top[0]),
                             f"{top[1] / tot * 100:.0f}%"))
            blocks.append(block(lbl, rows=rows, n="10-0",
                                tone="good" if side == "own" else "bad"))

    if blocks:
        _hdr("Defense & runs")
        grid(blocks, cols=4)

    _team_flags(tlines)


def _team_flags(tlines, cols=3):
    """Every team-level generator line that fired, one block each, uncapped."""
    if not tlines:
        return
    _hdr(f"Team flags — {len(tlines)} fired",
         "Biggest gaps from the league field, strongest first. Sample-gated.")
    grid([block(str(ln.get("metric") or "Read"),
                n=f"n={ln.get('n')}",
                lines=[_b(str(ln["text"]))])
          for ln in tlines], cols=cols)
