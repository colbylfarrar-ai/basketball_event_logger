"""
scheme_situational.py — WHEN a team goes to a scheme or a set, not just how often.

The dashboard already shows scheme usage as a flat season share ("42% man") and
scheme efficiency as PPP (helpers/defenses.py). Both answer "what do they run".
Neither answers the question a coach actually asks: **where does a look spike?**
"They play zone to stop a run." "They sit in man against a BLOB." "They press
when they're down ten." A season share averages every one of those away.

This module cuts the possession pool into game-state slices and compares each
tag's usage rate INSIDE the cut against that team's own baseline rate. The
baseline is the team's own season mix, not the league's — the read is "they do
this MORE THAN THEY NORMALLY DO", which is what makes it actionable. A spike is
only reported when the cut has a real sample and the gap clears a threshold.

Two sides off one machine, mirroring the defenses/playtypes duality:
  • side='defense' → the `defense` tag on possessions the team DEFENDS: the
    schemes it goes to. The scout read.
  • side='offense' → the `play_type` tag on the team's OWN possessions: the sets
    it calls. The self-scout read.

The cuts (founder-selected):
  after_run   possessions while the OPPONENT is on a run — the "zone to stop a
              run" read. Reuses situational.annotate's run state (>= RUN_PTS
              unanswered), so "on a run" means the same thing here as everywhere.
  deadball    possessions the offense tagged BLOB / SLOB — the inbounds read.
  margin      usage by score state (trailing big ... leading big).
  clutch      4th quarter inside CLUTCH_MARGIN.

Quarter/period openers are deliberately NOT a cut here. They were considered and
left out; situational.py already slices by quarter if that changes.

Streamlit-free (pure python). Display: the Team Dashboard Play Style + Defense
tabs, as verdict lines.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.situational as SIT
import helpers.playtypes as PT
import helpers.defenses as DF
import helpers.team_analytics as TA

# A cut needs this many tagged possessions before its rates mean anything, and a
# tag must move at least this far off the team's own baseline to be called a
# spike. Both deliberately blunt: a 10-possession cut on a high-school book is
# noise, and a 5-point usage wobble is not a tendency.
MIN_CUT_POSS = 12
MIN_BASE_POSS = 25
MIN_DELTA = 0.12          # 12 percentage points off the team's own baseline

CLUTCH_MARGIN = 5         # 4th-quarter margin that counts as clutch
DEADBALL_SETS = ("blob", "slob")

# Score-state buckets, in display order: (key, label, predicate on margin)
MARGIN_BUCKETS = [
    ("down_big", "Down 10+",    lambda m: m <= -10),
    ("down",     "Down 3-9",    lambda m: -10 < m <= -3),
    ("close",    "Within 2",    lambda m: -3 < m < 3),
    ("up",       "Up 3-9",      lambda m: 3 <= m < 10),
    ("up_big",   "Up 10+",      lambda m: m >= 10),
]


def _ends_possession(e):
    """A possession ends on a shot or a turnover — the app-wide rule (a foul is
    not a possession; see playtypes/defenses)."""
    return e.get("event_type") in ("shot", "turnover")


def _tag_of(e, side):
    """The scheme (defense) or set call (offense) tag on this possession, folded
    to the canonical key set. None when untagged — untagged possessions are
    excluded from BOTH the cut and the baseline, so a coverage gap can't read as
    a tendency."""
    if side == "defense":
        return DF._norm(e.get("defense"))
    pt = e.get("play_type")
    if not pt:
        return None
    return pt if pt in {k for k, _ in PT.NAMED_PLAY_TYPES} else "other"


def _label_of(side):
    if side == "defense":
        return {k: l for k, l, _f in DF.DEFENSES}
    return dict(PT.NAMED_PLAY_TYPES)


def _possessions(team_id, events, side):
    """The team's tagged possessions for this side, annotated with game state.

    Returns [(tag, sit, event)] where `sit` is situational.annotate's
    {q, margin, run} from THIS team's perspective.
    """
    SIT.annotate(events, team_id)
    # The allowed-side rule (same as defenses/playtypes): on the DEFENSE side the
    # selector is "shooter isn't us", which on a league-wide event list matches
    # every possession in the league — including games this team never played.
    # Gate to the team's own games first. The offense side is self-gating
    # (shooter == us implies our game) but pays nothing for the same guard.
    own = TA.event_team_games(team_id, events)
    out = []
    for e in events:
        if not _ends_possession(e):
            continue
        if e.get("game_id") not in own:
            continue
        st = e.get("shooter_team_id")
        if st is None:
            continue
        # side=offense → the team's own possessions; defense → the ones it guards
        if (st == team_id) != (side == "offense"):
            continue
        tag = _tag_of(e, side)
        if tag is None:
            continue
        out.append((tag, e.get("_sit") or {}, e))
    return out


def _rates(rows):
    """{tag: share} + total, over [(tag, sit, e)]."""
    n = defaultdict(int)
    for tag, _s, _e in rows:
        n[tag] += 1
    tot = sum(n.values())
    return ({k: v / tot for k, v in n.items()} if tot else {}), tot


def _cut_rows(base_rate, base_n, rows, min_delta=MIN_DELTA):
    """Spikes in `rows` against the team's own `base_rate`. Sorted by |delta|."""
    rate, n = _rates(rows)
    if n < MIN_CUT_POSS:
        return [], n
    out = []
    for tag, r in rate.items():
        b = base_rate.get(tag, 0.0)
        d = r - b
        if abs(d) < min_delta:
            continue
        out.append({"tag": tag, "cut_rate": r, "base_rate": b, "delta": d,
                    "cut_n": int(round(r * n)), "cut_poss": n,
                    "base_poss": base_n})
    out.sort(key=lambda x: -abs(x["delta"]))
    return out, n


def scheme_situational(team_id, events, side="defense", min_delta=MIN_DELTA):
    """Where this team's scheme / set usage spikes off its OWN baseline.

    Returns {'available': bool, 'side', 'base_poss', 'base_rate', 'labels',
    'cuts': [{key, label, blurb, poss, rows: [...]}]} — cuts with no qualifying
    spike are dropped, so an empty 'cuts' means "nothing unusual", which is
    itself an honest answer.
    """
    rows = _possessions(team_id, events, side)
    base_rate, base_n = _rates(rows)
    labels = _label_of(side)
    if base_n < MIN_BASE_POSS:
        return {"available": False, "side": side, "base_poss": base_n,
                "base_rate": base_rate, "labels": labels, "cuts": []}

    cuts = []

    def _emit(key, label, blurb, sub):
        found, n = _cut_rows(base_rate, base_n, sub, min_delta)
        if found:
            cuts.append({"key": key, "label": label, "blurb": blurb,
                         "poss": n, "rows": found})

    def _add(key, label, blurb, sel):
        """Cut selected on the GAME STATE (situational.annotate's dict)."""
        _emit(key, label, blurb, [r for r in rows if sel(r[1])])

    def _add_ev(key, label, blurb, sel):
        """Cut selected on the EVENT itself (a tag on the possession)."""
        _emit(key, label, blurb, [r for r in rows if sel(r[2])])

    _add("after_run", "While the opponent is on a run",
         "Possessions where the other team has a run going — the "
         "“go zone to stop the bleeding” read.",
         lambda s: s.get("run") == "opp")
    _add("own_run", "While they're on a run",
         "Possessions where THIS team has a run going — what they ride when "
         "it's working.",
         lambda s: s.get("run") == "us")

    # The dead-ball cut keys off the OFFENSE's set tag on the possession itself,
    # not the game state, so it selects on the event rather than `sit`.
    #
    # DEFENSE side only. On the offense side the cut criterion (play_type is a
    # BLOB/SLOB) IS the tag being measured, so it can only ever report that a
    # BLOB possession is a BLOB — a tautology that scores as a huge spike
    # (+80 pts off baseline) and crowds out the real findings. The question only
    # means something when the thing cut on and the thing measured are different.
    if side == "defense":
        _add_ev("deadball", "Out of a dead ball (BLOB / SLOB)",
                "Possessions the offense tagged as a baseline or sideline "
                "inbound — what they sit in on inbounds.",
                lambda e: e.get("play_type") in DEADBALL_SETS)

    for mkey, mlabel, pred in MARGIN_BUCKETS:
        _add(f"margin_{mkey}", mlabel,
             f"Possessions with the score state {mlabel.lower()}.",
             lambda s, _p=pred: _p(s.get("margin", 0)))

    _add("clutch", "Clutch (4th, within 5)",
         "Fourth-quarter possessions inside five points.",
         lambda s: s.get("q", 1) >= 4 and abs(s.get("margin", 0)) <= CLUTCH_MARGIN)

    return {"available": True, "side": side, "base_poss": base_n,
            "base_rate": base_rate, "labels": labels, "cuts": cuts}


def verdict_lines(res, top=4):
    """The spikes as ready-to-render prose, strongest first.

    Returns [{text, delta, cut, tag}] — the house verdict-line shape. Deliberately
    plain: each line names the cut, the tag, the cut rate, the baseline it's
    measured against, and the sample, so nothing is asserted without its number.
    """
    if not res.get("available"):
        return []
    labels = res["labels"]
    verb_more = "sit in" if res["side"] == "defense" else "call"
    out = []
    for c in res["cuts"]:
        for r in c["rows"]:
            tag = labels.get(r["tag"], r["tag"])
            up = r["delta"] > 0
            verb = "jumps to" if up else "drops to"
            out.append({
                "text": (f"**{c['label']}** — {tag} {verb} "
                         f"**{r['cut_rate'] * 100:.0f}%** of possessions vs a "
                         f"{r['base_rate'] * 100:.0f}% season baseline "
                         f"({r['delta'] * 100:+.0f} pts, {r['cut_poss']} poss). "
                         + (f"They {verb_more} it more when this happens."
                            if up else "They get off it when this happens.")),
                "delta": r["delta"], "cut": c["key"], "tag": r["tag"],
                "cut_poss": r["cut_poss"]})
    out.sort(key=lambda x: -abs(x["delta"]))
    return out[:top]
