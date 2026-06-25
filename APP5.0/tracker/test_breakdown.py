"""
Unit test for helpers/breakdown.py (four-factors per play_type / defense).
Runs on SYNTHETIC events — no DB needed — so the four-factors math is pinned
exactly (there is no live tagged data yet to eyeball).
Run: python tracker/test_breakdown.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers.breakdown import (factors_by_tag, play_type_factors,  # noqa: E402
                               defense_factors, MIN_REB_CHANCES)

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def ev(team, tag_field, tag, etype, **kw):
    """Build one event row (dict like stats.fetch_events yields)."""
    e = {"shooter_team_id": team, "event_type": etype, "shot_type": None,
         "shot_result": None, "rebounder_team_id": None,
         "play_type": None, "defense": None}
    e[tag_field] = tag
    e.update(kw)
    return e


T1, T2 = 1, 2


def build_transition_offense():
    """Team 1 offense, play_type='transition': hand-computable four factors."""
    evs = []
    # 20 made 2P, 0 threes
    for _ in range(20):
        evs.append(ev(T1, "play_type", "transition", "shot",
                      shot_type=2, shot_result="make"))
    # 16 missed shots → 6 OREB (team1), 10 opp DREB (team2)
    for _ in range(6):
        evs.append(ev(T1, "play_type", "transition", "shot",
                      shot_type=2, shot_result="miss", rebounder_team_id=T1))
    for _ in range(10):
        evs.append(ev(T1, "play_type", "transition", "shot",
                      shot_type=2, shot_result="miss", rebounder_team_id=T2))
    # 4 turnovers tagged transition
    for _ in range(4):
        evs.append(ev(T1, "play_type", "transition", "turnover"))
    # 5 FTs tagged transition, 3 makes
    for i in range(5):
        evs.append(ev(T1, "play_type", "transition", "free_throw",
                      shot_result=("make" if i < 3 else "miss")))
    return evs


print("four-factors math (transition, team 1 offense)")
evs = build_transition_offense()
# add noise that must NOT count: opponent transition shot + an untagged shot
evs.append(ev(T2, "play_type", "transition", "shot", shot_type=2, shot_result="make"))
evs.append(ev(T1, "play_type", None, "shot", shot_type=2, shot_result="make"))

cells = factors_by_tag(evs, T1, "play_type", {"transition"}, offense=True, min_poss=40)
c = cells["transition"]
ok(c["FGA"] == 36, f"FGA=36 (got {c['FGA']})")
ok(c["poss"] == 40, f"poss=FGA+TOV=40 (got {c['poss']})")
ok(round(c["eFG"], 4) == 0.5556, f"eFG=20/36=.5556 (got {round(c['eFG'],4)})")
ok(round(c["OREB%"], 4) == 0.375, f"OREB%=6/16=.375 (got {round(c['OREB%'],4)})")
ok(c["OREB_n"] == 16, f"OREB chances=16 (got {c['OREB_n']})")
ok(round(c["TOV%"], 4) == 0.10, f"TOV%=4/40=.10 (got {round(c['TOV%'],4)})")
ok(round(c["FTr"], 4) == 0.0833, f"FTr=3/36=.0833 (got {round(c['FTr'],4)})")
ok(round(c["PPP"], 4) == 1.0, f"PPP=40/40=1.0 (got {round(c['PPP'],4)})")

print("sample-size gate")
ok(c["stable"] is True, "stable at min_poss=40 (poss=40)")
c2 = factors_by_tag(evs, T1, "play_type", {"transition"}, offense=True, min_poss=41)["transition"]
ok(c2["stable"] is False, "not stable at min_poss=41")

print("OREB% suppressed on thin rebound sample")
thin = [ev(T1, "play_type", "iso", "shot", shot_type=2, shot_result="miss",
           rebounder_team_id=T2) for _ in range(MIN_REB_CHANCES - 1)]
tc = factors_by_tag(thin, T1, "play_type", {"iso"}, offense=True, min_poss=1)["iso"]
ok(tc["OREB%"] is None, f"OREB% None when chances < {MIN_REB_CHANCES}")

print("offense / defense side filtering")
# offense=False for team 1 → only the opponent (team 2) transition shot
off_false = factors_by_tag(evs, T1, "play_type", {"transition"}, offense=False, min_poss=1)
ok(off_false["transition"]["FGA"] == 1, "offense=False keeps only opponent shots")

print("untagged events excluded")
ok(c["FGA"] == 36, "untagged play_type shot not counted (still 36)")

print("wrappers import + run on passed events")
pt = play_type_factors(T1, events=evs, min_poss=40)
ok(any(r["key"] == "transition" and r["stable"] for r in pt["rows"]),
   "play_type_factors returns a stable transition row")
ok(pt["n_stable"] >= 1 and pt["total_poss"] >= 40, "summary fields populated")

# defense tag mirror: team 1 defending → opponent (team 2) shots tagged 'man_press'
def_evs = [ev(T2, "defense", "man_press", "shot", shot_type=2,
              shot_result="make") for _ in range(12)]
dev = defense_factors(T1, events=def_evs, min_poss=10)
ok(any(r["key"] == "man_press" for r in dev["rows"]),
   "defense_factors reads opponent shots under the team's scheme")

print(f"\nPASS — {PASS} checks")
