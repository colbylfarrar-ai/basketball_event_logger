"""
pronouns.py — one pronoun set per league, so the prose matches the roster.

Every prose surface in this app was written against the girls' book and hard-
coded "she"/"her" into its sentences. Selecting the Boys league changed every
number on the page and none of the words, so a boys' coach read "she reaches
her 3rd foul" about his own player. That is the bug this module exists to end.

`teams.gender` is the single source: 'F' → she/her, 'M' → he/him, and anything
else — None, the "All" option on the shared `ui.gender_radio`, a league-wide
pool that spans both — → the singular they. Neutral is the DEFAULT rather than
a special case, so a render site that never learns its gender degrades to
correct-but-generic instead of confidently wrong.

Verb agreement travels with the pronoun, because it has to. "she is carrying"
and "they are carrying" are not the same sentence with one word swapped, and a
render site that only swaps the pronoun ships "they is carrying". Call `v()`
with the third-person-singular spelling you would have typed and it hands back
the plural form when the set is `they`:

    p = pronouns.for_gender(gender)
    f"{p.Subj} {p.v('reaches')} {p.poss} {ord_} foul"
    # F → "She reaches her 3rd foul"      M → "He reaches his 3rd foul"
    # None → "They reach their 3rd foul"

Capitalised variants are properties (`Subj`, `Obj`, `Poss`, ...) so a sentence
can open with one without `.capitalize()` at every call site.

Streamlit-free and dependency-free — the engines (`foul_trouble`, `involvement`)
import it exactly like the views do.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── verbs whose third-person-singular is not a plain -s ──────────────────────
# `v()` strips the trailing 's' for the plural set, which is right for the long
# tail ("reaches" → "reach", "loses" → "lose", "plays" → "play"). These are the
# ones where that rule produces nonsense, so they are looked up instead.
_IRREGULAR = {
    "is": "are", "was": "were", "has": "have", "does": "do",
    "goes": "go", "isn't": "aren't", "wasn't": "weren't",
    "hasn't": "haven't", "doesn't": "don't", "'s": "'re",
}


@dataclass(frozen=True)
class Pronouns:
    """One pronoun set, plus the verb agreement that has to travel with it."""

    subj: str           # she / he / they
    obj: str            # her / him / them
    poss: str           # her / his / their      (determiner: "her shots")
    poss_abs: str       # hers / his / theirs    (standalone: "the ball is hers")
    refl: str           # herself / himself / themselves
    plural: bool        # singular `they` takes plural agreement

    # Sentence-initial forms, so call sites stay f-string-shaped.
    @property
    def Subj(self) -> str:
        return self.subj.capitalize()

    @property
    def Obj(self) -> str:
        return self.obj.capitalize()

    @property
    def Poss(self) -> str:
        return self.poss.capitalize()

    @property
    def PossAbs(self) -> str:
        return self.poss_abs.capitalize()

    @property
    def Refl(self) -> str:
        return self.refl.capitalize()

    def v(self, third_singular: str) -> str:
        """Agree a verb with this set. Pass the "she ___" spelling.

        `v("reaches")` → "reaches" for she/he, "reach" for they. Irregulars are
        table-driven. Everything else drops the trailing 's' — except after a
        sibilant stem, where the third-person ending is '-es' and dropping one
        letter leaves "reache". A verb that does not end in 's' is returned
        untouched, so `v("play")` or `v("drew")` is safe if a call site guesses
        wrong.
        """
        if not self.plural:
            return third_singular
        low = third_singular.lower()
        if low in _IRREGULAR:
            out = _IRREGULAR[low]
            return out.capitalize() if third_singular[:1].isupper() else out
        if not low.endswith("s"):
            return third_singular
        # "carries" → "carry": a consonant + y went to -ies.
        if low.endswith("ies") and len(low) > 4:
            return third_singular[:-3] + "y"
        # "reaches"/"passes"/"fixes" drop two letters; "loses"/"plays" drop one.
        # The test is the stem the '-es' would leave behind: a sibilant or 'o'
        # took the long ending, anything else took the plain 's'.
        if low.endswith("es") and low[:-2].endswith(
                ("ch", "sh", "ss", "x", "z", "o")):
            return third_singular[:-2]
        return third_singular[:-1]


FEMALE = Pronouns("she", "her", "her", "hers", "herself", plural=False)
MALE = Pronouns("he", "him", "his", "his", "himself", plural=False)
NEUTRAL = Pronouns("they", "them", "their", "theirs", "themselves", plural=True)


def for_gender(gender: str | None) -> Pronouns:
    """`teams.gender` → the pronoun set. Unknown/mixed/None → singular they.

    Accepts the stored codes ('F'/'M') and the display labels ('Girls'/'Boys')
    so a caller holding either can pass it straight through.
    """
    g = (gender or "").strip().upper()[:1]
    if g == "F" or g == "G":        # 'F', or 'Girls' from a display label
        return FEMALE
    if g == "M" or g == "B":        # 'M', or 'Boys'
        return MALE
    return NEUTRAL
