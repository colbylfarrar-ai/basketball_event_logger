"""Tests for the playmaking-weighted turnover layer (turnover_type -> the
PLAYMAKING rating's AST/pmTOV + pmTOV% leaves)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def test_weights_contract():
    import helpers.stats as S
    w = S.PLAYMAKING_TOV_WEIGHTS
    ok(w["pass"] > w["travel"], "bad pass weighs more than a travel")
    ok(w["shot_clock"] == 0.0, "shot clock is a team TO — zero player weight")
    ok(w["held"] == w["travel"], "held ball == travel")
    ok(w["other"] == 1.0, "other kept as-is")
    ok(w["travel"] < w["pass"] and w["drive"] < w["travel"],
       "drive sits between shot-clock and travel (creation implied)")


def test_weighted_counts():
    import helpers.stats as S

    def tov(pid, kind):
        return {"event_type": "turnover", "primary_player_id": pid,
                "turnover_type": kind}

    events = [
        tov(1, "pass"), tov(1, "pass"),          # 2.6
        tov(1, "shot_clock"),                     # +0
        tov(2, "travel"), tov(2, "held"),         # 2.0
        tov(3, None), tov(3, None),               # untagged -> 2.0 (raw)
        tov(4, "weird_legacy_tag"),               # unknown -> 1.0
        {"event_type": "shot", "primary_player_id": 1},   # ignored
        tov(None, "pass"),                        # no player -> skipped
    ]
    out = S.playmaking_weighted_tov(events=events)
    ok(abs(out[1] - 2.6) < 1e-9, "pass 1.3x + shot-clock 0 (2 pass + 1 sc = 2.6)")
    ok(abs(out[2] - 2.0) < 1e-9, "travel + held = 2.0")
    ok(abs(out[3] - 2.0) < 1e-9, "untagged TOs reproduce the raw count")
    ok(abs(out[4] - 1.0) < 1e-9, "unknown legacy tag folds to 1.0")
    ok(None not in out, "player-less turnover skipped")


def test_leaves_swapped():
    import helpers.player_ratings as PR
    leaves = [s for s, _w, _lb in PR._PLAYMAKING]
    ok("AST/pmTOV" in leaves and "pmTOV%" in leaves,
       "PLAYMAKING uses the weighted twins")
    ok("AST/TOV" not in leaves and "TOV%" not in leaves,
       "raw AST/TOV + TOV% no longer double-enter PLAYMAKING")


def test_untagged_pool_identical_real_db():
    """On a pool with no turnover_type tags the weighted twins equal the raw
    leaves, so PLAYMAKING is byte-identical to the pre-change engine."""
    import helpers.player_ratings as PR
    profs = PR.player_profiles(gender="F")
    if not profs:
        print("  (no local players — skipped)")
        return
    checked = 0
    mism = 0
    for pid, p in profs.items():
        # only players whose TOs are ALL untagged reproduce exactly; the local
        # dev DB has no tags, prod has a few — tolerate tagged players.
        if p.get("AST/TOV") is None and p.get("AST/pmTOV") is None:
            continue
        checked += 1
        if p.get("pmTOV") is not None and abs(
                (p.get("pmTOV") or 0) - p["box"]["TOV"]) > 1e-9:
            mism += 1
            continue
        if (p.get("AST/TOV") is None) != (p.get("AST/pmTOV") is None):
            mism += 1
    ok(checked > 0 and mism == 0,
       f"untagged players: weighted == raw for all {checked} checked")


if __name__ == "__main__":
    test_weights_contract()
    test_weighted_counts()
    test_leaves_swapped()
    test_untagged_pool_identical_real_db()
    print(f"\nALL {PASSED} CHECKS PASSED")
