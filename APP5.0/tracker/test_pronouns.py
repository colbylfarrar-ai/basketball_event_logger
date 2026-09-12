"""
Pronouns — the prose follows the roster, not the league it was written against.

THE BUG THIS GUARDS AGAINST is the one that shipped: every prose surface in the
app was written for the girls' book and hard-coded "she"/"her" into its
sentences, so a boys' coach selecting the Boys league got every number changed
and none of the words — "she reaches her 3rd foul" about his own player.

Two rules carry the whole fix and both are checked here:

  * `teams.gender` picks the set, and anything the app cannot resolve ('All',
    None, a league-wide pool spanning both) falls to the singular they. Neutral
    is the DEFAULT, never a wrong guess;
  * verb agreement travels WITH the pronoun. Swapping only the pronoun ships
    "they is carrying", so `v()` is checked against every third-person form the
    render sites actually pass, plus the spelling traps ("reaches" → "reach",
    not "reache"; "loses" → "lose", not "los").

The last block is the regression proper: it drives the real render helpers at
both leagues and asserts no female pronoun survives a boys' render.

Run: python tracker/test_pronouns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.pronouns as PRON                     # noqa: E402
import helpers.foul_trouble as FT                   # noqa: E402
import helpers.involvement as IV                    # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("\n-- the set resolves off teams.gender --------------------------------")

ok(PRON.for_gender("F") is PRON.FEMALE, "'F' -> she/her")
ok(PRON.for_gender("M") is PRON.MALE, "'M' -> he/him")
ok(PRON.for_gender(None) is PRON.NEUTRAL,
   "None -> singular they, NOT the girls' book (the bug this file exists for)")
ok(PRON.for_gender("") is PRON.NEUTRAL, "empty string -> they")
ok(PRON.for_gender("All") is PRON.NEUTRAL,
   "the gender_radio 'All' option spans both leagues, so it gets they")
ok(PRON.for_gender("Girls") is PRON.FEMALE and PRON.for_gender("Boys") is PRON.MALE,
   "display labels resolve too, so a caller holding either can pass it through")
ok(PRON.for_gender(" f ") is PRON.FEMALE, "whitespace and case do not matter")

print("\n-- the forms are complete ------------------------------------------")

for _name, _p in (("F", PRON.FEMALE), ("M", PRON.MALE), ("they", PRON.NEUTRAL)):
    ok(all(getattr(_p, f) for f in
           ("subj", "obj", "poss", "poss_abs", "refl")),
       f"{_name}: every form is populated")
    ok(_p.Subj == _p.subj.capitalize() and _p.Poss == _p.poss.capitalize(),
       f"{_name}: sentence-initial variants capitalize the same word")

ok(PRON.MALE.poss == "his" and PRON.MALE.poss_abs == "his",
   "the male determiner and the standalone are both 'his' (they differ for F)")
ok(PRON.FEMALE.poss == "her" and PRON.FEMALE.poss_abs == "hers",
   "and 'her shots' / 'the ball is hers' are NOT the same word")

print("\n-- verb agreement travels with the pronoun -------------------------")

ok(PRON.FEMALE.v("reaches") == "reaches" and PRON.MALE.v("is") == "is",
   "singular sets pass the verb straight through")

_N = PRON.NEUTRAL
for _third, _plural in (
        ("is", "are"), ("was", "were"), ("has", "have"), ("does", "do"),
        ("goes", "go"), ("'s", "'re"),
        ("reaches", "reach"),          # sibilant stem: -es, not -s
        ("passes", "pass"), ("fixes", "fix"), ("watches", "watch"),
        ("pushes", "push"),
        ("loses", "lose"), ("closes", "close"),   # plain -s after a silent e
        ("carries", "carry"), ("flies", "fly"),   # consonant + y went to -ies
        ("dies", "die"), ("ties", "tie"),         # but short ones did not
        ("picks", "pick"), ("gets", "get"), ("plays", "play"),
        ("scores", "score"), ("checks", "check"), ("fouls", "foul")):
    ok(_N.v(_third) == _plural, f"they {_plural}  (from '{_third}')")

for _untouched in ("guarded", "drew", "shot", "contested", "reached", "play"):
    ok(_N.v(_untouched) == _untouched,
       f"'{_untouched}' has no -s to strip and is returned unchanged")

ok(_N.v("WAS").upper() == "WERE",
   "an all-caps call site can upper() the result (the Involvement help text)")

print("\n-- the render helpers actually follow it ---------------------------")

# Minimal shapes, matching what the engines return. The point is the PROSE.
_bench = {7: {2: {"games": 5, "season_share": 62.0, "after_share": 31.0,
                  "drag": 31.0}}}
_early = {7: {2: {"games": 5, "early": 4, "share": 0.8}}}
_carried = {7: {"games": 5, "carry_share": 30.0, "clean_share": 70.0,
                "drag": 40.0}}
_inv = {7: {"plays_on": 40, "involved": 24, "rate": 60.0, "as_scorer": 6,
            "as_passer": 10, "as_screener": 5, "as_hockey": 3, "tagged": 8}}
_names = {7: "Player Seven"}

FEM = ("she", "her", "hers", "herself")


def _render(pron):
    """Every line the four render helpers produce for one pronoun set."""
    return " ".join(
        t for _b, _n, t in
        FT.foul_trouble_verdict(_bench, None, names=_names, pron=pron)
        + FT.quarter_rule_lines(_early, _carried, names=_names, pron=pron)
        + IV.involvement_verdict(_inv, names=_names, pron=pron))


_boys = _render(PRON.MALE).lower()
ok(_boys, "the boys' render produced lines at all")
for _w in FEM:
    ok(f" {_w} " not in f" {_boys} ",
       f"no '{_w}' anywhere in a boys' render — the reported bug")
ok(" he " in f" {_boys} " or " his " in f" {_boys} ",
   "and it says he/his instead")

_girls = _render(PRON.FEMALE).lower()
ok(" her " in f" {_girls} " or " she " in f" {_girls} ",
   "the girls' render is unchanged from what shipped")

_they = _render(PRON.NEUTRAL).lower()
for _w in FEM + ("he", "him", "his"):
    ok(f" {_w} " not in f" {_they} ",
       f"an unresolved league never says '{_w}'")
ok(" they " in f" {_they} " or " their " in f" {_they} ",
   "it says they/their")

# Agreement is the half a naive pronoun swap gets wrong.
for _bad in ("they is", "they has", "they reaches", "they was", "they loses",
             "they picks", "they gets"):
    ok(_bad not in _they, f"no '{_bad}' — the verb agreed with the pronoun")

# A caller that passes nothing must not fall back to the girls' book.
_default = " ".join(
    t for _b, _n, t in
    FT.foul_trouble_verdict(_bench, None, names=_names)
    + IV.involvement_verdict(_inv, names=_names)).lower()
for _w in FEM:
    ok(f" {_w} " not in f" {_default} ",
       f"a caller passing no pron gets they, not '{_w}'")

print(f"\n{PASS} checks passed.")
