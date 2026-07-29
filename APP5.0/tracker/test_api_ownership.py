"""Per-game authorization on the tracker API.

current_api_user proves you hold a Paid plan; it never said WHICH games are
yours. Before this gate a valid token was a league-wide master key — any paying
coach could read, rewrite, finish or publish any other coach's tracked game over
HTTP, straight past the Streamlit co-op gate (which guards only the in-app read
path). These tests pin the rule from both sides, because both directions matter:

  * another coach's claimed game must be REFUSED (the hole), and
  * an UNCLAIMED game must stay writable (track-to-scout is the product, not an
    attack — opponent-tracking a game you are not playing in is normal, and the
    first writer claims it via games.tracked_by).

Hermetic: own temp DB, seeded rows, no network. Run:
    python tracker/test_api_ownership.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_apiown_test_")
sys.path.insert(0, str(_APP))

from database.db import execute, query          # noqa: E402
import helpers.entitlement as ENT               # noqa: E402
import tracker.api as API                       # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed: two coaches, two teams, four games ──────────────────────────────────
execute("INSERT INTO teams (id, name, gender, class) VALUES (1,'Alpha','F','3A')")
execute("INSERT INTO teams (id, name, gender, class) VALUES (2,'Bravo','F','3A')")
execute("INSERT INTO teams (id, name, gender, class) VALUES (3,'Delta','F','3A')")

for email, tid in (("ann@x.com", 1), ("bob@x.com", 2)):
    execute("INSERT INTO app_users (email, role, plan, team_id) VALUES (?,?,?,?)",
            (email, "coach", "paid", tid))
    execute("INSERT OR IGNORE INTO coach_teams (coach_email, team_id) VALUES (?,?)",
            (email, tid))

# 10 = Bob's own claimed game, Ann not in it   -> Ann must be refused
# 11 = unclaimed game between two other teams  -> Ann may claim it (opponent scout)
# 12 = Bob claimed it, but Ann's team plays in it -> Ann may write (her own team)
# 13 = Bob's claimed game, pooled              -> Ann may READ if league-wide
execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked, tracked_by) "
        "VALUES (10, 2, 3, '2026-01-05', 'Current', 1, 'bob@x.com')")
execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked, tracked_by) "
        "VALUES (11, 2, 3, '2026-01-06', 'Current', 0, '')")
execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked, tracked_by) "
        "VALUES (12, 1, 2, '2026-01-07', 'Current', 1, 'bob@x.com')")
execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked, tracked_by, in_pool) "
        "VALUES (13, 2, 3, '2026-01-08', 'Current', 1, 'bob@x.com', 1)")

ANN = ENT.gating_identity(query(
    "SELECT email, role, plan, paid_until, team_id, pool_banned "
    "FROM app_users WHERE email='ann@x.com'")[0])
ADMIN = {"email": "root@x.com", "role": "admin", "plan": "paid",
         "team_id": None, "team_ids": [], "shares_pool": 1, "pool_banned": 0}


def g(gid):
    return API._game_row(gid)


print("-- the identity the API resolves carries what the gates read ---------")

ok(ANN["team_ids"] == [1],
   "gating_identity pulls team_ids from coach_teams (not just the legacy team_id)")
ok(ENT._own_teams(ANN) == {1},
   "so _own_teams sees her real team set")
ok(ANN["shares_pool"] == 0,
   "and shares_pool defaults Solo until a team opts in")


print("\n-- writes: another coach's game is refused --------------------------")

ok(not API._may_write_game(ANN, g(10)),
   "Ann may NOT write Bob's claimed game — this is the league-wide master key, closed")
ok(API._may_write_game(ANN, g(11)),
   "an UNCLAIMED game stays writable: track-to-scout survives the gate")
ok(API._may_write_game(ANN, g(12)),
   "and a game HER OWN team plays in is writable even though Bob logged it")
ok(API._may_write_game(ADMIN, g(10)),
   "admin still writes anything")


print("\n-- reads: co-op decides what writing does not ------------------------")

ok(not API._may_read_game(ANN, g(10)),
   "a Solo coach cannot read another coach's un-pooled game")
ok(not API._may_read_game(ANN, g(13)),
   "nor a POOLED game while she is Solo — the co-op is reciprocal")

execute("UPDATE teams SET shares_pool=1 WHERE id=1")
ANN_LW = ENT.gating_identity(query(
    "SELECT email, role, plan, paid_until, team_id, pool_banned "
    "FROM app_users WHERE email='ann@x.com'")[0])
ok(ANN_LW["shares_pool"] == 1,
   "once her team opts in the identity reports League-wide")
ok(API._may_read_game(ANN_LW, g(13)),
   "and then she may READ the pooled game (share to scout)")
ok(not API._may_read_game(ANN_LW, g(10)),
   "but Bob's UN-pooled game stays private even to a league-wide coach")
ok(not API._may_write_game(ANN_LW, g(13)),
   "reading a pooled game never grants writing it")


print("\n-- a past season is an open archive (retro tracking) -----------------")

execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked, tracked_by) "
        "VALUES (14, 2, 3, '2025-01-05', '2024-2025', 1, 'bob@x.com')")
ok(API._may_read_game(ANN, g(14)),
   "last season's games are readable by everyone (the owner's archive rule)")
ok(not API._may_write_game(ANN, g(14)),
   "but the archive is READ-only — Ann still cannot rewrite Bob's past game")


print("\n-- the guest link is scoped to its owner, not to the league ----------")

# A guest token resolves to its owner coach, so it reaches exactly the owner's
# games. Previously `undo` took only current_api_user, making an assistant
# scorer link a league-wide delete token with no expiry.
GUEST_OF_ANN = dict(ANN, guest=True)
ok(not API._may_write_game(GUEST_OF_ANN, g(10)),
   "Ann's assistant cannot undo Bob's game")
ok(API._may_write_game(GUEST_OF_ANN, g(12)),
   "but can still score the game Ann's team is playing")

# ── and a PINNED link narrows further, to a single game ──────────────────────
# Owner-scoping still leaves an assistant the owner's whole season. A link
# issued for one game now carries that game_id and reaches nothing else, so a
# parent helping at one tournament is not handed the rest of the year.
from fastapi import HTTPException                # noqa: E402

PINNED = dict(ANN, guest=True, guest_game_id=12)
UNPINNED = dict(ANN, guest=True, guest_game_id=None)


def _gate_raises(user, game_id):
    try:
        API._guest_game_gate(user, game_id)
        return False
    except HTTPException as exc:
        return exc.status_code == 403


ok(not _gate_raises(PINNED, 12), "a pinned link opens the game it was issued for")
# game 11 is unclaimed, so ownership alone WOULD let Ann's assistant write it —
# which is exactly why the pin has to be a separate check
ok(API._may_write_game(PINNED, g(11)), "ownership alone would allow game 11")
ok(_gate_raises(PINNED, 11),
   "but the pin refuses it — narrowing INSIDE the owner's own reach is the point")
ok(not _gate_raises(UNPINNED, 11),
   "an UNPINNED link keeps that owner-wide reach — that is what every link "
   "issued before the column existed was handed out as, so narrowing them "
   "retroactively would break an assistant mid-season")
ok(not _gate_raises(dict(ANN, guest=False, guest_game_id=12), 11),
   "the pin applies to guests only; a real coach's own token is unaffected")

# the pin is enforced on top of ownership, never instead of it
ok(not API._may_write_game(PINNED, g(10)),
   "a pinned link still cannot reach Bob's game either")


print("\n-- every game-scoped route actually declares a gate ------------------")

_src = (_APP / "tracker" / "api.py").read_text(encoding="utf-8")
import re                                        # noqa: E402


def _signature_at(src, pos):
    """Full def signature starting at `pos`, balancing parens — a naive
    `[^)]*` stops inside `Body(None)` and reports a gated route as ungated."""
    start = src.index("(", pos)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[pos:i + 1]
    raise AssertionError("unbalanced signature")


_routes = []
for m in re.finditer(r'@api\.(?:get|post|put|delete)\("(/games/\{game_id\}[^"]*)"\)\s*\n',
                     _src):
    _routes.append((m.group(1), _signature_at(_src, m.end())))
ok(len(_routes) >= 16, f"found {len(_routes)} game-scoped routes to check")
_ungated = [r for r, sig in _routes if "require_game_" not in sig]
ok(not _ungated,
   f"all {len(_routes)} game-scoped routes depend on a require_game_* gate"
   + (f" — MISSING: {_ungated}" if _ungated else ""))


print(f"\nALL {PASS} CHECKS PASSED")
