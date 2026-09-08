"""Overview zone C must LEAD with a sentence, not with five key-value rows.

THE BOOK §12.3: `team_card` rendered a header reading "Verdict — model reads"
over Pythagorean / luck / momentum / tracked rank and no verdict. The engine
that writes the verdict — `team_insights.team_insight_feed` — was already
cached league-wide and already consumed by Rankings and the War Room; the one
surface a coach opens first was the one that did not read it.

Two things only a real render catches, and both of them are why this file is a
render smoke rather than a unit test:

  * the feed is fetched inside a zone that is drawn per-column, so a name that
    is not in scope there is a NameError no engine test can see;
  * the opt-out is a CONTRACT between two files. Rankings renders the same feed
    wider and lower on the same screen, so it passes `verdict_lines=[]`. If that
    attribute is ever renamed on one side only, the coach reads the same
    sentence twice and nothing fails.

AUTH TRAP: APP5.0/.streamlit/secrets.toml gates every page, so this chdirs into
tracker/ (a secrets-free cwd) before rendering.
SEASON TRAP: SEAS.ACTIVE is "Current" and holds no tracked games; the tracked
book is under the archived "2025-2026" label and the picker must be driven.

Run: python tracker/test_overview_verdict_render.py
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


def _text(at):
    out = []
    for kind in ("markdown", "caption", "text", "info", "subheader", "header",
                 "title", "metric", "warning", "error"):
        try:
            for el in at.get(kind) or []:
                for attr in ("value", "label"):
                    v = getattr(el, attr, None)
                    if isinstance(v, str):
                        out.append(v)
        except Exception:
            pass
    return "\n".join(out)


def run():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import helpers.ui as UI
    import helpers.entitlement as ENT
    import helpers.dashboard.team_card as TC

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    real_radio, real_paid, real_wide = (
        UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide)
    UI.gender_radio = lambda *a, **k: "F"
    ENT.has_paid_plan = lambda *a, **k: True
    ENT.viewer_is_league_wide = lambda *a, **k: True

    try:
        # The engine half first: whatever the page is meant to print has to
        # exist before a missing sentence can be blamed on the renderer.
        lines = TC._insight_feed("F", SEASON).get(TEAM, [])
        ok(bool(lines), f"the feed has reads for team {TEAM} ({len(lines)} lines)")
        ok(all(isinstance(ln.get("n"), (int, float)) for ln in lines),
           "every line carries its own n — B1, no number without its sample")

        at = AppTest.from_file(os.path.join(_APP, "pages",
                                            "6_Team_Dashboard.py"),
                               default_timeout=900)
        at.session_state["ta_team"] = TEAM
        at.session_state["ta_gender"] = "F"
        at.session_state["ta_season"] = SEASON
        at.session_state["td_view"] = "Overview"
        at.run()
        assert not at.exception, "Overview raised: " + repr(
            [repr(e.value)[:400] for e in at.exception])

        body = _text(at)
        print(f"  rendered {len(body)} chars of text")
        ok("Sign in to continue" not in body, "no sign-in wall")
        ok("Verdict — model reads" in body, "zone C rendered")

        # The verdict itself. The feed's text is markdown with **bold**; the
        # zone converts those to <b>, so match on a bold-stripped body.
        flat = body.replace("**", "").replace("<b>", "").replace("</b>", "")
        lead = lines[0]["text"].replace("**", "")
        ok(lead[:40] in flat,
           f"the lead verdict is on the page: {lead[:60]!r}")
        ok(f"n={lines[0]['n']}" in flat,
           "and its sample is printed beside it")
        ok("league-relative auto-scout read" in body,
           "the caption says what kind of claim the sentence is")

        # It leads. The evidence rows follow it, they do not replace it.
        i_verdict = flat.find(lead[:40])
        i_pyth = flat.find("Pythagorean W-L")
        ok(i_verdict >= 0 and (i_pyth < 0 or i_verdict < i_pyth),
           "the sentence comes BEFORE the key-value evidence, not after it")

        # The opt-out contract with Rankings. Reading the attribute the page
        # sets is the only way to catch a one-sided rename.
        import re
        src = open(os.path.join(_APP, "pages", "5_Rankings.py"),
                   encoding="utf-8").read()
        ok(re.search(r"verdict_lines\s*=\s*\[\]", src),
           "Rankings still opts out (it renders the same feed wider, below)")
        card = open(os.path.join(_APP, "helpers", "dashboard", "team_card.py"),
                    encoding="utf-8").read()
        ok('getattr(ctx, "verdict_lines", None)' in card,
           "and the card still reads the attribute Rankings sets")
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
