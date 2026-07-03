"""
entitlement.py — coach-tier gating across TWO independent axes.

AXIS 1 — DEPTH (Free vs Paid). Box score + final results are Free and visible to
everyone, always. Event-logger ("tracked") play-by-play depth — shot charts,
lineups, four factors, scouting — is Paid. `has_paid_plan()` is that gate.
Source-of-truth for which stats are depth: player_ratings.EVENT_DERIVED_STATS +
box_score.box_only_table(). See memory [[app5-gating-taxonomy]].

AXIS 2 — SHARING (the TEAM-LEVEL Coaches' Co-op toggle, teams.shares_pool,
DEFAULT 0 = Solo/private). A program is one unit: if any coach on a team opts in,
the whole team is League-wide. A coach's effective status = their team's flag
(carried on the identity dict as `shares_pool`). RECIPROCAL and binary:
  • SOLO (off):  full depth on your team's OWN games; your depth stays PRIVATE
                 (others see only your box score); you do NOT scout the pool.
  • LEAGUE-WIDE (on): your team's tracked games join the shared pool (other co-op
                 coaches scout them) AND every coach on the team scouts the ENTIRE
                 pool — every league-wide team, no per-team friction. Share to scout.

READ RULES enforced here:
  • box / results            — everyone, always (not gated here; box_only path).
  • your OWN tracked depth    — any Paid coach, always (Solo or League-wide).
  • another team's depth      — only if YOU are League-wide AND that game is
                                pooled (its logging coach's team is League-wide).
  admin / local owner         — everything (treated League-wide + Paid).

A Paid League-wide coach is NEVER told "you can't scout team X": a team with no
pooled tracked games simply renders neutral ("hasn't shared tracked data" — their
privacy choice). The ONLY gate on a Paid coach's scouting is their own Solo
toggle, surfaced as an INVITE to go League-wide (not a denial).

`games.in_pool` is the denormalized truth for "is this game pooled" (recomputed
from the logging coach's TEAM shares_pool at finish, on a toggle flip, and via
recompute_game_pool()). Streamlit-free + pure so it stays unit-testable headless;
the viewer identity dict is what helpers.auth.current_user() returns
({'email','role','plan','paid_until','team_id','shares_pool', ...}), where
`shares_pool` is the viewer's TEAM flag.
"""
from __future__ import annotations

from datetime import date

from database.db import query, execute
import helpers.game_dedup as GD

# The active-season sentinel (mirrors helpers.seasons.ACTIVE; kept local so this
# gating module has no import cycle). A PAST season is an OPEN ARCHIVE — the co-op
# / Paid depth gates below all bypass it (owner rule: last year's data is public,
# full depth, to everyone; no competitive edge left to protect).
_ACTIVE_SEASON = "Current"


def _is_past_season(season) -> bool:
    return season not in (None, "", _ACTIVE_SEASON)


# ── lock / invite copy (one source so it stays consistent across surfaces) ──────
MSG_PAID = ("🔒 Tracked analytics — shot charts, lineups, four factors and "
            "scouting — are a **Paid** feature. Upgrade to unlock.")
MSG_FREE_DEMO = ("🎁 Your **first game is free** to try — open it to see the live "
                 "box score, shot chart and win-probability light up. Upgrade to "
                 "unlock tracked depth on every game.")
MSG_COOP_INVITE = ("🔒 You're in **Solo** mode. Join the **Coaches' Co-op** in "
                   "Settings to scout every league-wide team — your tracked games "
                   "join the shared pool and you scout the whole pool in return. "
                   "Share to scout.")
MSG_NOT_SHARED = ("This team hasn't shared its tracked data with the Coaches' "
                  "Co-op — only box-score views are available.")
MSG_POOL_BANNED = ("🔒 Your **Coaches' Co-op** access is currently suspended by the "
                   "admin — your tracked games are private and the pool is hidden. "
                   "You still have full depth on your own team. Contact the admin to "
                   "restore access.")


def has_paid_plan(ident: dict | None) -> bool:
    """Viewer holds a Paid plan (AXIS 1). Admin always qualifies; a future
    paid_until counts even if the plan text still says 'free' (the Stripe poll
    writes the date)."""
    if not ident:
        return False
    if ident.get("role") == "admin":
        return True
    if ident.get("plan") == "paid":
        return True
    pu = (ident.get("paid_until") or "").strip()
    if pu:
        try:
            return pu >= date.today().isoformat()
        except Exception:
            return False
    return False


def is_pool_banned(ident: dict | None) -> bool:
    """Admin moderation flag: this coach is suspended from the Coaches' Co-op
    (app_users.pool_banned). Admin / local owner can't be banned."""
    if not ident or ident.get("role") == "admin":
        return False
    return bool(ident.get("pool_banned"))


def viewer_is_league_wide(ident: dict | None) -> bool:
    """Is this coach in the Coaches' Co-op — sharing into AND scouting the pool?
    Reads the TEAM-level reciprocity switch carried on the identity as
    `shares_pool` (helpers.auth resolves it from teams.shares_pool for the coach's
    team). Admin / local owner always qualifies. A coach the admin has BANNED
    (pool_banned) is forced out regardless of the team toggle. AXIS 2 — independent
    of plan; compose with has_paid_plan for any scouting gate."""
    if not ident:
        return False
    if ident.get("role") == "admin":
        return True
    return bool(ident.get("shares_pool")) and not is_pool_banned(ident)


# Back-compat alias.
viewer_in_pool = viewer_is_league_wide


def pooled_game_ids(season="Current") -> set[int]:
    """Tracked game ids in the shared pool (games.in_pool = 1) — the read-filter
    candidate set for every LEAGUE-WIDE tracked aggregation. Duplicate tracks of
    the same real game are collapsed to one canonical (most-detailed / admin-pinned)
    row so the pool never double-counts or shows two stat lines — see game_dedup.
    `season` defaults to the active season; in_pool is frozen at rollover, so an
    archived label returns exactly what was shared THAT season (no leak)."""
    return GD.representative_game_ids(
        {r["id"] for r in query(
            "SELECT id FROM games WHERE in_pool=1 AND season=?", (season,))})


def pool_team_ids() -> set[int]:
    """Teams that field ≥1 pooled tracked game (derived from games.in_pool). Kept
    for legacy callers / display only — per-coach gating no longer keys on a
    team-level pool flag."""
    return {r["id"] for r in query(
        "SELECT DISTINCT t.id FROM teams t JOIN games g "
        "ON g.in_pool=1 AND (g.team1_id=t.id OR g.team2_id=t.id)")}


def _own_teams(ident: dict | None) -> set:
    """Every team the viewer staffs (multi-team). Reads identity['team_ids'] (set
    by auth.require_login), falling back to the legacy single team_id."""
    if not ident:
        return set()
    ids = ident.get("team_ids")
    if ids:
        return {int(t) for t in ids if t is not None}
    t = ident.get("team_id")
    return {int(t)} if t is not None else set()


def team_has_pooled_tracked(team_id, season="Current") -> bool:
    """Does this team appear in ≥1 pooled tracked game (its depth is share-to-scout
    visible to any league-wide coach) in `season`?"""
    if team_id is None:
        return False
    rows = query("SELECT 1 FROM games WHERE in_pool=1 AND tracked=1 "
                 "AND season=? AND (team1_id=? OR team2_id=?) LIMIT 1",
                 (season, team_id, team_id))
    return bool(rows)


def can_see_team_tracked(ident: dict | None, team_id, pool=None) -> bool:
    """May this viewer see TRACKED depth for `team_id`? Paid AND (own team OR
    League-wide). The DATA read-filter decides WHICH games actually render — a
    non-pooled team just comes back empty/neutral, never a hard denial. `pool` is
    accepted-but-ignored (legacy signature)."""
    if not has_paid_plan(ident):
        return False
    if ident.get("role") == "admin":
        return True
    if team_id is not None and int(team_id) in _own_teams(ident):
        return True
    return viewer_is_league_wide(ident)


def can_see_game_tracked(ident: dict | None, team1_id, team2_id,
                         pool=None, *, in_pool=None) -> bool:
    """May this viewer open a tracked GAME's depth (it reveals both teams)? Paid
    AND (own team is in it OR (League-wide AND the game is pooled)). Pass `in_pool`
    for a specific game; without it, fall back to whether either team has any
    pooled tracked data (used where no single game is in scope, e.g. a matchup
    projection drawn from both teams' tracked ratings)."""
    if not has_paid_plan(ident):
        return False
    if ident.get("role") == "admin":
        return True
    own = _own_teams(ident)
    if (team1_id is not None and int(team1_id) in own) or \
       (team2_id is not None and int(team2_id) in own):
        return True
    if not viewer_is_league_wide(ident):
        return False
    if in_pool is not None:
        return bool(in_pool)
    return team_has_pooled_tracked(team1_id) or team_has_pooled_tracked(team2_id)


def visible_tracked_game_ids(ident: dict | None, season="Current") -> set[int] | None:
    """The set of tracked game ids whose DEPTH this viewer may aggregate — the
    read-filter's teeth. None means UNRESTRICTED (admin / local owner). Otherwise:
    own-team tracked games ∪ (the pooled set, if League-wide). A Solo coach gets
    own games only; a Free viewer gets an empty set (depth is gated upstream).
    `season` scopes to the active season by default (archived labels view history).
    A PAST season is an open archive → unrestricted (None) for everyone."""
    if _is_past_season(season):
        return None                          # past = open archive, full depth
    if ident and ident.get("role") == "admin":
        return None
    ids: set[int] = set()
    own = _own_teams(ident)
    if own:
        ph = ",".join("?" * len(own))
        params = (season,) + tuple(own) + tuple(own)
        ids |= {r["id"] for r in query(
            f"SELECT id FROM games WHERE tracked=1 AND season=? "
            f"AND (team1_id IN ({ph}) OR team2_id IN ({ph}))", params)}
    if viewer_is_league_wide(ident):
        ids |= pooled_game_ids(season)
    return GD.representative_game_ids(ids)   # one canonical row per double-tracked game


def team_visible_tracked_ids(ident: dict | None, team_id, season="Current") -> set[int] | None:
    """The tracked game ids of ONE team whose depth this viewer may aggregate.
    None = unrestricted (own team / admin → the team's full tracked depth).
    A league-wide scout of another team → only that team's POOLED games (so a
    coach who opponent-tracked this team while League-wide shares those, but the
    team's own Solo games stay private). Used to scope the team dashboard bundle.
    `season` scopes the pooled-visibility query (frozen in_pool → correct history).
    A PAST season is an open archive → unrestricted (None) for everyone."""
    if _is_past_season(season):
        return None                      # past = open archive, full depth
    if ident and ident.get("role") == "admin":
        return None
    if team_id is not None and int(team_id) in _own_teams(ident):
        return None                      # own team → full depth, always
    # league-wide scout of another team → that team's pooled games only, with
    # duplicate tracks collapsed to the canonical (most-detailed / pinned) row.
    return GD.representative_game_ids({r["id"] for r in query(
        "SELECT id FROM games WHERE in_pool=1 AND tracked=1 AND season=? "
        "AND (team1_id=? OR team2_id=?)", (season, team_id, team_id))})


def tracked_gate(ident: dict | None, team_id, raw_has_tracked: bool, pool=None,
                 season="Current"):
    """Resolve a team's tracked-depth visibility for the UI.

    Returns (visible, lock_msg):
      visible  — viewer may see this team's tracked depth.
      lock_msg — None when visible, or when there's simply no tracked data at all
                 (caller shows its own 'track a game' note). Otherwise one of the
                 three co-op messages: Paid feature / co-op INVITE / not-shared.

    A PAST season is an open archive: any viewer sees full tracked depth, no Paid
    / co-op gate (owner rule)."""
    if not raw_has_tracked:
        return False, None
    if _is_past_season(season):
        return True, None                    # past = open archive, full depth
    if not has_paid_plan(ident):
        return False, MSG_PAID
    if ident.get("role") == "admin":
        return True, None
    if team_id is not None and int(team_id) in _own_teams(ident):
        return True, None               # own team → always
    # Paid coach scouting ANOTHER team:
    if not viewer_is_league_wide(ident):
        # a banned coach gets a suspension notice, not a co-op invite they can't act on
        return False, (MSG_POOL_BANNED if is_pool_banned(ident) else MSG_COOP_INVITE)
    if team_has_pooled_tracked(team_id):
        return True, None
    return False, MSG_NOT_SHARED        # their privacy choice — neutral


def free_demo_game_id(ident: dict | None) -> int | None:
    """The ONE game a FREE coach may open in full tracked depth — a
    try-before-you-buy demo. Deterministic + stable: their own team's earliest
    game (lowest id). Paid/admin are unrestricted, so the concept doesn't apply
    (returns None). A coach with no team, or no games yet, gets None.

    Stable on purpose — keys on the immutable game id, not event counts or
    tracked_by, so the free slot never silently moves to a different game (and
    re-locks one the coach already saw) and it works no matter which writer
    logged the game (PWA or the Streamlit manual form)."""
    if ident is None or has_paid_plan(ident):
        return None
    own = _own_teams(ident)
    if not own:
        return None
    ph = ",".join("?" * len(own))
    rows = query(
        f"SELECT id FROM games WHERE team1_id IN ({ph}) OR team2_id IN ({ph}) "
        f"ORDER BY id LIMIT 1", tuple(own) + tuple(own))
    return rows[0]["id"] if rows else None


def can_see_tracked_game_view(ident: dict | None, game_id) -> bool:
    """Game Tracker page (live command center + manual logging + shot chart):
    Paid/admin see any game; a FREE coach sees ONLY their single free-demo game.
    This is the one place a Free plan is granted tracked depth — the demo hook;
    every other tracked surface stays gated on has_paid_plan/co-op."""
    if has_paid_plan(ident):
        return True
    return game_id is not None and game_id == free_demo_game_id(ident)


def recompute_game_pool(game_id=None) -> None:
    """Pool the ACTIVE season's games logged by a League-wide coach.

    SEASON-LOCKED + MONOTONIC: we only ever SET in_pool=1 here, never clear it.
    A game that was shared while its coach was League-wide STAYS pooled for the
    rest of the season — flipping to Solo stops FUTURE sharing (newly logged games
    default in_pool=0 and aren't touched here) but never retroactively un-shares a
    game other coaches may already have scouted. Flipping Solo→League-wide shares
    the coach's not-yet-pooled active-season games (their choice). A new season
    starts fresh (past-season games keep their flag but are an open archive anyway).

    A coach the admin has BANNED (pool_banned) is purged from the pool even if
    already shared — moderation overrides the season-lock stickiness, because the
    point is removing bad data. Unbanning re-shares per their shares_pool toggle.

    Call after a coach flips their toggle, after an admin ban/unban, at finish_game,
    or to repair. Pass a game_id to refresh a single game (e.g. at finish)."""
    # 1) ban purge: a banned coach's active-season games leave the pool.
    purge = ("UPDATE games SET in_pool=0 WHERE in_pool=1 AND season='Current' "
             "AND tracked_by IN (SELECT email FROM app_users WHERE pool_banned=1)")
    # 2) monotonic share: a game joins iff its logging coach's TEAM is League-wide
    #    (teams.shares_pool=1) and the coach isn't banned (never clears).
    share = ("UPDATE games SET in_pool=1 WHERE in_pool=0 AND season='Current' "
             "AND tracked_by != '' AND tracked_by IN "
             "(SELECT ct.coach_email FROM coach_teams ct "
             " JOIN teams t ON ct.team_id = t.id "
             " JOIN app_users u ON u.email = ct.coach_email "
             " WHERE t.shares_pool=1 AND u.pool_banned=0)")
    if game_id is not None:
        execute(purge + " AND id=?", (game_id,))
        execute(share + " AND id=?", (game_id,))
    else:
        execute(purge)
        execute(share)
