"""Every percentile on screen has to say what pool it is over. (B1)

`cards.pctile_bar` is the app's most-reused explanation primitive, and it had no
pool-size parameter at all — so a percentile computed over five teams was
visually and textually identical to one computed over 748. On the tracked plane
the pools are small enough that this is not a rounding concern:

    girls   22 tracked teams
    boys    10 tracked teams  — every boys percentile is a multiple of ten,
                                and the distinct values are exactly {0,10,…,90}

"DRtg 96.1 · 80th pct · elite defense" means second of five, and reads as top of
the state. That sentence is the fastest way to lose a coach's trust, and in
October there are four or five readers who do not already know the pool sizes.

Two rules, both from the founder's rulings:

  * Q4 — below a pool of ten, show the RANK. A rank of 5 is a fact; a percentile
    computed from five observations is not.
  * Q6 — both gates, and DISCLOSE. Say which one is biting rather than silently
    withholding the number.

The static half of this file is the one that matters long-term: the failure mode
is a new call site that forgets the pool, which renders perfectly and says
nothing wrong until a coach believes it.

Run: python -m pytest tracker/test_pctile_pool.py
"""
import ast
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.cards as CARDS                          # noqa: E402


def test_a_percentile_over_a_real_pool_states_the_pool():
    """22 tracked girls teams is a pool worth a percentile — and the reader
    still gets told how many."""
    out = CARDS.pctile_bar("Defense", "96.1 DRtg", 80, n=22)
    assert "80th" in out
    assert "of 22" in out, out


def test_a_pool_under_the_floor_shows_the_rank_instead():
    """Five teams cannot carry a percentile, and the rank says the same thing
    without the borrowed authority.

    `stats.percentile` is `100 * (count strictly below) / n`, so over five teams
    the only reachable values are {0, 20, 40, 60, 80, 100} and each one names a
    rank exactly: 60th is three teams below, which is second of five. (THE BOOK
    §10 reads its 80th-of-five example as second; on this codebase's percentile
    it is first. The arithmetic here follows the helper that actually computes
    the number.)"""
    out = CARDS.pctile_bar("Defense", "96.1 DRtg", 60, n=5)
    assert "2nd of 5" in out, out
    assert "60th" not in out, ("a percentile computed from five observations is "
                               f"still on screen: {out}")
    assert "1st of 5" in CARDS.pctile_bar("Defense", "96.1 DRtg", 80, n=5)
    assert "5th of 5" in CARDS.pctile_bar("Defense", "96.1 DRtg", 0, n=5)


def test_the_floor_is_the_ruling_and_is_named_once():
    """Q4 set it at ten. It is a constant so that the officials lab, the
    superlative gates and this primitive cannot end up with three floors — which
    is what the Officiating Lab already runs on one screen."""
    assert CARDS.POOL_FLOOR == 10
    out = CARDS.pctile_bar("Offense", "108 ORtg", 90, n=CARDS.POOL_FLOOR)
    assert "90th" in out and "of 10" in out, out


def test_no_pool_at_all_still_renders_rather_than_raising():
    """The un-migrated shape stays legal so a missed site degrades to today's
    output instead of throwing inside a page's try/except and printing
    "unavailable". The gate against missing sites is the static test below,
    which fails loudly at test time rather than quietly at render time."""
    out = CARDS.pctile_bar("Offense", "108 ORtg", 90)
    assert "90th" in out


def test_an_absent_percentile_is_still_a_dash():
    assert "—" in CARDS.pctile_bar("Offense", "—", None, n=22)


# ── the static gate ───────────────────────────────────────────────────────────
_NAMES = {"pctile_bar", "_pctile_bar"}


def _bad_calls(path):
    """(line, snippet) for every pctile_bar call that names no pool."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name not in _NAMES:
            continue
        if len(node.args) >= 4 or any(kw.arg == "n" for kw in node.keywords):
            continue
        out.append((node.lineno, lines[node.lineno - 1].strip()))
    return sorted(set(out))


def test_every_call_site_names_the_pool_its_percentile_came_from():
    """The rule, made mechanical.

    A bar that cannot state its pool is a bar that should not be drawn, so the
    honest answer at a site with no pool in hand is to find the pool — not to
    leave the argument off. Where a wrapper forwards to this primitive it has to
    take the pool too, which is why `_pctile_bar` counts as the same name."""
    bad = []
    for sub in ("pages", "helpers"):
        for path in sorted((_APP / sub).rglob("*.py")):
            for line, snippet in _bad_calls(path):
                bad.append(f"{path.relative_to(_APP)}:{line}: {snippet}")
    assert not bad, ("a percentile bar is drawn without saying what pool it is "
                     "over at:\n  " + "\n  ".join(bad))
