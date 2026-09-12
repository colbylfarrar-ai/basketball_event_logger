"""An UNPLAYED fixture in the active season wears the sentinel, and that is right.

FREEZE_PUNCHLIST_2026-09-09 §6 flagged 23 production games dated 2026-12-08 →
2027-02-16 sitting on `season='Current'` and asked whether
`auto_season_rollover.py` relabels them "or November opens on an empty
schedule". Measured on the production snapshot, the answer is that there was
never anything to relabel:

  * `SEAS.ACTIVE` — the literal string 'Current' — is **the stamp an
    active-season row carries**, not a stale placeholder. `execute_rollover`
    replaces it with a real label on the way OUT of a season, which is why
    every row currently in the active season has it.
  * Production's `app_settings.active_season` is already **2026-2027**, and
    those 23 games are dated inside 2026-2027. They are stamped correctly.
  * `auto_advance_if_due` therefore no-ops through the whole season — measured
    on the snapshot at 2026-10-01, 2026-11-15 and 2027-02-16, all
    "up-to-date" — and rolls on 2027-10-01, stamping exactly those rows
    '2026-2027' and leaving 'Current' at zero.

So this file exists to stop the FIX, not the bug. "Tidying" those rows to
'2026-2027' by hand is the change that would actually empty the schedule: an
active-season read looks for the sentinel, so a hand-stamped fixture becomes
invisible to the season it belongs to while the rollover later stamps the
season again over nothing.

Run: python tracker/test_season_sentinel_fixtures.py   (also under pytest)
"""
import datetime as dt
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.seasons as SZ                                  # noqa: E402


def test_the_sentinel_is_the_active_season_stamp():
    """'Current' means "this season", so it is what an active-season row holds."""
    assert SZ.ACTIVE == "Current"
    assert SZ.is_current(SZ.ACTIVE)
    assert SZ.is_current(None) and SZ.is_current("")
    # A real label is NOT the active season, which is the asymmetry the whole
    # scheme rests on: stamping a live fixture '2026-2027' takes it out of the
    # active season even while 2026-2027 IS the active season.
    assert not SZ.is_current("2026-2027")


def test_an_unplayed_fixture_survives_to_the_right_label():
    """The production shape, driven through the real decision function.

    Active season 2026-2027, fixtures dated inside it wearing the sentinel.
    The rollover must do nothing until the NEXT October, then stamp them with
    the season they were played in.
    """
    stamped = []
    origA, origP, origE = SZ.active_label, SZ.rollover_plan, SZ.execute_rollover
    state = {"active": "2026-2027", "fixtures": "Current"}

    SZ.rollover_plan = lambda outgoing_label=None: {
        "returning": [], "graduating": [], "grad_year": None,
        "label": outgoing_label}

    def _roll(new_label, carry, outgoing_label=None):
        # what execute_rollover really does to `games`, in one line:
        #   UPDATE games SET season=? WHERE season='Current'
        if state["fixtures"] == SZ.ACTIVE:
            state["fixtures"] = outgoing_label
        state["active"] = new_label
        stamped.append((outgoing_label, new_label))
        return 0

    SZ.execute_rollover = _roll
    try:
        SZ.active_label = lambda: state["active"]

        # Through the whole 2026-2027 season the daily timer must do nothing —
        # the season already rolled, so there is nothing to advance to.
        for day in (dt.date(2026, 9, 12), dt.date(2026, 10, 1),
                    dt.date(2026, 11, 15), dt.date(2026, 12, 8),
                    dt.date(2027, 2, 16), dt.date(2027, 9, 30)):
            r = SZ.auto_advance_if_due(today=day)
            assert r["rolled"] is False, f"{day} rolled and must not have: {r}"
            assert state["fixtures"] == SZ.ACTIVE, \
                f"{day} relabelled a live fixture to {state['fixtures']!r}"
        assert not stamped, f"the timer touched the book: {stamped}"

        # Next October it rolls, and the fixtures take the season they were
        # actually played in — not the one that is starting.
        r = SZ.auto_advance_if_due(today=dt.date(2027, 10, 1))
        assert r["rolled"] is True and r["to"] == "2027-2028"
        assert state["fixtures"] == "2026-2027", \
            f"fixtures were stamped {state['fixtures']!r}, wanted '2026-2027'"
        assert stamped == [("2026-2027", "2027-2028")]
    finally:
        SZ.active_label, SZ.rollover_plan, SZ.execute_rollover = origA, origP, origE


def test_hand_stamping_a_live_fixture_is_what_breaks_it():
    """The counterfactual, so the docstring above is a fact and not a claim.

    Someone reading punch-list §6 as a defect 'fixes' the 23 rows to
    '2026-2027'. The rollover then has nothing matching the sentinel to stamp,
    and the rows no longer answer to the active season for the whole year they
    are live in.
    """
    state = {"active": "2026-2027", "fixtures": "2026-2027"}   # hand-stamped
    # An active-season read looks for the sentinel. The hand-stamped row is
    # not it, for the entire season the fixture is actually live in.
    assert not SZ.is_current(state["fixtures"])

    origA, origP, origE = SZ.active_label, SZ.rollover_plan, SZ.execute_rollover
    SZ.rollover_plan = lambda outgoing_label=None: {
        "returning": [], "graduating": [], "grad_year": None,
        "label": outgoing_label}

    def _roll(new_label, carry, outgoing_label=None):
        if state["fixtures"] == SZ.ACTIVE:      # never matches now
            state["fixtures"] = outgoing_label
        state["active"] = new_label
        return 0

    SZ.execute_rollover = _roll
    try:
        SZ.active_label = lambda: state["active"]
        SZ.auto_advance_if_due(today=dt.date(2027, 10, 1))
        # It lands on the same label by luck here, because the hand-stamp
        # happened to guess the right season. The damage is the year in
        # between, when the row answered to no active-season read.
        assert state["fixtures"] == "2026-2027"
    finally:
        SZ.active_label, SZ.rollover_plan, SZ.execute_rollover = origA, origP, origE


if __name__ == "__main__":
    test_the_sentinel_is_the_active_season_stamp()
    test_an_unplayed_fixture_survives_to_the_right_label()
    test_hand_stamping_a_live_fixture_is_what_breaks_it()
    print("ALL 3 CHECKS PASSED")
