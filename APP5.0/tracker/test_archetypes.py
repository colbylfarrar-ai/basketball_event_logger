"""
test_archetypes.py — the player-archetype naming layer (helpers/archetypes.py).

_name_for is pure (an axis-score dict → a label), so the two-way QUALITY read
(Two-Way Star / Offensive Engine / Defensive Anchor / Flamethrower) and the STYLE
fallback are pinned with crafted axis profiles — no DB. A final synthetic
cluster_players smoke confirms the pipeline runs end-to-end.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.archetypes as A


def _axes(**kw):
    ax = {a: 0.0 for a in A._AXES}
    ax.update(kw)
    return ax


def test_two_way_star():
    assert A._name_for(_axes(offense_q=0.8, defense_q=0.7)) == "Two-Way Star"


def test_offensive_engine():
    # good offense, liability on D
    assert A._name_for(_axes(offense_q=0.7, defense_q=-0.5,
                             scoring=0.6)) == "Offensive Engine"


def test_defensive_anchor():
    # locks it up, offense a passenger
    assert A._name_for(_axes(defense_q=0.7, offense_q=-0.5,
                             blocks=0.6)) == "Defensive Anchor"


def test_flamethrower_needs_shooting_to_be_the_identity():
    # elite shooting that IS the top style axis + holds up on D → Flamethrower
    assert A._name_for(_axes(shooting=0.9, defense_q=0.1,
                             offense_q=0.3)) == "Flamethrower"
    # high shooting but PLAYMAKING dominates → NOT Flamethrower (was a bug)
    assert A._name_for(_axes(shooting=0.75, playmaking=0.95, defense_q=0.1)) \
        != "Flamethrower"


def test_pure_shooter_bad_defense_stays_style():
    # great shooter, bad D, not the two-way profile → style name (badge
    # vocabulary since the taxonomy alignment), not Flamethrower
    n = A._name_for(_axes(shooting=0.9, defense_q=-0.5, offense_q=0.2,
                          creation=-0.2))
    assert n == "Sharpshooter"


def test_role_player_when_nothing_stands_out():
    assert A._name_for(_axes(offense_q=0.1, defense_q=-0.1)) == "Role Player"


def test_style_fallback_still_works():
    # style names now come from the shared badge-archetype taxonomy
    assert A._name_for(_axes(playmaking=0.8)) == "Floor General"
    assert A._name_for(_axes(rebounding=0.8, blocks=0.6)) == "Interior Anchor"
    assert A._name_for(_axes(rebounding=0.8)) == "Rebounder"
    assert A._name_for(_axes(steals=0.8)) == "Defensive Specialist"
    assert A._name_for(_axes(scoring=0.8)) == "Scorer"


def test_offense_defense_are_clustering_features():
    assert "OFFENSE" in A.DEFAULT_FEATURES and "DEFENSE" in A.DEFAULT_FEATURES


def test_cluster_players_smoke_synthetic():
    # two clean archetypes: elite two-way scorers vs low-usage role players
    table = {}
    for i in range(8):
        table[i] = {"name": f"star{i}", "PPG": 20, "USG%": 28, "TS%": 60,
                    "3PA/G": 6, "3P%": 40, "3PR": 0.5, "AST/TOV": 2.0, "APG": 4,
                    "RPG": 7, "SPG": 2.5, "BPG": 1.2, "OREB/G": 2, "DREB/G": 5,
                    "RimFGA%": 40, "SelfCr%": 60, "SCPass%": 20, "SCCreated%": 10,
                    "OFFENSE": 72, "DEFENSE": 70, "OVERALL": 72}
    for i in range(8, 18):
        table[i] = {"name": f"role{i}", "PPG": 4, "USG%": 12, "TS%": 48,
                    "3PA/G": 1, "3P%": 30, "3PR": 0.3, "AST/TOV": 0.8, "APG": 1,
                    "RPG": 2, "SPG": 0.5, "BPG": 0.1, "OREB/G": 0.5, "DREB/G": 1.5,
                    "RimFGA%": 30, "SelfCr%": 30, "SCPass%": 50, "SCCreated%": 10,
                    "OFFENSE": 44, "DEFENSE": 46, "OVERALL": 45}
    res = A.cluster_players(table)
    assert res["k"] >= 2 and res["clusters"]
    # every player got an archetype + a fit
    assert all("archetype" in p and "fit" in p for p in res["players"].values())
    # the elite group should read as an elite two-way profile
    top = max(res["clusters"], key=lambda c: c["avg_overall"] or 0)
    assert top["axes"]["offense_q"] > 0 and top["axes"]["defense_q"] > 0


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for f in fns:
        try:
            f()
            ok += 1
            print(f"  ok  {f.__name__}")
        except Exception as ex:
            print(f"  FAIL {f.__name__} -> {ex!r}")
            traceback.print_exc()
    print(f"\n{ok}/{len(fns)} archetype checks passed")
