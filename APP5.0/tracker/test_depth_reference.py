"""The shot-depth captions must quote THIS book, not a constant typed in 2026.

Three numbers for the same quantity live in the app, and no two agree:

    insights_identity   "0.60 points per shot against 1.14 at the rim"
    shot_diet           "0.55 points a trip, against 1.09 at the rim"
    shot_kinds          computed — girls 0.548 / 1.072, boys 0.753 / 1.276

The computed pair is the true one, and `shot_kinds.py` even carries a comment
saying an earlier hardcoding was replaced by it — the fix reached the evidence
line under the table and not the two headers above it. So `shot_diet`'s pair is
the GIRLS' numbers shown verbatim to a boys team whose rim is worth 1.28, and
`insights_identity`'s pair matches neither gender.

That is the §8.4 finding, and it is worse than a stale number: the two captions
are the sentences that TEACH a coach what the dead band costs, and in October
they get read by people who cannot check them.

The gate here is two-sided on purpose. A behavioural test that the reference
follows the book (two books, two answers), and a static one that the retired
literals do not come back — because the failure mode is somebody typing a
plausible number into a caption, which no runtime assertion can see.

Run: python -m pytest tracker/test_depth_reference.py
"""
import re
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.shot_kinds as SK                        # noqa: E402


def _shots(n_rim, rim_pts, n_band, band_pts):
    """A synthetic located-shot list: `n_rim` 2s at the cup and `n_band` 2s from
    the dead band, with a stated number of MAKES in each so the PPS is exact.

    Pure dicts in the mapped_shots() shape — no DB, because the reference is a
    pure function of a shot list and a fixture that needed a book would be
    testing the feed instead of the arithmetic."""
    out = []
    for i in range(n_rim):
        out.append({"x": 0.0, "y": 2.0, "value": 2, "make": i < rim_pts // 2})
    for i in range(n_band):
        out.append({"x": 0.0, "y": 12.0, "value": 2, "make": i < band_pts // 2})
    return out


# Both books clear MIN_KIND_RATE_ATT in both cells; only the RIM conversion
# differs, which is exactly the girls/boys split the captions flatten.
_A = _shots(n_rim=100, rim_pts=100, n_band=100, band_pts=60)    # rim 1.00
_B = _shots(n_rim=100, rim_pts=140, n_band=100, band_pts=60)    # rim 1.40


def test_the_reference_follows_the_book_it_is_given():
    """Two books, two answers. A caption built from either must not be able to
    quote the other's rim value."""
    a = SK.depth_reference(shots=_A)
    b = SK.depth_reference(shots=_B)
    assert a is not None and b is not None
    assert round(a["rim_pps"], 2) == 1.00
    assert round(b["rim_pps"], 2) == 1.40
    assert round(a["pps"], 2) == round(b["pps"], 2) == 0.60


def test_the_sentence_carries_the_computed_numbers_and_its_sample():
    """The prose is built from the reference, and it states how many located
    shots are behind it — a league constant with no sample on it is the §10
    finding, and this caption is read by coaches who cannot check it."""
    line = SK.depth_value_line(SK.depth_reference(shots=_B))
    assert "1.40" in line and "0.60" in line, line
    assert "200" in line, ("the sentence does not say how many located shots it "
                           f"is computed over: {line}")


def test_a_sample_too_thin_to_price_returns_no_reference():
    """Below the per-cell attempt gate there is no number, and a caller must get
    None rather than a rounded guess. A missing sentence costs less than a wrong
    one — the whole reason this finding is a blocker."""
    thin = _shots(n_rim=SK.MIN_KIND_RATE_ATT - 1, rim_pts=20,
                  n_band=SK.MIN_KIND_RATE_ATT - 1, band_pts=10)
    assert SK.depth_reference(shots=thin) is None


def test_neither_caption_still_carries_a_hardcoded_pair():
    """The two headers that were wrong, checked as text.

    Matched as a NUMBER next to the words the captions use, not as a bare
    "1.09": module constants and measured values are quoted all over these files
    in comments explaining what was found, and a scan that cannot tell a
    rendered caption from its own changelog is a scan somebody deletes."""
    hardcoded = re.compile(
        r'"[^"]*\d\.\d\d\s*(points (a trip|per shot)|at the rim)', re.I)
    bad = []
    for rel in ("helpers/dashboard/shot_diet.py",
                "helpers/dashboard/insights_identity.py"):
        src = (_APP / rel).read_text(encoding="utf-8")
        for i, ln in enumerate(src.splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue                      # comments may quote what was found
            if hardcoded.search(ln):
                bad.append(f"{rel}:{i}: {ln.strip()}")
    assert not bad, ("a shot-depth caption prices the dead band from a literal "
                     "instead of from the book:\n  " + "\n  ".join(bad))
