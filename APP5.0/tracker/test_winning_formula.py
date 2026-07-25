"""
Winning-formula miner (spec 5l) — synthetic control, then the real book.

The load-bearing risk here is not a crash, it is a TAUTOLOGY sold as insight.
Four-factor differentials arithmetically reconstruct point margin, so a model
predicting margin from them will always look brilliant (LOO R^2 ~0.98 on the
live book). These checks pin the properties that make the surface honest:

  1. rows mirror exactly, so the fit cannot learn a phantom home edge;
  2. every factor is oriented higher-is-better BEFORE differencing;
  3. shares are comparable to Oliver's published weights;
  4. reconstruction R^2 is treated as a plumbing alarm, never as skill;
  5. the verdict refuses to speak when the data has not earned it.

Run: python tracker/test_winning_formula.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.winning_formula as WF                # noqa: E402
import helpers.stats as S                           # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def box(**kw):
    b = S._blank_box()
    b.update(kw)
    return S.finalize_box(b)


print("\n-- factor orientation: higher is better BEFORE differencing -------")

good = box(**{"2PA": 50, "2PM": 30, "3PA": 10, "3PM": 4, "TOV": 5,
              "ORB": 12, "DRB": 20, "FTM": 15, "FTA": 20, "AST": 20,
              "STL": 10, "BLK": 4})
bad = box(**{"2PA": 50, "2PM": 15, "3PA": 10, "3PM": 1, "TOV": 20,
             "ORB": 4, "DRB": 20, "FTM": 3, "FTA": 5, "AST": 5,
             "STL": 2, "BLK": 0})

fg, fb = WF._factor_set(good, bad), WF._factor_set(bad, good)
ok(fg["eFG"] > fb["eFG"], "better shooting scores higher on eFG")
ok(fg["TOV"] > fb["TOV"],
   "FEWER turnovers scores HIGHER (negated at source, not flipped later)")
ok(fg["ORB"] > fb["ORB"], "more offensive boards scores higher")
ok(fg["FTR"] > fb["FTR"], "more free throws per shot scores higher")
ok(fg["STK"] > fb["STK"], "more steals+blocks scores higher")
ok(fg["PACE"] == S.estimate_possessions(good),
   "pace is the possession level, not a rate")

zero = box()
fz = WF._factor_set(zero, zero)
ok(fz["TOV"] is None and fz["eFG"] is None,
   "an empty box yields None rather than a fake zero")

print("\n-- the four factors reconstruct margin (they must) ----------------")

ok(set(WF.CORE_KEYS) == {"eFG", "TOV", "ORB", "FTR"},
   "the model is exactly Oliver's four, so the shares stay comparable")
ok(sum(WF.OLIVER.values()) == 1.0, "Oliver's published weights sum to 1")
ok(set(WF.CONTEXT_KEYS).isdisjoint(WF.CORE_KEYS),
   "context factors never enter the fit")

print("\n-- against the live book ------------------------------------------")

rows = WF.game_rows(gender="F", season="2025-2026")
ok(len(rows) > 0, f"game_rows built ({len(rows)} team-games)")
ok(len(rows) % 2 == 0, "every game contributes exactly two rows")

by_game = {}
for r in rows:
    by_game.setdefault(r["game_id"], []).append(r)
mirrored = 0
for gid, pair in by_game.items():
    assert len(pair) == 2, f"FAIL: game {gid} produced {len(pair)} rows"
    a, b = pair
    assert a["margin"] == -b["margin"], f"FAIL: margins not mirrored in {gid}"
    for k in WF.CORE_KEYS:
        if a["diffs"][k] is None or b["diffs"][k] is None:
            continue
        assert abs(a["diffs"][k] + b["diffs"][k]) < 1e-9, \
            f"FAIL: {k} not mirrored in game {gid}"
    mirrored += 1
ok(mirrored == len(by_game),
   f"all {mirrored} games mirror exactly (no phantom home-court intercept)")

ok(all(r["won"] == (r["margin"] > 0) for r in rows),
   "won agrees with the sign of margin")
ok(all(r["diffs"]["PACE"] is None or r["diffs"]["PACE"] > 0 for r in rows),
   "pace is a positive level in every row")

fit = WF.league_formula(rows=rows)
print(f"  league: n_games={fit['n_games']} recon_r2={fit['recon_r2']} "
      f"valid={fit['valid']}")
ok(fit["enough"], f"cleared the {WF.MIN_LEAGUE_GAMES}-game minimum")
ok(fit["valid"], "reconstruction check passes — boxes and scores agree")
ok(fit["recon_r2"] > 0.8,
   f"R^2 is high BECAUSE this is an accounting identity ({fit['recon_r2']})")
ok(len(fit["factors"]) == 4, "four fitted factors")
ok(len(fit["context"]) == 4, "four context correlations, unfitted")
ok(all(f.get("beta") is not None for f in fit["factors"]),
   "every core factor carries a coefficient")
ok(all("beta" not in c for c in fit["context"]),
   "no context entry carries a coefficient — correlation only")

shares = [f["share"] for f in fit["factors"]]
ok(abs(sum(shares) - 1.0) < 1e-6, "shares sum to 1, like Oliver's weights")
ok(all(s >= 0 for s in shares), "no negative shares")
ok(fit["factors"] == sorted(fit["factors"], key=lambda f: -f["share"]),
   "factors come back ranked by share")
ok(all(abs(f["gap"] - (f["share"] - f["oliver"])) < 1e-9
       for f in fit["factors"]), "gap is share minus Oliver's weight")

for f in fit["factors"]:
    print(f"    {f['key']:<5} share {f['share'] * 100:5.1f}%  "
          f"oliver {f['oliver'] * 100:4.0f}%  beta {f['beta']:6.2f}  r {f['r']}")

v = WF.verdict(fit)
ok(v["kind"] == "verdict", "the league verdict fires")
ok("standard deviation" in v["text"],
   "the sentence names the unit, so the number is interpretable")
ok("Oliver" in v["text"], "the sentence anchors against the published weights")
ok(str(fit["n_games"]) in v["text"], "the sentence carries its sample size")
ok("cause" not in v["text"].lower() and "because" not in v["text"].lower(),
   "the sentence makes no causal claim")
print(f"    {v['text']}")

print("\n-- suppressors are surfaced, not hidden ---------------------------")
sup = WF.suppressors(fit)
print(f"    {len(sup)} factor(s) where the fit and the raw correlation clash: "
      f"{[s['key'] for s in sup]}")
ok(all((s["r"] > 0) != (s["beta"] > 0) for s in sup),
   "every reported suppressor really does disagree in sign")

print("\n-- honest refusals -------------------------------------------------")

thin = WF._fit(rows[:4], WF.MIN_LEAGUE_GAMES)
ok(not thin["enough"], "a 2-game slice does not clear the minimum")
tv = WF.verdict(thin)
ok(tv["kind"] == "thin", "and the verdict says so rather than guessing")
ok(str(WF.MIN_LEAGUE_GAMES) in tv["text"], "the refusal names what is needed")

ok(WF.verdict(None)["kind"] == "thin", "a missing fit refuses safely")
ok(WF._fit([], WF.MIN_LEAGUE_GAMES)["n_games"] == 0, "empty rows -> zero games")
ok(WF.game_rows(game_ids=[]) == [], "no game ids -> no rows")

broken = dict(fit, valid=False, recon_r2=0.1)
bv = WF.verdict(broken)
ok(bv["kind"] == "broken", "a failed reconstruction refuses to rank")
ok("box data" in bv["text"], "and points at the inputs, not at the league")

print("\n-- team scope ------------------------------------------------------")

counts = {}
for r in rows:
    counts[r["team_id"]] = counts.get(r["team_id"], 0) + 1
tid = max(counts, key=counts.get)
tf = WF.team_formula(tid, rows=rows)
ok(tf["n_games"] == counts[tid], f"team fit sees only its own games ({tf['n_games']})")
ok(tf["n_games"] < fit["n_games"], "and fewer than the league")
tvv = WF.verdict(tf, scope="your games")
ok(tvv["kind"] == "verdict", "the team verdict fires on the deepest team")
ok("your games" in tvv["text"], "and is scoped to them")
ok(" leans " not in tvv["text"],
   "the sentence avoids a verb that would disagree with a plural scope")
print(f"    {tvv['text']}")

thin_team = [t for t, c in counts.items() if c < WF.MIN_TEAM_GAMES]
if thin_team:
    t2 = WF.team_formula(thin_team[0], rows=rows)
    ok(WF.verdict(t2, scope="your games")["kind"] == "thin",
       f"a {t2['n_games']}-game team gets the refusal, not a ranking")

print(f"\n{PASS} checks passed.")
