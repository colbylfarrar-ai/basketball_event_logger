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
import re
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


# ── the OTHER shape: a percentile written into a string ──────────────────────
# `pctile_bar` is not the only way a percentile reaches a screen. The chips,
# the KPI tiles and the ranked tables write one straight into an f-string —
# `f"{_ORD(best['pct'])} pct"`, `"Pctile": f"{mine['pct']:.0f}"` — and the
# static test above cannot see any of them, because no call to the primitive is
# made. That is exactly how six chips on Charts → Play Style and
# Charts → Defense → Scheme spent a release saying "91st pct" about a pool of
# eleven teams.
#
# The fix at those sites is `stats.pctile_badge(pct, pool_n)`, which renders
# "91st of 11" or, under the floor, "4th of 5". This test holds the line: a NEW
# site that writes a raw percentile into a rendered string fails here.
#
# KNOWN, and the backlog rather than a bug — each of these is a percentile whose
# pool is invisible, on a surface outside the 2026-09-12 Charts/Lab/box scrub.
# Remove an entry when you fix it; do not add one without a reason.
_RAW_PCT_ALLOWED = {
    ("helpers/dashboard/scout_tab.py", "the scout sheet's set-call chips"),
    ("helpers/dashboard/player_card.py", "the player card's play-type rows"),
    ("pages/5_Rankings.py", "four Rankings play-type / scheme tables"),
    ("pages/7_Players.py", "a badge chip"),
}
_ALLOWED_FILES = {f for f, _why in _RAW_PCT_ALLOWED}

#: `_ORD(x["pct"])` / `ordinal(x['pct'])` — an ordinal built from a pct key.
_RX_ORD = re.compile(
    r"""(_ORD|_ord|ordinal)\(\s*[A-Za-z_][\w\[\]'".]*\[\s*['"]pct['"]\s*\]""")
#: a "Pct" / "Pctile" dict key whose value formats a percentile directly.
_RX_COL = re.compile(r"""['"]Pct(ile)?['"]\s*:\s*\(?\s*(f?['"]|round\()""")


def _raw_pct_sites(path):
    """Lines that render a percentile with no pool in sight.

    The window is two lines either side, not the line itself: a correct site
    can legitimately put the pool on the next argument (a metric's delta), and
    flagging that would push authors toward deleting the pool rather than
    moving it."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines, 1):
        if not (_RX_ORD.search(line) or _RX_COL.search(line)):
            continue
        near = " ".join(lines[max(0, i - 3):i + 2])
        if "pctile_badge" in near or "_PCTB" in near or "pool_n" in near:
            continue                      # the pool is right there
        out.append(f"{i}: {line.strip()[:100]}")
    return out


def test_no_new_percentile_is_written_into_a_string_without_its_pool():
    """Every raw-percentile render is either fixed or on the named backlog."""
    found = {}
    for sub in ("pages", "helpers"):
        for path in sorted((_APP / sub).rglob("*.py")):
            rel = str(path.relative_to(_APP)).replace(chr(92), "/")
            sites = _raw_pct_sites(path)
            if sites:
                found[rel] = sites
    new = {f: v for f, v in found.items() if f not in _ALLOWED_FILES}
    msg = "; ".join(f"{f} {v}" for f, v in sorted(new.items()))
    assert not new, (
        "a percentile is written into a rendered string without the pool it "
        "was ranked against - use stats.pctile_badge(pct, pool_n): " + msg)


def test_the_backlog_is_real_and_shrinks():
    """An allowlist nobody prunes becomes a permission slip. Every named file
    must still contain at least one raw render — when it does not, delete the
    entry rather than leaving a stale exemption behind."""
    stale = [f"{rel} ({why})" for rel, why in sorted(_RAW_PCT_ALLOWED)
             if not (_APP / rel).exists() or not _raw_pct_sites(_APP / rel)]
    assert not stale, ("these files no longer render a bare percentile - drop "
                       "them from _RAW_PCT_ALLOWED: " + "; ".join(stale))
