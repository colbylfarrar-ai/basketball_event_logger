"""
test_possession_value.py — unit tests for the Tier-2 possession-value ledger
(helpers/possession_value.py). Synthetic events with a known outcome mix → exact
arithmetic checks for both the offense and defense (allowed) sides.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
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


# ── displayed percentages must close at 100 ──────────────────────────────────
# The four outcomes PARTITION the possessions, so every surface that prints
# them prints a total the coach will add up. Rounding each share on its own
# broke that (Adair Girls: 33.5 / 29.8 / 17.8 / 18.9 -> 34+30+18+19 = 101);
# outcome_pcts uses largest-remainder so the column always closes.
def test_outcome_pcts_sum_to_100():
    L = PV.possession_ledger(1, offense=True, events=_events())
    pc = PV.outcome_pcts(L)
    assert set(pc) == {"scored", "oreb", "lost", "turnover"}
    assert sum(pc.values()) == 100


def test_outcome_pcts_close_at_100_on_awkward_splits():
    """The rounding cases that motivated this: independently rounding these
    gives 101 and 99 respectively."""
    def led(counts):
        poss = sum(counts.values())
        return {"poss": poss,
                "outcomes": [{"key": k, "n": v} for k, v in counts.items()]}

    # 540/304/480/287 of 1611 -> 33.5 / 18.9 / 29.8 / 17.8 (the real team)
    pc = PV.outcome_pcts(led({"scored": 540, "oreb": 304,
                              "lost": 480, "turnover": 287}))
    assert sum(pc.values()) == 100
    # every bucket stays within a point of its exact share
    assert pc["scored"] in (33, 34) and pc["oreb"] in (18, 19)
    assert pc["lost"] in (29, 30) and pc["turnover"] in (17, 18)

    # a split whose naive rounding UNDERshoots
    pc = PV.outcome_pcts(led({"scored": 1, "oreb": 1, "lost": 1, "turnover": 3}))
    assert sum(pc.values()) == 100


def test_outcome_pcts_empty_ledger():
    assert PV.outcome_pcts(None) == {}
    assert PV.outcome_pcts({}) == {}
    assert PV.outcome_pcts({"poss": 0, "outcomes": []}) == {}
