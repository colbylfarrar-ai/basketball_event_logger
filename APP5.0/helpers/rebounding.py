"""
rebounding.py — rebounding enrichment from the tags coaches already log
(founder batch item 6, 2026-07-18: "biggest info gap, tags can flood it").

No new tracking. Every read derives from existing optional tags on missed
shots — rebound_by (85% coverage league-wide), guarded_by (the on-ball
defender), play_type, shot_type/zone:

  • defender_secures — when a player is the ON-BALL defender (guarded_by) on
    a missed shot: how often THEY grab the board, and how often their TEAM
    does (the box-out read: did contesting the shot turn into ending the
    possession?).
  • on-ball vs off-ball DREB split — a player's defensive rebounds split by
    whether they were guarding the shooter (cleans up their own assignment)
    or crashing from elsewhere (weak-side rebounder).
  • own-miss recovery — shooter rebounds their own miss.
  • PnR rebounds by role — on missed PnR-tagged shots, who secures: the
    handler (shooter), the screener (shot_created_by — the roll/pop man),
    another teammate, or the defense. The play_type taxonomy has one 'pnr'
    key, so "roller vs setter" is expressed through the shot-creator tag.
  • 3PA long-rebound profile — OREB% on a team's own 3PT vs 2PT misses (long
    carom vs interior scrum) and who secures opponent 3-miss boards. Rebound
    LOCATION isn't tracked; the shot's type/zone is the axis (stated in UI).

Denominator honesty: every rate divides by misses WITH a tagged rebound only
(untagged rebounds are unknown, not "not you"). `n` rides alongside every
rate; thin rates get an EB-stabilized twin via helpers.shrinkage where a pool
prior exists. Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
import helpers.shrinkage as SHR

_safe = S._safe

MIN_ONBALL = 5      # min tagged on-ball misses before defender_secures shows


def _miss_rows(events):
    """Missed FGs with a tagged rebound + the derived sides, one pass."""
    for e in events:
        if (e["event_type"] != "shot" or e["shot_result"] != "miss"
                or e["rebound_by_id"] is None
                or e["shooter_team_id"] is None):
            continue
        yield e, (e["rebounder_team_id"] == e["shooter_team_id"])   # oreb?


def player_rebounding(gender=None, game_ids=None, events=None):
    """{pid: metrics} over the sample (default tracked scope).

    Metrics (each with its n): onball_misses, def_secure_self, def_secure_team
    (+ _stab), dreb_onball, dreb_offball, onball_share, own_miss_rec (+ n),
    dreb3, dreb2, oreb3, oreb2."""
    if events is None:
        events = S.fetch_events(game_ids) if game_ids is not None \
            else S.fetch_events()
        if gender is not None and game_ids is None:
            import helpers.playtypes as PT
            gids = set(PT._tracked_game_ids(gender))
            events = [e for e in events if e["game_id"] in gids]

    P = defaultdict(lambda: {
        "onball_misses": 0, "def_secure_self": 0, "def_secure_team": 0,
        "dreb_onball": 0, "dreb_offball": 0,
        "own_misses": 0, "own_miss_rec": 0,
        "dreb3": 0, "dreb2": 0, "oreb3": 0, "oreb2": 0,
    })

    for e, is_oreb in _miss_rows(events):
        reb, shooter = e["rebound_by_id"], e["primary_player_id"]
        guard = e["guarded_by_id"]
        three = (e["shot_type"] == 3)
        # on-ball defender outcomes
        if guard is not None:
            g = P[guard]
            g["onball_misses"] += 1
            if not is_oreb:
                g["def_secure_team"] += 1
                if reb == guard:
                    g["def_secure_self"] += 1
        # rebounder splits
        r = P[reb]
        if is_oreb:
            r["oreb3" if three else "oreb2"] += 1
        else:
            r["dreb3" if three else "dreb2"] += 1
            if guard == reb:
                r["dreb_onball"] += 1
            else:
                r["dreb_offball"] += 1
        # own-miss recovery
        if shooter is not None:
            P[shooter]["own_misses"] += 1
            if reb == shooter:
                P[shooter]["own_miss_rec"] += 1

    # rates + EB stabilization on the two headline rates
    team_pairs = [(m["def_secure_team"], m["onball_misses"])
                  for m in P.values() if m["onball_misses"] > 0]
    prior_mean, k = SHR.eb_prior(team_pairs) if team_pairs else (0.7, 10.0)
    out = {}
    for pid, m in P.items():
        ob = m["onball_misses"]
        dreb = m["dreb_onball"] + m["dreb_offball"]
        out[pid] = dict(
            m,
            def_secure_team_pct=_safe(m["def_secure_team"] * 100.0, ob),
            def_secure_self_pct=_safe(m["def_secure_self"] * 100.0, ob),
            def_secure_team_stab=round(SHR.stabilize_rate(
                m["def_secure_team"], ob, prior_mean, k) * 100.0, 1)
            if ob else None,
            onball_share=_safe(m["dreb_onball"] * 100.0, dreb),
            own_miss_rec_pct=_safe(m["own_miss_rec"] * 100.0, m["own_misses"]),
            dreb=dreb,
            oreb=m["oreb3"] + m["oreb2"],
        )
    return out


def team_long_rebound_profile(team_id, game_ids=None, events=None):
    """The 3PA long-carom profile for one team's OWN misses:
    {'three': {'misses', 'oreb', 'oreb_pct', 'by_zone': {zone: (oreb, n)}},
     'two': {...}} — OREB% on 3s vs 2s answers "do our long rebounds leak?"."""
    if events is None:
        import helpers.team_analytics as TA
        gids = game_ids if game_ids is not None else TA.event_team_games(team_id)
        events = S.fetch_events(gids) if gids else []
    out = {"three": {"misses": 0, "oreb": 0, "by_zone": defaultdict(lambda: [0, 0])},
           "two":   {"misses": 0, "oreb": 0, "by_zone": defaultdict(lambda: [0, 0])}}
    for e, is_oreb in _miss_rows(events):
        if e["shooter_team_id"] != team_id:
            continue
        b = out["three" if e["shot_type"] == 3 else "two"]
        b["misses"] += 1
        z = e["zone"] or "?"
        b["by_zone"][z][1] += 1
        if is_oreb:
            b["oreb"] += 1
            b["by_zone"][z][0] += 1
    for b in out.values():
        b["oreb_pct"] = _safe(b["oreb"] * 100.0, b["misses"])
        b["by_zone"] = {z: tuple(v) for z, v in b["by_zone"].items()}
    return out


def pnr_rebound_roles(gender=None, game_ids=None, events=None, team_id=None):
    """On missed PnR-tagged shots (play_type='pnr'): who secures the board.
    {'misses', 'handler', 'screener', 'other_off', 'defense'} — handler = the
    shooter, screener = shot_created_by (the roll/pop man); the single 'pnr'
    play_type key means roles come from the creator tag, not the set call.

    `team_id` (optional) scopes to ONE team's own PnR misses (shooter on
    team_id) — "who chases OUR ball-screen caroms" for the team dashboard;
    default None keeps the league-wide read used on the Players page."""
    if events is None:
        events = S.fetch_events(game_ids) if game_ids is not None \
            else S.fetch_events()
        if gender is not None and game_ids is None:
            import helpers.playtypes as PT
            gids = set(PT._tracked_game_ids(gender))
            events = [e for e in events if e["game_id"] in gids]
    out = {"misses": 0, "handler": 0, "screener": 0, "other_off": 0,
           "defense": 0}
    for e, is_oreb in _miss_rows(events):
        if (e.get("play_type") or "") != "pnr":
            continue
        if team_id is not None and e["shooter_team_id"] != team_id:
            continue
        out["misses"] += 1
        if not is_oreb:
            out["defense"] += 1
        elif e["rebound_by_id"] == e["primary_player_id"]:
            out["handler"] += 1
        elif (e["shot_created_by_id"] is not None
              and e["rebound_by_id"] == e["shot_created_by_id"]):
            out["screener"] += 1
        else:
            out["other_off"] += 1
    return out
