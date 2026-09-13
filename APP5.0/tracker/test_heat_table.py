"""A heated cell computed over five teams is a lie. (B1, extended to the grid)

`cards.pctile_bar` exists because "DRtg 96.1 · 80th pct · elite defense" once
meant *second of five* on screen, and `tracker/test_pctile_pool.py` guards the
row-level version of that rule. `ui.heat_table` is the grid-level counterpart —
the first `background_gradient`-shaped thing in this repo — and it can tell the
identical lie in a different shape: a dark-green cell in a six-row table reads as
"elite in this sport" and means "third of six".

So it carries the same discipline, and this file is the test that proves it:

  * below `POOL_FLOOR` NOTHING is coloured, and the table says why
  * at or above it, colour is the percentile WITHIN THE RENDERED ROWS, and the
    pool size is stated under the table
  * average is left uncoloured, so a field with no outliers looks like one
  * the direction set is honoured — a low TOV% must not paint red

The thin-pool assert is the point of the file. Everything else is the shape
around it.

Run: python -m pytest tracker/test_heat_table.py
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

from helpers.stats import POOL_FLOOR              # noqa: E402
import helpers.ui as UI                           # noqa: E402


def _render(df, **kw):
    """Run `heat_table` without Streamlit, capturing what it hands the page.

    The colour decision and the render are deliberately in one function — a
    caller cannot get the table without the pool line under it — so the seam
    this reaches through is the render call itself.

    Returns (object handed to st.dataframe, joined captions).
    """
    seen = {"obj": None, "cap": []}
    old_df, old_cap = UI.st.dataframe, UI.st.caption
    UI.st.dataframe = lambda obj, **_k: seen.__setitem__("obj", obj)
    UI.st.caption = lambda txt, *_a, **_k: seen["cap"].append(str(txt))
    try:
        UI.heat_table(df, "t", **kw)
    finally:
        UI.st.dataframe, UI.st.caption = old_df, old_cap
    return seen["obj"], " ".join(seen["cap"])


def _styles(df, **kw):
    """`{"styled": bool, "cells": [css…], "caption": str}`."""
    obj, cap = _render(df, **kw)
    styled = obj is not None and not isinstance(obj, pd.DataFrame)
    cells = list(_ctx(obj).values()) if styled else []
    return {"styled": styled, "cells": cells, "caption": cap}


def _ctx(styler):
    """(row, col) -> the cell's CSS as one string. Styler.apply is lazy, so
    `_compute()` is what materialises it."""
    if styler is None or isinstance(styler, pd.DataFrame):
        return {}
    out = {}
    for pos, css in styler._compute().ctx.items():
        if isinstance(css, str):
            out[pos] = css
        else:
            # pandas hands back a list of "prop: value" strings, or of
            # (prop, value) pairs depending on version.
            out[pos] = "; ".join(
                c if isinstance(c, str) else ": ".join(str(x) for x in c)
                for c in css)
    return out


def _styles_ctx(df, **kw):
    """(row, col) -> css, for column-level asserts."""
    obj, _ = _render(df, **kw)
    return _ctx(obj)


def _frame(n, col="NetRtg"):
    return pd.DataFrame({"name": [f"P{i}" for i in range(n)],
                         col: [float(i) for i in range(n)]})


# ── THE RULE ─────────────────────────────────────────────────────────────────

def test_thin_pool_is_never_coloured():
    """Below POOL_FLOOR: no Styler at all, and the caption says the order IS
    the rank. This is the assert the module exists for."""
    for n in range(2, POOL_FLOOR):
        got = _styles(_frame(n))
        assert not got["styled"], (
            f"a pool of {n} was heated; POOL_FLOOR is {POOL_FLOOR} and "
            "`pctile_bar` degrades to a rank at exactly this size")
        assert str(n) in got["caption"]
        assert "rank" in got["caption"].lower()


def test_pool_at_the_floor_is_coloured_and_states_its_size():
    got = _styles(_frame(POOL_FLOOR))
    assert got["styled"], "a pool at POOL_FLOOR should colour"
    assert any(c for c in got["cells"]), "nothing was actually painted"
    assert str(POOL_FLOOR) in got["caption"]


def test_pool_n_overrides_the_row_count():
    """A caller that knows its pool is thinner than the rows on screen (a
    league table padded with untracked rows, say) must be able to say so, and
    saying so must WITHHOLD colour rather than merely relabel it."""
    got = _styles(_frame(POOL_FLOOR + 6), pool_n=4)
    assert not got["styled"]
    assert "4" in got["caption"]


def test_identity_columns_are_never_heated():
    """Rank is the sort drawn twice; GP is a count, not an achievement; and
    ShotRating is shot DIFFICULTY, so green-high would tell a coach that taking
    hard shots is good."""
    df = _frame(POOL_FLOOR + 4)
    df["Rank"] = range(1, len(df) + 1)
    df["GP"] = 12
    df["ShotRating"] = [float(i) for i in range(len(df))]
    ctx = _styles_ctx(df)
    assert ctx, "nothing was painted at all"
    painted = {list(df.columns)[c] for (_r, c), css in ctx.items() if css}
    assert painted == {"NetRtg"}, painted


def test_direction_is_honoured_for_lower_is_better_columns():
    """The whole value of heat is that a colour means something without reading
    the number. A low turnover rate painting red would invert that, on the one
    column a coach is most likely to check."""
    n = POOL_FLOOR + 2
    df = pd.DataFrame({"name": [f"P{i}" for i in range(n)],
                       "TOV%": [float(i) for i in range(n)]})
    ctx = _styles_ctx(df)
    col = list(df.columns).index("TOV%")
    lowest = ctx.get((0, col), "")            # TOV% = 0, the BEST row
    highest = ctx.get((n - 1, col), "")       # the WORST row
    good = UI.GOOD.lstrip("#")
    bad = UI.BAD.lstrip("#")
    gr, gg, gb = (int(good[i:i + 2], 16) for i in (0, 2, 4))
    br, bg, bb = (int(bad[i:i + 2], 16) for i in (0, 2, 4))
    assert f"rgba({gr},{gg},{gb}" in lowest, (
        f"the LOWEST TOV% was not painted with GOOD: {lowest!r}")
    assert f"rgba({br},{bg},{bb}" in highest, (
        f"the HIGHEST TOV% was not painted with BAD: {highest!r}")


def test_average_is_left_uncoloured():
    """A field where every cell is coloured has no outliers in it, which is the
    opposite of what scanning is for."""
    n = 21
    df = pd.DataFrame({"name": [f"P{i}" for i in range(n)],
                       "NetRtg": [float(i) for i in range(n)]})
    ctx = _styles_ctx(df)
    col = list(df.columns).index("NetRtg")
    assert ctx.get((n // 2, col), "") == "", "the median row was painted"
    assert ctx.get((0, col), "") != ""
    assert ctx.get((n - 1, col), "") != ""


def test_a_constant_column_paints_nothing():
    """Every value identical is not a ranking. A gradient over one value draws
    an order that does not exist."""
    n = POOL_FLOOR + 5
    df = pd.DataFrame({"name": [f"P{i}" for i in range(n)],
                       "NetRtg": [7.0] * n})
    ctx = _styles_ctx(df)
    assert not any(ctx.values()), ctx


def test_empty_frame_renders_nothing_rather_than_raising():
    assert _styles(pd.DataFrame())["caption"] == ""


# ── the pool line is not optional ────────────────────────────────────────────

@pytest.mark.parametrize("n", [3, POOL_FLOOR, 40])
def test_every_render_states_its_pool(n):
    cap = _styles(_frame(n))["caption"]
    assert str(n) in cap, f"pool of {n} did not state its size: {cap!r}"
