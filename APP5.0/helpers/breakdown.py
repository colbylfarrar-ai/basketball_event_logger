"""
breakdown.py — four-factors-style detail per play_type / per defense tag.

Streamlit-FREE engine. Every metric is computed DIRECTLY from tagged events —
there is NO possession reconstruction, because the event model already carries
what we need:

  • a missed SHOT event stores `rebound_by_id` + `rebounder_team_id` (see
    stats.aggregate_player_boxes), so OREB% for that shot's play_type/defense is
    exact — the rebound is attached to the very shot it came off.
  • TURNOVER and FREE_THROW events carry the same sticky `play_type` / `defense`
    tag the shots do, so TOV% and FT-rate aggregate by the same filter.

Each event also carries `shooter_team_id` = the primary actor's team (shot
shooter, turnover committer, or FT shooter — all keyed off primary_player_id in
stats.fetch_events), so offense/defense side selection is one comparison.

GATING: a (play_type|defense) cell only "earns" the full four factors once it
clears MIN_POSS_DETAIL possessions (FGA + TOV). Below that the OREB%/TOV% split
is too noisy to show — the founder's call was ~100. Cells expose `stable` +
`poss` so the UI can show progress ("47 / 100") until then. This lights up only
as coaches tag plays in the tracker; with no tags it returns empty, gracefully.

Four factors (Dean Oliver): eFG% (shooting), TOV% (ball security), OREB%
(second chances), FT-rate (getting to the line). PPP ties them together.
"""
from __future__ import annotations

from helpers.stats import _safe, fetch_events

#: Show the full four-factors breakdown for a type once it has at least this many
#: possessions (FGA + TOV) — ~3-4 games' worth, enough for the OREB%/TOV% splits
#: to settle. Tunable; per-type (not the sparser play_type × defense cross-tab,
#: which would need a higher bar).
MIN_POSS_DETAIL = 70

#: OREB% needs enough missed-shot rebound chances to mean anything; below this we
#: surface it as None even when the cell is otherwise stable.
MIN_REB_CHANCES = 15


def _blank():
    return {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0,
            "OREB": 0, "oppDREB": 0, "TOV": 0, "FTA": 0, "FTM": 0}


def factors_by_tag(events, team_id, tag_field, valid_keys, *, offense=True,
                   min_poss=MIN_POSS_DETAIL):
    """Core: aggregate four-factors counts per `tag_field` value over `events`.

    `tag_field` is 'play_type' or 'defense'. `offense=True` keeps the team's own
    actions (shooter_team_id == team_id); `offense=False` keeps what it allowed.
    Unknown/legacy tags fold into 'other'. Returns {tag_key: factors_dict}.
    """
    valid = set(valid_keys)
    agg: dict = {}
    for e in events:
        team = e["shooter_team_id"]                 # primary actor's team
        if team is None or offense != (team == team_id):
            continue
        tag = e.get(tag_field)
        if not tag:
            continue
        if tag not in valid:
            tag = "other"
        c = agg.get(tag)
        if c is None:
            c = agg[tag] = _blank()
        et = e["event_type"]
        if et == "shot":
            c["FGA"] += 1
            is3 = e["shot_type"] == 3
            if is3:
                c["FG3A"] += 1
            if e["shot_result"] == "make":
                c["FGM"] += 1
                c["PTS"] += 3 if is3 else 2
                if is3:
                    c["FG3M"] += 1
            else:
                # rebound is on the missed-shot event itself
                rt = e["rebounder_team_id"]
                if rt is not None:
                    if rt == team:
                        c["OREB"] += 1
                    else:
                        c["oppDREB"] += 1
        elif et == "turnover":
            c["TOV"] += 1
        elif et == "free_throw":
            c["FTA"] += 1
            if e["shot_result"] == "make":
                c["FTM"] += 1

    out = {}
    for k, c in agg.items():
        poss = c["FGA"] + c["TOV"]
        if poss == 0:
            continue
        reb_chances = c["OREB"] + c["oppDREB"]
        out[k] = {
            "poss": poss, "FGA": c["FGA"], "FGM": c["FGM"], "TOV": c["TOV"],
            "PTS": c["PTS"],
            "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
            "FG%": _safe(c["FGM"], c["FGA"]),
            "3PArate": _safe(c["FG3A"], c["FGA"]),
            "OREB%": (_safe(c["OREB"], reb_chances)
                      if reb_chances >= MIN_REB_CHANCES else None),
            "OREB_n": reb_chances,
            "TOV%": _safe(c["TOV"], poss),
            "FTr": _safe(c["FTM"], c["FGA"]),       # FT made per FGA (Oliver FT-rate)
            "PPP": _safe(c["PTS"], poss),
            "stable": poss >= min_poss,
        }
    return out


def _rows(cells, labels):
    """Attach human labels, sort by PPP desc, summarize. Returns a dict the UI
    renders directly."""
    rows = []
    for key, f in cells.items():
        r = dict(f)
        r["key"] = key
        r["label"] = labels.get(key, key.title())
        rows.append(r)
    rows.sort(key=lambda r: r["PPP"], reverse=True)
    return {
        "rows": rows,
        "n_types": len(rows),
        "n_stable": sum(1 for r in rows if r["stable"]),
        "total_poss": sum(r["poss"] for r in rows),
    }


def play_type_factors(team_id, gender=None, game_ids=None, events=None, *,
                      offense=True, min_poss=MIN_POSS_DETAIL):
    """Four-factors detail per explicit play_type (set call) for a team. See
    factors_by_tag. With no events it does one tracked-game pass for `gender`."""
    from helpers.playtypes import NAMED_PLAY_TYPES, _tracked_game_ids
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = fetch_events(gids) if gids else []
    keys = {k for k, _ in NAMED_PLAY_TYPES}
    cells = factors_by_tag(events, team_id, "play_type", keys,
                           offense=offense, min_poss=min_poss)
    return _rows(cells, dict(NAMED_PLAY_TYPES))


def defense_factors(team_id, gender=None, game_ids=None, events=None, *,
                    offense=False, min_poss=MIN_POSS_DETAIL):
    """Four-factors detail per defense scheme for a team. `offense=False` (the
    default) reads what the team's defense ALLOWED (opponent shots under each
    scheme); `offense=True` reads what the team faced from that scheme."""
    from helpers.defenses import DEFENSES
    from helpers.playtypes import _tracked_game_ids
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = fetch_events(gids) if gids else []
    keys = {d[0] for d in DEFENSES}
    labels = {d[0]: d[1] for d in DEFENSES}
    cells = factors_by_tag(events, team_id, "defense", keys,
                           offense=offense, min_poss=min_poss)
    return _rows(cells, labels)
