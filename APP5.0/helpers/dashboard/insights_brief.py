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
            f"color:{colour}'>{v:+.1f}</div></div>")
    return ("<div class='gloss-card' style='padding:11px 14px'>"
            + "".join(rows) + "</div>")


def _identity(des):
    """The one-line read on what actually decides this team's games."""
    key, label, mean_abs, signed = des["ranked_terms"][0]
    m = des["means"]
    if key == "volume":
        return (f"**Wins on volume.** {m['fga_gap']:+.1f} FGA/g — "
                f"ORB {m['orb_gap']:+.1f}, TOV {m['tov_gap']:+.1f}. "
                f"Swings ±{mean_abs:.1f} pts/g, the largest of the four.")
    if key == "making":
        return (f"**Lives and dies on shot-making.** {signed:+.1f} pts/g "
                f"against what the looks were worth — ±{mean_abs:.1f} pts/g, "
                f"the largest of the four and the least repeatable. "
                + ("The record is running ahead of the process."
                   if signed > 0 else
                   "The process is running ahead of the record."))
    if key == "quality":
        return (f"**Wins on shot selection.** Looks worth {signed:+.1f} pts/g "
                f"more than the opponent's before anything drops — "
                f"±{mean_abs:.1f} pts/g, the largest of the four.")
    return (f"**Decided at the line.** {signed:+.1f} pts/g on FTs — "
            f"±{mean_abs:.1f} pts/g, the largest of the four.")


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
                       f"{m['margin']:+.1f} margin/g · every point of it split "
                       f"four ways, and the four add up exactly")

    _cols = st.columns(4)
    _ranked = {k: (lbl, a, s) for k, lbl, a, s in des["ranked_terms"]}
    _lead_key = des["ranked_terms"][0][0]
    _subs = {
        "volume": f"ORB {m['orb_gap']:+.1f} · TOV {m['tov_gap']:+.1f}",
        "quality": "look value vs opp",
        "making": "vs what looks were worth",
        "ft_margin": "FT margin",
    }
    for i, (key, label) in enumerate(_TERMS):
        v = m.get(key, 0.0)
        lead = " ★" if key == _lead_key else ""
        _cols[i].markdown(
            _tile(label + lead, f"{v:+.1f}", _subs.get(key, ""),
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

    # ── defense + runs, side by side ─────────────────────────────────────────
    dcol, rcol = st.columns(2)

    with dcol:
        mine = allowed.get("mine") if allowed else None
        dl = []
        if mine and mine.get("n", 0) >= 80:
            contest = mine.get("contest_share")
            lg = allowed.get("league_contest")
            if contest is not None and lg is not None:
                sb = REL.measured("team", "contest_share_allowed")
                dl.append((
                    "Contest",
                    f"<b>{contest * 100:.0f}%</b> of allowed FGA contested vs "
                    f"<b>{lg * 100:.0f}%</b> lg "
                    f"<span class='badge' style='margin-left:4px'>r={sb:.2f}"
                    f"</span> — most repeatable team defensive number on the "
                    f"book."))
            band = allowed.get("league_band") or {}
            labels = allowed.get("band_labels") or {}
            pps = allowed.get("band_pps") or {}
            gaps = sorted(
                ((b, mine["band"].get(b, 0.0), lgs)
                 for b, lgs in band.items()),
                key=lambda t: -abs(t[1] - t[2]))
            for b, share, lgs in gaps:
                if abs(share - lgs) < 0.04:
                    continue
                v = pps.get(b)
                dl.append((
                    None,
                    f"Allows <b>{share * 100:.0f}%</b> from "
                    f"<b>{labels.get(b, b)}</b> vs {lgs * 100:.0f}% lg "
                    f"({(share - lgs) * 100:+.0f})"
                    + (f" · {v:.2f} PPS" if v is not None else "")))
        if dl:
            _hdr("Defense — what they make you take")
            st.markdown(_bullets(dl), unsafe_allow_html=True)
            st.markdown(_chips([
                ("Opp FGA", mine["n"]),
                ("Opp PPS", f"{mine['opp_pps']:.2f}"),
                ("Opp 3PA share", f"{mine['three_share'] * 100:.0f}%")]),
                unsafe_allow_html=True)

    with rcol:
        if anat:
            import helpers.runs as RN
            rl = []
            for side, lbl in (("own", "Made"), ("allowed", "Allowed")):
                s = anat.get(side) or {}
                if not s.get("n"):
                    continue
                trig = RN._mode_share(s["trigger"])
                dfn = RN._mode_share(s["defense"])
                pts = s.get("points") or {}
                tot = sum(pts.values())
                bits = [f"<b>{s['n']}</b> runs · {s['avg_pts']:.0f} pts in "
                        f"{s['avg_secs'] / 60:.1f} min"]
                if trig and trig[1] >= 0.30:
                    bits.append(f"{trig[1] * 100:.0f}% "
                                f"{RN.TRIGGER_LABELS.get(trig[0], trig[0])}")
                if dfn and dfn[1] >= 0.35:
                    bits.append(f"{str(dfn[0]).replace('_', ' ')} "
                                f"{dfn[1] * 100:.0f}%")
                if tot:
                    top = max(pts.items(), key=lambda kv: kv[1])
                    where = ("FT" if top[0] == "ft"
                             else RN._band_phrase(top[0]))
                    bits.append(f"{top[1] / tot * 100:.0f}% from {where}")
                rl.append((lbl, " · ".join(bits)))
            if rl:
                _hdr("Runs — 10-0 swings")
                st.markdown(_bullets(rl), unsafe_allow_html=True)

    _team_flags(tlines)


def _team_flags(tlines):
    """Every team-level generator line that fired, one per row, uncapped."""
    if not tlines:
        return
    _hdr(f"Team flags — {len(tlines)} fired",
         "Biggest gaps from the league field, strongest first. Sample-gated.")
    rows = []
    for ln in tlines:
        rows.append(
            f"<div style='margin:3px 0;font-size:12.5px;line-height:1.45'>"
            f"<span class='badge accent' style='margin-right:6px'>"
            f"{html.escape(str(ln['metric']))}</span>"
            f"<span style='color:var(--subtext);font-size:10px;"
            f"margin-right:5px'>n={ln.get('n')}</span>"
            f"{_b(str(ln['text']))}</div>")
    st.markdown(f"<div class='gloss-card'>{''.join(rows)}</div>",
                unsafe_allow_html=True)
