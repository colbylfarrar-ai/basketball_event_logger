"""One lock ladder, and the archive opens all of it.

Two findings from the sweep meet in this file.

**§9.1 — the dangle stops in three places and nobody decided that.** The ruling
is that last season is given away whole: `default_read_season()` is 2025-2026,
`_is_past_season` calls it PAST, and every archive-bypassed read gate returns
unrestricted. Four surfaces honour that; three do not. `pages/8_Officials.py`,
`pages/14_Hall_of_Fame.py` and the Team Dashboard's Projection tab hard-stop
Free with a bare `has_paid_plan` check, while `pages/9_War_Room.py` guards
correctly with `if _is_cur_season and not has_paid_plan`. So a Free coach
browsing last season gets the Insights deck, the whole War Room and the Players
page — and is locked out of the Officiating Lab, the Hall of Fame's tracked
block and Projection.

One screen even contradicts itself: on Rankings → Team, `can_see_team_tracked`
hid the tracked rank in the header while `tracked_gate` rendered the full
tracked deep dive immediately below it, because only the second had the bypass.

**§14.2 — six copies of the same message ladder.** box_score, Rankings, Players,
War Room, `tracked_gate` itself, and the three page-level stops all re-derive
"is this Paid / banned / Solo / not-shared". Six copies is six places for the
§9.1 fix to be applied five times.

`lock_reason` is the one ladder. It takes a `scope` because the surfaces really
do differ on one axis and only one: a TEAM surface lets your own team through,
a POOL surface (Rankings, Players — whole-league aggregates) does not, because
owning a team does not buy you the league. And it takes `paid_msg` so a surface
can still name what is behind its own lock — box_score's comment is right that
"a coach who can see the box already knows what a box score is".

Run: python -m pytest tracker/test_lock_reason.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_lockreason_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
import helpers.entitlement as ENT                      # noqa: E402

DB.initialize_database()

PAST = "2020-2021"          # any label that is not the active season


@pytest.fixture(autouse=True)
def _this_modules_db():
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


FREE = {"email": "free@x", "plan": "free", "role": "coach", "team_ids": {1}}
SOLO = {"email": "solo@x", "plan": "paid", "role": "coach", "team_ids": {1},
        "shares_pool": False}
COOP = {"email": "coop@x", "plan": "paid", "role": "coach", "team_ids": {1},
        "shares_pool": True}
BANNED = {"email": "ban@x", "plan": "paid", "role": "coach", "team_ids": {1},
          "shares_pool": True, "pool_banned": True}
ADMIN = {"email": "a@x", "plan": "paid", "role": "admin"}
CURRENT = ENT._ACTIVE_SEASON


# ── the archive is open to everyone, on every surface ────────────────────────

def test_a_a_past_season_locks_nobody():
    for ident in (FREE, SOLO, BANNED, None):
        for scope in ("team", "pool"):
            assert ENT.lock_reason(ident, team_id=2, season=PAST,
                                   scope=scope) is None, (ident, scope)


def test_b_can_see_team_tracked_bypasses_the_archive_too():
    """The Rankings self-contradiction: this gate hid the tracked rank in the
    header while tracked_gate rendered the deep dive underneath it."""
    assert ENT.can_see_team_tracked(FREE, 2, season=PAST) is True
    assert ENT.can_see_team_tracked(FREE, 2, season=CURRENT) is False


def test_c_can_see_game_tracked_bypasses_the_archive_too():
    assert ENT.can_see_game_tracked(FREE, 2, 3, season=PAST) is True
    assert ENT.can_see_game_tracked(FREE, 2, 3, season=CURRENT) is False


def test_d_the_bypass_defaults_off_so_no_caller_silently_opens():
    """Both gates keep their old signature. A caller that passes no season is
    asking about the CURRENT season and must get the old answer."""
    assert ENT.can_see_team_tracked(FREE, 2) is False
    assert ENT.can_see_game_tracked(FREE, 2, 3) is False


# ── the ladder, in the current season ────────────────────────────────────────

def test_e_free_gets_the_paid_message():
    assert ENT.lock_reason(FREE, team_id=2, season=CURRENT) == ENT.MSG_PAID


def test_f_a_surface_can_name_what_is_behind_its_own_lock():
    mine = "🔒 Tracked league analytics are a **Paid** feature."
    assert ENT.lock_reason(FREE, team_id=2, season=CURRENT,
                           paid_msg=mine) == mine


def test_g_moderation_outranks_the_co_op_invite():
    """A banned coach gets the suspension notice, not an invite they cannot
    act on. This is the B3 ruling and it must survive the consolidation."""
    assert ENT.lock_reason(BANNED, team_id=2, season=CURRENT,
                           scope="pool") == ENT.MSG_POOL_BANNED


def test_h_a_solo_paid_coach_gets_the_co_op_invite_on_a_pool_surface():
    assert ENT.lock_reason(SOLO, team_id=None, season=CURRENT,
                           scope="pool") == ENT.MSG_COOP_INVITE


def test_i_own_team_passes_a_team_surface_but_not_a_pool_surface():
    """The one axis the six copies actually differed on. Owning a team does not
    buy you the league."""
    assert ENT.lock_reason(SOLO, team_id=1, season=CURRENT,
                           scope="team") is None
    assert ENT.lock_reason(SOLO, team_id=1, season=CURRENT,
                           scope="pool") == ENT.MSG_COOP_INVITE


def test_j_admin_has_zero_gate():
    for scope in ("team", "pool"):
        assert ENT.lock_reason(ADMIN, team_id=999, season=CURRENT,
                               scope=scope) is None


def test_k_a_co_op_coach_clears_a_pool_surface():
    assert ENT.lock_reason(COOP, team_id=None, season=CURRENT,
                           scope="pool") is None


# ── tracked_gate keeps its contract while delegating ─────────────────────────

def test_l_tracked_gate_still_returns_nothing_for_a_team_with_no_data():
    assert ENT.tracked_gate(COOP, 2, False, season=CURRENT) == (False, None)


def test_m_tracked_gate_agrees_with_the_ladder_it_now_delegates_to():
    for ident in (FREE, SOLO, COOP, BANNED, ADMIN):
        vis, msg = ENT.tracked_gate(ident, 1, True, season=CURRENT)
        assert msg == ENT.lock_reason(ident, 1, CURRENT, scope="team")
        assert vis is (msg is None)
