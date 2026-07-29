"""The Insights OFFENSE tab, and the engine under it.

WHY THIS TAB EXISTS. `defense_profile.py` opens by calling itself "the
DEFENSIVE mirror of the offensive shot/role profile". That offensive profile
had never been assembled — its pieces were scattered across Charts, the
playstyle tab and the scout cards — so the Insights page carried a Defense tab
and no counterpart, and the app looked most confident about the side it
measures WORST. Defender assignment shares repeat at SB .17-.64 because the
opponent picks the assignment; a shooter's own diet repeats at .70-.92.

WHAT THIS FILE PINS
  1. the engine's arithmetic, including the "20% by construction" claim the
     OLOAD% caption makes to a coach — stated as the DENOMINATOR-WEIGHTED mean,
     which is the form that is exactly 1/5;
  2. the shape contract — `shooter_diets` must stay assignable to
     `defense_profile`'s generic pool/edge/team-relative helpers, because the
     alternative is two implementations of one idea drifting apart;
  3. that the tab RENDERS CONTENT rather than an empty state (see the trap
     below);
  4. that the reliability refusal survives contact with the offense tab: a
     per-player rim FG% (SB .11) may never be presented as a trait.

THE TRAP THIS FILE WAS WRITTEN AGAINST. A render test that only asserts
"no exception" passes over a blank tab, and this codebase has been bitten by
that three separate ways (auth gate, wrong season, unseeded `seg`). So every
render assertion below keys on TEXT THAT ONLY APPEARS WHEN REAL ROWS DREW.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_offense_tab.py
"""
import os
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


import helpers.seasons as SEAS                      # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.offense_profile as OP                # noqa: E402
import helpers.defense_profile as DP                # noqa: E402
import helpers.lineups as LU                        # noqa: E402
import helpers.reliability as REL                   # noqa: E402
from database.db import query                       # noqa: E402


def _tracked():
    best = (None, None, [])
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            pool = SEAS.game_pool(value, gender=g, tracked_only=True) or []
            if len(pool) > len(best[2]):
                best = (value, g, sorted(pool))
    return best


SEASON, GENDER, GIDS = _tracked()
if not GIDS:
    print("  -- no tracked games in this DB; skipped")
    sys.exit(0)

counts = {}
for r in query("SELECT team1_id a, team2_id b FROM games WHERE tracked=1"):
    for t in (r["a"], r["b"]):
        if t is not None:
            counts[t] = counts.get(t, 0) + 1
TEAM_ID = max(counts, key=counts.get)

EV = S.fetch_events(GIDS)
FLOOR = LU._event_floor(GIDS)
print(f"pool: {SEASON}/{GENDER} — {len(GIDS)} games, {len(EV)} events; "
      f"team {TEAM_ID}")


print("\n-- the diet is the player's own, and it adds up ---------------------")

diets = OP.shooter_diets(EV, team_id=TEAM_ID)
ok(len(diets) >= 3, f"a roster's worth of shooters cleared the gate "
                    f"({len(diets)})")
for pid, d in diets.items():
    assert d["n"] >= OP.MIN_SHOTS, "the attempt gate leaked"
    _bs = sum(d["band"].values())
    assert abs(_bs - 1.0) < 1e-9, f"band shares sum to {_bs}, not 1"
    _cs = sum(d["creation"].values())
    assert abs(_cs - 1.0) < 1e-9, f"creation shares sum to {_cs}, not 1"
    assert 0 <= (d["FG%"] or 0) <= 1 and (d["PPS"] or 0) >= 0, "rate range"
ok(True, "every diet's shares sum to exactly 1 and its rates are in range")

# The SHOOTER, not the player fouled or the assister. Reading the wrong id here
# is the offensive twin of the foul-convention trap in foul_trouble.py.
_shots = [e for e in EV if e["event_type"] == "shot"
          and e.get("primary_player_id") is not None]
_mine = [e for e in _shots
         if e["primary_player_id"] in diets]
ok(sum(d["n"] for d in diets.values()) == len(_mine),
   "every counted attempt is keyed on primary_player_id (the shooter)")

_roster = {r["id"] for r in
           query("SELECT id FROM players WHERE team_id=?", (TEAM_ID,))}
ok(all(p in _roster for p in diets),
   "team_id actually filters — every shooter is on that roster")


print("\n-- OLOAD%: the 20% the caption promises a coach ---------------------")

load = OP.shooter_load(EV, floor=FLOOR, game_ids=GIDS)
ok(len(load) > 0, f"OLOAD% built for {len(load)} players")
mine = {p: l for p, l in load.items() if l["team_id"] == TEAM_ID}
_sh = sum(l["shots"] for l in mine.values())
_dn = sum(l["denom"] for l in mine.values())
ok(abs(_sh / _dn - 0.20) < 0.005,
   f"the DENOMINATOR-WEIGHTED mean is 1/5 by construction "
   f"({_sh / _dn * 100:.2f}%) — every shot adds 1 numerator and 5 denominators")
_unw = sum(l["load"] for l in mine.values()) / len(mine)
ok(_unw < _sh / _dn,
   f"the unweighted roster mean sits BELOW it ({_unw * 100:.1f}%) because bench "
   f"players carry small denominators — so 20% is a line to read one player "
   f"against, not a column total")
ok(all(l["shots"] <= l["denom"] for l in load.values()),
   "nobody takes more shots than her team took while she was on the floor")

# THE CASE THAT BROKE THE ABOVE. The numerator used to be incremented before the
# lineup guards and the denominator only after them, so a shot with no floor
# snapshot counted for the shooter and gave nobody a denominator. The live book
# has a snapshot on every shot, which is why the two invariants above still held
# — this forces the gap the ordering created.
_pid = max(mine, key=lambda p: mine[p]["denom"])
_ghost = dict(EV[0], id=-999, event_type="shot", primary_player_id=_pid,
              shooter_team_id=TEAM_ID)
_load2 = OP.shooter_load(list(EV) + [_ghost], floor=FLOOR, game_ids=GIDS)
ok(_load2[_pid]["shots"] == load[_pid]["shots"],
   f"a shot with no lineup snapshot adds NO numerator either — it cannot be "
   f"divided by a floor it never recorded (got {_load2[_pid]['shots']} vs "
   f"{load[_pid]['shots']})")
ok(_load2[_pid]["denom"] == load[_pid]["denom"], "and no denominator")
_sh2 = sum(l["shots"] for l in _load2.values() if l["team_id"] == TEAM_ID)
_dn2 = sum(l["denom"] for l in _load2.values() if l["team_id"] == TEAM_ID)
ok(abs(_sh2 / _dn2 - 0.20) < 0.005,
   f"so the 20% the caption promises survives an unsnapshotted shot "
   f"({_sh2 / _dn2 * 100:.2f}%)")
ok(all(l["shots"] <= l["denom"] for l in _load2.values()),
   "and the share still cannot exceed 100%")


print("\n-- the shape contract with the defensive module ---------------------")

# If this breaks, the two sides have drifted and one of them is about to grow a
# second implementation of pools/edges.
_d2 = DP.team_relative(dict(diets), keys=OP.TEAM_RELATIVE)
ok(any(k.endswith("_vs_team") for d in _d2.values() for k in d),
   "defense_profile.team_relative accepts an offensive diet unchanged")
_edges = DP.diet_edges(_d2)
ok(len(_edges) > 0, f"diet_edges ranks offensive diets too ({len(_edges)} "
                    f"players with edges)")
_axes = {e["axis"] for es in _edges.values() for e in es}
ok(_axes <= {"band", "kind", "play", "creation"},
   f"and only over the axes both sides share ({sorted(_axes)})")
for es in _edges.values():
    for e in es:
        assert e["n"] >= DP.EDGE_MIN_N, "the edge count gate leaked"
ok(True, f"no edge is reported under n={DP.EDGE_MIN_N}")

_off_keys = set(next(iter(diets.values())))
_def_keys = set(next(iter(DP.defender_diets(EV).values())))
_shared = {"band", "kind", "play", "creation", "family", "scheme", "n", "FGA",
           "FG%", "PPS", "three_share", "rim_share", "paint_share",
           "drive_share", "catch_share", "onball_share", "offball_share"}
ok(_shared <= _off_keys and _shared <= _def_keys,
   "both sides carry the shared key set a renderer can format either way")


print("\n-- the team's own diet, the thing 'allowed' mirrors ------------------")

own = OP.team_own_diet(EV)
allowed = DP.team_allowed_diet(EV)
ok(TEAM_ID in own, "the team's own diet is built")
_t = own[TEAM_ID]
ok(abs(sum(_t["band"].values()) - 1.0) < 1e-9, "its band shares sum to 1")
ok(_t["n"] == sum(_t["band_n"].values()),
   "and its band counts sum to its attempt count")
ok(set(own) & set(allowed),
   "own and allowed are computed over the same teams, so they can be read "
   "side by side")
ok("fg" in _t and not any(k.endswith("_fg") for k in _t["band"]),
   "per-BAND shooting is absent — unmeasurable at six teams, in either "
   "direction")


print("\n-- the reliability refusal survives the new surface -----------------")

ok(REL.measured("player", "kind_fg") < REL.WEAK_SB,
   f"per-player rim FG% is below the floor (r="
   f"{REL.measured('player', 'kind_fg'):.2f} < {REL.WEAK_SB})")
ok(REL.measured("player", "band_share") > REL.STABLE_SB,
   f"while the depth SHARES the board leads with are stable "
   f"(r={REL.measured('player', 'band_share'):.2f})")
_src = (_APP / "helpers" / "dashboard" / "insights_deep.py").read_text(
    encoding="utf-8")
_board = _src[_src.index("def render_offense_board"):
              _src.index("def render_defense_board")]
ok("rim04" in _board and "Inside 4ft" in _board,
   "the board shows the rim SHARE, which is the reliable read")
ok("kind_fg" in _board,
   "and names the rim-FG% refusal explicitly rather than silently omitting it")


print("\n-- the tab renders CONTENT, not an empty state ----------------------")

import streamlit as st                              # noqa: E402
from streamlit.testing.v1 import AppTest            # noqa: E402
import helpers.ui as UI                             # noqa: E402

st.page_link = lambda *a, **k: None
st.sidebar.page_link = lambda *a, **k: None
UI.gender_radio = lambda *a, **k: GENDER

_cwd = os.getcwd()
os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
try:
    at = AppTest.from_file(str(_APP / "pages" / "6_Team_Dashboard.py"),
                           default_timeout=1800)
    at.session_state["ta_team"] = TEAM_ID
    at.session_state["ta_season"] = SEASON
    at.session_state["td_view"] = "Insights"
    # The 2026-07-26 recut cut Insights by the QUESTION a coach asks rather
    # than by data category, so there is no "Offense" tab any more: the
    # offensive board sits beside its defensive twin under "Who's helping",
    # which is where a coach asks who is contributing. The sections are `_seg`
    # and therefore LAZY, so the section has to be opened, not just rendered.
    at.session_state["ins_section"] = "Who's helping"
    at.run()
    ok(not at.exception,
       f"Insights renders: {[repr(e.value)[:200] for e in at.exception]}")

    body = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
    cap = " ".join(c.value for c in at.caption if isinstance(c.value, str))
    both = body + " " + cap

    ok("what each player actually shoots" in both.lower(),
       "the offense board's header drew")
    ok("what each player is asked to guard" in both.lower(),
       "and its defensive twin drew beside it — one question, both sides")
    ok(both.lower().index("what each player actually shoots")
       < both.lower().index("what each player is asked to guard"),
       "offense still sits BEFORE defense: the app measures the side a shooter "
       "chooses (.70-.92) better than the side an opponent chooses (.17-.64), "
       "and the order should not suggest otherwise")
    ok("OLOAD%" in both, "the OLOAD% column drew")
    # the real content check: a player's name inside the offense table
    _names = {r["id"]: r["name"] for r in
              query("SELECT id, name FROM players WHERE team_id=?", (TEAM_ID,))}
    _top = max(mine, key=lambda p: mine[p]["load"]) if mine else None
    ok(_top is not None and _names.get(_top, "\x00") in both,
       f"and the highest-OLOAD player ({_names.get(_top)}) is named in it")
    ok("20% is average by construction" in both,
       "the caption states the construction a coach needs to read the column")
    ok("Shot diet taken" in both,
       "the team's own diet block drew beside the per-player table")
finally:
    os.chdir(_cwd)

print(f"\nALL {PASS} CHECKS PASSED")
