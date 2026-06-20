"""
cards.py — shared player/team "card" + rating primitives for the display pages.

These small formatters, percentile bars, tier labels, glass tiles, on/off cards
and gauges were copy-pasted across 6_Players.py, 5_Team_Dashboard.py and
4_Rankings.py. They now live here once so a tweak (a colour, a threshold) lands
everywhere at once.

UI helper (imports streamlit/plotly) — the display mirror of the Streamlit-free
engines. Do NOT import it from the engine layer.

Two gauges, intentionally distinct:
  • ``gauge_dial``  — a 0-100 dial with a delta vs a reference (default 50 = pool
                      average). Caller passes the bar ``color``.
  • ``gauge_range`` — a value vs a league ``[vmin,vmax]`` range, league average
                      (``ref``) drawn as a cyan threshold; zones key off
                      ``good_high``. Bar uses the page ``accent``.
"""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Fixed semantic colours (the per-page ACCENT is passed in where it matters).
_GOOD = "#3fb950"
_BAD = "#e74c3c"
_CYBER = "#00e5ff"


# ── labels ────────────────────────────────────────────────────────────────────
def team_short(team):
    """Trim the redundant gender suffix so team labels stay compact."""
    for suf in (" Girls", " Boys"):
        if team.endswith(suf):
            return team[:-len(suf)]
    return team


# ── number formatting ─────────────────────────────────────────────────────────
def fmt(v, kind):
    """Format a stat value by ``kind`` tag. ``—`` for None.

    int · f1 · f2 · f3 · pct (``v`` already 0-100, 1 dp) · spp (signed)."""
    if v is None:
        return "—"
    if kind == "int":
        return f"{int(v)}"
    if kind == "f1":
        return f"{v:.1f}"
    if kind == "f2":
        return f"{v:.2f}"
    if kind == "f3":
        return f"{v:.3f}"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "spp":              # signed percentage points (e.g. SMOE)
        return f"{v:+.1f}"
    return str(v)


# ── percentile rank + bar ─────────────────────────────────────────────────────
def pctile(val, key, pool, lower_better=False):
    """Percentile rank of ``val`` for stat ``key`` within ``pool`` (0-100)."""
    vals = [r[key] for r in pool if r.get(key) is not None]
    if val is None or not vals:
        return None
    below = sum(1 for v in vals if v < val)
    eq = sum(1 for v in vals if v == val)
    p = (below + 0.5 * eq) / len(vals) * 100
    return round(100 - p) if lower_better else round(p)


def pctile_color(p):
    """Percentile (0-100) → quartile colour (player palette)."""
    if p is None:
        return "#8b949e"
    return ("#2ea043" if p >= 75 else "#3fb950" if p >= 50
            else "#f0a500" if p >= 25 else "#da3633")


def pctile_bar(label, value_str, p):
    """One percentile-bar row of HTML (uses the .pl-pct-* classes)."""
    c = pctile_color(p)
    w = 0 if p is None else max(2, min(100, p))
    rank = f"{p}th" if p is not None else "—"
    return (f"<div class='pl-pct'><div class='pl-pct-top'>"
            f"<span class='pl-pct-lbl'>{html.escape(str(label))}</span>"
            f"<span class='pl-pct-val'>{html.escape(str(value_str))} · "
            f"<span style='color:{c}'>{rank}</span></span></div>"
            f"<div class='pl-pct-track'><div class='pl-pct-fill' "
            f"style='width:{w}%;background:{c}'></div></div></div>")


def tier(ovrl):
    """(color, label) tier off an OVERALL rating (50 = pool average)."""
    if ovrl is None:
        return ("#8b949e", "UNRATED")
    if ovrl >= 70:
        return ("#f0a500", "ELITE")
    if ovrl >= 62:
        return ("#2ecc71", "GREAT")
    if ovrl >= 54:
        return ("#58a6ff", "ABOVE AVG")
    if ovrl >= 46:
        return ("#c9d1d9", "AVERAGE")
    return ("#8b949e", "DEVELOPING")


def tier_class(ovrl):
    """OVERALL rating → the assets/style.css ``.v-*`` tint class (Phase 0 0.2).

    The CSS counterpart to ``tier()`` — use it on FRESH markup so the headline
    number's colour is theme-reactive (``.v-elite`` reskins with the accent)
    instead of a baked hex. Same 70/62/54/46 ladder. ``""`` when unrated, so a
    caller can fall back to the default text colour."""
    if ovrl is None:
        return "v-dev"
    if ovrl >= 70:
        return "v-elite"
    if ovrl >= 62:
        return "v-great"
    if ovrl >= 54:
        return "v-above"
    if ovrl >= 46:
        return "v-avg"
    return "v-dev"


# ── confidence affordance (how firmly the sample backs a number) ──────────────
def conf_level(n, k=3.0, sig=None):
    """Classify how trustworthy a stat is → ``"stable" | "fair" | "weak"``.

    Two evidence models, matching what the engine already computes:
      • ``sig`` given (RAPM significance bool, rapm.py): True → stable, False → weak.
      • else volume ``n`` vs prior weight ``k`` (the shrinkage stabilizer's
        games-/attempts-equivalent, helpers/shrinkage.py): the shrink fraction
        ``n/(n+k)`` ≥0.8 → stable, ≥0.55 → fair, else weak (directional).
    """
    if sig is not None:
        return "stable" if sig else "weak"
    if n is None:
        return "weak"
    frac = n / (n + k) if (n + k) else 0.0
    return "stable" if frac >= 0.8 else "fair" if frac >= 0.55 else "weak"


_CONF_CLS = {"stable": "conf-stable", "fair": "conf-fair", "weak": "conf-weak"}
_CONF_WORD = {"stable": "stable", "fair": "fair", "weak": "directional"}


def conf_dot(n, k=3.0, sig=None, *, title=None):
    """A bare confidence dot (HTML span; ``.conf-dot`` classes in style.css).

    Drop next to a headline value so tier-colour never ships without telling the
    coach how firmly the sample backs it. ``title`` overrides the hover text."""
    lvl = conf_level(n, k, sig)
    tip = title or {"stable": "Stable — well-sampled",
                    "fair": "Fair — moderate sample",
                    "weak": "Directional — small sample"}[lvl]
    return (f"<span class='conf-dot {_CONF_CLS[lvl]}' "
            f"title='{html.escape(str(tip))}'></span>")


def conf_chip(n, k=3.0, sig=None, *, label=None):
    """Confidence dot + word as a pill (``.conf-chip``). Use where there's room
    for a labelled affordance (rating tiles, RAPM rows). ``label`` overrides the
    word (e.g. 'n=4')."""
    lvl = conf_level(n, k, sig)
    word = label or _CONF_WORD[lvl]
    return (f"<span class='conf-chip'><span class='conf-dot {_CONF_CLS[lvl]}'>"
            f"</span>{html.escape(str(word))}</span>")


def stat_kpi(label, value, *, ovrl=None, pct=None, conf_n=None, conf_k=3.0,
             sig=None, sub=""):
    """The Phase-0 headline KPI tile: a number that knows its RANK and its
    CONFIDENCE (HTML string; ``.mini-tile`` + ``.v-*`` + ``.pl-pct-*`` classes).

    ``ovrl`` tints the value by tier (``tier_class``); ``pct`` draws a percentile
    bar; ``conf_n``/``conf_k`` or ``sig`` append a confidence dot. The fix for
    "every st.metric looks the same" — drop into a column with st.markdown."""
    vcls = tier_class(ovrl) if ovrl is not None else "v-avg"
    dot = (conf_dot(conf_n, conf_k, sig)
           if (conf_n is not None or sig is not None) else "")
    bar = ""
    if pct is not None:
        c = pctile_color(pct)
        w = max(2, min(100, pct))
        bar = (f"<div class='pl-pct-track' style='margin-top:8px'>"
               f"<div class='pl-pct-fill' style='width:{w}%;background:{c}'>"
               f"</div></div>")
    return (f"<div class='mini-tile' style='text-align:left'>"
            f"<div class='mini-lbl'>{html.escape(str(label))}{dot}</div>"
            f"<div class='mini-val {vcls}'>{html.escape(str(value))}</div>"
            + (f"<div class='mini-sub'>{html.escape(str(sub))}</div>"
               if sub else "")
            + bar + "</div>")


# ── glass KPI tile + on/off comparison card ───────────────────────────────────
def glass(label, value, sub="", color="var(--text)"):
    """Glassmorphism KPI tile (HTML string; uses the .pl-glass-* classes)."""
    return (f"<div class='pl-glass'><div class='pl-glass-l'>{html.escape(str(label))}</div>"
            f"<div class='pl-glass-v' style='color:{color}'>{html.escape(str(value))}</div>"
            f"<div class='pl-glass-s'>{html.escape(str(sub))}</div></div>")


def onoff_html(label, on_v, off_v, on_n, off_n, n_lbl="opps",
               higher_better=True):
    """On-court vs off-court comparison card with a coloured delta (HTML string)."""
    on_s = f"{on_v:.1f}%" if on_v is not None else "—"
    off_s = f"{off_v:.1f}%" if off_v is not None else "—"
    if on_v is None or off_v is None:
        dclr, dstr, impact = "#8b949e", "—", "~ Neutral"
    else:
        d = on_v - off_v
        good = (d > 1) if higher_better else (d < -1)
        bad = (d < -1) if higher_better else (d > 1)
        dclr = "#2ea043" if good else "#da3633" if bad else "#f0a500"
        dstr = f"{d:+.1f}%"
        impact = "↑ Positive" if good else "↓ Negative" if bad else "~ Neutral"
    return (
        f"<div style='background:var(--card-bg);border:1px solid var(--card-border);"
        f"border-radius:10px;padding:14px'>"
        f"<div style='font-size:11px;color:var(--subtext);text-transform:uppercase;"
        f"letter-spacing:1px;margin-bottom:8px'>{html.escape(str(label))}</div>"
        f"<div style='display:flex;justify-content:space-around;"
        f"align-items:center;margin-bottom:8px'>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:var(--subtext)'>ON COURT</div>"
        f"<div style='font-size:24px;font-weight:800;color:var(--text)'>{on_s}</div>"
        f"<div style='font-size:10px;color:#484f58'>{html.escape(str(n_lbl))}={on_n}</div></div>"
        f"<div style='font-size:18px;color:var(--card-border)'>vs</div>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:var(--subtext)'>OFF COURT</div>"
        f"<div style='font-size:24px;font-weight:800;color:var(--text)'>{off_s}</div>"
        f"<div style='font-size:10px;color:#484f58'>{html.escape(str(n_lbl))}={off_n}</div></div>"
        f"</div>"
        f"<div style='text-align:center;padding:6px;background:var(--card-bg-2);"
        f"border-radius:6px'><span style='font-weight:700;color:{dclr}'>{dstr}</span>"
        f"<span style='font-size:11px;color:{dclr};margin-left:6px'>{impact}</span>"
        f"</div></div>")


# ── horizontal leader bar ─────────────────────────────────────────────────────
def bar_h(names, vals, texts, color="#f0a500", height=None):
    """Shared horizontal leader-bar figure. ``names``/``vals``/``texts`` are
    parallel and already in bottom-to-top order (caller reverses so #1 sits on
    top). ``height`` None → auto-size to the row count. Each page keeps its own
    tiny prep (labels, sort, qualify gate) and calls this for the look."""
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", marker_color=color,
        marker_line_width=0, text=texts, textposition="auto",
        textfont=dict(size=11), cliponaxis=False,
        hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_layout(
        template="plotly_dark", height=height or (60 + 26 * len(names)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=14, t=6, b=6), showlegend=False,
        font=dict(size=11, color="#c9d1d9"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11), automargin=True)
    return fig


# ── gauges ────────────────────────────────────────────────────────────────────
def gauge_dial(value, title, color, ref=50, vmax=100, vmin=0):
    """0-vmax indicator dial with a delta vs ``ref`` (default 50 = pool average).
    Caller passes the bar ``color``."""
    if value is None:
        value = 0
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=value,
        delta={"reference": ref, "increasing": {"color": "#2ea043"},
               "decreasing": {"color": "#da3633"}},
        number={"font": {"size": 26, "color": "#f0f6fc"}},
        title={"text": title, "font": {"size": 12, "color": "#8b949e"}},
        gauge={
            "axis": {"range": [vmin, vmax], "tickwidth": 1,
                     "tickcolor": "#30363d", "tickfont": {"size": 8}},
            "bar": {"color": color, "thickness": 0.28},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [
                {"range": [vmin, ref], "color": "rgba(48,54,61,0.35)"},
                {"range": [ref, vmax], "color": "rgba(48,54,61,0.15)"}],
            "threshold": {"line": {"color": "#8b949e", "width": 2},
                          "thickness": 0.75, "value": ref}}))
    fig.update_layout(height=190, paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=18, r=18, t=40, b=8),
                      font=dict(color="#c9d1d9"))
    return fig


# ── table polish (st.dataframe) ───────────────────────────────────────────────
def style_df(df, grad_cols=None, signed_cols=None):
    """Return a pandas ``Styler`` for ``st.dataframe`` with a dark-friendly
    red→green heat on ``grad_cols`` (higher = greener) and red/green text on
    ``signed_cols`` (negative = red). Matplotlib-free, so it works on the deploy
    mirror. Falls back to the plain DataFrame if styling can't apply."""
    try:
        sty = df.style
        for c in (grad_cols or []):
            if c not in df.columns:
                continue
            col = pd.to_numeric(df[c], errors="coerce")
            lo = col.min()
            span = (col.max() - lo) or 1

            def _bg(v, lo=lo, span=span):
                try:
                    t = max(0.0, min(1.0, (float(v) - lo) / span))
                except (TypeError, ValueError):
                    return ""
                r = int(231 - (231 - 63) * t)
                g = int(76 + (185 - 76) * t)
                b = int(60 + (80 - 60) * t)
                return f"background-color: rgba({r},{g},{b},0.22)"

            sty = sty.map(_bg, subset=[c])

        def _sign(v):
            try:
                return (f"color:{_GOOD}" if float(v) > 0
                        else f"color:{_BAD}" if float(v) < 0 else "")
            except (TypeError, ValueError):
                return ""

        for c in (signed_cols or []):
            if c in df.columns:
                sty = sty.map(_sign, subset=[c])
        return sty
    except Exception:
        return df


def gauge_range(value, vmin, vmax, label, suffix="", good_high=True, ref=None,
                height=210, accent="#f0a500"):
    """Value vs a league ``[vmin,vmax]`` range with the league average (``ref``)
    drawn as a cyan threshold. Red/amber/green zones key off ``good_high``; the
    delta vs ref is shown when ref is given. Bar uses the page ``accent``."""
    span = (vmax - vmin) or 1
    lo, hi = vmin + span / 3, vmin + 2 * span / 3
    if good_high:
        zones = [(vmin, lo, "rgba(231,76,60,.20)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(63,185,80,.22)")]
    else:
        zones = [(vmin, lo, "rgba(63,185,80,.22)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(231,76,60,.20)")]
    mode = "gauge+number+delta" if ref is not None else "gauge+number"
    ind = dict(
        mode=mode, value=value,
        number={"suffix": suffix, "font": {"size": 28, "color": "#f0f6fc"}},
        gauge={
            "axis": {"range": [vmin, vmax], "tickwidth": 1,
                     "tickcolor": "#30363d", "tickfont": {"size": 9}},
            "bar": {"color": accent, "thickness": 0.3},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [{"range": [a, b], "color": c} for a, b, c in zones]},
        title={"text": label, "font": {"size": 12, "color": "#8b949e"}})
    if ref is not None:
        ind["delta"] = {"reference": ref, "increasing": {"color": _GOOD},
                        "decreasing": {"color": _BAD}, "font": {"size": 12}}
        ind["gauge"]["threshold"] = {"line": {"color": _CYBER, "width": 3},
                                     "thickness": 0.85, "value": ref}
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(template="plotly_dark", height=height,
                      paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=22, r=22, t=46, b=10),
                      font=dict(color="#c9d1d9"))
    return fig
