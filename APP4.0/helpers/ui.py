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

# Match the in-app system font stack so chart text reads as one with the UI.
FONT_FAMILY = ("'Segoe UI Variable Display','Segoe UI',-apple-system,"
               "BlinkMacSystemFont,Inter,Roboto,sans-serif")

_CSS_PATH = _ROOT / "assets" / "styles.css"


# ── Page boot ───────────────────────────────────────────────────────────────────
def page_chrome():
    """Standard page boot, returning ``(settings_dict, accent_hex)``.

    Runs DB init, applies the stored page config + theme, and injects the global
    stylesheet. ``apply_page_config`` is the first ``st.*`` call (Streamlit
    requires set_page_config to come first), so call this before any other
    ``st.*`` on the page.
    """
    initialize_database()
    cfg = get_all_settings()
    apply_page_config(cfg)
    if _CSS_PATH.exists():
        st.markdown(
            f"<style>{_CSS_PATH.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )
    apply_theme_css(cfg)
    return cfg, get_setting("accent_color", "#f0a500")


# ── Chart primitives ─────────────────────────────────────────────────────────────
def rgb(hex_color):
    """'#rrggbb' → (r, g, b) ints."""
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16))


def q_label(q):
    """Quarter number → label ('Q1'..'Q4', then 'OT1', 'OT2', ...)."""
    return f"Q{q}" if q <= 4 else f"OT{q - 4}"


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
