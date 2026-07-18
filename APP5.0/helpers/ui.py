"""
ui.py — shared Streamlit UI primitives for the display pages.

Every page repeated the same boot sequence (init DB → apply settings → inject
the global stylesheet → apply theme CSS) and the same Plotly chart styling
(`_rgb` / `_style` / `_q_label`). That boilerplate now lives here once.

This module IMPORTS streamlit on purpose — it is the UI layer, the mirror of the
Streamlit-free engine in stats.py / team_ratings.py / etc. (box_score.py is the
other UI helper). Do NOT import it from the engine.

Page usage:

    from helpers.ui import page_chrome, rgb as _rgb, style_fig as _style, q_label as _q_label
    _cfg, ACCENT = page_chrome()
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import streamlit as st

from database.db import initialize_database
from helpers.settings_utils import (
    get_all_settings, apply_page_config, apply_theme_css, get_setting,
)

# ── Static chart palette ────────────────────────────────────────────────────────
# ACCENT is dynamic (resolved per-page from settings); these are the fixed colours
# every chart shares.
CARD_BG = "#161b22"
GRID    = "#21262d"
AWAY    = "#e74c3c"
GOOD    = "#3fb950"
BAD     = "#e74c3c"

# Modern categorical palette (used for multi-series charts with no explicit colour)
PALETTE = ["#58a6ff", "#3fb950", "#f0a500", "#bc8cff", "#ff7b72", "#56d4dd",
           "#e3b341", "#ec6cb9", "#79c0ff", "#d29922", "#7ee787", "#ffa657"]

# Shared Plotly colorscales, anchored to the constants above.
# HEAT: sequential card-bg → GOOD — the default for more-is-better heatmaps
# (zero/low cells fade into the card instead of shouting).
HEAT = [[0.0, CARD_BG], [1.0, GOOD]]
# DIVERGE: BAD → dark neutral → GOOD — for signed metrics centred on 0/average
# (net rating, SMOE, +/-); pin the midpoint to the neutral value (e.g. zmid=0).
DIVERGE = [[0.0, BAD], [0.5, GRID], [1.0, GOOD]]

# Match the in-app system font stack so chart text reads as one with the UI.
FONT_FAMILY = ("'Segoe UI Variable Display','Segoe UI',-apple-system,"
               "BlinkMacSystemFont,Inter,Roboto,sans-serif")

_CSS_PATH = _ROOT / "assets" / "style.css"


def _sync_external_writes():
    """Mobile-tracker writes happen in another process, so they can't call
    st.cache_data.clear() the way the Streamlit pages do. The tracker API bumps
    app_settings.data_version instead; when this session sees the value move,
    it clears the global data cache once. First sight in a session just records
    the value — the ttl=600 on every cache bounds any staleness from before
    the session started."""
    from database.db import query
    try:
        row = query("SELECT value FROM app_settings WHERE key='data_version'")
    except Exception:
        return
    ver = row[0]["value"] if row else "0"
    seen = st.session_state.get("_data_version_seen")
    if seen is not None and seen != ver:
        st.cache_data.clear()
    st.session_state["_data_version_seen"] = ver


# ── Page boot ───────────────────────────────────────────────────────────────────
def page_chrome(title: str = None):
    """Standard page boot, returning ``(settings_dict, accent_hex)``.

    Runs DB init, applies the stored page config + theme, and injects the global
    stylesheet. ``apply_page_config`` is the first ``st.*`` call (Streamlit
    requires set_page_config to come first), so call this before any other
    ``st.*`` on the page. ``title`` names the browser tab per page.
    """
    initialize_database()
    _sync_external_writes()
    cfg = get_all_settings()
    apply_page_config(cfg, title)
    if _CSS_PATH.exists():
        st.markdown(
            f"<style>{_CSS_PATH.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )
    apply_theme_css(cfg)
    from helpers.auth import require_login
    require_login()
    # Always-available data refresh — kept LAST in page_chrome. Clearing stamps
    # a session time string; first run of a session shows no caption.
    if st.sidebar.button("↻ Refresh data", key="_chrome_refresh"):
        from datetime import datetime
        st.cache_data.clear()
        st.session_state["_data_refreshed_at"] = (
            datetime.now().strftime("%I:%M %p").lstrip("0"))
        st.session_state["_data_just_refreshed"] = True
        st.rerun()
    if st.session_state.pop("_data_just_refreshed", False):
        try:
            st.toast("Data refreshed", icon="↻")
        except Exception:
            pass
    _refreshed = st.session_state.get("_data_refreshed_at")
    if _refreshed:
        st.sidebar.caption(f"Data refreshed at {_refreshed}")
    # Global search — jump to any team's dashboard or player's profile from
    # any page (the command palette, Tier 2 item 12).
    if st.sidebar.button("🔎 Go to team / player…", key="_chrome_palette"):
        _palette_dialog()
    return cfg, get_setting("accent_color", "#f0a500")


@st.cache_data(ttl=600, show_spinner=False)
def _pdf_bytes(html_doc: str):
    from helpers.pdf_export import html_to_pdf
    return html_to_pdf(html_doc)


def pdf_or_html_download(label: str, html_doc: str, basename: str, *, key: str):
    """The one-click export pair: a real PDF (when an engine is installed —
    xhtml2pdf ships in requirements) plus the HTML original; falls back to the
    old HTML-only button with print instructions when no engine works."""
    pdf = _pdf_bytes(html_doc)
    if pdf:
        c1, c2 = st.columns(2)
        c1.download_button(f"⬇ {label} (PDF)", pdf,
                           file_name=f"{basename}.pdf",
                           mime="application/pdf", key=f"{key}_pdf")
        c2.download_button("HTML version", html_doc,
                           file_name=f"{basename}.html",
                           mime="text/html", key=key)
    else:
        st.download_button(f"⬇ {label} (HTML — open & print to PDF)", html_doc,
                           file_name=f"{basename}.html", mime="text/html",
                           key=key)


# ── Command palette (global search — Tier 2 item 12) ────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _palette_pool():
    """The searchable universe: every team + every active player (one cached
    query each). Cheap enough to hold whole — the league is a few hundred rows."""
    from database.db import query
    teams = query("SELECT id, name, class, gender FROM teams ORDER BY name")
    players = query(
        "SELECT p.id, p.name, p.number, t.name AS team, t.gender AS gender "
        "FROM players p JOIN teams t ON t.id = p.team_id "
        "WHERE p.archived = 0 ORDER BY p.name")
    return teams, players


@st.dialog("Go to…")
def _palette_dialog():
    """Global search: type a team or player name, click a hit, land on its
    surface. Teams seed the Team Dashboard's league + team keys; players seed
    the Players page's league + Player Profile pick (via the same handoff the
    ?player= deep-link uses)."""
    q = st.text_input("Search teams & players", key="_palette_q",
                      placeholder="Start typing a team or player name…")
    ql = (q or "").strip().lower()
    if len(ql) < 2:
        st.caption("Type at least 2 letters. Teams open their dashboard; "
                   "players load into the Players → Player Profile tab.")
        return
    teams, players = _palette_pool()
    t_hits = [t for t in teams if ql in t["name"].lower()][:8]
    p_hits = [p for p in players if ql in p["name"].lower()][:8]
    if not t_hits and not p_hits:
        st.caption("No team or player matches that.")
        return
    if t_hits:
        st.markdown("**Teams**")
        for t in t_hits:
            if st.button(f"{t['name']}  ({t['class']} · "
                         f"{gender_label(t['gender'])})",
                         key=f"_pal_t{t['id']}", width="stretch"):
                st.session_state["ta_gender"] = t["gender"]
                st.session_state["ta_team"] = t["id"]
                st.switch_page("pages/6_Team_Dashboard.py")
    if p_hits:
        st.markdown("**Players**")
        for p in p_hits:
            _num = f"#{p['number']} " if p.get("number") not in (None, "") else ""
            if st.button(f"{_num}{p['name']} — {p['team']} "
                         f"({gender_label(p['gender'])})",
                         key=f"_pal_p{p['id']}", width="stretch"):
                st.session_state["pl_gender"] = p["gender"]
                st.session_state["_palette_player"] = p["id"]
                st.switch_page("pages/7_Players.py")


def page_header(title: str, sub: str = None, chips: list = None):
    """Unified page header — a drop-in replacement for a bare ``st.title``.

    ``sub`` renders as an ``st.caption`` line under the title. ``chips`` is an
    optional list of short strings rendered as one compact row of ``.stat-chip``
    pills (assets/style.css). With only ``title`` it is byte-for-byte
    ``st.title``, so pages can adopt it with no layout surprises.
    """
    st.title(title)
    if sub:
        st.caption(sub)
    if chips:
        row = "".join(f"<span class='stat-chip'>{html.escape(str(c))}</span>"
                      for c in chips)
        st.markdown(
            "<div style='display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 10px'>"
            f"{row}</div>",
            unsafe_allow_html=True)


def masthead(title: str, *, kicker: str = "HOOPTRACKS", sub: str = None,
             icon: str = "🏀", chips: list = None):
    """Branded page masthead — the HoopTracks identity band (compact ``.lab-hero``
    grammar: an accent kicker eyebrow over a gradient-text title).

    A drop-in upgrade for ``page_header`` on the flagship pages so they read as one
    product rather than bare ``st.title`` chrome. The gradient title reskins with
    the chosen accent (``.masthead-title`` shares ``.lab-hero-name``'s clip), so
    the brand feel comes from a consistent *treatment*, not a stamped logo."""
    chip_html = ""
    if chips:
        chip_html = "".join(
            f"<span class='stat-chip'>{html.escape(str(c))}</span>" for c in chips)
        chip_html = f"<div class='masthead-chips'>{chip_html}</div>"
    sub_html = (f"<div class='masthead-sub'>{html.escape(str(sub))}</div>"
                if sub else "")
    st.markdown(
        f"<div class='masthead'>"
        f"<div class='masthead-kicker'>{icon} {html.escape(str(kicker))}</div>"
        f"<div class='masthead-title lab-hero-name'>{html.escape(str(title))}</div>"
        f"{sub_html}{chip_html}</div>",
        unsafe_allow_html=True)


# ── Chart primitives ─────────────────────────────────────────────────────────────
def rgb(hex_color):
    """'#rrggbb' → (r, g, b) ints."""
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16))


def q_label(q):
    """Quarter number → label ('Q1'..'Q4', then 'OT1', 'OT2', ...)."""
    return f"Q{q}" if q <= 4 else f"OT{q - 4}"


# ── League / score primitives ────────────────────────────────────────────────────
def gender_label(g):
    """League gender code → display label ('F' → 'Girls', 'M' → 'Boys')."""
    return "Girls" if g == "F" else "Boys"


def gender_radio(container=None, *, default="F", key=None, label="League",
                 horizontal=True, include_all=False):
    """Shared Girls/Boys league toggle. Returns 'F' or 'M'.

    ``include_all=True`` prepends an "All" option which returns ``None`` —
    matching the existing "All → no gender filter" convention (Officials page).
    Pass ``default=None`` to start on "All".

    `container` is an st.columns slot (or st, the default). Single source for the
    st.radio(['F','M']) pattern repeated across Rankings / Team Dashboard /
    Players / War Room.
    """
    c = container if container is not None else st
    opts = ([None, "F", "M"] if include_all else ["F", "M"])
    return c.radio(label, opts, index=opts.index(default),
                   format_func=lambda g: "All" if g is None else gender_label(g),
                   horizontal=horizontal, key=key)


def season_picker(container=None, *, key=None, label="Season"):
    """Shared season selector. Returns the season VALUE to pass to season-scoped
    engines: ``'Current'`` for the active season or an archive label like
    ``'2025-2026'``.

    Renders nothing and returns ``seasons.ACTIVE`` when there are no archived
    seasons yet (pre-rollover) — so the picker stays invisible until there is an
    archive to switch to. Previous seasons are an OPEN ARCHIVE (free, full depth to
    everyone); see ``helpers/seasons.py``. NOTE: this is the single-source picker —
    wiring each page to actually switch its data + bypass gating on the returned
    value is the remaining integration step (kept out of the live gated pages until
    it can be verified against real archive data at season rollover).
    """
    import helpers.seasons as SEAS
    opts = SEAS.season_options()                 # [(value, label)], active first
    if len(opts) <= 1:
        return SEAS.ACTIVE                        # no archives → nothing to pick
    c = container if container is not None else st
    labels = dict(opts)
    values = [v for v, _ in opts]
    return c.selectbox(label, values, index=0,
                       format_func=lambda v: labels.get(v, v), key=key)


def score_card(rows, *, footer="", footer_top=False, style_names=False):
    """Return HTML for the standard score card (CSS in assets/style.css).

    `rows` = [(name, points, won_bool), …] rendered top-to-bottom; the winner row
    gets `.score-winner`, the loser `.score-loser` — on the points cell, and on
    the team name too when `style_names=True`. An optional 4th element per row is
    raw badge HTML (e.g. a rank chip from `rank_chip`) shown after the team name.
    `footer` is the small meta line (date / margin, may hold a badge span);
    `footer_top` renders it above the rows.
    Caller wraps the result with st.markdown(..., unsafe_allow_html=True).
    """
    body = ""
    for row in rows:
        name, pts, won = row[0], row[1], row[2]
        badge = row[3] if len(row) > 3 else ""
        cls = "score-winner" if won else "score-loser"
        ncls = f" {cls}" if style_names else ""
        body += (
            "<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<span class='score-card-team{ncls}'>{html.escape(str(name))}{badge}</span>"
            f"<span class='score-card-pts {cls}'>{pts}</span></div>")
    foot = f"<div class='score-card-date'>{footer}</div>" if footer else ""
    inner = (foot + body) if footer_top else (body + foot)
    return f"<div class='score-card'>{inner}</div>"


def rank_chip(cls, rank, *, prefix=""):
    """Small muted '<class> #<rank>' chip for score cards / headers. Returns ""
    when `rank` is falsy (team not yet ranked) so callers append unconditionally.
    `prefix` labels the system when needed (e.g. 'TRK ')."""
    if not rank:
        return ""
    label = f"{html.escape(str(cls))} #{rank}" if cls else f"#{rank}"
    return f"<span class='rank-chip'>{html.escape(prefix)}{label}</span>"


def style_fig(fig, height=340, **kw):
    """Apply the shared modern dark Plotly theme. Pass ``margin=`` to override.

    Additive aesthetic upgrade: system-matched font, a modern categorical
    colourway (only affects traces with no explicit colour), and a crisp dark
    hover card. Existing call sites are unchanged — colours set per-trace win.
    """
    margin = kw.pop("margin", dict(l=46, r=22, t=46, b=42))
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=margin,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        font=dict(family=FONT_FAMILY, size=12, color="#c9d1d9"),
        colorway=PALETTE,
        hoverlabel=dict(bgcolor="#0d1117", bordercolor="#30363d",
                        font=dict(family=FONT_FAMILY, size=12, color="#f0f6fc")),
        bargap=0.22, **kw)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    return fig


# ── Dashboard / BI primitives ─────────────────────────────────────────────────
# Pure-Streamlit/Plotly building blocks for the "blend of analytics + cutting-edge
# dashboard" look. No extra pip dependencies (works on the deploy mirror + CPU
# box). NOTE: st.metric is ALREADY styled into KPI cards by the Modern UI 2.0
# layer in assets/styles.css ([data-testid="stMetric"]) — do not re-inject that.

def gauge(value, title="", vmin=0, vmax=100, ref=None, suffix="", accent=None,
          height=190, number_fmt=".0f", bands=None):
    """A Plotly Indicator dial — the BI 'gauge' KPI. Returns a styled figure.

    `ref` draws a threshold + a delta vs that reference (e.g. league average).
    `bands` = list of (lo, hi, color) coloured zones; defaults to subtle
    red/amber/green thirds. `accent` colours the value bar (defaults to gold).
    """
    import plotly.graph_objects as go
    accent = accent or "#f0a500"
    if bands is None:
        third = (vmax - vmin) / 3
        bands = [(vmin, vmin + third, "rgba(231,76,60,0.20)"),
                 (vmin + third, vmin + 2 * third, "rgba(240,165,0,0.18)"),
                 (vmin + 2 * third, vmax, "rgba(63,185,80,0.20)")]
    mode = "gauge+number+delta" if ref is not None else "gauge+number"
    g = dict(
        axis=dict(range=[vmin, vmax], tickfont=dict(size=9, color="#8b949e")),
        bar=dict(color=accent, thickness=0.28),
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
        steps=[dict(range=[lo, hi], color=c) for lo, hi, c in bands],
    )
    if ref is not None:
        g["threshold"] = dict(line=dict(color="#f0f6fc", width=2), thickness=0.75,
                              value=ref)
    fig = go.Figure(go.Indicator(
        mode=mode, value=value,
        number=dict(suffix=suffix, font=dict(size=26, color="#f0f6fc"),
                    valueformat=number_fmt),
        delta=(dict(reference=ref, valueformat="+.1f",
                    increasing=dict(color=GOOD), decreasing=dict(color=BAD))
               if ref is not None else None),
        title=dict(text=title, font=dict(size=12, color="#c9d1d9")),
        gauge=g))
    fig.update_layout(height=height, margin=dict(l=14, r=14, t=34, b=6),
                      paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(family=FONT_FAMILY, color="#c9d1d9"))
    return fig


def kpi(col, label, value, delta=None, help=None, delta_color="normal"):
    """Thin wrapper over st.metric so BI scorecard call sites read declaratively.
    `col` is an st.columns slot (or st itself)."""
    col.metric(label, value, delta, help=help, delta_color=delta_color)


# ── Rich table + chart wrappers (optional deps, graceful fallback) ────────────────
# streamlit-aggrid and streamlit-extras are optional. If either can't import (e.g.
# the deploy mirror, or a stripped venv), these degrade to the native Streamlit
# widget so no page breaks. Single source so the rich-table / chart-export look is
# identical everywhere — the display mirror of the "degrade gracefully" rule.

def grid(df, key, *, height=480, page_size=25, fit_columns=False, pin_first=True):
    """Sortable, per-column-filter table via streamlit-aggrid; native
    ``st.dataframe`` fallback. ``key`` must be unique per call. Use for any dense,
    explorable table (rankings, stat dumps) where the user benefits from in-grid
    sort/filter the static dataframe can't give.

    Readability defaults (laptop + phone): headers WRAP instead of truncating to
    "Abc…", a per-column minimum width keeps values from clipping to "1…" (the grid
    scrolls horizontally past the viewport rather than squishing every column), and
    the first column (the identity — name/team) is PINNED left so it stays visible
    while you scroll the stat columns. Pass ``pin_first=False`` for a narrow /
    single-entity table where pinning just wastes space.

    Numeric columns are display-rounded (cards.round_df: 1 decimal, 2 on
    small-magnitude ratio columns) — no raw float tails in any grid."""
    try:
        from helpers.cards import round_df
        df = round_df(df)
    except Exception:
        pass
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
        gob = GridOptionsBuilder.from_dataframe(df)
        gob.configure_default_column(
            filter=True, sortable=True, resizable=True,
            minWidth=74, wrapHeaderText=True, autoHeaderHeight=True)
        if pin_first and len(df.columns):
            # Identity column: pin left + a touch wider so names aren't clipped.
            gob.configure_column(df.columns[0], pinned="left", minWidth=132)
        gob.configure_pagination(paginationAutoPageSize=False,
                                 paginationPageSize=page_size)
        # NO_UPDATE: sort/filter/page clicks stay inside the grid iframe instead
        # of rerunning the whole host page (nothing reads the grid's return).
        AgGrid(df, gridOptions=gob.build(), height=height, theme="streamlit",
               key=key, fit_columns_on_grid_load=fit_columns,
               update_mode=GridUpdateMode.NO_UPDATE)
    except Exception:
        st.dataframe(df, hide_index=True, width="stretch", key=f"{key}_native")


def chart(fig, *, data=None, key=None, export=("CSV",)):
    """Render a Plotly ``fig``. When ``data`` is supplied AND streamlit-extras is
    importable, wrap it in a ``chart_container`` that adds *Dataframe* + *Export*
    (CSV) tabs beneath the chart — so any viz becomes inspectable / downloadable
    with no per-page boilerplate. Plain ``st.plotly_chart`` otherwise. Honours the
    app width convention (``width='stretch'``)."""
    if data is not None:
        try:
            from streamlit_extras.chart_container import chart_container
            with chart_container(data, export_formats=list(export)):
                st.plotly_chart(fig, width="stretch", key=key)
            return
        except Exception:
            pass
    st.plotly_chart(fig, width="stretch", key=key)


# ── Empty state / loading ───────────────────────────────────────────────────────
def empty_state(title, body="", *, icon="🏀", cta=None, page=None):
    """Branded empty-state card — the polished replacement for a bare ``st.info``.

    Use on any tab/section that has no data yet (e.g. an untracked team). Accent
    and theming come from the global ``.empty-state`` CSS (assets/style.css), so
    it restyles with the chosen theme. ``cta`` is an optional next-step line;
    pass ``page`` (an ``st.page_link`` target, e.g. ``"pages/1_Input_Hub.py"``)
    to render the CTA as a real clickable link instead of the static pill."""
    cta_html = f"<div class='empty-state-cta'>{cta}</div>" if cta and not page else ""
    st.markdown(
        f"<div class='empty-state'><div class='empty-state-icon'>{icon}</div>"
        f"<div class='empty-state-title'>{title}</div>"
        f"<div class='empty-state-body'>{body}</div>{cta_html}</div>",
        unsafe_allow_html=True)
    if page:
        st.page_link(page, label=cta or "Open")


def loading(msg="Crunching the numbers…"):
    """Spinner contextmanager for heavy cached calls: ``with ui.loading('…'):``.
    Thin passthrough over ``st.spinner`` so call sites read consistently."""
    return st.spinner(msg)


# ── Team identity colour ─────────────────────────────────────────────────────────
def team_color(name, team_id=None):
    """A stable identity colour for a team, so each team carries one colour across
    every chart/card with **no schema change**.

    The colour is a deterministic hash of the team name into the shared
    ``PALETTE`` (``hashlib`` — stable across processes, unlike ``hash()``). If
    ``team_id`` is given and a per-team override is stored in ``app_settings``
    (set on the Settings page, key ``team_color::<id>``), that override wins."""
    if team_id is not None:
        try:
            from helpers.settings_utils import get_setting
            override = get_setting(f"team_color::{team_id}", "")
            if override:
                return override
        except Exception:
            pass
    import hashlib
    digest = hashlib.md5(str(name).strip().lower().encode("utf-8")).hexdigest()
    return PALETTE[int(digest, 16) % len(PALETTE)]


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 0/1/2 — shared "analytics lab" components
#  Single source for the signature tiles + the win-probability ribbon + the
#  modern input wrappers, so pages stop re-implementing inline HTML and every
#  surface picks up theme/motion/tier encoding from assets/style.css at once.
# ══════════════════════════════════════════════════════════════════════════════

def lab_hero(name, sub=None, *, chips=None, form=None, phase=None, accent=None):
    """Neon team/page identity band (the `.lab-hero` look, previously inline on
    only 2 pages). ``phase`` renders an ANALYZE/BUILD/PLAN pill; ``form`` is a
    list of recent 'W'/'L' rendered as glowing pills; ``chips`` a row of
    stat-chips. Drop-in richer alternative to ``page_header`` for hero pages."""
    accent = accent or get_setting("accent_color", "#f0a500")
    phase_html = (f"<span class='badge accent' style='margin-bottom:9px'>"
                  f"{html.escape(str(phase))}</span><br>" if phase else "")
    sub_html = (f"<div class='lab-hero-sub'>{html.escape(str(sub))}</div>"
                if sub else "")
    chip_html = "".join(f"<span class='stat-chip'>{html.escape(str(c))}</span>"
                        for c in (chips or []))
    chips_wrap = (f"<div class='lab-hero-chips'>{chip_html}</div>"
                  if chip_html else "")
    form_html = ""
    if form:
        pills = "".join(
            f"<span class='form-pill "
            f"{'w' if str(f).upper().startswith('W') else 'l'}'>"
            f"{html.escape(str(f)[:1].upper())}</span>" for f in form)
        form_html = (
            "<div class='form-strip' style='margin-top:13px'>"
            "<span style='font-size:10px;color:var(--subtext);"
            "text-transform:uppercase;letter-spacing:1.4px;margin-right:2px'>"
            f"Last {len(form)}</span>{pills}</div>")
    st.markdown(
        f"<div class='lab-hero'>{phase_html}"
        f"<div class='lab-hero-name' style='color:{accent}'>"
        f"{html.escape(str(name))}</div>"
        f"{sub_html}{chips_wrap}{form_html}</div>",
        unsafe_allow_html=True)


def wp_ribbon(curve, *, home_name="Home", accent=None, height=240, swings=3,
              total_secs=None):
    """Filled win-probability ribbon from a ``win_probability.wp_curve`` result
    (a list of ``(elapsed_secs, margin, wp)`` where ``wp`` is the home win prob
    0-1). Returns a styled ``go.Figure`` (or ``None`` for <2 points) so the
    caller places it where it wants. Quarter gridlines + markers on the biggest
    win-prob swings make the drama legible. This is the one curve the landing
    page used to compute and throw away."""
    import plotly.graph_objects as go
    if not curve or len(curve) < 2:
        return None
    accent = accent or get_setting("accent_color", "#f0a500")
    xs = [c[0] for c in curve]
    wp = [100 * c[2] for c in curve]
    r, g, b = rgb(accent)
    total = total_secs or xs[-1] or 1
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=wp, line_shape="hv", mode="lines",
        line=dict(color=accent, width=2.6), fill="tozeroy",
        fillcolor=f"rgba({r},{g},{b},0.14)", name=f"{home_name} win %",
        hovertemplate=f"{home_name} win: " + "%{y:.0f}%<extra></extra>"))
    fig.add_hline(y=50, line=dict(color="#8b949e", width=1, dash="dot"))
    # quarter dividers (480s HS quarters) within range
    for tk in range(480, int(total) + 1, 480):
        if tk < total:
            fig.add_vline(x=tk, line=dict(color="#30363d", width=1, dash="dot"))
    # markers on the biggest single-step win-prob swings
    if swings and len(curve) > 2:
        order = sorted(range(1, len(curve)),
                       key=lambda i: -abs(curve[i][2] - curve[i - 1][2]))
        pk = order[:swings]
        fig.add_trace(go.Scatter(
            x=[xs[i] for i in pk], y=[wp[i] for i in pk], mode="markers",
            marker=dict(size=9, color=accent,
                        line=dict(color="#0d1117", width=1.5)),
            hoverinfo="skip", showlegend=False))
    fig.update_yaxes(range=[0, 100], ticksuffix="%",
                     title=f"{home_name} win probability")
    fig.update_xaxes(visible=False)
    style_fig(fig, height, margin=dict(l=46, r=14, t=28, b=10), showlegend=False)
    return fig


def engine_status(label="Crunching the numbers…", steps=None):
    """``st.status`` wrapper for heavy engine calls — narrates that real
    computation is happening instead of a bare spinner. ``steps`` pre-writes
    narration lines. Use as ``with ui.engine_status('Solving RAPM…', [...]):``.
    Degrades to ``st.spinner`` on older Streamlit."""
    try:
        s = st.status(label, expanded=False)
        for line in (steps or []):
            s.write(line)
        return s
    except Exception:
        return st.spinner(label)


def seg(label, options, *, default=None, key=None, format_func=str,
        help=None, label_visibility="visible", container=None):
    """``st.segmented_control`` view-switcher with an ``st.radio`` fallback.
    Use for per-game/per-100, scope, off/def toggles — pill UI that feels modern
    and reruns instantly inside a fragment. ``container`` is an st.columns slot
    (or st, the default), mirroring ``gender_radio``."""
    c = container if container is not None else st
    dflt = default if default is not None else (options[0] if options else None)
    try:
        return c.segmented_control(
            label, options, default=dflt, key=key, format_func=format_func,
            help=help, label_visibility=label_visibility)
    except Exception:
        idx = options.index(default) if default in options else 0
        return c.radio(label, options, index=idx, key=key,
                       format_func=format_func, horizontal=True, help=help,
                       label_visibility=label_visibility)


def info_popover(label, body_md, *, icon="ⓘ"):
    """A click-to-reveal glossary / formula / detail popover (``st.popover``),
    falling back to an expander. The third disclosure layer that keeps dense
    pages clean without deleting any data."""
    try:
        with st.popover(f"{icon} {label}"):
            st.markdown(body_md)
    except Exception:
        with st.expander(f"{icon} {label}"):
            st.markdown(body_md)


def stat_help(abbr, *, icon="ⓘ", label=None):
    """Inline glossary popover for a stat ``abbr`` — its definition + formula,
    pulled straight from ``helpers.glossary.STAT_DEFS`` so the explanation lives
    in one place. Silent no-op when the abbr isn't in the glossary, so call sites
    stay safe to sprinkle next to any number."""
    try:
        from helpers.glossary import STAT_DEFS
        row = next((d for d in STAT_DEFS if d and d[0] == abbr), None)
        if not row:
            return
        full = row[1] if len(row) > 1 else abbr
        cat = row[2] if len(row) > 2 else ""
        formula = row[3] if len(row) > 3 else ""
        defn = row[4] if len(row) > 4 else ""
        how = row[5] if len(row) > 5 else ""
        body = f"**{full}**" + (f"  ·  _{cat}_" if cat else "") + "\n\n" + (defn or "")
        if formula:
            body += f"\n\n**Formula:** `{formula}`"
        if how:
            body += f"\n\n{how}"
        info_popover(label or abbr, body, icon=icon)
    except Exception:
        pass


def glossary_key(*abbrs, label="Stat key", icon="📖"):
    """One click-to-reveal popover defining several stat abbreviations at once
    (pulled from glossary.STAT_DEFS). Drop above any dense table so coaches can
    decode the columns without hunting — the multi-stat companion to ``stat_help``.
    Silently skips any abbr not in the glossary; renders nothing if none match."""
    try:
        from helpers.glossary import STAT_DEFS
        defs = {d[0]: d for d in STAT_DEFS if d}
        lines = []
        for a in abbrs:
            row = defs.get(a)
            if not row:
                continue
            full = row[1] if len(row) > 1 else a
            formula = row[3] if len(row) > 3 else ""
            defn = row[4] if len(row) > 4 else ""
            line = f"**{a}** — {full}" + (f": {defn}" if defn else "")
            if formula:
                line += f"  \n`{formula}`"
            lines.append(line)
        if lines:
            info_popover(label, "\n\n".join(lines), icon=icon)
    except Exception:
        pass


def chart_select(fig, *, key, selection_mode="points", on_select="rerun",
                 data=None):
    """Like ``chart()`` but returns Plotly selection events so a chart can be a
    cross-filter INPUT (tap a point → caller slices the panel beside it). Returns
    the selection dict (``{'selection': {...}}``) or None. Degrades to a plain
    render (returns None) on older Streamlit without ``on_select``."""
    try:
        return st.plotly_chart(fig, width="stretch", key=key,
                               on_select=on_select,
                               selection_mode=selection_mode)
    except TypeError:
        chart(fig, data=data, key=key)
        return None


def court_panel(fig, *, key, df=None, selection_mode="points"):
    """Render a shot-court figure as a cross-filter INPUT: tap shots/hexes and the
    Plotly selection comes back so the caller can slice the table/box beside it.
    Returns the selection dict (or None). Thin wrapper over ``chart_select`` so
    every court that wants drill-down behaves the same."""
    return chart_select(fig, key=key, selection_mode=selection_mode, data=df)


def shot_panel(shots, *, zone_data=None, model=None, key, title="Shots",
               height=470):
    """The unified shot surface — a segmented toggle between the located-shot DOTS,
    a points-over-expected HEAT hexbin (needs a league make-rate ``model``), and the
    legacy ZONE chart. Graceful by design: falls back to zones when there's no x,y,
    and returns False when there's nothing to show (caller renders an empty state).
    One helper so the x,y experience is identical on Players / Team / Scout, with
    the zone fallback for games that aren't tap-tracked. Returns True if rendered."""
    import helpers.court as _court
    located = bool(shots)
    opts = []
    if located:
        opts.append("Shot map")
        if model is not None:
            opts.append("Heat vs xPts")
    if zone_data:
        opts.append("Zones")
    if not opts:
        return False
    view = opts[0] if len(opts) == 1 else (seg("View", opts, key=f"{key}_view")
                                           or opts[0])
    if view == "Heat vs xPts" and located and model is not None:
        fig, _n = _court.shot_hexbin(shots, title=f"{title} — points over expected",
                                     model=model, mode="poe", height=height)
        st.plotly_chart(fig, width="stretch", key=f"{key}_poe")
        st.caption("Hexagon colour = points/shot **above/below** what the league "
                   "make-rate model expects from that spot — green beats the shot's "
                   "difficulty, red is below. Shot *quality*, not just makes.")
    elif view == "Shot map" and located:
        fig, _n = _court.shot_map(shots, title=title, height=height)
        st.plotly_chart(fig, width="stretch", key=f"{key}_map")
    elif zone_data:
        fig, ok = _court.shot_chart(zone_data, title=f"{title} (zones)",
                                    height=height)
        if not ok:
            return False
        st.plotly_chart(fig, width="stretch", key=f"{key}_zone")
    else:
        return False
    return True


def selected_xy(selection):
    """Pull ``[(x, y), …]`` out of a plotly ``on_select`` payload (returned by
    ``court_panel``/``chart_select``), robust to the few shapes Streamlit uses.
    Empty list when nothing is selected."""
    if not selection:
        return []
    sel = selection.get("selection") if isinstance(selection, dict) else None
    pts = (sel or {}).get("points") if isinstance(sel, dict) else None
    out = []
    for p in (pts or []):
        x, y = p.get("x"), p.get("y")
        if x is not None and y is not None:
            out.append((x, y))
    return out


# ── Signature HTML tiles (return strings; caller wraps with st.markdown) ──────
def _tile(cls, label, value, sub, label_cls, value_cls, tier_class, color):
    vc = f" {tier_class}" if tier_class else ""
    style = f" style='color:{color}'" if color else ""
    return (f"<div class='{cls}'>"
            f"<div class='{label_cls}'>{html.escape(str(label))}</div>"
            f"<div class='{value_cls}{vc}'{style}>{html.escape(str(value))}</div>"
            + (f"<div class='{label_cls.rsplit('-', 1)[0]}-sub'>"
               f"{html.escape(str(sub))}</div>" if sub else "")
            + "</div>")


def spotlight(num, label, sub="", *, tier_class="", color=None):
    """Big 'made-up metric' hero tile (the ``.spotlight`` look). ``tier_class``
    (from ``cards.tier_class``) tints the number by league tier."""
    vc = f" {tier_class}" if tier_class else ""
    style = f" style='color:{color}'" if color else ""
    return (f"<div class='spotlight'>"
            f"<div class='spotlight-num{vc}'{style}>{html.escape(str(num))}</div>"
            f"<div class='spotlight-lbl'>{html.escape(str(label))}</div>"
            + (f"<div class='spotlight-sub'>{html.escape(str(sub))}</div>"
               if sub else "") + "</div>")


def mini_tile(label, value, sub="", *, tier_class="", color=None):
    """Compact stat tile for dense grids (``.mini-tile``)."""
    return _tile("mini-tile", label, value, sub, "mini-lbl", "mini-val",
                 tier_class, color)


def chip(text, *, kind=""):
    """A small ``.badge`` pill. ``kind`` ∈ {'', 'accent', 'good', 'bad'}."""
    k = f" {kind}" if kind else ""
    return f"<span class='badge{k}'>{html.escape(str(text))}</span>"
