"""The depth cross-tab has two axes and only one of them was ever supplied.

THE BOOK §12.6: `shot_kinds.kind_by_shot_tag` takes the shot column to cross
against depth, and both live call sites hardcoded `"defense"`. `"play_type"`
was never passed — on a column tagged on 93% of shots — so the offensive half
of the table did not exist. The engine was always general; the callers were not.

What this holds:

  * the engine buckets on whatever tag it is given, not on a baked-in one;
  * `shot_diet.render_concedes` takes that tag through rather than pinning it;
  * the Play Style tab supplies "play_type" and the Defense tab still supplies
    "defense" — a wiring fact with nothing to fail if one side is edited, which
    is exactly how it came to be missing in the first place;
  * the copy follows the axis. The defensive caption's worked example is a
    scramble conceding rim looks by definition. Left on the offensive table it
    would be explaining a scramble beside a table of post-ups.

Run: python -m pytest tracker/test_playtype_depth_cross.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.shot_kinds as SK                        # noqa: E402


def _shot(play_type=None, defense=None, x=0.0, y=1.0, value=2, make=True):
    """One located shot in the shape `shot_kinds._shots` yields."""
    return {"x": x, "y": y, "value": value, "make": make, "approx": False,
            "dist": (x * x + y * y) ** 0.5, "zone": None, "guarded": None,
            "player_id": 1, "team_id": 1,
            "play_type": play_type, "defense": defense}


def test_the_engine_buckets_on_whichever_tag_it_is_given():
    n = SK.MIN_KIND_RATE_ATT
    shots = ([_shot(play_type="post", defense="man") for _ in range(n)]
             + [_shot(play_type="iso", defense="man", y=20.0) for _ in range(n)])

    by_set = SK.kind_by_shot_tag(shots, "play_type")
    assert set(by_set) == {"post", "iso"}, \
        "the play_type axis buckets, and it always could"

    by_def = SK.kind_by_shot_tag(shots, "defense")
    assert set(by_def) == {"man"}, "and the defense axis still buckets its own"

    # the two axes cut the SAME shots differently — which is the whole reason
    # both are worth having, and why one of them being unreachable mattered
    assert by_def["man"]["_meta"]["located"] == 2 * n
    assert by_set["post"]["_meta"]["located"] == n


def test_thin_tag_values_are_dropped_not_shown_thin():
    shots = ([_shot(play_type="post") for _ in range(SK.MIN_KIND_RATE_ATT)]
             + [_shot(play_type="duckin") for _ in range(2)])
    out = SK.kind_by_shot_tag(shots, "play_type")
    assert "post" in out and "duckin" not in out


def test_render_concedes_takes_the_tag_through():
    """A default-only parameter is how this stayed broken, so assert the seam."""
    import inspect
    import helpers.dashboard.shot_diet as SD
    sig = inspect.signature(SD.render_concedes)
    assert "tag" in sig.parameters, "render_concedes pins the axis again"
    assert sig.parameters["tag"].default == "defense", \
        "the defensive call site relies on the default"
    assert "unit" in sig.parameters, "…and the copy has to follow the axis"

    src = inspect.getsource(SD.render_concedes)
    assert 'kind_by_shot_tag(shots, tag,' in src, \
        "the tag stops at the signature and never reaches the engine"


def test_both_call_sites_supply_their_own_axis():
    ps = (_APP / "helpers" / "dashboard" / "playstyle_tab.py").read_text(
        encoding="utf-8")
    df = (_APP / "helpers" / "dashboard" / "defense_tab.py").read_text(
        encoding="utf-8")
    assert 'tag="play_type"' in ps, \
        "the Play Style tab stopped asking for the offensive axis"
    assert "render_concedes(" in df, "the Defense tab stopped rendering at all"

    # and the league normalizer reaches the new call site. Without it every
    # post row in the league reads as a finding, which is the failure the
    # defensive version was already written to avoid.
    assert "located_pool" in ps, "the offensive table lost its league baseline"
    td = (_APP / "pages" / "6_Team_Dashboard.py").read_text(encoding="utf-8")
    assert td.count("located_pool=_located_pool(") == 2, \
        "the page stopped supplying the league feed to one of the two tabs"


def test_the_worked_example_in_the_caption_follows_the_axis():
    """The scramble sentence is a defensive explanation and belongs there."""
    import inspect
    import helpers.dashboard.shot_diet as SD
    src = inspect.getsource(SD.render_concedes)
    assert 'tag == "defense"' in src, \
        "one caption is being shown for both axes again"
    assert "post-up finishes at the rim" in src, \
        "the offensive axis has no worked example of its own"
