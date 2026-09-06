"""The tablet layout depends on three CONTIGUOUS groups of elements in
index.html. If an id moves between groups the wide layout silently breaks --
an element lands in the wrong column, or a hot control drops below the fold --
and nothing else in the suite would notice. See
docs/superpowers/specs/2026-09-05-tablet-layout-design.md."""
import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parent / "static"

COL_LEFT = ["track-head", "subs-panel", "court-wrap", "shot-caption"]
COL_RIGHT = ["mode-row", "track-tip", "defense-bar", "playtype-bar",
             "flow-opts", "flow"]
COLD = ["to-row", "action-row", "sync-status", "coverage-badge",
        "pbp-toggle", "pbp"]


def _wrapper_body(html, cls):
    """The markup between <div class="cls"> and its matching close.

    The wrappers hold no nested <div class=...> siblings of their own at author
    time, so a non-greedy match to the next wrapper open (or </section>) is
    enough -- and is checked by the id assertions below anyway."""
    m = re.search(r'<div class="' + cls + r'">(.*?)\n  </div>', html, re.S)
    assert m, f"no <div class=\"{cls}\"> wrapper in index.html"
    return m.group(1)


def test_wrappers_hold_exactly_their_groups():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for cls, expected in (("col-left", COL_LEFT),
                          ("col-right", COL_RIGHT),
                          ("tracker-cold", COLD)):
        body = _wrapper_body(html, cls)
        found = re.findall(r'id="([\w-]+)"', body)
        got = [i for i in found if i in expected]
        assert got == expected, f"{cls}: expected {expected}, got {got}"
        # nothing from another group leaked in
        others = set(COL_LEFT + COL_RIGHT + COLD) - set(expected)
        assert not (set(found) & others), f"{cls} contains foreign ids"


def test_wide_rules_key_off_is_wide_only():
    """Every wrapper rule either is the one shared display:contents reset, or is
    scoped to html.is-wide. A wrapper rule that is scoped to neither -- say one
    left inside an `@media (min-width: 768px)` block -- would apply the flex
    column to a phone held in landscape, the one regression this layout must
    not have."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    reset = ".col-left, .col-right, .tracker-cold { display: contents; }"
    assert reset in css, f"missing the shared narrow-mode reset: {reset}"
    for m in re.finditer(r"^([^\n{]*\.(?:col-left|col-right|tracker-cold)[^\n{]*)\{",
                         css, re.M):
        sel = m.group(1).strip()
        if sel + " {" == reset.split("{")[0].strip() + " {":
            continue                      # the reset itself, intentionally global
        assert "is-wide" in sel, f"wrapper rule not scoped to html.is-wide: {sel}"
