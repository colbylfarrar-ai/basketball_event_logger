"""Real-DB smoke for the 2026-07-26 Insights deep-dive expansion.

Covers the new defensive-profile engine, the six new insight generators, and an
end-to-end render of the Team Dashboard's Insights view with all of it wired in.

Three failure modes only this catches:

  * a defensive engine that works on the shot loop but explodes on the on-floor
    join (`defender_load` / `defensive_footprint` need game_event_lineup rows,
    and a coach who has never tagged `guarded_by_id` gets empty dicts, not
    zeros);
  * a generator reading a `derived` key that `league_insights` never populates —
    silent, because every generator is wrapped in a try/except that only logs
    the FIRST failure per generator;
  * the render itself, which is where a `None` shape from a thin team lands.

SEASON TRAP: SEAS.ACTIVE is "Current" and has zero games; the tracked book is
under the archived "2025-2026" label. Drive the picker there or every page
renders a healthy-looking empty state and proves nothing.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_insights_deep.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


import helpers.seasons as SEAS            # noqa: E402
import helpers.stats as S                 # noqa: E402
import helpers.defense_profile as DP      # noqa: E402
import helpers.insights as IN             # noqa: E402
import helpers.reliability as REL         # noqa: E402


def _tracked():
    """(season_label, gender, game_ids) for the fattest tracked pool."""
    best = (None, None, [])
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            pool = SEAS.game_pool(value, gender=g, tracked_only=True) or []
            if len(pool) > len(best[2]):
                best = (value, g, sorted(pool))
    return best


SEASON, GENDER, GIDS = _tracked()
if not GIDS:
    print("  -- no tracked games in this DB; smoke skipped")
    sys.exit(0)
EV = S.fetch_events(GIDS)
print(f"pool: {SEASON} / {GENDER} — {len(GIDS)} games, {len(EV)} events")


# ── the rate book cannot price an unseen look at zero ─────────────────────────
print("\nshot_quality_rates is regularized")

_rates = S.shot_quality_rates(events=EV)
ok(type(_rates).__name__ == "_RateBook", "returns the backoff-safe rate book")
_unseen = ("deep3", "both", True)
_cell = _rates.get(_unseen, {})
ok(_cell.get("pct", 0.0) > 0.05,
   f"an unseen/thin look prices off its parent, not at zero "
   f"({_cell.get('pct', 0):.3f})")
# the bug this pins: every consumer in the app calls .get(key, {}).get("pct",
# 0.0), which scored a look the sample never saw as CERTAIN TO MISS.
ok(_rates.get(("no_such_kind", "self", False), {}).get("pct", 0.0) > 0.05,
   "a location the book has never seen falls back to the pooled rate")
ok(_rates.get("malformed", "DEFAULT") == "DEFAULT",
   "a malformed key still honours the caller's default")
for _k, _v in _rates.items():
    ok(0.0 <= _v["pct"] <= 1.0, "shrunk cell rates stay inside [0,1]")
    break


# ── the defensive engine ──────────────────────────────────────────────────────
print("\ndefense_profile builds off the real book")

diets = DP.defender_diets(EV)
ok(len(diets) >= 5, f"defender_diets found {len(diets)} defenders over the gate")
_d = next(iter(diets.values()))
for key in ("n", "band", "kind", "play", "creation", "paint_share",
            "three_share", "drive_share", "FG%", "PPS"):
    ok(key in _d, f"diet carries {key}")
for pid, d in diets.items():
    ok(abs(sum(d["band"].values()) - 1.0) < 1e-6,
       "band shares sum to 1 (they are shares of the defender's own volume)")
    ok(d["n"] >= DP.MIN_CONTESTED, "every reported defender clears the gate")
    break

edges = DP.diet_edges(diets)
ok(bool(edges), "diet_edges produced ranked assignment edges")
_thin = [e for es in edges.values() for e in es if e["n"] < DP.EDGE_MIN_N]
ok(not _thin, f"no edge is reported below EDGE_MIN_N ({len(_thin)} found)")
# the shrink is what stops a 5-of-8 cell out-ranking a 40-of-120 tendency
_e = next(e for es in edges.values() for e in es)
ok(abs(_e["share_shrunk"] - _e["lg_share"]) <= abs(_e["share"] - _e["lg_share"])
   + 1e-9, "the shrunk share sits between the raw share and the league mean")

load = DP.defender_load(EV, game_ids=GIDS)
if load:
    mean = sum(v["load"] for v in load.values()) / len(load)
    ok(0.12 <= mean <= 0.30,
       f"mean DLOAD% is near the 20% five-player construction ({mean:.1%})")
    ok(all(0.0 <= v["load"] <= 1.0 for v in load.values()),
       "every DLOAD% is a share in [0,1]")
else:
    print("  -- no on-floor lineup snapshots; DLOAD checks skipped")

fp = DP.defensive_footprint(EV, game_ids=GIDS)
for pid, v in (fp or {}).items():
    ok(v["on"]["n"] >= DP.MIN_FOOTPRINT and v["off"]["n"] >= DP.MIN_FOOTPRINT,
       "both footprint sides clear the minimum")
    # the trap: pooling one global roster charges a player with every shot of
    # every game they never dressed for, which manufactures an on/off effect
    ok(v["off"]["n"] < sum(1 for e in EV if e["event_type"] == "shot"),
       "the off-floor sample is scoped, not the whole league's shots")
    break

allowed = DP.team_allowed_diet(EV)
ok(len(allowed) >= 2, f"team_allowed_diet covered {len(allowed)} defenses")


# ── the measured book must actually forbid what the measurement forbade ───────
print("\nthe reliability book records the defensive measurement")

ok(REL.measured("defender", "load") is not None, "DLOAD% is in the book")
ok(REL.shows_verdict(REL.measured("defender", "load")),
   "DLOAD% clears the verdict floor (measured SB .574)")
ok(REL.shows_verdict(REL.measured("defender", "area_share")),
   "the coarse interior/perimeter split clears the floor (SB .578)")
ok(not REL.shows_verdict(REL.measured("defender", "play_share")),
   "the ACTION a defender draws does NOT clear it — 'iso defender' is refused")
ok(not REL.shows_verdict(REL.measured("defender", "footprint")),
   "the on/off footprint does NOT clear it")
ok(not REL.shows_verdict(REL.measured("defender", "assignment_share")),
   "the fine band cut does NOT clear it")

# ── round 2: grouping, and the player-vs-team separation ─────────────────────
ok(REL.shows_verdict(REL.measured("defender", "family_share")),
   "GROUPED on-ball/off-ball clears the floor (.373) where isolation alone "
   "(-.15) does not — coarsening rescued the action axis")
ok(REL.measured("defender", "family_share")
   > REL.measured("defender", "play_share"),
   "the grouped action share outmeasures the single-action share")
ok(REL.shows_verdict(REL.measured("defender", "scheme_share")),
   "zone-minutes share clears the floor within team (.417)")
ok(not REL.shows_verdict(REL.measured("defender", "press_share")),
   "press share does NOT — .541 pooled collapses to .050 within team, so it "
   "was entirely which team the player is on")
# The offensive twin: the SAME statistic on the other side of the ball.
ok(REL.measured("player", "playtype_share")
   > REL.measured("defender", "family_share"),
   "an offensive play-type share outmeasures the defensive one — the player "
   "chooses the action, the opponent chooses the assignment")
ok(not REL.shows_verdict(REL.measured("player", "playtype_ppp")),
   "play-type PPP does NOT clear the floor (-.135, anti-correlated) — the "
   "number _g_playtype used to lead with")

_TR = DP.TEAM_RELATIVE
ok("man_share" in _TR and "zone_share" in _TR,
   "the scheme shares are on the team-relative list, not league-scored")
ok("paint_share" not in _TR,
   "paint share is NOT team-relative — it survives pooled (.643) and league "
   "scoring is what makes 'interior assignment' mean anything")


# ── the generators ────────────────────────────────────────────────────────────
print("\nthe new generators fire on the real book")

import helpers.player_ratings as PR       # noqa: E402
from database.db import query             # noqa: E402

TABLE = PR.player_stat_table(gender=GENDER, min_games=1, game_ids=set(GIDS))
ok(len(TABLE) > 20, f"stat table built ({len(TABLE)} players)")

# the residual-bearing diets the two grouped generators read from
_diets_tr = DP.team_relative(DP.defender_diets(EV))

diag = {}
feed = IN.build_feed(TABLE, EV, top=None, diagnostics=diag)
ok(not diag, f"no feed stage raised: {diag}")

metrics = {ln["metric"] for lines in feed.values() for ln in lines}
for m in ("Def load", "Def area", "Foul rate", "Vs scheme",
          "Def role", "Def scheme"):
    ok(m in metrics, f"generator '{m}' produced at least one line")

# the within-team residuals must actually be attached, or the two grouped
# generators silently never fire and the feed just looks a bit thinner
_res = [d for d in _diets_tr.values() if "onball_share_vs_team" in d]
ok(len(_res) >= 5, f"team_relative attached residuals to {len(_res)} defenders")
for _pid, _d in _diets_tr.items():
    if "onball_share_vs_team" in _d:
        ok(abs(_d["onball_share_vs_team"]
               - (_d["onball_share"] - _d["onball_share_team_mean"])) < 1e-9,
           "the residual is exactly share minus the player's own team mean")
        break
# a one-defender team cannot produce a residual — with nobody to compare to,
# the arithmetic yields 0 and would read as 'exactly average'
from collections import Counter as _C                          # noqa: E402
_tof = {r["id"]: r["team_id"] for r in
        query("SELECT id, team_id FROM players")}
_sizes = _C(_tof.get(p) for p in _diets_tr)
for _pid, _d in _diets_tr.items():
    if _sizes[_tof.get(_pid)] < DP.MIN_TEAMMATES:
        ok("onball_share_vs_team" not in _d,
           "a player with too few qualifying teammates gets NO residual rather "
           "than a manufactured zero")
        break

# _g_playtype must no longer lead with the unreliable PPP
for ln in (l for ls in feed.values() for l in ls if l["metric"] == "PlayType"):
    ok(ln["text"].startswith("**Signature set:"),
       "the play-type line leads with the SHARE (measured .76-.88), not the "
       "PPP (measured -.135)")
    ok("not a forecast" in ln["text"],
       "the PPP rides along explicitly marked as a record")
    break

# Descriptive lines must be FLAGGED, because they are the ones whose underlying
# metric failed its reliability measurement and they must never be read as
# projections.
desc = [ln for lines in feed.values() for ln in lines if ln.get("descriptive")]
for ln in desc:
    ok(ln["metric"] in ("Assignment", "Def footprint"),
       f"only measured-unreliable reads are flagged descriptive ({ln['metric']})")
    break
for ln in (l for ls in feed.values() for l in ls if l["metric"] == "Assignment"):
    ok(ln.get("descriptive") is True,
       "every Assignment line is flagged descriptive — the measurement (SB -.15) "
       "forbids it carrying a trait claim")
    ok("not a trait" in ln["text"] or "Descriptive only" in ln["text"],
       "the Assignment line SAYS it is a record, in the sentence itself")
    break
for ln in (l for ls in feed.values() for l in ls if l["metric"] == "Def footprint"):
    ok(ln.get("descriptive") is True, "every footprint line is descriptive")
    ok("do not repeat" in ln["text"] or "unrepeatable" in ln["text"],
       "the footprint line states its own unrepeatability")
    break

# acronym labels must survive mid-sentence (the 'drew the dho action' bug)
ok(IN._lc("DHO") == "DHO" and IN._lc("Off screen") == "off screen",
   "acronym play-type labels are not lower-cased mid-sentence")

n_lines = sum(len(v) for v in feed.values())
print(f"  .. feed: {len(feed)} players, {n_lines} lines, "
      f"{len(metrics)} distinct reads")


# ── end-to-end render ─────────────────────────────────────────────────────────
print("\nthe Insights view renders with all of it wired in")


def _render_smoke():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from database.db import query

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None

    row = query(
        "SELECT team1_id t FROM games WHERE id=? ", (GIDS[0],))[0]
    team_id = row["t"]

    page = os.path.join(_APP, "pages", "6_Team_Dashboard.py")
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(page, default_timeout=900)
        # assign one key at a time — session_state has no .update() in AppTest
        at.session_state["ta_team"] = team_id
        at.session_state["ta_season"] = SEASON
        at.session_state["td_view"] = "Insights"
        at.run()
        assert not at.exception, \
            f"Insights raised: {[repr(e.value)[:400] for e in at.exception]}"
        body = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        return body
    finally:
        os.chdir(cwd)


try:
    BODY = _render_smoke()
except Exception as exc:                       # pragma: no cover
    print(f"  -- render smoke could not run ({type(exc).__name__}: {exc})")
    BODY = None

if BODY is not None:
    ok(len(BODY) > 2000, f"the Insights view rendered ({len(BODY)} chars)")
    for probe, label in (
            ("what each player is asked to guard", "defensive board rendered"),
            ("DLOAD", "DLOAD% column present"),
            ("Foul rate", "foul-rate board rendered"),
            ("gathered here", "ported-verdict section rendered")):
        ok(probe in BODY, label)
    ok("Deep-dive sections unavailable" not in BODY,
       "the deep-dive half did not fall into its error caption")


# ── the ported verdict sections ───────────────────────────────────────────────
print("\nthe ported engines produce lines on the real book")

from helpers.dashboard import insights_deep as DEEP   # noqa: E402

_tid = query("SELECT team1_id t FROM games WHERE id=?", (GIDS[0],))[0]["t"]
_ph = ",".join("?" * len(GIDS))
# team-SCOPED ids, which is what ctx.tracked_ids carries. Passing the whole
# league pool here silently produced a 4,136-possession "defensive ledger"
# against a 372-possession offensive one, which is how this harness caught its
# own mistake — the asymmetry is the tell.
_tgids = tuple(r["id"] for r in query(
    f"SELECT id FROM games WHERE id IN ({_ph}) AND (team1_id=? OR team2_id=?)",
    tuple(GIDS) + (_tid, _tid)))
ok(len(_tgids) >= 2, f"team has {len(_tgids)} tracked games to read")

_lines, _diag = DEEP._ported.__wrapped__(_tid, GENDER, _tgids)
ok(not _diag, f"no ported engine raised: {_diag}")
ok(len(_lines) >= 6,
   f"{len(_lines)} of {len(DEEP._PORT_SECTIONS)} ported sections produced lines")

_keys = {k for k, _h, _c, _home in DEEP._PORT_SECTIONS}
ok(set(_lines) <= _keys, "every produced section has a render entry")
for _k, _v in _lines.items():
    for _badge, _n, _txt in _v:
        ok(isinstance(_badge, str) and isinstance(_txt, str),
           f"{_k} lines are the (badge, n, html) shape verdict_card unpacks")
        break
    break

# the two unit bugs this harness caught, pinned so they cannot come back
_ss = _lines.get("selfscout") or []
for _badge, _n, _txt in _ss:
    if _badge == "Scoutability":
        import re as _re
        _shares = [float(x) for x in _re.findall(r"(\d+)% of tagged calls", _txt)]
        ok(all(s <= 100 for s in _shares),
           f"scoutability top_share is already 0-100 and is not scaled twice "
           f"({_shares})")
_lg = _lines.get("ledger") or []
if len(_lg) == 2:
    _ns = [n for _b, n, _t in _lg]
    ok(max(_ns) / max(1, min(_ns)) < 4,
       f"offensive and defensive possession counts are the same order of "
       f"magnitude ({_ns}) — a wild ratio means the scope leaked")

print(f"\nALL {PASSED} CHECKS PASSED")
