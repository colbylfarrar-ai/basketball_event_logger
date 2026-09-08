"""One player card, and a door into it from the table a coach actually reads.

THE BOOK §14.1 asked for the player view consolidated into one screen, on the
grounds that `player_card.py` is "shared by the Team Dashboard Roster view, the
Players page, a quick-view dialog and the Insights deck's player lines — four
surfaces disagreeing about what belongs where".

Measured before building anything, THREE of those four already share one
renderer: `build_card_ctx` + `render_card` serve the Team Dashboard's Profile
view (6_Team_Dashboard._render_profile), the Players page's Profile tab, and
the Players page's quick-view dialog. The Insights deck's player lines are
prose from the insight feed, not a card, and are a different artefact on
purpose. So the consolidation the finding asks for is largely already done.

What was NOT done is a door. The roster scan is the table a coach looks at
most, and the only route from it into a card was to switch to the Player
sub-view and re-pick the name already on screen. This adds `ctx.quick_view` —
the page's opener over the SAME builder and renderer — so the roster gets a
door rather than a fourth version of the card.

Two shapes this had to get right, and both were wrong on the first cut and
found by rendering rather than by a unit test:

  * `ctx.players` is the bundle's LIST of stat rows, not a {pid: row} map, and
    the pid on those rows is `_pid` — the stat table's own pid is its dict KEY
    and is not a column;
  * the picker labels through `stats.player_label`, because a scouted player's
    `name` is a bare jersey number and a dropdown full of integers is §10's
    finding in the one place a coach chooses from.

AUTH TRAP: chdir into tracker/ (a secrets-free cwd) or every page renders the
~38.8k "Sign in to continue" shell with at.exception EMPTY.
SEASON TRAP: the tracked book is under the archived "2025-2026" label.

Run: python tracker/test_roster_quick_view.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

SEASON = "2025-2026"
TEAM = 1
PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


def run():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import helpers.ui as UI
    import helpers.entitlement as ENT

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    real = (UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide)
    UI.gender_radio = lambda *a, **k: "F"
    ENT.has_paid_plan = lambda *a, **k: True
    ENT.viewer_is_league_wide = lambda *a, **k: True
    try:
        at = AppTest.from_file(os.path.join(_APP, "pages",
                                            "6_Team_Dashboard.py"),
                               default_timeout=1200)
        for k, v in dict(ta_team=TEAM, ta_gender="F", ta_season=SEASON,
                         td_view="Roster", td_roster_view="Roster").items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, "Roster raised: " + repr(
            [repr(e.value)[:400] for e in at.exception])

        labels = [getattr(s, "label", "") for s in (at.get("selectbox") or [])]
        buttons = [getattr(b, "label", "") for b in (at.get("button") or [])]
        ok("Open a card" in labels, "the roster scan offers the card opener")
        ok("Open card" in buttons, "…with the button that fires it")

        sel = [s for s in at.get("selectbox")
               if getattr(s, "label", "") == "Open a card"][0]
        opts = [o for o in sel.options if o and "Pick a player" not in str(o)]
        ok(len(opts) >= 5, f"the picker is populated ({len(opts)} players)")
        ok(not any(str(o).strip().isdigit() for o in opts),
           "no option is a bare jersey number — player_label, not row['name']")

        # the opener is the PAGE's, over the shared builder — assert the seam
        src = open(os.path.join(_APP, "pages", "6_Team_Dashboard.py"),
                   encoding="utf-8").read()
        ok("def _roster_quick_view(" in src, "the page still defines an opener")
        ok("_players_ctx.quick_view = _roster_quick_view" in src,
           "…and still hands it to the roster tab")
        ok("from helpers.dashboard.player_card import quick_view" in src,
           "the opener still routes through the SHARED dialog, not a copy")

        tab = open(os.path.join(_APP, "helpers", "dashboard",
                                "players_tab.py"), encoding="utf-8").read()
        ok('getattr(ctx, "quick_view", None)' in tab,
           "the tab still reads the attribute the page sets")
        ok('p.get("_pid")' in tab,
           "the tab still reads _pid — bundle rows carry no 'id'")
        ok("_PLBL(p)" in tab, "…and still labels through player_label")

        # the three surfaces that were already one, held so a future edit
        # cannot quietly fork the card again
        for path, what in (
                ("pages/7_Players.py", "the Players page profile"),
                ("pages/6_Team_Dashboard.py", "the dashboard profile")):
            s2 = open(os.path.join(_APP, *path.split("/")), encoding="utf-8").read()
            ok("render_card(build_card_ctx(" in s2,
               f"{what} still renders the shared card")
        pc = open(os.path.join(_APP, "helpers", "dashboard", "player_card.py"),
                  encoding="utf-8").read()
        ok(pc.count("def render_card(") == 1,
           "there is still exactly ONE card renderer")
        ok("ctx = build_card_ctx(" in pc,
           "and the modal still builds its ctx the same way")
    finally:
        UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide = real


if __name__ == "__main__":
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        run()
    finally:
        os.chdir(cwd)
    print(f"\n{PASSED} checks passed.")
