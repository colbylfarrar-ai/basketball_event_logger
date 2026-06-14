"""
Tests for helpers/game_dedup.py against a THROWAWAY DB.
Run: python tracker/test_game_dedup.py

Proves the core promise: when one real game is tracked twice, the MORE DETAILED
track wins even if the other logged MORE events; an admin override can pin either
one; and a non-duplicated set passes through untouched.

Uses fresh high-id teams + a far-future date so the seeded stale DB can't collide.
Assertions are membership/explicit-id based (like test_seasons / test_entitlement).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_dedup_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query          # noqa: E402
import helpers.game_dedup as GD                  # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── fixtures ──────────────────────────────────────────────────────────────────
A = execute("INSERT INTO teams (name,class,gender) VALUES ('DedupA','3A','F')")
B = execute("INSERT INTO teams (name,class,gender) VALUES ('DedupB','3A','F')")
p1 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (A, "P1", 1))
p2 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (A, "P2", 2))
p3 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (B, "P3", 3))
off = execute("INSERT INTO officials (name,official_id) VALUES ('Ref',900001)")

DATE = "2099-12-25"


def _game():
    return execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,in_pool) "
                   "VALUES (?,?,?,1,'Current',1)", (A, B, DATE))


# Full set of game_events columns we may populate.
_COLS = ("game_id", "event_type", "quarter", "time", "primary_player_id",
         "shot_result", "shot_type", "shot_x", "shot_y", "pass_from_id",
         "shot_created_by_id", "guarded_by_id", "rebound_by_id", "stolen_by_id",
         "official_id")


def _ev(game_id, event_type, **kw):
    row = {c: None for c in _COLS}
    row.update(game_id=game_id, event_type=event_type,
               quarter=kw.pop("quarter", 1), time=kw.pop("time", "8:00"))
    row.update(kw)
    ph = ",".join("?" * len(_COLS))
    execute(f"INSERT INTO game_events ({','.join(_COLS)}) VALUES ({ph})",
            tuple(row[c] for c in _COLS))


# g_rich: 4 events, every applicable detail field filled.
g_rich = _game()
_ev(g_rich, "shot", primary_player_id=p1, shot_result="make", shot_type=2,
    shot_x=10.0, shot_y=5.0, shot_created_by_id=p2, guarded_by_id=p3)
_ev(g_rich, "shot", primary_player_id=p1, shot_result="miss", shot_type=3,
    shot_x=20.0, shot_y=8.0, pass_from_id=p2, guarded_by_id=p3, rebound_by_id=p2)
_ev(g_rich, "turnover", primary_player_id=p1, stolen_by_id=p3, guarded_by_id=p3)
_ev(g_rich, "foul", primary_player_id=p3, official_id=off, guarded_by_id=p1)

# g_bare: 6 events (MORE), only the required columns — no detail at all.
g_bare = _game()
for _ in range(3):
    _ev(g_bare, "shot")
_ev(g_bare, "shot")
_ev(g_bare, "turnover")
_ev(g_bare, "foul")

# g_other: a different matchup (different date) — must never collapse with the pair.
g_other = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,in_pool) "
                  "VALUES (?,?,?,1,'Current',1)", (A, B, "2099-12-26"))
_ev(g_other, "shot", primary_player_id=p1, shot_result="make", shot_type=2,
    shot_x=1.0, shot_y=1.0)

# ── detail score ────────────────────────────────────────────────────────────
print("detail_scores")
sc = GD.detail_scores([g_rich, g_bare])
ok(sc[g_rich]["events"] == 4 and sc[g_bare]["events"] == 6, "event counts (bare has MORE)")
ok(sc[g_rich]["score"] > sc[g_bare]["score"], "rich game scores higher despite fewer events")
ok(sc[g_bare]["score"] == 0.0, "bare game has zero detail score")

# ── matchup key ───────────────────────────────────────────────────────────────
print("matchup_key")
ok(GD.matchup_key(DATE, A, B) == GD.matchup_key(DATE, B, A), "home/away-agnostic key")
ok(GD.matchup_key(DATE, A, B) != GD.matchup_key("2099-12-26", A, B), "date distinguishes")

# ── representative pick ─────────────────────────────────────────────────────
print("representative_game_ids")
ok(GD.representative_game_ids({g_rich}) == {g_rich}, "single id passes through")
ok(GD.representative_game_ids({g_rich, g_bare}) == {g_rich},
   "duplicate matchup collapses to the more DETAILED game (not the higher event count)")
ok(GD.representative_game_ids({g_rich, g_bare, g_other}) == {g_rich, g_other},
   "different matchup is preserved; only the dup collapses")

# ── admin override ────────────────────────────────────────────────────────────
print("admin override")
key = GD.matchup_key(DATE, A, B)
GD.set_override(key, g_bare)
ok(GD.representative_game_ids({g_rich, g_bare}) == {g_bare},
   "override pins the chosen game even though it's less detailed")
GD.clear_override(key)
ok(GD.representative_game_ids({g_rich, g_bare}) == {g_rich},
   "clearing the override reverts to the auto most-detailed pick")

# ── admin listing ─────────────────────────────────────────────────────────────
print("duplicate_matchups")
dups = {d["key"]: d for d in GD.duplicate_matchups()}
ok(key in dups, "our double-tracked matchup is listed")
mine = dups[key]
ok(mine["candidates"][0]["game_id"] == g_rich, "candidates sorted best (most detailed) first")
ok({c["game_id"] for c in mine["candidates"]} == {g_rich, g_bare}, "both tracks listed")
ok(mine["override"] is None, "no override after clear")

# ── entitlement wiring (the canonical pick reaches the pool read-filter) ──────
print("entitlement.pooled_game_ids collapses duplicates")
import helpers.entitlement as ENT             # noqa: E402
pooled = ENT.pooled_game_ids()
ok(g_rich in pooled and g_bare not in pooled,
   "pooled_game_ids surfaces only the canonical (detailed) track of the dup")
ok(g_other in pooled, "the non-duplicated pooled game is still present")

print(f"\nALL {PASS} CHECKS PASSED")
