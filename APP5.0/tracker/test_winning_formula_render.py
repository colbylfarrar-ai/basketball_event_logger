"""Headless render of the new Charts surfaces (spec 5l + 4c).

Covers Charts > Winning Formula and Charts > Offense > Playmaking >
Connection Matrix.

Unit tests cover the maths; this covers the things only a real render catches --
a name that is not in scope inside a fragment, a column_config that Streamlit
rejects, a verdict box that renders empty. Both of the bugs found when the Stops
subtab shipped on 2026-07-24 were of exactly this kind and no unit test could
have seen either.

AUTH TRAP: APP5.0/.streamlit/secrets.toml exists, so AppTest run with the repo
as cwd renders a ~38.8k-char "Sign in to continue" shell for EVERY page with
at.exception EMPTY. Identical char counts across two different pages is the
tell. This file chdirs to tracker/ (no secrets there) before running.

SEASON TRAP: SEAS.ACTIVE is "Current" == 2026-2027 with zero games. The tracked
book is under the archived "2025-2026" label and the picker must be driven.

Run with the REAL interpreter:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_winning_formula_render.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

SEASON = "2025-2026"
PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


def _text(at):
    out = []
    for kind in ("markdown", "caption", "text", "info", "subheader", "header",
                 "title", "metric", "warning", "error"):
        try:
            for el in at.get(kind) or []:
                v = getattr(el, "value", None)
                if isinstance(v, str):
                    out.append(v)
                lbl = getattr(el, "label", None)
                if isinstance(lbl, str):
                    out.append(lbl)
        except Exception:
            pass
    return "\n".join(out)


def run():
    global PASSED
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import helpers.ui as UI
    import helpers.entitlement as ENT

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    real_radio, real_paid, real_wide = (
        UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide)
    UI.gender_radio = lambda *a, **k: "F"
    ENT.has_paid_plan = lambda *a, **k: True
    ENT.viewer_is_league_wide = lambda *a, **k: True
    # ONE RENDER PER SUB-VIEW. This used to be a single render that asserted
    # on Winning Formula AND on Charts > Offense > Playmaking at the same time,
    # which only worked because `st.tabs` executes every tab body on every run.
    # The 2026-07-26 recut made Charts' inner switcher a `_seg`, so only the
    # open sub-view runs — that is the perf fix, and it means this harness has
    # to open each sub-view it wants to check.
    def _open(sub, nested=None):
        at = AppTest.from_file(os.path.join(_APP, "pages",
                                            "6_Team_Dashboard.py"),
                               default_timeout=900)
        at.session_state["ta_team"] = 1
        at.session_state["ta_season"] = SEASON
        at.session_state["td_view"] = "Charts"
        at.session_state["ch_sub"] = sub
        if nested:
            at.session_state["ch_sub_off"] = nested
        at.run()
        assert not at.exception, \
            f"Charts[{sub}] raised: " \
            + repr([repr(e.value)[:400] for e in at.exception])
        return at

    try:
        at = _open("Winning Formula")

        body = _text(at)
        print(f"  rendered {len(body)} chars of text, "
              f"{len(at.dataframe)} tables")
        ok(len(body) > 40000,
           f"NOT the 38.8k auth shell — real page rendered ({len(body)} chars)")
        ok("Sign in to continue" not in body, "no sign-in wall")
        ok("No finished games" not in body, "not the empty state")

        low = body.lower()
        # NOTE: AppTest does not expose st.tabs labels, and the switcher is a
        # `_seg` now anyway — the sub-view is proved by its CONTENT.
        ok("oliver" in low, "the Oliver anchor made it onto the page")
        ok("exchange rate" in low,
           "the honesty caption ('read this as an exchange rate') rendered")
        ok("four factors" in low, "the factors are named")
        ok("standard deviation" in low,
           "the verdict's unit is on the page, so the number is interpretable")

        # the specific harm this surface must never do
        ok("causes" not in low, "no causal language on the page")

        # the engine's own numbers should be reachable from the render
        import helpers.winning_formula as WF
        rows = WF.game_rows(gender="F", season=SEASON)
        lg = WF.league_formula(rows=rows)
        ok(lg["valid"], "engine agrees the fit is valid for this pool")
        top = lg["factors"][0]["noun"]
        ok(top.lower() in low,
           f"the league's top lever ({top!r}) appears in the rendered text")

        # the accessor is arrow_data_frame, not "dataframe" -- at.get("dataframe")
        # silently returns [] and would make a missing table look like a pass
        n_tables = len(at.dataframe)
        ok(n_tables >= 2,
           f"Charts rendered {n_tables} tables including the formula pair")

        # ── Charts > Offense > Playmaking ─────────────────────────────────
        # Its own render: a different sub-view is a different body now.
        at = _open("Offense", nested="Playmaking")
        low = _text(at).lower()

        # connection matrix (spec 4c)
        ok("connection matrix" in low, "the connection matrix rendered")
        ok("expected assists" in low,
           "the grid is labelled in xA, not raw assist counts")
        ok("teammates fed" in low,
           "the distributor roll-up rendered (a hub is not a high assist total)")
        ok("main line" in low, "the connection verdict box rendered")
        ok(len(at.get("plotly_chart") or []) > 0,
           "the heat-grid chart rendered alongside the node-link network")

        # ── Charts > Offense > Playmaking: involvement (spec 4d) ──────────
        ok("hand in the basket" in low, "the involvement panel rendered")
        ok("most involved" in low, "its verdict box rendered")
        ok("minutes stat" in low,
           "the caption explains the on-floor denominator, which is the "
           "whole design")
        ok("participation is not causation" in low,
           "and refuses the causal reading explicitly")

        # -- Charts > Offense > Playmaking: hero-ball Gini (spec 5j) -------
        ok("system offence or hero ball" in low, "the concentration panel rendered")
        ok("per-minute scoring rates" in low,
           "the headline is the rate Gini, not the raw point-total one")
        ok("rotation-depth stat" in low,
           "and the caption names the confound it divides out")
        ok("not a judgement" in low,
           "and refuses to tell a coach their concentration is wrong")
    finally:
        UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide = (
            real_radio, real_paid, real_wide)


if __name__ == "__main__":
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        run()
    finally:
        os.chdir(cwd)
    print(f"\n{PASSED} checks passed.")
