"""
badges.py — NBA-2K-style player badges, data-driven.

Basketball-Index's badge layer is the most *legible* way to surface advanced
stats: instead of "84th percentile in 3P%", a player simply earns a Gold
**Deadeye**. APP5.0 already computes every percentile it needs, so this turns
them into a transparent, gated badge wall — huge engagement for HS players and
parents, near-zero cost to compute.

Every badge is rule-based and explainable: it reads ONE stat (or a small combo)
from player_ratings.player_stat_table, ranks the player against the eligible
pool, and awards Bronze / Silver / Gold by percentile — but only if the player
clears a minimum-volume gate (so a 2-for-2 night can't mint a Gold shooter).
Each badge carries its prerequisites so the UI can show *why* it was earned.

Pure data layer: stdlib only, no streamlit, no DB. Pass it the dict returned by
player_stat_table.
"""
from __future__ import annotations


# Default percentile cutoffs for the three tiers.
GOLD, SILVER, BRONZE = 90.0, 75.0, 60.0
_TIER_RANK = {"Gold": 3, "Silver": 2, "Bronze": 1, None: 0}


def _percentile(value, pool, higher_better=True):
    """Mid-rank percentile (0-100) of value within pool (non-None numbers).

    Uses (#worse + 0.5*#ties) / n. Counting only strictly-worse members capped
    the unique pool leader at (n-1)/n*100 — e.g. 87.5 in a pool of 8 — which put
    Gold (>=90) out of reach on a single-team roster; the 0.5*tie term restores a
    reachable ceiling (unique leader of 8 -> 93.75)."""
    vals = [v for v in pool if v is not None]
    if not vals or value is None:
        return None
    if higher_better:
        below = sum(1 for v in vals if v < value)
    else:
        below = sum(1 for v in vals if v > value)
    eq = sum(1 for v in vals if v == value)
    return 100.0 * (below + 0.5 * eq) / len(vals)


def _tier(pct, gold=GOLD, silver=SILVER, bronze=BRONZE):
    if pct is None:
        return None
    if pct >= gold:
        return "Gold"
    if pct >= silver:
        return "Silver"
    if pct >= bronze:
        return "Bronze"
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  BADGE CATALOG
# ══════════════════════════════════════════════════════════════════════════════
#
#  Each badge is a dict:
#     key, name, emoji, cat        identity
#     stat                         player_stat_table key it ranks on
#     higher_better (default True) invert for lower-is-better stats (TOV%, DSHOT%)
#     gate (stat, min)             minimum volume to be eligible (optional)
#     desc                         what it rewards (shown as the prerequisite)
#     combo(row, P)                OPTIONAL custom predicate returning a tier
#                                  string ("Gold"/"Silver"/"Bronze") or None,
#                                  where P(stat) = that player's percentile.
#                                  When present, `stat` is ignored for tiering.

BADGES = [
    # ── Shooting ──────────────────────────────────────────────────────────────
    {"key": "deadeye", "name": "Deadeye", "emoji": "", "cat": "Shooting",
     "stat": "3P%", "gate": ("3PA", 10),
     "desc": "Elite three-point accuracy on real volume (≥10 3PA)."},
    {"key": "sniper", "name": "Volume Sniper", "emoji": "", "cat": "Shooting",
     "stat": "3PM", "gate": ("3PA", 12),
     "desc": "Makes threes in bulk."},
    {"key": "flamethrower", "name": "Flamethrower", "emoji": "", "cat": "Shooting",
     "stat": "eFG%", "gate": ("FGA", 20),
     "desc": "Top-tier effective field-goal % at volume."},
    {"key": "charity", "name": "Charity Stripe", "emoji": "", "cat": "Shooting",
     "stat": "FT%", "gate": ("FTA", 12),
     "desc": "Automatic from the free-throw line."},
    {"key": "hot_hand", "name": "Hot Hand", "emoji": "", "cat": "Shooting",
     "stat": "SMOE", "gate": ("FGA", 20),
     "desc": "Finishes well above the expected value of their shot diet (SMOE)."},

    # ── Scoring ───────────────────────────────────────────────────────────────
    {"key": "bucket", "name": "Bucket Getter", "emoji": "", "cat": "Scoring",
     "stat": "PPG", "gate": ("GP", 1),
     "desc": "Leads the way as a primary scorer."},
    {"key": "efficient", "name": "Efficient Scorer", "emoji": "", "cat": "Scoring",
     "stat": "TS%", "gate": ("FGA", 20),
     "desc": "Scores at a high true-shooting clip on real usage.",
     "combo": lambda r, P: _tier(min(P("TS%") or 0, P("PPG") or 0))},
    {"key": "paint_beast", "name": "Paint Beast", "emoji": "", "cat": "Scoring",
     "stat": "PaintPTS", "gate": ("PaintA", 10),
     "desc": "Dominates scoring inside."},
    {"key": "self_creator", "name": "Self-Creator", "emoji": "", "cat": "Scoring",
     "stat": "SelfCr%", "gate": ("FGA", 20),
     "desc": "Generates their own shot — low assist dependency."},
    {"key": "closer", "name": "Closer", "emoji": "", "cat": "Scoring",
     "stat": "Q4PPG", "gate": ("FGA", 15),
     "desc": "Pours it on in the fourth quarter."},
    {"key": "tough_shot", "name": "Tough-Shot Maker", "emoji": "", "cat": "Scoring",
     "stat": "ShotRating", "gate": ("FGA", 20),
     "desc": "Takes (and makes a living on) the hardest shots."},

    # ── Playmaking ────────────────────────────────────────────────────────────
    {"key": "floor_general", "name": "Floor General", "emoji": "", "cat": "Playmaking",
     "stat": "APG", "gate": ("GP", 1),
     "desc": "Runs the offense and racks up assists."},
    {"key": "dime_drop", "name": "Dime Dropper", "emoji": "", "cat": "Playmaking",
     "stat": "AST/TOV", "gate": ("AST", 8),
     "desc": "Creates for others while protecting the ball (AST/TO)."},
    {"key": "connector", "name": "Connector", "emoji": "", "cat": "Playmaking",
     "stat": "SC/G", "gate": ("GP", 1),
     "desc": "Keeps the ball moving — shots created per game."},

    # ── Defense ───────────────────────────────────────────────────────────────
    {"key": "pickpocket", "name": "Pickpocket", "emoji": "", "cat": "Defense",
     "stat": "SPG", "gate": ("GP", 1),
     "desc": "A menace in passing lanes."},
    {"key": "rim_protect", "name": "Rim Protector", "emoji": "", "cat": "Defense",
     "stat": "BPG", "gate": ("GP", 1),
     "desc": "Erases shots at the basket."},
    {"key": "lockdown", "name": "Lockdown", "emoji": "", "cat": "Defense",
     "stat": "DSHOT%", "higher_better": False, "gate": ("defFGA", 12),
     "desc": "Smothers the shots they contest (low defended FG%)."},
    {"key": "disruptor", "name": "Disruptor", "emoji": "", "cat": "Defense",
     "stat": "STOCKS/32", "gate": ("MIN", 32),
     "desc": "Stocks (steals + blocks) per 32 — total defensive activity."},

    # ── Rebounding ────────────────────────────────────────────────────────────
    {"key": "glass", "name": "Glass Cleaner", "emoji": "", "cat": "Rebounding",
     "stat": "RPG", "gate": ("GP", 1),
     "desc": "Owns the defensive glass."},
    {"key": "putback", "name": "Putback Hunter", "emoji": "", "cat": "Rebounding",
     "stat": "OREB/G", "gate": ("GP", 1),
     "desc": "Crashes the offensive boards for second chances."},

    # ── Creation / role (tracker-rich) ──────────────────────────────────────────
    {"key": "screen_assist", "name": "Screen Assist", "emoji": "", "cat": "Playmaking",
     "stat": "SCCreated%", "gate": ("SC", 12),
     "desc": "Frees teammates — high share of shot-creation from setting screens."},
    {"key": "catch_shoot", "name": "Catch & Shoot", "emoji": "", "cat": "Shooting",
     "stat": "SCPass%", "gate": ("FGA", 20),
     "desc": "Lethal spot-up — efficient on passes into the shot.",
     "combo": lambda r, P: _tier(min(P("SCPass%") or 0, P("eFG%") or 0))},

    # ── Hand side (true half-court split mapped to handedness) ───────────────────
    {"key": "two_handed", "name": "Two-Handed Threat", "emoji": "", "cat": "Scoring",
     "stat": "Weak_FG%",
     "gate": lambda r: (r.get("Weak_FGA") or 0) >= 15 and (r.get("Dom_FGA") or 0) >= 15,
     "desc": "No weak side — finishes going either direction (both hands ≥15 FGA).",
     "combo": lambda r, P: _tier(min(P("Dom_FG%") or 0, P("Weak_FG%") or 0))},

    # ── True tap-distance (richer than the zone shadow) ─────────────────────────
    {"key": "rim_finisher", "name": "Rim Finisher", "emoji": "", "cat": "Scoring",
     "stat": "Near_FG%", "gate": ("Near_FGA", 15),
     "desc": "Finishes at the rim — FG% inside 5 ft on real volume."},
    {"key": "deep_range", "name": "Deep Range", "emoji": "", "cat": "Shooting",
     "stat": "Deep_FG%", "gate": ("Deep_FGA", 12),
     "desc": "Makes them from way out — FG% on shots 19.75+ ft."},

    # ── Play-type (one-tap coach tags; sparse until tagging volume grows) ────────
    {"key": "pnr_maestro", "name": "PnR Maestro", "emoji": "", "cat": "Scoring",
     "stat": "PnR_PPP", "gate": ("PnR_poss", 15),
     "desc": "Elite scoring out of the pick & roll (tagged plays)."},
    {"key": "post_hub", "name": "Post Hub", "emoji": "", "cat": "Scoring",
     "stat": "Post_PPP", "gate": ("Post_poss", 15),
     "desc": "Efficient post-up scorer (tagged plays)."},

    # ── Two-way / Identity ────────────────────────────────────────────────────
    {"key": "two_way", "name": "Two-Way Wire", "emoji": "", "cat": "Two-Way",
     "stat": "2WAY", "gate": ("GP", 1),
     "desc": "Impacts both ends — average of offense + defense rating."},
    {"key": "swiss_army", "name": "Swiss-Army Knife", "emoji": "", "cat": "Two-Way",
     "stat": "VERSATILITY", "gate": ("GP", 1),
     "desc": "Fills every column of the box score."},
    {"key": "iron", "name": "Iron Player", "emoji": "", "cat": "Two-Way",
     "stat": "MPG", "gate": ("GP", 2),
     "desc": "Logs heavy minutes night in, night out."},
    {"key": "franchise", "name": "Franchise Cornerstone", "emoji": "", "cat": "Two-Way",
     "stat": "OVERALL", "gate": ("GP", 2),
     "desc": "Top-shelf all-around player rating."},
]


# ══════════════════════════════════════════════════════════════════════════════
#  AWARD
# ══════════════════════════════════════════════════════════════════════════════

def _gate_ok(row, gate):
    if not gate:
        return True
    if callable(gate):          # custom multi-field gate (e.g. dual hand-side volume)
        return bool(gate(row))
    stat, minimum = gate
    v = row.get(stat)
    return v is not None and v >= minimum


def award_badges(table, gold=GOLD, silver=SILVER, bronze=BRONZE):
    """
    Award badges to every player in a player_stat_table mapping.

    Returns {player_id: [badge, ...]} where each badge is a dict:
        key, name, emoji, cat, tier ("Gold"/"Silver"/"Bronze"), pct, desc
    sorted strongest-first (Gold → Bronze, then by percentile). Eligibility for
    each badge's percentile pool is gated on volume, so percentiles are computed
    against the players who actually qualify, not the whole roster.
    """
    if not table:
        return {}
    pids = list(table)

    # percentile pools per badge stat, over the players who clear that badge's gate
    pct_cache = {}  # (stat_key, gate_tuple, higher_better) -> {pid: pct}
    def _pcts(stat, gate, higher_better):
        key = (stat, gate, higher_better)
        if key in pct_cache:
            return pct_cache[key]
        eligible = [p for p in pids if _gate_ok(table[p], gate)]
        pool = [table[p].get(stat) for p in eligible]
        out = {p: _percentile(table[p].get(stat), pool, higher_better) for p in eligible}
        pct_cache[key] = out
        return out

    awarded = {p: [] for p in pids}
    for b in BADGES:
        stat = b["stat"]
        hib = b.get("higher_better", True)
        gate = b.get("gate")
        pcts = _pcts(stat, gate, hib)
        combo = b.get("combo")
        for p in pids:
            row = table[p]
            if not _gate_ok(row, gate):
                continue
            if combo is not None:
                # combo predicate gets a percentile lookup over the gated pool
                def P(s, _gate=gate, _hib=True):
                    return _pcts(s, _gate, _hib).get(p)
                tier = combo(row, P)
                pct = pcts.get(p)
            else:
                pct = pcts.get(p)
                tier = _tier(pct, gold, silver, bronze)
            if tier:
                awarded[p].append({
                    "key": b["key"], "name": b["name"], "emoji": b["emoji"],
                    "cat": b["cat"], "tier": tier,
                    "pct": round(pct) if pct is not None else None,
                    "desc": b["desc"],
                })
    for p in pids:
        awarded[p].sort(key=lambda x: (-_TIER_RANK[x["tier"]], -(x["pct"] or 0)))
    return awarded


def badge_points(badge_list):
    """Olympic-style score for a player's badge haul (Gold 5 / Silver 3 / Bronze 1)."""
    pts = {"Gold": 5, "Silver": 3, "Bronze": 1}
    return sum(pts.get(b["tier"], 0) for b in badge_list)
