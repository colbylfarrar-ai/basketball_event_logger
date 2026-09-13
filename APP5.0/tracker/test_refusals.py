"""The "what we measured and refused" surface must not become a story.

`faq.REFUSALS` is the app's most credible asset put on a screen: five reads it
declined to ship, plus a sixth that was measured and deliberately not applied.
Its entire value rests on every entry being CHECKABLE — a college analyst who
finds one number in it that the repo does not actually compute stops believing
the other five, and correctly.

So this file does exactly two things, and both are about honesty rather than
behaviour:

  1. every entry names a source, and every file it names EXISTS
  2. every reliability figure quoted in prose matches `reliability.MEASURED`

The second is the one that will catch a real regression: re-measuring a metric
updates `MEASURED` and leaves the prose behind, and prose that disagrees with
the table is worse than no surface at all.

Run: python -m pytest tracker/test_refusals.py
"""
import re
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.faq as FAQ                       # noqa: E402
import helpers.reliability as REL               # noqa: E402


ENTRIES = FAQ.refusals()


def test_there_are_entries_and_they_are_well_formed():
    assert len(ENTRIES) >= 5
    ids = [e[0] for e in ENTRIES]
    assert len(set(ids)) == len(ids), f"duplicate ids: {ids}"
    for e in ENTRIES:
        assert len(e) == 5, e[0]
        _id, claim, measurement, verdict, source = e
        assert claim.strip() and measurement.strip() and verdict.strip()
        assert source.strip(), f"{_id} has no citation"


@pytest.mark.parametrize("entry", ENTRIES, ids=[e[0] for e in ENTRIES])
def test_every_cited_file_exists(entry):
    """A citation pointing at a file that is gone is the fastest way to turn a
    credibility surface into the opposite of one."""
    source = entry[4]
    # "helpers/foo.py", "stats.py:1439", "tools/measure_garbage.py" — take the
    # path-looking tokens and resolve each against the app root, then helpers/.
    for tok in re.findall(r"[\w/]+\.py", source):
        p = _APP / tok
        if p.exists():
            continue
        for sub in ("helpers", "tools", "tracker", "pages", "database"):
            if (_APP / sub / tok).exists():
                break
        else:
            pytest.fail(f"{entry[0]}: cited file not found: {tok}")


@pytest.mark.parametrize("entry", ENTRIES, ids=[e[0] for e in ENTRIES])
def test_every_cited_MEASURED_key_is_real(entry):
    """`reliability.MEASURED ("player", "onoff_off")` in a citation must name a
    key that is actually in the table."""
    for unit, metric in re.findall(r'\("(\w+)",\s*"(\w+)"\)', entry[4]):
        assert (unit, metric) in REL.MEASURED, (
            f'{entry[0]}: MEASURED has no ("{unit}", "{metric}")')


# (entry id, the SB the prose claims, the MEASURED key it must match). Written
# out rather than scraped: a regex over prose would silently pass the day
# somebody rewords a sentence, which is precisely when this should fail.
QUOTED = [
    ("onoff", -0.21, ("player", "onoff_off")),
    ("xppp", 0.176, ("team", "xpps_forecasts_pps")),
    ("quarters", 0.596, ("team", "quarter_pace")),
    ("quarters", -0.135, ("team", "quarter_efg")),
    ("quarters", 0.082, ("team", "quarter_tov")),
    ("defensive-shares", 0.643, ("defender", "area_share")),
    ("defensive-shares", 0.574, ("defender", "load")),
    ("defensive-shares", -0.15, ("defender", "play_share")),
]


@pytest.mark.parametrize("eid,quoted,key", QUOTED,
                         ids=[f"{e}-{k[1]}" for e, _q, k in QUOTED])
def test_quoted_numbers_match_the_measured_table(eid, quoted, key):
    """The prose and the table have to agree. Re-measuring updates one of them;
    this is what notices the other did not move."""
    actual = REL.MEASURED[key]
    assert abs(actual - quoted) <= 0.005, (
        f"{eid} quotes {quoted:+.3f} for {key}; MEASURED says {actual:+.3f}")
    body = next(e for e in ENTRIES if e[0] == eid)[2]
    # The figure has to be legible in the entry, in one of the shapes the prose
    # actually uses (".596", "0.596", "-0.135", "−0.15" with a real minus).
    frags = {f"{abs(quoted):.3f}".rstrip("0"), f"{abs(quoted):.3f}",
             f"{abs(quoted):.2f}", f"{abs(quoted):.3f}".lstrip("0"),
             f"{abs(quoted):.2f}".lstrip("0")}
    assert any(f in body for f in frags), (
        f"{eid} does not print {quoted} anywhere: looked for {sorted(frags)}")


def test_the_garbage_entry_reads_the_live_constants():
    """The garbage-time entry quotes both thresholds by value. If either
    constant moves, the published table is describing a measurement of
    something else."""
    import helpers.situational as SIT
    import helpers.runs as RN
    body = next(e for e in ENTRIES if e[0] == "garbage-time")[2]
    assert f"GARBAGE = {SIT.GARBAGE}" in body, SIT.GARBAGE
    assert f"GARBAGE_MARGIN = {RN.GARBAGE_MARGIN}" in body, RN.GARBAGE_MARGIN


def test_no_entry_claims_a_reliability_for_an_unmeasured_stat():
    """`STAT_RELIABILITY` is a join, not an opinion. Every row must land on a
    key the measured table actually holds — borrowing a neighbouring metric's
    number is the exact mistake that produced the -0.135 action-axis result."""
    for abbr, key in REL.STAT_RELIABILITY.items():
        assert key in REL.MEASURED, f"{abbr} -> {key} is not in MEASURED"


def test_an_unmapped_stat_says_not_yet_measured():
    """The phrase is the product. It has to survive a refactor."""
    txt = REL.chip_text("a stat nobody has ever measured")
    assert "not yet measured" in txt.lower()
    assert "r =" not in txt, "an unmeasured stat must not print an r"
