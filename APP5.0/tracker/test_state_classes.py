"""
test_state_classes.py — state-scoped class grouping (helpers/team_ratings.py).

Classes are state associations: '4A' in Oklahoma must never group with '4A' in
Texas. _assign_ranks partitions ClassRank by (state, class) and stamps the
display label 'class_lbl' ('4A' in a one-state field, 'OK 4A' once the field
spans states). A one-state field must be byte-identical to the old behavior.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.team_ratings as TR


def _field(rows):
    """{tid: row} with Rating descending in list order."""
    out = {}
    for i, (state, cls) in enumerate(rows, 1):
        out[i] = {"name": f"T{i}", "class": cls, "state": state,
                  "Rating": 100.0 - i}
    return out


def test_single_state_identical_to_class_only():
    # pin the league-level switch: a one-state LEAGUE keeps plain labels
    _orig = TR.league_multi_state
    TR.league_multi_state = lambda: False
    try:
        r = _field([("OK", "4A"), ("OK", "4A"), ("OK", "3A")])
        TR._assign_ranks(r)
        assert [r[t]["ClassRank"] for t in (1, 2, 3)] == [1, 2, 1]
        assert r[1]["ClassOf"] == 2 and r[3]["ClassOf"] == 1
        assert all(v["class_lbl"] == v["class"] for v in r.values())   # no prefix
    finally:
        TR.league_multi_state = _orig


def test_subset_field_labels_follow_the_league():
    """A single-state SUBSET field (e.g. tracked teams all in OK) must still
    qualify labels when the LEAGUE spans states — else the scored table says
    'OK 3A' while the tracked table says '3A' and label-keyed filters match
    nothing (the empty archive Tracked-tab bug)."""
    _orig = TR.league_multi_state
    TR.league_multi_state = lambda: True
    try:
        r = _field([("OK", "4A"), ("OK", "3A")])
        TR._assign_ranks(r)
        assert r[1]["class_lbl"] == "OK 4A" and r[2]["class_lbl"] == "OK 3A"
    finally:
        TR.league_multi_state = _orig


def test_multi_state_partitions_and_labels():
    r = _field([("OK", "4A"), ("TX", "4A"), ("OK", "4A"), ("TX", "4A")])
    TR._assign_ranks(r)
    # each state's 4A ranks independently: OK gets 1,2 — TX gets 1,2
    assert (r[1]["ClassRank"], r[3]["ClassRank"]) == (1, 2)   # OK pair
    assert (r[2]["ClassRank"], r[4]["ClassRank"]) == (1, 2)   # TX pair
    assert r[1]["ClassOf"] == 2 and r[2]["ClassOf"] == 2      # not 4
    assert r[1]["class_lbl"] == "OK 4A" and r[2]["class_lbl"] == "TX 4A"


def test_class_label_edge_cases():
    assert TR.class_label("4A", "OK", multi=False) == "4A"
    assert TR.class_label("4A", "OK", multi=True) == "OK 4A"
    assert TR.class_label("4A", "", multi=True) == "4A"        # unstated state
    assert TR.class_label(None, "OK", multi=True) == "N/A"     # unclassed


def test_real_field_smoke():
    """Real DB: every scored row carries state + class_lbl; one-state field
    keeps plain labels and old-style class ranks."""
    scored = TR.score_ratings(gender="F")
    if not scored:
        return
    states = {v.get("state") for v in scored.values()}
    assert all("state" in v and "class_lbl" in v for v in scored.values())
    if len(states) == 1:
        assert all(v["class_lbl"] == v["class"] for v in scored.values())
