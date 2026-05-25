"""
helpers/ui_utils.py
───────────────────
Shared UI primitives used across multiple pages.

Exports:
  PLOT_LAYOUT        — common Plotly layout kwargs
  patch_dataframe()  — call once per page to make st.dataframe Arrow-safe
  bar_h()            — horizontal bar chart helper
  normalize_col()    — 0-100 normalisation for a pandas Series
  percentile_of()    — what percentile is one value inside a Series
  pctile_bar_html()  — HTML snippet for a colour-coded percentile bar row
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import warnings
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler as _PdStyler


# ── Shared Plotly theme ───────────────────────────────────────────────────────
PLOT_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font_color="#c9d1d9",
    margin=dict(l=10, r=10, t=30, b=10),
)


# ── Arrow-safe st.dataframe wrapper ──────────────────────────────────────────
def patch_dataframe() -> None:
    """
    Call once near the top of each page (after `import streamlit as st`).
    Monkey-patches st.dataframe so every DataFrame is Arrow-safe before
    rendering, and suppresses Streamlit's internal Pandas4Warning.
    """
    _orig = st.dataframe

    def _safe_df(data=None, *args, **kwargs):
        if data is not None and not isinstance(data, _PdStyler):
            data = data.copy()
            for _c in data.columns:
                if data[_c].dtype.kind == 'O' or isinstance(data[_c].dtype, pd.StringDtype):
                    data[_c] = data[_c].astype(str)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            return _orig(data, *args, **kwargs)

    st.dataframe = _safe_df


# ── Horizontal bar chart ──────────────────────────────────────────────────────
def bar_h(df: pd.DataFrame, x_col: str, y_col: str,
          color: str = "#f0a500", title: str = "") -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df[x_col], y=df[y_col], orientation="h",
        marker_color=color,
        text=[f"{v:.1f}" if isinstance(v, float) else str(v) for v in df[x_col]],
        textposition="outside",
    ))
    fig.update_layout(
        **PLOT_LAYOUT, title=title,
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        xaxis=dict(showgrid=False),
        height=max(300, len(df) * 40),
    )
    return fig


# ── Normalisation ─────────────────────────────────────────────────────────────
def normalize_col(series: pd.Series) -> pd.Series:
    """Scale a Series to 0–100.  Returns 50 everywhere when all values equal."""
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([50.0] * len(series), index=series.index)
    return (series - mn) / (mx - mn) * 100


# ── Percentile helpers ────────────────────────────────────────────────────────
def percentile_of(val, series: pd.Series) -> float:
    """Return what percentile *val* sits at within *series* (0–100)."""
    vals = series.dropna().values
    if len(vals) == 0:
        return 50.0
    return float((vals < val).sum() / len(vals) * 100)


def pctile_bar_html(label: str, val, pct: float,
                    higher_better: bool = True) -> str:
    """Return an HTML string for one colour-coded percentile bar row."""
    effective = pct if higher_better else (100.0 - pct)
    color = ("#2ecc71" if effective >= 75
             else "#f0a500" if effective >= 50
             else "#e74c3c")
    val_str = f"{val:.1f}" if isinstance(val, float) else str(val)
    pct_str = f"{effective:.0f}th"
    return f"""
<div class="pctile-row">
  <div class="pctile-label-row">
    <span class="pctile-stat">{label}</span>
    <div style="display:flex;gap:10px;align-items:center">
      <span class="pctile-val">{val_str}</span>
      <span class="pctile-rank" style="color:{color}">{pct_str}</span>
    </div>
  </div>
  <div class="pctile-track">
    <div class="pctile-fill" style="width:{min(100, effective):.1f}%;background:{color}"></div>
  </div>
</div>"""
