"""The two ways into Players' Profile section still land there.

`pages/7_Players.py` used to be eight `st.tabs`, which execute EVERY body on
every rerun. That is what made these two entry points work without anyone
having to think about them:

  1. `?player=<id>` — a link out of a landing or search leaderboard.
  2. `_palette_player` — the sidebar command palette (`helpers.ui._palette_dialog`),
     which is on every page in the app and `switch_page`s here.

Both are consumed inside `_fx_prof`. The 2026-09-12 conversion to lazy `_seg`
dispatch means `_fx_prof` runs ONLY when its section is open — so both links
silently landed on "Leaders" and did nothing. Nothing raised; the coach just
got the wrong screen, which is the failure mode no suite catches by accident.

The page now parks `pl_view` before the switcher is built. This pins that, and
pins the half that is easy to get wrong in the other direction: parking must
not TRAP the coach in the Profile for as long as `?player=` sits in the URL.

Run: python tracker/test_players_deeplink.py
"""
import os
import sys

# Needs a secrets-free cwd (the real secrets.toml [auth] gates every page) and
# rebinds a module global, both process-wide. Run as its own process.
RUN_AS_SCRIPT = True

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


def _at(**state):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    at = AppTest.from_file(os.path.join(_APP, "pages", "7_Players.py"),
                           default_timeout=300)
    for k, v in state.items():
        at.session_state[k] = v
    return at


def _view_of(at):
    """Whichever section the switcher settled on, read back off its key.

    AppTest's session_state is a SafeSessionState proxy, not a dict: it has no
    `.get`, and `__getattr__` turns that into `AttributeError: get not found in
    session_state` rather than anything that names the real problem.
    """
    try:
        return at.session_state["pl_view"]
    except (KeyError, AttributeError):
        return None


def run():
    # A SECRETS-FREE cwd, or every assertion below measures the login wall.
    # The real .streamlit/secrets.toml carries an [auth] block, `require_login`
    # calls st.stop(), and the page never reaches its switcher — so `pl_view`
    # comes back None and the failure reads like the deep link is broken rather
    # than like the page never rendered. Process-wide, which is what
    # RUN_AS_SCRIPT buys us. (`tracker/` has no secrets.toml; that is the point.)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    import helpers.auth as AUTH
    AUTH._LOCAL_IDENTITY = {"email": "colbyl.farrar@gmail.com", "name": "Colby",
                            "role": "admin", "plan": "paid", "paid_until": "",
                            "team_id": 1, "team_ids": [1], "shares_pool": 0,
                            "pool_banned": 0}

    print("-- the default --------------------------------------------------")
    at = _at()
    at.run()
    ok(not at.exception, f"the page opens clean ({at.exception})")
    # Assert the switcher actually RAN. `None` here means the page stopped
    # early — almost always the auth gate — and every later assertion would be
    # comparing None to a section name and calling it a routing bug.
    ok(_view_of(at) == "Leaders",
       f"the section switcher ran and opened on Leaders "
       f"(got {_view_of(at)!r} — None means the page st.stop()ed, check auth)")

    print("\n-- the command palette ------------------------------------------")
    # The palette sets this and switch_page()s here. It is the entry point most
    # likely to be used, because it is in the sidebar of every page.
    at = _at(_palette_player=1)
    at.run()
    ok(not at.exception, f"palette handoff renders ({at.exception})")
    ok(_view_of(at) == "Player Profile",
       f"a palette player opens the Profile (got {_view_of(at)!r})")

    print("\n-- ?player= deep link -------------------------------------------")
    at = _at()
    at.query_params["player"] = "1"
    at.run()
    ok(not at.exception, f"deep link renders ({at.exception})")
    ok(_view_of(at) == "Player Profile",
       f"?player= opens the Profile (got {_view_of(at)!r})")

    print("\n-- and it does NOT trap the coach there --------------------------")
    # The param stays in the URL after the jump. If the park fired on every run
    # rather than only on a NEW id, the coach could never reach another section
    # while it sat there — a worse bug than the one being fixed.
    at = _at(_prof_deeplink="1", pl_view="Shot Lab")
    at.query_params["player"] = "1"
    at.run()
    ok(not at.exception, f"an already-consumed deep link renders ({at.exception})")
    ok(_view_of(at) == "Shot Lab",
       f"a consumed ?player= leaves the chosen section alone "
       f"(got {_view_of(at)!r})")

    print(f"\n{PASSED} checks passed.")


if __name__ == "__main__":
    run()
