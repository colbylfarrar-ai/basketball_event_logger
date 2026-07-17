"""Headless render smoke for the Rankings "Team Charts" story dispatch.

Every story under League landscape -> Team Charts must render real charts. A
story that renders ZERO charts is a failure, not a pass — this whole file exists
because three separate traps each produce a silent, exception-free blank page:

  1. AUTH. ``auth_enabled()`` is ``"auth" in st.secrets``, and st.secrets is read
     from CWD/.streamlit/. Running inside APP5.0 (which has a real secrets.toml)
     makes require_login() call st.stop(): the page renders nothing and reports
     no exception. This test chdirs to a secrets-free cwd.
  2. SEASON. ``SEAS.ACTIVE`` is the CURRENT season, which may legitimately have
     no tracked games yet (they live in the archived label). The page then shows
     its correct empty state — and a naive smoke reads that as "passed".
  3. SEG DEFAULT. A ``seg`` renders its DEFAULT silently, so an unseeded run only
     ever exercises the first story (the gotcha UI_DENSITY_PLAN records in blood).

Run: python tracker/test_rankings_stories.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0
STORIES = ["Offense", "Play Style", "Defense", "Quarters & Pace"]


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _tracked_season(gender="F"):
    """The season label that actually HAS tracked games, as the picker shows it.

    Returns (season_label_for_widget, gender) or (None, None) when the DB has no
    tracked games at all — in which case the render test is skipped rather than
    reported as a false pass.
    """
    import helpers.seasons as SEAS
    import helpers.team_ratings as TR
    for value, label in SEAS.season_options():
        for g in (gender, "M" if gender == "F" else "F"):
            if TR.tracked_ratings(gender=g, season=value):
                return label, g
    return None, None


def test_stories_render():
    """Each story renders at least one chart with the real DB behind it."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    # st.page_link raises KeyError('url_pathname') under AppTest (no page ctx).
    # It's chrome, not content — stub it so the body can be exercised.
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None

    season_label, gender = _tracked_season()
    if not season_label:
        print("  -- no tracked games in this DB; render smoke skipped")
        return

    page = os.path.join(_APP, "pages", "5_Rankings.py")
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        for story in STORIES:
            at = AppTest.from_file(page, default_timeout=300)
            at.session_state["rk_view"] = "League landscape"
            at.session_state["rk_ll_section"] = "Team Charts"
            at.session_state["rk_chart_story"] = story
            at.session_state["rk_season"] = season_label
            at.run()
            assert not at.exception, \
                f"{story} raised: {[repr(e.value)[:200] for e in at.exception]}"
            n = len(at.get("plotly_chart") or [])
            ok(n > 0, f"{story} rendered {n} charts")
    finally:
        os.chdir(cwd)


def test_style_pack_shape():
    """team_style_pack returns the four style lenses, and an untagged team is
    absent rather than zeroed (a thin sample must never plot as league-worst)."""
    import helpers.league_analytics as LA
    import helpers.seasons as SEAS
    import helpers.team_ratings as TR

    season = gender = None
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            if TR.tracked_ratings(gender=g, season=value):
                season, gender = value, g
                break
        if season:
            break
    if not season:
        print("  -- no tracked games in this DB; style-pack shape test skipped")
        return

    p = LA.team_style_pack(gender=gender, season=season)
    ok(bool(p["teams"]), f"style pack found {len(p['teams'])} tracked teams")
    for k in ("sets", "schemes", "faced", "lens"):
        ok(k in p, f"style pack exposes '{k}'")

    # A zero-possession row is LEGAL: team_named_playtypes keeps a set that only
    # ever drew fouls (poss == 0 and FD > 0), and stats._safe gives it PPP 0.0
    # rather than None. So PPP alone can NOT be trusted to mean "has a sample" —
    # every consumer must gate on `poss`. This asserts the trap still exists (so
    # the rule stays honest if the engine changes) and that thin rows really are
    # thin, not silently real.
    thin = 0
    for t in p["teams"]:
        for k in ("sets", "schemes", "faced"):
            for row in (p[k].get(t) or {}).values():
                if row["poss"] == 0:
                    thin += 1
                    assert row["PPP"] == 0.0, \
                        f"{k}: zero-poss row for team {t} — expected PPP 0.0 " \
                        f"from _safe, got {row['PPP']!r}; consumers gate on poss"
    ok(True, f"{thin} zero-poss rows carry PPP 0.0 — consumers must gate on poss")


if __name__ == "__main__":
    test_style_pack_shape()
    test_stories_render()
    print(f"\nALL {PASSED} CHECKS PASSED")
