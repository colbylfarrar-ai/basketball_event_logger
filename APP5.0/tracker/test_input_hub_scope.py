"""
The Input Hub's ownership gate, and the sections it absorbed on 2026-09-12.

Until that date this page imported no entitlement at all: its only gate queued
DELETES for admin approval, so every UPDATE and INSERT was league-wide open —
any signed-in coach could rename any team or rewrite any game's score. The page
that gated the SAME writes hard (Roster & District) was merged into it, and a
merge in that direction is exactly how a gate gets lost. These checks are here
so it cannot be lost quietly.

Rendered end to end rather than unit-tested, because the gate is page-level: the
helpers close over the identity `page_chrome` resolves, and a unit test would be
testing a copy of them.

Identity comes from APP5_DEMO_AS (helpers/auth.identity_for) — the same path the
offline demo uses — because seeding session_state does NOT survive
`require_login`, which overwrites `auth_user` on every page run.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_input_hub_scope.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_hub_scope_")
_APP = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _APP)

from database.db import execute                      # noqa: E402
import helpers.auth as AUTH                          # noqa: E402

PASSED = 0
SEASON = "2025-2026"
MINE, THEIRS = 1, 2
ADMIN = "boss@school.org"
COACH = "coach@school.org"


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


# ── a two-team league, one coach who owns exactly one of them ────────────────
execute("INSERT INTO teams (id, name, gender, class, district) VALUES (?,?,?,?,?)",
        (MINE, "Mine Girls", "F", "3A", "3A-4"))
execute("INSERT INTO teams (id, name, gender, class, district) VALUES (?,?,?,?,?)",
        (THEIRS, "Theirs Girls", "F", "3A", "3A-4"))
execute("INSERT INTO teams (id, name, gender, class) VALUES (?,?,?,?)",
        (3, "Third Girls", "F", "3A"))
for t, nm in ((MINE, "Mine Player"), (THEIRS, "Theirs Player")):
    execute("INSERT INTO players (team_id, name, number, season, archived) "
            "VALUES (?,?,?,?,0)", (t, nm, 12, "Current"))
_MY_GAME = execute(
    "INSERT INTO games (team1_id, team2_id, date, home_score, away_score, "
    "season, game_type) VALUES (?,?,?,?,?,?,?)",
    (MINE, THEIRS, "2026-01-10", 60, 50, SEASON, "Regular"))
_THEIR_GAME = execute(
    "INSERT INTO games (team1_id, team2_id, date, home_score, away_score, "
    "season, game_type) VALUES (?,?,?,?,?,?,?)",
    (THEIRS, 3, "2026-01-11", 70, 40, SEASON, "Regular"))

AUTH.add_user(ADMIN, "admin", "Boss", added_by="bootstrap")
AUTH.add_user(COACH, "coach", "Coach", added_by=ADMIN)
AUTH.set_teams(COACH, [MINE])
ok(AUTH.identity_for(COACH)["team_ids"] == [MINE], "the coach staffs one team")


def render(page, as_email, state=None):
    """Render one page as one identity. Returns (AppTest, all text)."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    os.environ[AUTH.DEMO_AS_ENV] = as_email
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(os.path.join(_APP, "pages", page),
                               default_timeout=600)
        for k, v in (state or {}).items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, (
            f"{page} as {as_email} raised: "
            f"{[repr(e.value)[:400] for e in at.exception]}")
        txt = " ".join(
            [m.value for m in at.markdown if isinstance(m.value, str)]
            + [c.value for c in at.caption if isinstance(c.value, str)]
            + [i.value for i in at.info if isinstance(i.value, str)])
        return at, txt
    finally:
        os.chdir(cwd)
        os.environ.pop(AUTH.DEMO_AS_ENV, None)


HUB = "1_Input_Hub.py"

# ── every section stands up, for both roles ──────────────────────────────────
# The section list itself changed (Team Schedule folded into Games), and each
# body only runs when its own section is selected — so a name leaked from a
# neighbour is a NameError the moment a coach opens that section.
for _who in (ADMIN, COACH):
    for _sec in ("Teams", "Players", "Games", "Officials", "Season Archive"):
        at, _ = render(HUB, _who, {"hub_section": _sec})
        ok(True, f"{_sec} renders as {'admin' if _who == ADMIN else 'coach'}")

# Both points of view of the Games section, which is where two sections became
# one. "One team" is the old Team Schedule.
for _pov in ("League", "One team"):
    render(HUB, COACH, {"hub_section": "Games", "games_pov": _pov})
    ok(True, f"Games / {_pov} renders")

# ── the read scope ───────────────────────────────────────────────────────────
# Asserted on the frame the page LOADED (`_teams_orig` et al), not on the
# rendered widget: the editor's frame is what a Save is diffed against, so that
# is the thing whose scope decides what a coach can write.
def loaded(at, key):
    df = at.session_state[key]
    return df, set(df["name"].tolist()) if "name" in df else set()


at, _ = render(HUB, COACH, {"hub_section": "Teams"})
_df, _names = loaded(at, "_teams_orig")
ok(_names == {"Mine Girls"},
   f"a coach's Teams grid holds only his own team ({sorted(_names)})")

at, _ = render(HUB, ADMIN, {"hub_section": "Teams"})
_df, _names = loaded(at, "_teams_orig")
ok(len(_names) == 3, f"admin still sees the whole league ({len(_names)} teams)")
ok("district" in _df.columns,
   "Teams grid carries district (was Roster & District)")

at, _ = render(HUB, COACH, {"hub_section": "Games",
                            "games_view_szn": "All seasons"})
_gdf = at.session_state["_games_orig"]
ok(set(_gdf["id"].tolist()) == {_MY_GAME},
   f"a coach's Games grid holds only games his team played ({len(_gdf)} rows)")
ok("game_type" in _gdf.columns,
   "Games grid carries game type (was Roster & District)")

at, _ = render(HUB, ADMIN, {"hub_section": "Games",
                            "games_view_szn": "All seasons"})
ok(set(at.session_state["_games_orig"]["id"].tolist()) == {_MY_GAME, _THEIR_GAME},
   "admin sees both games")

at, _ = render(HUB, ADMIN, {"hub_section": "Players"})
_pdf = at.session_state["_players_orig"]
ok({"position", "availability"} <= set(_pdf.columns),
   "Players grid carries position + availability (was Roster & District)")

# The team PICKER is the players gate: the grid itself is one team at a time.
at, _ = render(HUB, COACH, {"hub_section": "Players"})
_opts = [o for s in at.selectbox for o in (s.options or [])
         if s.label == "Select Team"]
ok(_opts == ["Mine Girls"],
   f"a coach's roster picker offers only his own team ({_opts})")

# ── the dead table is no longer read ─────────────────────────────────────────
_src = Path(_APP, "pages", "1_Input_Hub.py").read_text(encoding="utf-8")
ok("FROM schedule" not in _src,
   "the Season Archive no longer reads the dead `schedule` table")
ok("_hubview == \"Team Schedule\"" not in _src,
   "Team Schedule is gone as a section — it is a point of view now")

# ── the page that was merged away is actually gone ───────────────────────────
ok(not Path(_APP, "pages", "11_Setup.py").exists(),
   "11_Setup.py is deleted, not orphaned")
ok(Path(_APP, "pages", "16_Box_Score_Entry.py").exists(),
   "Box Score Entry survived the merge as its own page")
_main = Path(_APP, "Main.py").read_text(encoding="utf-8")
ok("16_Box_Score_Entry.py" in _main, "Box Score Entry is in the nav")
ok("st.Page(\"pages/11_Setup.py\"" not in _main,
   "the nav no longer points at a file that does not exist")

# Box Score Entry stands up for both roles, and refuses a coach with no team.
render("16_Box_Score_Entry.py", ADMIN)
ok(True, "Box Score Entry renders as admin")
render("16_Box_Score_Entry.py", COACH)
ok(True, "Box Score Entry renders as coach")

AUTH.add_user("nobody@school.org", "coach", "Nobody", added_by=ADMIN)
_at, _txt = render("16_Box_Score_Entry.py", "nobody@school.org")
ok("No team assigned" in _txt,
   "a coach with no team is stopped, not shown every game in the league")

print(f"\nALL {PASSED} CHECKS PASSED")
