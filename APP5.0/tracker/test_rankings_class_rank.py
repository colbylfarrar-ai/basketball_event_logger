"""Rankings -> Overview carries the class rank next to the overall rank.

Three things are pinned here, and the third is the one that would have shipped
a wrong number:

  1. "Cls Rk" is in BOTH published column sets (Core and Composites), directly
     after "Rank", so the two ranks read as a pair.
  2. Every value states its pool ("#3 of 74") or is an em dash. A rank that does
     not name the pool it was taken over is the house's oldest rule
     (`helpers/cards.pctile_bar`, memory `pctile-pool-convention`), and the
     public-rank mess on live.hooptracks.com is what breaking it looks like.
  3. `_assign_ranks` gives a CLASSLESS team a ClassRank anyway — it buckets on
     (state, class) and a missing class is just another bucket key. So "every
     team has a ClassRank" is true and useless: that bucket is "every classless
     team in this state", which is not a class ladder. The page must print an em
     dash for those rows, and this test asserts the trap still exists so the
     guard is never removed as dead code.

     The sharp edge is that the class column holds the literal string 'N/A'
     far more often than NULL, and `class_label` renders both the same way —
     so a blank-only guard looks right and passes 'N/A' through. Measured on
     the book: 21 distinct (state, 'N/A') buckets, all labelled 'N/A', whose
     class ranks would interleave as if they were one ladder. Both this and
     `helpers.ui.rank_chip` (which was printing 'N/A #63' on score cards) are
     pinned below.

Run: python tracker/test_rankings_class_rank.py   (also collected by pytest)
"""
import os
import re
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0
CELL = re.compile(r"^(#\d+ of \d+|#\d+|—)$")


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _played_season():
    """The season label the picker shows for a season that has FINISHED games.

    SEAS.ACTIVE ("Current") holds next season's schedule and zero results
    (memory `season-rollover-active-is-empty`), so an unseeded render lands on
    the correct empty state and a naive smoke reads that as a pass.
    """
    import helpers.seasons as SEAS
    import helpers.team_ratings as TR
    for value, label in SEAS.season_options():
        if TR.score_ratings(gender="F", season=value):
            return label
    return None


def _overview_table(colset, season_label):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    # st.page_link raises KeyError('url_pathname') under AppTest (no page ctx).
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None

    at = AppTest.from_file(os.path.join(_APP, "pages", "5_Rankings.py"),
                           default_timeout=900)
    at.session_state["rk_view"] = "Overview"
    at.session_state["rk_season"] = season_label
    at.session_state["rk_ov_cols"] = colset
    at.run()
    assert not at.exception, \
        f"{colset} raised: {[repr(e.value)[:300] for e in at.exception]}"
    for e in at.main:
        if type(e).__name__ != "Dataframe":
            continue
        try:
            cols = list(e.value.columns)
        except Exception:
            continue
        if "Rank" in cols and "Team" in cols and "Cls Rk" in cols:
            return e.value
    return None


def test_overview_shows_class_rank():
    season_label = _played_season()
    if not season_label:
        print("  -- no finished games in this book; Overview render skipped")
        return

    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        for colset in ("Core", "Composites"):
            df = _overview_table(colset, season_label)
            ok(df is not None, f"{colset}: the Overview table carries 'Cls Rk'")
            cols = list(df.columns)
            # Adjacent to Rank. "Delta Rk" is allowed to follow the pair, never
            # to split it.
            ok(cols.index("Cls Rk") == cols.index("Rank") + 1,
               f"{colset}: 'Cls Rk' sits immediately after 'Rank'")

            bad = [v for v in df["Cls Rk"] if not CELL.match(str(v))]
            ok(not bad,
               f"{colset}: every cell states its pool or is an em dash "
               f"({len(df)} rows, {len(bad)} malformed)")

            # Within one class, the class rank must follow the overall rank:
            # both orders come from the same Rating, so any inversion means the
            # column was joined to the wrong row.
            seen, inversions = {}, 0
            for _i, row in df.iterrows():
                cell = str(row["Cls Rk"])
                if cell == "—":
                    continue
                cls = row["Class"]
                n = int(cell.split()[0].lstrip("#"))
                if cls in seen and n < seen[cls]:
                    inversions += 1
                seen[cls] = n
            ok(inversions == 0,
               f"{colset}: class rank rises with overall rank inside every "
               f"class ({len(seen)} classes, {inversions} inversions)")
    finally:
        os.chdir(cwd)


def test_classless_teams_get_a_meaningless_class_rank():
    """The trap the em dash exists for — asserted, not assumed."""
    import helpers.team_ratings as TR

    for gender in ("F", "M"):
        rated = TR.score_ratings(gender=gender)
        if not rated:
            continue
        classless = [r for r in rated.values()
                     if (r.get("class") or "").strip().upper() in ("", "N/A")]
        if not classless:
            continue
        ok(all(r.get("ClassRank") for r in classless),
           f"{gender}: all {len(classless)} classless teams still carry a "
           f"ClassRank — which is why the page must not print it")
        # And they are pooled together rather than left alone, so the number
        # would read as a real ladder position.
        ok(any((r.get("ClassOf") or 0) > 1 for r in classless),
           f"{gender}: classless teams share a bucket (ClassOf > 1), so the "
           f"number would look like a class rank and is not one")

        # And they are split across MORE THAN ONE bucket while sharing one
        # display label — the reason the guard cannot key on the label.
        buckets = {((r.get("state") or ""), r.get("class")) for r in classless}
        labels = {r.get("class_lbl") for r in classless}
        ok(len(buckets) > len(labels),
           f"{gender}: {len(buckets)} classless buckets collapse to "
           f"{len(labels)} label(s) — interleaved ladders under one name")

        # The chip every score card calls must decline to render them.
        from helpers.ui import rank_chip
        r = classless[0]
        ok(rank_chip(r.get("class_lbl"), r.get("ClassRank")) == "",
           f"{gender}: rank_chip prints nothing for a classless team "
           f"(was 'N/A #{r.get('ClassRank')}')")
        # ...while a real class still renders.
        real = next((x for x in rated.values()
                     if (x.get("class") or "").strip().upper()
                     not in ("", "N/A")), None)
        if real:
            ok(rank_chip(real.get("class_lbl"), real.get("ClassRank")) != "",
               f"{gender}: rank_chip still renders a real class chip "
               f"({real.get('class_lbl')} #{real.get('ClassRank')})")
        return
    print("  -- no classless rated teams in this book; guard test skipped")


if __name__ == "__main__":
    test_classless_teams_get_a_meaningless_class_rank()
    test_overview_shows_class_rank()
    print(f"\nALL {PASSED} CHECKS PASSED")
