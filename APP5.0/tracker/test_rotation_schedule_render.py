"""Headless render smoke for the Suggested Rotation on BOTH surfaces.

The scheduler has its own db-free unit tests (test_rotation_schedule.py); this
one proves the section actually DRAWS — on the Team Dashboard -> Projection and
in the War Room -> Lineups -> Rotation optimizer, which share one renderer.

The same three traps as the Rankings smoke apply and are handled the same way:
AUTH (chdir to a secrets-free cwd so require_login doesn't st.stop() into a
silent blank page), SEASON (seed the label that actually has tracked games, not
the current one), and SEG DEFAULT (seed every segmented control on the path —
an unseeded seg silently renders its first option, so the page under test is
never reached).

Run: python tracker/test_rotation_schedule_render.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _projectable_team():
    """A (team_id, season_value, season_label, gender) the engine can actually
    project — anything less and the surface renders its honest empty state and a
    naive smoke reads that as a pass."""
    import helpers.seasons as SEAS
    import helpers.lineup_projection as LP
    from database.db import query
    for value, label in SEAS.season_options():
        rows = query("SELECT team1_id AS t, COUNT(*) n FROM games WHERE tracked=1 "
                     "AND season=? GROUP BY team1_id ORDER BY n DESC LIMIT 5",
                     (value,))
        for r in rows:
            ctx = LP.build_context(r["t"], season=value)
            if ctx.get("gated"):
                continue
            g = query("SELECT gender FROM teams WHERE id=?", (r["t"],))
            return r["t"], value, label, (g[0]["gender"] if g else "F")
    return None, None, None, None


def test_schedule_engine_on_real_data():
    """The scheduler runs on a real roster: 16 blocks, budget respected."""
    import helpers.lineup_projection as LP
    import helpers.rotation_schedule as RS
    tid, season, _label, _g = _projectable_team()
    if tid is None:
        print("  -- no projectable team in this DB; engine smoke skipped")
        return
    ctx = LP.build_context(tid, season=season)
    opt = LP.optimize_minutes(tid, ctx=ctx)
    s = RS.suggest_rotation(tid, ctx, opt, game_ids=ctx.get("game_ids"))
    assert not s.get("gated"), s.get("gated")
    ok(len(s["blocks"]) == RS.N_BLOCKS, f"{len(s['blocks'])} blocks scheduled")
    ok(all(len(b["five"]) == RS.SLOTS for b in s["blocks"]),
       "every block puts five on the floor")
    ok(s["minutes"] == {p: float(m) for p, m in s["target_minutes"].items()},
       "scheduled minutes match the optimizer exactly")
    ok(any(p["preset"] or "Rotation five" not in p["label"]
           for p in s["segments"]), "preset fives make it into the plan")
    ok(max(r["entries"] for r in s["stints"]) <= 6,
       "no player is asked to check in more than 6 times")


def _run_page(page, state):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    at = AppTest.from_file(os.path.join(_APP, "pages", page), default_timeout=400)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, \
        f"{page} raised: {[repr(e.value)[:300] for e in at.exception]}"
    return at


def _assert_drawn(at, where):
    """The section is present AND its chart really rendered.

    AppTest does not expose a plotly element's `key`, so identify the chart by
    its own caption — which is written directly after st.plotly_chart inside the
    same try block. A swallowed chart exception drops the caption with it, so
    this can't pass on a section that silently failed to draw."""
    md = " ".join(m.value for m in (at.get("markdown") or []))
    caps = " ".join(c.value for c in (at.get("caption") or []))
    ok("Suggested rotation" in md, f"{where} rendered the Suggested Rotation section")
    ok(len(at.get("plotly_chart") or []) > 0, f"{where} rendered a chart")
    ok("Dotted lines = quarter breaks" in caps,
       f"{where} drew the rotation chart itself")


def test_both_surfaces_draw_the_chart():
    tid, _season, label, _g = _projectable_team()
    if tid is None:
        print("  -- no projectable team in this DB; render smoke skipped")
        return
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))    # secrets-free cwd
    try:
        at = _run_page("6_Team_Dashboard.py",
                       {"ta_team": tid, "ta_season": label, "td_view": "Projection"})
        _assert_drawn(at, "dashboard Projection")

        at = _run_page("9_War_Room.py",
                       {"wr_view": "Lineups", "wr_lu_view": "Rotation optimizer",
                        "wropt_team": tid, "wr_season": label})
        _assert_drawn(at, "War Room Lineups")
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    test_schedule_engine_on_real_data()
    test_both_surfaces_draw_the_chart()
    print(f"--- {PASSED} rotation-render checks pass ---")
