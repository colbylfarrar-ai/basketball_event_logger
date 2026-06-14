"""
Smoke test for helpers/entitlement.py — PER-COACH binary co-op reciprocity,
against a THROWAWAY DB. Run: python tracker/test_entitlement.py

Model under test (two axes):
  AXIS 1  Free vs Paid (has_paid_plan): box = Free; tracked depth = Paid.
  AXIS 2  Solo vs League-wide (TEAM-LEVEL teams.shares_pool, default Solo):
            Solo       → full depth on your OWN games only; private; no pool.
            League-wide→ the team's games join the pool AND every coach on the team
                         scouts every pooled team.
          A game is pooled iff its logging coach's TEAM (games.tracked_by -> the
          coach's team) is League-wide — denormalized onto games.in_pool by
          recompute_game_pool(). The identity dict's `shares_pool` carries the
          viewer's team flag (resolved by helpers.auth).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_ent_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query             # noqa: E402
import helpers.entitlement as E                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── fixtures: 4 teams, 4 coaches (Solo / League-wide / Free), 4 tracked games ───
A = execute("INSERT INTO teams (name,class,gender) VALUES ('A','3A','F')")
B = execute("INSERT INTO teams (name,class,gender) VALUES ('B','3A','F')")
C = execute("INSERT INTO teams (name,class,gender) VALUES ('C','3A','F')")
D = execute("INSERT INTO teams (name,class,gender) VALUES ('D','3A','F')")
Ee = execute("INSERT INTO teams (name,class,gender) VALUES ('E','3A','F')")

# coaches: a@x = Paid Solo (team A); b@x = Paid League-wide (team B);
# d@x = Paid League-wide (team D); f@x = Free (team A).
for email, team, plan, share in [("a@x", A, "paid", 0), ("b@x", B, "paid", 1),
                                 ("d@x", D, "paid", 1), ("f@x", A, "free", 0)]:
    execute("INSERT INTO app_users (email, role, name, team_id, plan, shares_pool) "
            "VALUES (?,?,?,?,?,?)", (email, "coach", "", team, plan, share))

# coach_teams is the source of truth for membership / pooling (multi-team). Seed
# it to mirror each coach's single team here (tests insert app_users directly).
for email, team in [("a@x", A), ("b@x", B), ("d@x", D), ("f@x", A)]:
    execute("INSERT INTO coach_teams (coach_email, team_id) VALUES (?,?)",
            (email, team))

# Team-level co-op is the canonical flag: a team is League-wide iff any of its
# coaches opted in. Here teams B and D are League-wide (b@x / d@x); A and C/E Solo.
execute("UPDATE teams SET shares_pool=1 WHERE id IN (?,?)", (B, D))


def _game(t1, t2, by):
    gid = execute("INSERT INTO games (team1_id,team2_id,date,home_score,away_score,"
                  "tracked,tracked_by) VALUES (?,?, '2026-01-01', 50,40, 1, ?)",
                  (t1, t2, by))
    return gid


g1 = _game(A, C, "a@x")   # A's own game, logged Solo          → NOT pooled
g2 = _game(B, C, "b@x")   # B logged League-wide               → pooled (B & C visible)
g3 = _game(B, D, "d@x")   # D logged League-wide (scout-game)  → pooled
g4 = _game(C, Ee, "")     # legacy / app-logged, no coach       → NOT pooled

# Derive games.in_pool from each game's logging coach (the read-path teeth).
E.recompute_game_pool()

admin = {"role": "admin", "plan": "free", "team_id": None, "shares_pool": 0}
free = {"role": "coach", "plan": "free", "team_id": A, "shares_pool": 0}
solo = {"role": "coach", "plan": "paid", "team_id": A, "shares_pool": 0}   # Paid Solo
lw = {"role": "coach", "plan": "paid", "team_id": B, "shares_pool": 1}     # Paid League-wide
lwD = {"role": "coach", "plan": "paid", "team_id": D, "shares_pool": 1}    # Paid League-wide

print("has_paid_plan")
ok(E.has_paid_plan(admin), "admin counts as paid")
ok(E.has_paid_plan(solo), "paid plan counts")
ok(not E.has_paid_plan(free), "free is not paid")
ok(not E.has_paid_plan(None), "no identity -> not paid")
ok(E.has_paid_plan({"role": "coach", "plan": "free", "paid_until": "2999-01-01"}),
   "future paid_until counts")
ok(not E.has_paid_plan({"role": "coach", "plan": "free", "paid_until": "2000-01-01"}),
   "past paid_until fails")

print("recompute_game_pool -> games.in_pool")
ok(E.pooled_game_ids() == {g2, g3}, "pooled games = league-wide-logged {g2,g3}")
ok(query("SELECT in_pool FROM games WHERE id=?", (g1,))[0]["in_pool"] == 0,
   "Solo coach's game is NOT pooled")
ok(query("SELECT in_pool FROM games WHERE id=?", (g4,))[0]["in_pool"] == 0,
   "legacy/app-logged game (no coach) is NOT pooled")

print("viewer_is_league_wide (the per-coach toggle)")
ok(E.viewer_is_league_wide(admin), "admin always league-wide")
ok(E.viewer_is_league_wide(lw), "shares_pool=1 -> league-wide")
ok(not E.viewer_is_league_wide(solo), "Paid Solo -> not league-wide")
ok(not E.viewer_is_league_wide(free), "Free Solo -> not league-wide")
ok(not E.viewer_is_league_wide(None), "no identity -> not league-wide")
ok(E.viewer_in_pool is E.viewer_is_league_wide, "viewer_in_pool back-compat alias")

print("team_has_pooled_tracked")
ok(not E.team_has_pooled_tracked(A), "team A (Solo games only) has no pooled depth")
ok(E.team_has_pooled_tracked(B), "team B is in a pooled game")
ok(E.team_has_pooled_tracked(C), "team C visible via the pooled B-vs-C game")
ok(E.team_has_pooled_tracked(D), "team D visible via the pooled scout-game")

print("can_see_team_tracked (Paid AND (own OR league-wide))")
ok(E.can_see_team_tracked(admin, C), "admin sees any team's tracked")
ok(not E.can_see_team_tracked(free, A), "free can't see even own tracked")
ok(E.can_see_team_tracked(solo, A), "Paid Solo sees OWN team")
ok(not E.can_see_team_tracked(solo, B), "Paid Solo can't scout another team")
ok(E.can_see_team_tracked(lw, B), "Paid League-wide sees own team")
ok(E.can_see_team_tracked(lw, C), "Paid League-wide may scout any team (data decides)")
ok(E.can_see_team_tracked(lwD, A), "Paid League-wide passes coarse gate even for a Solo team")

print("visible_tracked_game_ids (the read-filter teeth)")
ok(E.visible_tracked_game_ids(admin) is None, "admin -> unrestricted (None)")
ok(E.visible_tracked_game_ids(solo) == {g1}, "Paid Solo -> own games only, no pool")
ok(E.visible_tracked_game_ids(lw) == {g2, g3}, "League-wide -> own + pooled")
ok(E.visible_tracked_game_ids(lwD) == {g2, g3}, "League-wide D -> own(g3) + pooled")
ok(E.visible_tracked_game_ids(free) == {g1}, "Free -> own set (depth gated elsewhere)")
ok(E.visible_tracked_game_ids(None) == set(), "no identity -> empty set")

print("can_see_game_tracked (per-game, in_pool aware)")
ok(E.can_see_game_tracked(admin, A, C, in_pool=0), "admin sees any game")
ok(not E.can_see_game_tracked(free, B, C, in_pool=1), "free sees no game's depth")
ok(E.can_see_game_tracked(solo, A, C, in_pool=0), "Paid Solo sees their OWN game (any pool)")
ok(not E.can_see_game_tracked(solo, B, C, in_pool=1), "Paid Solo can't open another game")
ok(not E.can_see_game_tracked(lwD, A, C, in_pool=0),
   "scout can't open a Solo coach's non-pooled game (the teeth)")
ok(E.can_see_game_tracked(lwD, B, C, in_pool=1), "scout opens a pooled game")
ok(E.can_see_game_tracked(lw, B, D, in_pool=1), "League-wide sees own-team game")

print("tracked_gate (3 messages: Paid / co-op invite / not-shared)")
vis, msg = E.tracked_gate(free, A, True)
ok(not vis and "Paid" in msg, "free -> Paid-feature message")
vis, msg = E.tracked_gate(solo, A, True)
ok(vis and msg is None, "Paid Solo, OWN team -> visible")
vis, msg = E.tracked_gate(solo, B, True)
ok(not vis and "Co-op" in msg and "Solo" in msg, "Paid Solo scouting -> co-op INVITE")
vis, msg = E.tracked_gate(lwD, B, True)
ok(vis and msg is None, "League-wide scouting a pooled team -> visible")
vis, msg = E.tracked_gate(lwD, A, True)
ok(not vis and "hasn't shared" in msg, "League-wide scouting a non-pooled team -> neutral")
vis, msg = E.tracked_gate(lwD, D, True)
ok(vis and msg is None, "League-wide, OWN team -> visible")
vis, msg = E.tracked_gate(admin, A, True)
ok(vis and msg is None, "admin always visible")
vis, msg = E.tracked_gate(free, A, False)
ok(not vis and msg is None, "no tracked data -> no lock message (own note)")

print("recompute_game_pool is season-locked + monotonic (share to scout)")
execute("UPDATE teams SET shares_pool=1 WHERE id=?", (A,))
E.recompute_game_pool()
ok(g1 in E.pooled_game_ids(), "team A went League-wide -> g1 shared into the pool")
execute("UPDATE teams SET shares_pool=0 WHERE id=?", (A,))
E.recompute_game_pool()
ok(g1 in E.pooled_game_ids(),
   "team A back to Solo -> g1 STAYS pooled (season-locked, no retroactive un-share)")
# a NEW game logged while Solo is private — going Solo stops FUTURE sharing
g_solo = _game(A, C, "a@x")
E.recompute_game_pool(g_solo)
ok(g_solo not in E.pooled_game_ids(),
   "game logged while Solo is NOT pooled (future sharing stopped)")
# flipping the team back to League-wide shares the held-back game (their choice)
execute("UPDATE teams SET shares_pool=1 WHERE id=?", (A,))
E.recompute_game_pool()
ok(g_solo in E.pooled_game_ids(), "Solo -> League-wide shares the held-back game")

print("admin pool ban (moderation override)")
# b@x is Paid League-wide (team B); g2 (B-vs-C, tracked_by b@x) is pooled.
b_banned = {"role": "coach", "plan": "paid", "team_id": B,
            "shares_pool": 1, "pool_banned": 1}
ok(E.is_pool_banned(b_banned), "is_pool_banned true for a banned coach")
ok(not E.is_pool_banned(lw), "non-banned league-wide coach not flagged")
ok(not E.is_pool_banned(admin), "admin can't be banned")
ok(not E.viewer_is_league_wide(b_banned),
   "banned coach is NOT league-wide (forced Solo) even with shares_pool=1")
ok(E.can_see_team_tracked(b_banned, B), "banned coach STILL sees their OWN team")
ok(not E.can_see_team_tracked(b_banned, C), "banned coach can't scout the pool")
_vis, _msg = E.tracked_gate(b_banned, C, True)
ok(not _vis and "suspended" in _msg.lower(), "banned coach scouting -> suspension notice")
# DB-level purge: ban b@x, recompute -> their pooled games leave (overrides stickiness)
execute("UPDATE app_users SET pool_banned=1 WHERE email='b@x'")
E.recompute_game_pool()
ok(g2 not in E.pooled_game_ids(), "ban purges the coach's game from the pool")
ok(g3 in E.pooled_game_ids(), "another coach's pooled game is unaffected by the ban")
# unban restores per their shares_pool
execute("UPDATE app_users SET pool_banned=0 WHERE email='b@x'")
E.recompute_game_pool()
ok(g2 in E.pooled_game_ids(), "unban re-shares the coach's games")

print("multi-team staffing + dual-staff coupling")
import helpers.auth as AU                                       # noqa: E402
PB = execute("INSERT INTO teams (name,class,gender) VALUES ('ZZTest Boys','3A','M')")
PG = execute("INSERT INTO teams (name,class,gender) VALUES ('ZZTest Girls','3A','F')")
execute("INSERT INTO app_users (email, role, name, plan) "
        "VALUES ('p@x','coach','','paid')")
AU.set_teams("p@x", [PB, PG])
ok(sorted(AU.get_teams("p@x")) == sorted([PB, PG]),
   "coach can staff BOTH teams of one school")
p_ident = {"role": "coach", "plan": "paid", "team_ids": [PB, PG], "shares_pool": 0}
ok(E.can_see_team_tracked(p_ident, PB) and E.can_see_team_tracked(p_ident, PG),
   "dual coach sees OWN depth for BOTH teams")
ok(not AU.get_team_shares_pool(PB) and not AU.get_team_shares_pool(PG),
   "dual coach's teams start Solo")
AU.set_team_shares_pool(PB, True)
ok(AU.get_team_shares_pool(PB) and AU.get_team_shares_pool(PG),
   "coupling: one gender in the pool -> BOTH in the pool")
gPG = _game(PG, C, "p@x")
E.recompute_game_pool(gPG)
ok(gPG in E.pooled_game_ids(),
   "dual coach's girls game pools once the school is coupled League-wide")
AU.set_shares_pool("p@x", False)
ok(not AU.get_team_shares_pool(PB) and not AU.get_team_shares_pool(PG),
   "turning the coach Solo moves BOTH teams to Solo")
# a single-gender coach is unaffected by coupling (only their own team)
ok(not AU.get_team_shares_pool(C), "an unrelated team is untouched by coupling")

print(f"\nALL {PASS} CHECKS PASSED")
