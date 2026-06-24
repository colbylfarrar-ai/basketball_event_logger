"""
test_possession_value.py — unit tests for the Tier-2 possession-value ledger
(helpers/possession_value.py). Synthetic events with a known outcome mix → exact
arithmetic checks for both the offense and defense (allowed) sides.
"""
import helpers.possession_value as PV


def _events():
    T, OPP = 1, 2
    ev = []
    # team 1 offense: 3 made 2s, 2 made 3s
    for _ in range(3):
        ev.append({"event_type": "shot", "shooter_team_id": T, "shot_type": 2,
                   "shot_result": "make"})
    for _ in range(2):
        ev.append({"event_type": "shot", "shooter_team_id": T, "shot_type": 3,
                   "shot_result": "make"})
    # 2 missed FG with own offensive board, 2 missed FG lost to defense
    for _ in range(2):
        ev.append({"event_type": "shot", "shooter_team_id": T, "shot_type": 2,
                   "shot_result": "miss", "rebounder_team_id": T})
    for _ in range(2):
        ev.append({"event_type": "shot", "shooter_team_id": T, "shot_type": 2,
                   "shot_result": "miss", "rebounder_team_id": OPP})
    # 2 turnovers, 2 made FTs
    for _ in range(2):
        ev.append({"event_type": "turnover", "shooter_team_id": T})
    for _ in range(2):
        ev.append({"event_type": "free_throw", "shooter_team_id": T,
                   "shot_result": "make"})
    # opponent (for the defense side): 1 made 2, 1 turnover
    ev.append({"event_type": "shot", "shooter_team_id": OPP, "shot_type": 2,
               "shot_result": "make"})
    ev.append({"event_type": "turnover", "shooter_team_id": OPP})
    return ev


def test_offense_ledger_arithmetic():
    L = PV.possession_ledger(1, offense=True, events=_events())
    assert L["poss"] == 11 and L["fga"] == 9
    assert L["ppp"] == round(14 / 11, 3)
    assert L["tov_pct"] == round(2 / 11, 3)
    assert L["oreb_rate"] == 0.5                      # 2 of 4 misses kept
    assert L["efg"] == round(6 / 9, 3)                # (5 + 0.5*2)/9
    src = {s["key"]: s for s in L["sources"]}
    assert src["made2"]["pts"] == 6 and src["made3"]["pts"] == 6
    assert src["ft"]["pts"] == 2
    assert abs(sum(s["share"] for s in L["sources"]) - 1.0) < 0.01   # 3-dp rounding
    out = {o["key"]: o for o in L["outcomes"]}
    assert out["scored"]["n"] == 5 and out["oreb"]["n"] == 2
    assert out["lost"]["n"] == 2 and out["turnover"]["n"] == 2
    assert sum(o["n"] for o in L["outcomes"]) == L["poss"]


def test_defense_ledger_side():
    L = PV.possession_ledger(1, offense=False, events=_events())
    assert L["side"] == "defense"
    assert L["poss"] == 2                             # only the opponent's 2 trips
    assert L["tov_pct"] == 0.5                        # one of two was a turnover


def test_none_when_no_possessions():
    assert PV.possession_ledger(999, offense=True, events=_events()) is None


def test_team_ledger_bundle():
    b = PV.team_ledger(1, events=_events())
    assert b["offense"]["poss"] == 11 and b["defense"]["poss"] == 2
