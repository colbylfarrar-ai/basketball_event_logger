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


# ── the player-card "do it all" read (spec Part 1 §2) ────────────────────────
# Volume gates for the verdict. Higher than the raw-table gates on purpose: a
# table column can honestly print "62% (n=5)" and let the coach judge, but a
# VERDICT asserts something, so it needs enough n to be worth asserting.
VERDICT_MIN_ONBALL = 8
VERDICT_MIN_DREB = 6
VERDICT_MIN_OWN_MISS = 5

# The combined "does it all" read is calibrated on the POOL, not on absolute
# cutoffs, because both inputs are naturally compressed and absolute numbers
# make it fire for almost everyone. Measured on the live book (2026-07-24,
# 43 tracked games): EB shrinkage keeps box-out payoff inside 55-69 with a
# median of 62, and on-ball share runs 0-44 with a median of 14 — a defender
# only guards ONE shooter, so most of anyone's boards are off-ball by
# construction. A first pass using `stab >= 60 and share <= 30` tagged 25 of
# 57 players "does it all", which says nothing. Tertiles self-calibrate as the
# book grows and travel across genders/leagues without a retune.
VERDICT_COMBO_TOP = 2 / 3.0     # box-out payoff must sit in the pool's top third
VERDICT_COMBO_BOTTOM = 1 / 3.0  # on-ball share in the pool's bottom third


def _quantile(sorted_vals, q):
    """Nearest-rank quantile of a pre-sorted list (no numpy)."""
    if not sorted_vals:
        return None
    i = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[min(max(i, 0), len(sorted_vals) - 1)]


def rebounding_verdict(row, pool=None):
    """Plain-word rebounding read for one player: [(label, n, text)] ready for
    helpers.cards.verdict_card. Empty list when nothing clears its gate — an
    honest silence, not a hedged sentence.

    `row` is a player_stat_table row (or a `profiles` row — both carry the same
    engine key names). `pool` is the rows to rank against; when both `row` and a
    pool row carry a `team`, the pool is narrowed to that player's OWN TEAM,
    because "best on the team" is the claim a coach acts on and it must be
    literally true. An omitted (or all-thin) pool simply drops the ranking
    clause rather than inventing one.

    Three reads, combined because separately they mislead:
      * BOX-OUT PAYOFF (def_secure_team_stab) — value created by sealing the
        shooter off, whoever ends up with the ball.
      * OFF-BALL CRASH (onball_share) — a STYLE axis, never good/bad: a low
        share means their boards come from helping elsewhere, which is a
        different job, not a worse one.
      * OWN-MISS RECOVERY (own_miss_rec_pct) — rare-event effort read.

    The combined verdict is the point: a high box-out payoff AND a low on-ball
    share is the do-it-all defensive rebounder — seals their own assignment
    (so a TEAMMATE collects it) and still crashes from the weak side. Reading
    either number alone would call that same player a poor rebounder.
    """
    stab = row.get("def_secure_team_stab")
    ob = row.get("onball_misses") or 0
    share = row.get("onball_share")
    dreb = row.get("tagged_dreb") or 0
    own = row.get("own_miss_rec_pct")
    own_n = row.get("own_misses") or 0

    lines = []
    pool = [r for r in (pool or []) if r is not row]
    # The FULL pool calibrates the combined read's tertiles (a league-wide
    # distribution), while the team-narrowed pool below drives the "on the team"
    # ranking clause. Two different questions, two different comparison sets.
    _lg_stab = sorted(r["def_secure_team_stab"] for r in pool
                      if r.get("def_secure_team_stab") is not None
                      and (r.get("onball_misses") or 0) >= VERDICT_MIN_ONBALL)
    _lg_share = sorted(r["onball_share"] for r in pool
                       if r.get("onball_share") is not None
                       and (r.get("tagged_dreb") or 0) >= VERDICT_MIN_DREB)
    # Narrow to the player's own team when the rows say what team they are on,
    # so the ranking clause below can honestly say "on the team". Filter
    # STRICTLY once team info exists — even down to an empty pool, which just
    # drops the ranking clause. Falling back to the cross-team pool when a
    # player has no qualifying teammates would rank them against the whole
    # league while still saying "on the team".
    _team = row.get("team")
    if _team is not None and any(r.get("team") is not None for r in pool):
        pool = [r for r in pool if r.get("team") == _team]

    # ── box-out payoff, with an optional roster ranking ──────────────────
    if stab is not None and ob >= VERDICT_MIN_ONBALL:
        peers = [r["def_secure_team_stab"] for r in pool
                 if r.get("def_secure_team_stab") is not None
                 and (r.get("onball_misses") or 0) >= VERDICT_MIN_ONBALL]
        rank_txt = ""
        if peers:
            better = sum(1 for v in peers if v > stab)
            if better == 0:
                rank_txt = " — best on the team"
            elif better <= 1:
                rank_txt = " — 2nd on the team"
            elif stab < min(peers):
                rank_txt = " — last on the team"
        lines.append((
            "Box-out", ob,
            f"Their team ends the possession on <b>{stab:.0f}%</b> of the "
            f"shots they contest{rank_txt}."))

    # ── where the boards come from (style, never a grade) ────────────────
    if share is not None and dreb >= VERDICT_MIN_DREB:
        if share >= 60:
            txt = (f"Boards are mostly their OWN assignment "
                   f"(<b>{share:.0f}%</b> on-ball) — they finish what they "
                   f"guard rather than roam.")
        elif share <= 25:
            txt = (f"Only <b>{share:.0f}%</b> of their boards come off their "
                   f"own assignment — a weak-side crasher, not a "
                   f"clean-up-your-own rebounder.")
        else:
            txt = (f"Boards split between their own assignment and weak-side "
                   f"crashes (<b>{share:.0f}%</b> on-ball).")
        lines.append(("Board mix", dreb, txt))

    # ── the combined do-it-all read: the reason these ship together ──────
    # Pool-relative, not absolute (see VERDICT_COMBO_TOP): top-third box-out
    # payoff AND bottom-third on-ball share. Needs a real pool to calibrate
    # against, so it stays silent without one rather than guessing cutoffs.
    _hi = _quantile(_lg_stab, VERDICT_COMBO_TOP)
    _lo = _quantile(_lg_share, VERDICT_COMBO_BOTTOM)
    if (stab is not None and ob >= VERDICT_MIN_ONBALL
            and share is not None and dreb >= VERDICT_MIN_DREB
            and _hi is not None and _lo is not None
            and stab >= _hi and share <= _lo):
        lines.append((
            "Does it all", None,
            "Seals their own shooter <i>and</i> crashes from the weak side — "
            "the boards land elsewhere, so their own DREB count undersells "
            "the work."))

    # ── own-miss recovery (rare event; only speak when it's notable) ─────
    if own is not None and own_n >= VERDICT_MIN_OWN_MISS and own >= 20:
        lines.append((
            "Second chance", own_n,
            f"Chases down <b>{own:.0f}%</b> of their own misses."))

    return lines
