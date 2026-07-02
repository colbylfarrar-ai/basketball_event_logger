"""Tests for potential assists (SC_pass surfaced) + screen assists (SCR_AST /
scr_tag_*) in helpers/stats.py box aggregation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _shot(shooter, made, stype=2, passer=None, screener=None, play_type=None):
    return {"event_type": "shot", "primary_player_id": shooter,
            "shot_result": "make" if made else "miss", "shot_type": stype,
            "pass_from_id": passer, "shot_created_by_id": screener,
            "blocked_by_id": None, "guarded_by_id": None, "stolen_by_id": None,
            "rebound_by_id": None, "rebounder_team_id": None,
            "shooter_team_id": 1, "secondary_player_id": None,
            "official_id": None, "zone": "C" if stype == 2 else "RW",
            "play_type": play_type}


def test_potential_assists_count_misses():
    import helpers.stats as S
    events = [
        _shot(1, True, passer=9),    # feed finished  -> AST + PotAST
        _shot(1, False, passer=9),   # feed missed    -> PotAST only
        _shot(2, False, passer=9),   # feed missed    -> PotAST only
        _shot(1, True),              # unassisted make -> neither
    ]
    b = S.aggregate_player_boxes(events=events)[9]
    assert b["SC_pass"] == 3        # the potential assists
    assert b["AST"] == 1            # only the make converts


def test_screen_assist_makes_only():
    import helpers.stats as S
    events = [
        _shot(1, True, screener=7),   # credited screen, MAKE  -> ScrAST
        _shot(1, False, screener=7),  # credited screen, miss  -> SC_screen only
    ]
    b = S.aggregate_player_boxes(events=events)[7]
    assert b["SC_screen"] == 2
    assert b["SCR_AST"] == 1


def test_screen_tag_uncredited():
    import helpers.stats as S
    events = [
        _shot(1, True, play_type="pnr"),                 # tag, no screener
        _shot(1, False, play_type="dho"),                # tag, no screener
        _shot(1, True, play_type="offscreen", screener=7),  # credited -> NOT tag-bucket
        _shot(1, True, play_type="iso"),                 # non-screen set
        _shot(1, True),                                  # untagged
    ]
    b = S.aggregate_player_boxes(events=events)[1]
    assert b["scr_tag_FGA"] == 2
    assert b["scr_tag_FGM"] == 1
    # legacy fixtures without the play_type key must not crash
    ev = _shot(1, True)
    del ev["play_type"]
    S.aggregate_player_boxes(events=[ev])


def test_stat_table_keys_real_db():
    """player_stat_table rows must carry the new keys (values may be 0/None)."""
    import helpers.player_ratings as PR
    rows = PR.player_stat_table(gender="F")
    if not rows:                     # empty local DB is fine
        return
    r = next(iter(rows.values()))
    for k in ("PotAST", "PotAST/G", "ScrAST", "ScrAST/G",
              "ScrnFGA", "ScrnFGM", "FeedConv%", "ScrnFG%"):
        assert k in r, f"missing key {k}"


if __name__ == "__main__":
    for fn in [test_potential_assists_count_misses, test_screen_assist_makes_only,
               test_screen_tag_uncredited, test_stat_table_keys_real_db]:
        fn()
        print(f"PASS {fn.__name__}")
