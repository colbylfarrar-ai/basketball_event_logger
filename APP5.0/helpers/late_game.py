"""
late_game.py — intentional-foul (clock-stop) window detection.

The single shared detector for the "late fouling shouldn't help anyone" rule
(spec 2026-07-18 §4): a foul committed by the TRAILING team inside the final
WINDOW_SECS of Q4/OT, down by MARGIN_MIN..MARGIN_MAX, is a strategic clock-stop
— not a defensive breakdown, not a whistle-happy ref, not clutch shot-making by
whoever gets sent to the line. Every engine that would otherwise credit or
charge someone for these possessions imports THIS module so the definition
stays app-wide:

  • wpa            — free throws from a strategic foul earn damped credit
  • fouls          — the fouler's discipline counts skip them ('strategic' key)
  • ref engines    — call-rate/tendency aggregates exclude them

Margins outside the band are not strategic: up = you don't foul on purpose,
down big = the game is decided and WPA already self-damps to ~0 there.

Pure data layer: stdlib + database.db + helpers.stats clock utils. The margin
walk mirrors helpers/wpa.py (made shots + made FTs, shooter_team_id).
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S


WINDOW_SECS = 120     # final N seconds of Q4/OT that count as clock-stop time
MARGIN_MIN = 1        # fouling team must trail by at least this ...
MARGIN_MAX = 10       # ... and by no more than this (further back = decided)
FT_LINK_SECS = 5      # a FT within this many clock-secs of a flagged foul, by
                      # the fouled team, is the strategic foul's free throw


def _pteam(events):
    """{player_id: team_id} for everyone referenced — one query."""
    return {r["id"]: r["team_id"] for r in query(
        "SELECT id, team_id FROM players")}


def strategic_context(events, pteam=None):
    """Classify one-or-more games' events. Returns
    {"fouls": set(event_id), "fts": set(event_id)} — the strategic clock-stop
    fouls, and the free throws those fouls produced.

    `events` are rows in fetch_events shape (shooter_team_id joined in). Games
    are walked independently; pass `pteam` ({pid: team_id}) to skip the roster
    query (tests / hot loops)."""
    if pteam is None:
        pteam = _pteam(events)
    by_game = {}
    for e in events:
        by_game.setdefault(e["game_id"], []).append(e)

    fouls, fts = set(), set()
    for evs in by_game.values():
        evs = sorted(evs, key=lambda e: (S.elapsed(e["quarter"], e["time"]),
                                         e.get("id") or 0))
        end = max((S.elapsed(e["quarter"], e["time"]) for e in evs),
                  default=0) or 0
        pts = {}
        flagged_at = []                       # (elapsed, fouler_team)
        for e in evs:
            t = S.elapsed(e["quarter"], e["time"])
            et = e["event_type"]
            if et == "foul":
                fouler_team = pteam.get(e["secondary_player_id"])
                if (fouler_team is not None and e["quarter"] >= 4
                        and (end - t) <= WINDOW_SECS):
                    opp_pts = sum(v for k, v in pts.items()
                                  if k != fouler_team)
                    margin = pts.get(fouler_team, 0) - opp_pts
                    if -MARGIN_MAX <= margin <= -MARGIN_MIN:
                        fouls.add(e["id"])
                        flagged_at.append((t, fouler_team))
            elif et == "free_throw":
                sh_team = e.get("shooter_team_id")
                for ft_t, f_team in flagged_at:
                    if (abs(t - ft_t) <= FT_LINK_SECS
                            and sh_team is not None and sh_team != f_team):
                        fts.add(e["id"])
                        break
                if e["shot_result"] == "make" and sh_team is not None:
                    pts[sh_team] = pts.get(sh_team, 0) + 1
            elif et == "shot" and e["shot_result"] == "make":
                sh_team = e.get("shooter_team_id")
                if sh_team is not None:
                    pts[sh_team] = pts.get(sh_team, 0) + \
                        (3 if e["shot_type"] == 3 else 2)
    return {"fouls": fouls, "fts": fts}


def strategic_foul_event_ids(events, pteam=None):
    """Event ids of strategic clock-stop fouls in `events`."""
    return strategic_context(events, pteam=pteam)["fouls"]


def damped_ft_event_ids(events, pteam=None):
    """Event ids of free throws produced by strategic clock-stop fouls."""
    return strategic_context(events, pteam=pteam)["fts"]
