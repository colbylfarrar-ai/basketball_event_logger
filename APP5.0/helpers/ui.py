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
        st.rerun()
    _refreshed = st.session_state.get("_data_refreshed_at")
    if _refreshed:
        st.sidebar.caption(f"Data refreshed at {_refreshed}")
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


def score_card(rows, *, footer="", footer_top=False, style_names=False):
    """Return HTML for the standard score card (CSS in assets/style.css).

    `rows` = [(name, points, won_bool), …] rendered top-to-bottom; the winner row
    gets `.score-winner`, the loser `.score-loser` — on the points cell, and on
    the team name too when `style_names=True`. `footer` is the small meta line
    (date / margin, may hold a badge span); `footer_top` renders it above the rows.
    Caller wraps the result with st.markdown(..., unsafe_allow_html=True).
    """
    body = ""
    for name, pts, won in rows:
        cls = "score-winner" if won else "score-loser"
        ncls = f" {cls}" if style_names else ""
        body += (
            "<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<span class='score-card-team{ncls}'>{html.escape(str(name))}</span>"
            f"<span class='score-card-pts {cls}'>{pts}</span></div>")
    foot = f"<div class='score-card-date'>{footer}</div>" if footer else ""
    inner = (foot + body) if footer_top else (body + foot)
    return f"<div class='score-card'>{inner}</div>"


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
    single-entity table where pinning just wastes space."""
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
