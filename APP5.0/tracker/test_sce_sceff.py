"""SCE means one thing, everywhere. (B4)

Three definitions were in play and no two agreed:

    source      SCE means                          ScEff means
    the code    an alias of ScEff — the SAME       (2·2PM + 3·3PM)/(2·2PA + 3·3PA)
                number; self-creation lived
                under a different key, SelfCr%
    the glossary Self-Creation %, with the ScEff   Scoring Efficiency (matches
                entry warning "NOT the same       the code)
                as SCE / Self-Creation %"
    the founder  Shot Created %                    Shot Created Efficiency

Founder ruling Q12 settles it, and it says the GLOSSARY is right and the CODE is
wrong: `SCE` is Self-Created % — shots with no pass-from AND no set-up-by, which
is exactly what `stats` already counts as `shots_self` — and `ScEff` is points
scored over points possible, which is exactly what `stats.scoring_efficiency`
already computes. The formulas were never wrong. The DATA KEY was: fourteen
sites carried ScEff's number under the key `SCE`, several of them labelling the
column "ScEff" while reading `row["SCE"]` on the same line.

Why it is a launch blocker rather than a tidy-up: tap the stat key on the
Players page and you decode a scoring-efficiency column as self-creation. That
is unfixable-by-explanation once four coaches have learned it wrong in October.

The duplicate `Leverage` rides along — `STAT_DEFS` defines it twice for
unrelated concepts (the officials' game-worth blend and the win-probability
Leverage Index). Exact-match lookup takes the first, and the only current call
site happens to want that one, so it is right today by luck.

Run: python -m pytest tracker/test_sce_sceff.py
"""
import sys
from collections import Counter
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.glossary as GL                          # noqa: E402
import helpers.stats as S                              # noqa: E402


def _defs():
    return {d[0]: d for d in GL.STAT_DEFS}


def test_the_glossary_defines_each_key_once():
    """A key defined twice is a key whose meaning depends on which entry the
    lookup reaches first."""
    dupes = [k for k, n in Counter(d[0] for d in GL.STAT_DEFS).items() if n > 1]
    assert not dupes, f"defined more than once in STAT_DEFS: {dupes}"


def test_sce_is_self_creation():
    """Q12, as the glossary already had it."""
    assert "Self-Creation" in _defs()["SCE"][1], _defs()["SCE"][1]


def test_sceff_is_scoring_efficiency_and_no_longer_disclaims_sce():
    """The warning existed only because of the collision. With the collision
    gone it is a sentence pointing at a problem that no longer exists — and a
    reader who is told two stats are 'not the same' starts wondering which one
    they are looking at."""
    entry = _defs()["ScEff"]
    assert "Scoring Efficiency" in entry[1]
    blurb = " ".join(str(x) for x in entry)
    assert "NOT the same as SCE" not in blurb, blurb


def test_the_scoring_efficiency_formula_is_unchanged():
    """The rename must not touch the maths. Points scored over points possible:
    two 2s made of four attempted plus one 3 of two is (4+3)/(8+6).

    `shot_efficiency` works off PTS - FTM rather than off 2PM/3PM directly, so
    the box has to be a real one — free throws are excluded by subtraction, and
    an FT in here would prove the exclusion as well as the ratio."""
    box = S._blank_box()
    box.update({"2PM": 2, "2PA": 4, "3PM": 1, "3PA": 2,
                "FTM": 5, "FTA": 6, "PTS": 2 * 2 + 3 + 5})
    assert abs(S.shot_efficiency(box) - (7 / 14)) < 1e-9
    assert abs(S.scoring_efficiency(box) - S.shot_efficiency(box)) < 1e-12


def test_self_creation_counts_shots_with_neither_a_pass_nor_a_screener():
    """Q12's caveat, checked rather than assumed: the ruling defines SCE as no
    pass-from AND no set-up-by, and `shots_self` is exactly that counter — the
    else-branch after has_pass and has_sc, which is why no maths had to move."""
    box = S._blank_box()
    for k in ("shots_self", "shots_pass", "shots_sc", "shots_both"):
        assert k in box, k


# ── the collision, as text ────────────────────────────────────────────────────
def test_no_line_labels_a_column_sceff_while_reading_the_key_sce():
    """The exact shape of the bug, and the one a scan can see.

    `"ScEff": f"{r.get('SCE', 0) * 100:.0f}%"` is a column that says one thing
    and reads another. After the rename no line should mention both tokens —
    except the glossary, which now has to define them side by side precisely so
    a reader can tell them apart."""
    bad = []
    for sub in ("pages", "helpers"):
        for path in sorted((_APP / sub).rglob("*.py")):
            if path.name == "glossary.py":
                continue
            for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ln.lstrip().startswith("#"):
                    continue          # comments may explain the history
                if "ScEff" in ln and "SCE" in ln.replace("ScEff", ""):
                    bad.append(f"{path.relative_to(_APP)}:{i}: {ln.strip()}")
    assert not bad, ("a column labelled ScEff still reads the key SCE at:\n  "
                     + "\n  ".join(bad))


def test_the_old_self_creation_key_is_gone():
    """`SelfCr%` was self-creation under a name the glossary never used, which
    is half of why the collision survived. One key, one name."""
    bad = []
    for sub in ("pages", "helpers"):
        for path in sorted((_APP / sub).rglob("*.py")):
            for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "SelfCr%" in ln:
                    bad.append(f"{path.relative_to(_APP)}:{i}: {ln.strip()}")
    assert not bad, ("the pre-Q12 self-creation key survives at:\n  "
                     + "\n  ".join(bad))
