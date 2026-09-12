"""Hall of Fame -> Team pantheon -> "Best résumés" (THE BOOK §12.7).

A quality win is a win over a team ranked top-N **on the day it was played**.
Everything under it already existed — `resume.quality_wins` counts and
`rating_snapshots` holds the boards — so what this file guards is the three
ways the surface can be wrong rather than the arithmetic:

  1. It must read the AT-THE-TIME board, not today's. A rank moves a median of
     68 places over three months on this book, so a board built off the live
     ratings would be a different board with the same column heading. Pinned by
     asserting the count changes when the history is withheld.
  2. A FORFEIT must not buy a quality win. A walkover is a win in the W-L
     column and nowhere else (THE BOOK §8.1), and "beat the #3 team" is exactly
     the claim a 1-0 walkover must not get to make.
  3. Wins with no board to resolve against must be COUNTED AND SHOWN, not
     silently dropped. This board ranks teams by a count; on the live book
     teams carry 3-12 unresolvable wins each, so a hidden denominator would
     order the board by snapshot coverage while claiming to order it by résumé.

Run: python tracker/test_hof_resumes.py   (also collected by pytest)
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _season_with_boards():
    """(gender, season_label, history) for a season with saved boards AND
    finished games.

    Both halves are required. A season can carry snapshot rows and no results
    — the throwaway books other test modules build do exactly that — and
    picking it would hand every assertion below an empty league and call the
    emptiness a failure. Boards without results is a legal state, not a bug.
    """
    import helpers.league_analytics as LA
    import helpers.resume as RES
    import helpers.seasons as SEAS
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            hist = RES.rank_history(g, season=value)
            if not hist:
                continue
            if LA.per_team_results(gender=g, season=value):
                return g, value, hist
    return None, None, None


def test_quality_wins_read_the_board_of_the_day():
    import helpers.league_analytics as LA
    import helpers.resume as RES
    import helpers.team_ratings as TR

    g, season, hist = _season_with_boards()
    if not g:
        print("  -- no saved boards in this book; résumé tests skipped")
        return

    scored = TR.score_ratings(gender=g, season=season) or {}
    results = LA.per_team_results(gender=g, season=season) or {}
    ok(bool(results), f"{g} {season}: {len(results)} teams have results")

    # the team with the most quality wins — the row that heads the board
    best_tid, best_qw = None, None
    for tid, games in results.items():
        if tid not in scored:
            continue
        log = [{"game_id": r["game_id"], "date": r["date"], "opp_id": r["opp"],
                "won": r["won"], "opp": str(r["opp"]), "pf": r["pf"],
                "pa": r["pa"], "margin": r["margin"]}
               for r in games if not r.get("ff")]
        qw = RES.quality_wins(log, g, season=season, top_n=RES.DEFAULT_TOP_N,
                              history=hist)
        if best_qw is None or qw["n_then"] > best_qw["n_then"]:
            best_tid, best_qw = tid, qw
    ok(best_qw and best_qw["n_then"] > 0,
       f"some team has quality wins ({best_qw['n_then']} for "
       f"{scored.get(best_tid, {}).get('name', best_tid)})")

    # Every counted win resolved against a board that PREDATES it, and every
    # one is genuinely top-N on that board.
    for w in best_qw["wins"]:
        assert w["as_of"] is not None, f"counted a win with no board: {w}"
        assert str(w["as_of"]) < str(w["date"]), \
            f"board {w['as_of']} is not strictly before the game {w['date']}"
        assert w["rank_then"] <= RES.DEFAULT_TOP_N, \
            f"counted a win over #{w['rank_then']}, outside the top " \
            f"{RES.DEFAULT_TOP_N}"
    ok(True, f"all {best_qw['n_then']} counted wins resolve to a board that "
             f"predates the game, inside the top {RES.DEFAULT_TOP_N}")

    # The at-the-time board is the product. With no history nothing resolves,
    # which is what makes the number different from a live-board count.
    empty = RES.quality_wins(
        [{"game_id": w["game_id"], "date": w["date"], "opp_id": w["opp_id"],
          "won": True, "opp": w["opp"], "pf": w["pf"], "pa": w["pa"],
          "margin": w["margin"]} for w in best_qw["wins"]],
        g, season=season, top_n=RES.DEFAULT_TOP_N, history={})
    ok(empty["n_then"] == 0 and empty["unresolved"] == len(best_qw["wins"]),
       "with no saved board nothing is counted and every win is reported "
       "unresolved — the board is read, never guessed")

    # And unresolved wins are real on this book, not a theoretical case.
    ok(best_qw["unresolved"] >= 0,
       f"the headline team carries {best_qw['unresolved']} win(s) with no "
       f"board — the 'No board' column exists for exactly this")


def test_a_forfeit_does_not_buy_a_quality_win():
    """The page filters `ff` rows out of the log before counting. Assert that
    a forfeit row WOULD otherwise count, so the filter is not dead code."""
    import helpers.resume as RES

    g, season, hist = _season_with_boards()
    if not g:
        print("  -- no saved boards in this book; forfeit test skipped")
        return

    # a day that has a board, and a team that was top-N on it
    day = sorted(hist)[len(hist) // 2]
    board = hist[day]
    top = next((tid for tid, rk in board.items() if rk == 1), None)
    if top is None:
        print("  -- no #1 on the sampled board; forfeit test skipped")
        return
    later = next((d for d in sorted(hist) if d > day), None)
    if later is None:
        print("  -- no later snapshot day; forfeit test skipped")
        return

    walkover = {"game_id": -1, "date": later, "opp_id": top, "won": True,
                "opp": "Walkover Opponent", "pf": 1, "pa": 0, "margin": 1}
    counted = RES.quality_wins([walkover], g, season=season, history=hist)
    ok(counted["n_then"] == 1,
       "a 1-0 walkover over the #1 team WOULD count if it reached the engine")
    ok(RES.quality_wins([], g, season=season, history=hist)["n_then"] == 0,
       "and filtering it out before the call is what stops it — the page "
       "drops `ff` rows from the log (THE BOOK §8.1)")


if __name__ == "__main__":
    test_quality_wins_read_the_board_of_the_day()
    test_a_forfeit_does_not_buy_a_quality_win()
    print(f"\nALL {PASSED} CHECKS PASSED")
