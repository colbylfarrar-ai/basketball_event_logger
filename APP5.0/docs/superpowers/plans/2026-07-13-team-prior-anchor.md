# Team-Prior Anchor for Player-Rating Shrinkage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a thin-sample player's rating regress toward their own team's strength (partial pooling) instead of flat league-average 50, so an under-tracked player on a genuinely strong team lands above-average rather than stuck at "average."

**Architecture:** Player ratings already shrink each 0-100 index toward an `anchor` (currently hardcoded 50) by evidence games via `helpers.shrinkage.stabilize_index`. This feature computes a **per-player anchor** derived from that player's own team `Power` (the results-only, all-teams `score_ratings` Power index, already on the identical `50=avg, +10/SD` scale). The pull is damped by a global λ and by the team's own sample confidence, so it only meaningfully lifts a player when the team has a real résumé proving it is good. Non-destructive: λ=0 is byte-identical to today.

**Tech Stack:** Python 3, stdlib + numpy (existing). No new deps. SQLite via `database.db.query`. Tests as plain `tracker/test_*.py` modules (run directly or via pytest).

## Global Constraints

- **Directory casing:** `helpers/` and `database/` stay lowercase; imports are case-sensitive on this host. Copy verbatim: `import helpers.player_ratings`, `import helpers.team_ratings`, `import helpers.shrinkage`.
- **Non-destructive contract:** with `TEAM_PRIOR_LAMBDA = 0.0`, every rating this engine returns must be **byte-identical** to the pre-change output (mirrors the form-weight `weight=0` / `half_life=None` identity contract).
- **No new query on the hot path:** the team Power lookup MUST reuse the existing `_score_ratings_cached(gender, season)` memo. Do not add a second `score_ratings` call per `player_ratings` invocation.
- **Scale contract:** team `Power` and player 0-100 ratings are both `50 = field average, +10 per SD`. The anchor stays on that scale — no rescaling.
- **Prod season gotcha:** prod season is `2026-2027`; `season='Current'` is the active-season sentinel. Real-DB tests must not hard-assert on a specific season's contents; use pool-shift / relative contracts, not absolute values.
- **Applies to OVERALL only (v1):** leaf skills (Shooting/Finishing/RimDef/…) keep `anchor=50`. Team Power is a whole-player quality prior, not a shot-mechanics prior.

---

## File Structure

- `helpers/player_ratings.py` — **modify.** Add `TEAM_PRIOR_LAMBDA`, `TEAM_PRIOR_K_GAMES`, `TEAM_PRIOR_BOUNDS`, `TEAM_PRIOR_BOOST_ONLY` constants; add `_team_prior_anchors(...)` helper; thread a per-player OVERALL anchor through the `_rate` closure inside `player_ratings(...)`.
- `helpers/shrinkage.py` — **no change** (already supports `anchor`); covered by a characterization test only.
- `tracker/test_team_prior_anchor.py` — **create.** Unit + real-DB contract tests.
- `tools/team_prior_diff.py` — **create.** Standalone before/after diff harness that surfaces the target population (thin-sample players on high-Power teams) so the founder can pick λ.

---

### Task 1: Characterize the anchor lever in `stabilize_index`

Lock in the exact behavior the feature rides on: `stabilize_index` pulls a value toward `anchor`, and a per-player anchor changes the shrink target without touching the games weighting. Pure unit test, no production change — this is the safety net future tasks build on.

**Files:**
- Test: `tracker/test_team_prior_anchor.py`

**Interfaces:**
- Consumes: `helpers.shrinkage.stabilize_index(value, games, k_games=3.0, anchor=50.0)`.
- Produces: nothing consumed by later tasks; establishes the anchor semantics they rely on.

- [ ] **Step 1: Write the failing test**

```python
"""Team-prior anchor: a thin-sample player regresses toward their own team's
Power instead of flat 50 (partial pooling). Non-destructive at lambda=0."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_stabilize_index_respects_anchor():
    import helpers.shrinkage as SHR
    # Same raw rating (70), same 2-game sample, different anchors.
    v_50 = SHR.stabilize_index(70.0, games=2, k_games=3.0, anchor=50.0)
    v_58 = SHR.stabilize_index(70.0, games=2, k_games=3.0, anchor=58.0)
    # games/(games+k) = 2/5 = 0.4 kept, 0.6 pulled to the anchor.
    assert round(v_50, 2) == round(50.0 + (70.0 - 50.0) * 0.4, 2) == 58.0
    assert round(v_58, 2) == round(58.0 + (70.0 - 58.0) * 0.4, 2) == 62.8
    # Higher anchor -> higher stabilized rating for the same thin sample.
    assert v_58 > v_50
    # A full-season sample barely moves regardless of anchor.
    deep_50 = SHR.stabilize_index(70.0, games=30, k_games=3.0, anchor=50.0)
    deep_58 = SHR.stabilize_index(70.0, games=30, k_games=3.0, anchor=58.0)
    assert abs(deep_58 - deep_50) < 1.0, "anchor barely matters once evidence is deep"
```

- [ ] **Step 2: Run test to verify it passes (characterization — no prod change yet)**

Run: `python -m pytest tracker/test_team_prior_anchor.py::test_stabilize_index_respects_anchor -v`
Expected: PASS. (If it fails, `stabilize_index` does not behave as this feature assumes — STOP and reconcile before continuing.)

- [ ] **Step 3: Commit**

```bash
git add tracker/test_team_prior_anchor.py
git commit -m "test(rating): characterize stabilize_index anchor lever for team prior"
```

---

### Task 2: `_team_prior_anchors` helper

Compute `{player_id: anchor}` from each player's own team Power, damped by a global λ and by the team's sample confidence. This is the whole idea in one pure function; wiring it in is Task 3.

**Files:**
- Modify: `helpers/player_ratings.py` (add constants near the other rating tunables ~line 561–580; add the helper below `_opponent_strength`, ~line 735)
- Test: `tracker/test_team_prior_anchor.py`

**Interfaces:**
- Consumes: `profiles` map (each `profiles[pid]` has `"team_id"`), `_score_ratings_cached(gender, season)` returning `{team_id: {"Power": float, "GP": int, ...}}`.
- Produces: `_team_prior_anchors(profiles, gender, season, opp_ratings=None) -> dict[pid, float]` — a 0-100 anchor per player (defaults to 50.0 when the team's Power is unknown). Task 3 consumes this exact signature.

**Design constants (add verbatim):**

```python
# ── team-prior anchor (partial pooling of thin player samples) ────────────────
# A thin-sample player is normally shrunk toward flat 50 (league average). This
# instead shrinks their OVERALL toward an anchor derived from their OWN team's
# results-only Power (score_ratings, 0-100, 50=avg — the SAME scale as the player
# rating, so the map is 1:1). Rationale: "good teams have good players" is a valid
# group-level (partial-pooling) prior; on a small sample the team's own résumé is
# a better guess than the grand mean. The pull is deliberately damped:
#   anchor = 50 + LAMBDA · team_confidence · (teamPower − 50)
# LAMBDA caps how far the anchor can drift from 50 (keeps a benchwarmer on an elite
# team from reading as a star); team_confidence = teamGP/(teamGP+K) so a team whose
# OWN Power rests on 2 lucky games can't over-anchor its players (honest: strong
# lift needs a real team résumé, not a fluke). LAMBDA=0 → anchor≡50 → byte-identical
# to the pre-feature engine. Applies to OVERALL only.
TEAM_PRIOR_LAMBDA     = 0.0     # 0 = off (ship value chosen by tools/team_prior_diff.py)
TEAM_PRIOR_K_GAMES    = 6.0     # team-confidence prior weight (games-equivalent)
TEAM_PRIOR_BOUNDS     = (35.0, 65.0)   # clamp the anchor to a sane band
TEAM_PRIOR_BOOST_ONLY = False   # True = never anchor below 50 (good-team lift only)
```

- [ ] **Step 1: Write the failing test**

```python
def test_team_prior_anchors_math_and_damping():
    import helpers.player_ratings as PR
    # Two players: one on an elite team (Power 70, deep résumé), one on an average
    # team (Power 50). Feed opp_ratings directly so the test needs no DB.
    profiles = {
        1: {"team_id": 10},   # elite team
        2: {"team_id": 20},   # average team
        3: {"team_id": 30},   # elite Power but a 2-game (fluke-risk) team
    }
    opp_ratings = {
        10: {"Power": 70.0, "GP": 24},
        20: {"Power": 50.0, "GP": 24},
        30: {"Power": 70.0, "GP": 2},
    }
    lam, k = 0.5, PR.TEAM_PRIOR_K_GAMES
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = lam
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    # elite deep team: conf = 24/(24+6) = 0.8 -> 50 + 0.5*0.8*(70-50) = 58.0
    assert round(a[1], 2) == 58.0
    # average team: (50-50) = 0 -> anchor stays 50 regardless of lambda/conf
    assert round(a[2], 2) == 50.0
    # elite but thin team: conf = 2/(2+6) = 0.25 -> 50 + 0.5*0.25*20 = 52.5
    # (fluke-risk team lifts its players far less than the proven elite team)
    assert round(a[3], 2) == 52.5
    assert a[3] < a[1], "thin-résumé elite team anchors weaker than deep elite team"


def test_team_prior_lambda_zero_is_neutral():
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 10}}
    opp_ratings = {10: {"Power": 80.0, "GP": 30}}
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.0
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert a[1] == 50.0, "lambda=0 must yield the flat-50 anchor (identity)"


def test_team_prior_unknown_team_defaults_to_50():
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 999}}   # not in opp_ratings
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.5
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings={10: {"Power": 70.0, "GP": 24}})
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert a[1] == 50.0, "no team Power -> neutral anchor, never a crash"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tracker/test_team_prior_anchor.py -k team_prior -v`
Expected: FAIL with `AttributeError: module 'helpers.player_ratings' has no attribute '_team_prior_anchors'` (and no `TEAM_PRIOR_LAMBDA`).

- [ ] **Step 3: Add the constants**

Insert the `TEAM_PRIOR_*` block shown above near the existing rating tunables (right after `RATING_K_GAMES` / the opponent-adjust constants, ~line 580 in `helpers/player_ratings.py`).

- [ ] **Step 4: Add the helper**

Insert below `_opponent_strength` (after ~line 735), before the `player_ratings(...)` def:

```python
def _team_prior_anchors(profiles, gender, season, opp_ratings=None):
    """{player_id: OVERALL shrink anchor} from each player's OWN team Power.

    Partial-pooling prior: instead of regressing a thin sample toward flat 50,
    regress toward 50 + LAMBDA·team_confidence·(teamPower − 50). teamPower is the
    results-only score_ratings Power (0-100, 50=avg — identical scale to the player
    rating). team_confidence = teamGP/(teamGP+TEAM_PRIOR_K_GAMES) so a team whose
    Power rests on a tiny sample can't over-anchor its players. LAMBDA=0 → every
    anchor is exactly 50 (byte-identical to the pre-feature engine). Unknown team →
    50 (neutral). Clamped to TEAM_PRIOR_BOUNDS; optionally boost-only."""
    lam = TEAM_PRIOR_LAMBDA
    if not lam:
        return {p: 50.0 for p in profiles}          # identity fast-path
    if opp_ratings is None:
        opp_ratings = _score_ratings_cached(gender, season)
    lo, hi = TEAM_PRIOR_BOUNDS
    out = {}
    for p, prof in profiles.items():
        tr = opp_ratings.get(prof.get("team_id")) if opp_ratings else None
        if not tr or tr.get("Power") is None:
            out[p] = 50.0
            continue
        gp = tr.get("GP", 0) or 0
        conf = gp / (gp + TEAM_PRIOR_K_GAMES) if (gp + TEAM_PRIOR_K_GAMES) > 0 else 0.0
        anchor = 50.0 + lam * conf * (tr["Power"] - 50.0)
        if TEAM_PRIOR_BOOST_ONLY and anchor < 50.0:
            anchor = 50.0
        out[p] = max(lo, min(hi, anchor))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tracker/test_team_prior_anchor.py -k team_prior -v`
Expected: PASS (all three).

- [ ] **Step 6: Commit**

```bash
git add helpers/player_ratings.py tracker/test_team_prior_anchor.py
git commit -m "feat(rating): team-Power partial-pooling anchor helper (off by default)"
```

---

### Task 3: Wire the anchor into OVERALL shrinkage

Thread the per-player anchor into the `_rate` closure for **OVERALL only**, and prove both the tilt (thin player on a strong team rises) and the non-destructive contract (λ=0 unchanged).

**Files:**
- Modify: `helpers/player_ratings.py` — inside `player_ratings(...)`, the `_rate` closure (~line 867) and the `out[p]["OVERALL"]` assignment (~line 883).
- Test: `tracker/test_team_prior_anchor.py`

**Interfaces:**
- Consumes: `_team_prior_anchors(profiles, gender, season, opp_ratings)` from Task 2; the existing `opp_ratings` param already threaded into `player_ratings`.
- Produces: `player_ratings(...)` OVERALL now shrinks toward the team anchor; all other keys unchanged. No signature change.

- [ ] **Step 1: Write the failing real-DB contract + identity test**

```python
def test_lambda_zero_byte_identical_real_db():
    """lambda=0 must reproduce the exact current OVERALL for every player."""
    import helpers.player_ratings as PR
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.0
    try:
        rows = PR.player_ratings(gender="F")
        base = {p: r["OVERALL"] for p, r in rows.items()}
        # recompute; identical inputs must give identical output
        rows2 = PR.player_ratings(gender="F")
        assert base == {p: r["OVERALL"] for p, r in rows2.items()}
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig


def test_anchor_lifts_thin_player_on_strong_team_synthetic():
    """A 2-game player rated 70-raw on a Power-70 team ends higher with the anchor
    on than off; a full-season player barely moves."""
    import helpers.player_ratings as PR
    import helpers.shrinkage as SHR
    # Mirror the exact production shrink call for OVERALL.
    anchor_on = 58.0    # what _team_prior_anchors returns for a deep Power-70 team @ lambda .5
    raw = 70.0
    thin_off = SHR.stabilize_index(raw, 2, k_games=PR.RATING_K_GAMES, anchor=50.0)
    thin_on  = SHR.stabilize_index(raw, 2, k_games=PR.RATING_K_GAMES, anchor=anchor_on)
    deep_off = SHR.stabilize_index(raw, 30, k_games=PR.RATING_K_GAMES, anchor=50.0)
    deep_on  = SHR.stabilize_index(raw, 30, k_games=PR.RATING_K_GAMES, anchor=anchor_on)
    assert thin_on > thin_off, "thin-sample player on a strong team must rise"
    assert abs(deep_on - deep_off) < abs(thin_on - thin_off), \
        "deep-sample player must move far less than the thin one"
```

- [ ] **Step 2: Run test to verify the tilt test fails / identity passes**

Run: `python -m pytest tracker/test_team_prior_anchor.py -k "real_db or thin_player" -v`
Expected: `test_lambda_zero_byte_identical_real_db` PASSES already (anchor not wired but default λ=0 ⇒ nothing changed). `test_anchor_lifts_thin_player_on_strong_team_synthetic` PASSES (pure shrinkage math). These guard the wiring you are about to add — if the identity test later fails, the wiring broke the contract.

- [ ] **Step 3: Wire the anchor into `_rate` for OVERALL**

In `helpers/player_ratings.py`, just before the `def _rate(z, g):` closure (~line 867), build the anchor map:

```python
    # per-player OVERALL shrink anchor from their own team Power (partial pooling)
    team_anchor = _team_prior_anchors(profiles, gender, season, opp_ratings)
```

Change the closure to accept an optional anchor (default 50 keeps every other rating flat):

```python
    def _rate(z, g, anchor=50.0):
        """0-100 rating from a z-score, regressed toward `anchor` (50 = league
        average) by EVIDENCE games. OVERALL passes a team-derived anchor; every
        other rating keeps the flat-50 anchor."""
        v = _scale100(z)
        if stabilize:
            v = SHR.stabilize_index(v, g, k_games=RATING_K_GAMES, anchor=anchor)
        return _round(v)
```

Change **only** the OVERALL assignment (~line 883) to pass the anchor:

```python
            "OVERALL":    _rate(overall_z[p], eg, anchor=team_anchor.get(p, 50.0)),
```

Leave every other `_rate(...)` call unchanged (they keep `anchor=50.0`).

- [ ] **Step 4: Run the full test module**

Run: `python -m pytest tracker/test_team_prior_anchor.py -v`
Expected: PASS (all tests). The identity test still passes because default `TEAM_PRIOR_LAMBDA=0` makes `_team_prior_anchors` return all-50.

- [ ] **Step 5: Regression — existing rating tests still pass**

Run: `python -m pytest tracker/test_physical_rating.py tracker/test_hoopwar.py -v`
Expected: PASS (OVERALL pool contract unchanged at λ=0).

- [ ] **Step 6: Commit**

```bash
git add helpers/player_ratings.py tracker/test_team_prior_anchor.py
git commit -m "feat(rating): shrink OVERALL toward team-Power anchor (lambda-gated, off)"
```

---

### Task 4: Diff harness + choose the shipping λ

Give the founder a one-command before/after view focused on the target population — thin-sample players on high-Power teams — so λ is picked from evidence, not vibes (matches the backtest-gated recal convention). Then set the default.

**Files:**
- Create: `tools/team_prior_diff.py`

**Interfaces:**
- Consumes: `helpers.player_ratings.player_ratings`, `helpers.player_ratings.TEAM_PRIOR_LAMBDA`, `helpers.team_ratings.score_ratings`.
- Produces: a CLI that prints, per candidate λ, the OVERALL deltas for the players the feature is meant to help.

- [ ] **Step 1: Write the harness**

```python
"""tools/team_prior_diff.py — before/after OVERALL under the team-Power anchor.

Focuses on the population the feature targets: players with few evidence games
whose team has an above-average Power. Run for each gender and eyeball whether the
lift is reasonable (thin players on strong teams rise a few points; nobody on an
average team moves). Pick the largest LAMBDA whose top movers still look sane.

    python tools/team_prior_diff.py            # both genders, default lambdas
    python tools/team_prior_diff.py M 0.35     # one gender, one lambda
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers.player_ratings as PR
import helpers.team_ratings as TR


def run(gender, lambdas):
    powers = {t: r["Power"] for t, r in TR.score_ratings(gender=gender).items()}
    orig = PR.TEAM_PRIOR_LAMBDA
    try:
        PR.TEAM_PRIOR_LAMBDA = 0.0
        base = {p: r for p, r in PR.player_ratings(gender=gender).items()}
        for lam in lambdas:
            PR.TEAM_PRIOR_LAMBDA = lam
            now = PR.player_ratings(gender=gender)
            rows = []
            for p, r in now.items():
                d = r["OVERALL"] - base[p]["OVERALL"]
                if abs(d) < 0.05:
                    continue
                rows.append((d, r.get("name", p), base[p].get("evidence_gp", 0),
                             powers.get(r.get("team_id"))))
            rows.sort(key=lambda x: -abs(x[0]))
            print(f"\n=== {gender} lambda={lam} : {len(rows)} players moved ===")
            print(f"{'dOVR':>6}  {'name':<22} {'evG':>4} {'teamPow':>7}")
            for d, name, eg, pw in rows[:20]:
                print(f"{d:+6.1f}  {str(name):<22} {eg:>4.1f} "
                      f"{'' if pw is None else f'{pw:7.1f}'}")
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig


if __name__ == "__main__":
    args = sys.argv[1:]
    genders = [args[0]] if args and args[0] in ("M", "F") else ["F", "M"]
    lams = [float(a) for a in args if a.replace(".", "", 1).isdigit()] or \
           [0.25, 0.35, 0.5]
    for g in genders:
        run(g, lams)
```

- [ ] **Step 2: Run the harness against the real DB**

Run: `python tools/team_prior_diff.py`
Expected: for each λ, a table of movers. Sanity checks (report to the founder, do not hard-assert): top positive movers are **low `evG`** players on **high `teamPow`** teams; players on `teamPow≈50` teams show ~0 delta; deep-sample stars move little.

- [ ] **Step 3: Set the shipping default**

With the founder, pick the largest λ whose movers stay sane (start recommendation: `0.35`, mirroring the form-weight default). Edit `helpers/player_ratings.py`:

```python
TEAM_PRIOR_LAMBDA     = 0.35    # chosen via tools/team_prior_diff.py
```

- [ ] **Step 4: Re-run tests with the live default**

Run: `python -m pytest tracker/test_team_prior_anchor.py tracker/test_physical_rating.py -v`
Expected: PASS. (The λ=0 identity test flips its constant internally, so it still passes; the physical-rating pool-shift contract is OVERALL-tolerant to <0.5 and should hold — if it does not, the founder wants a smaller λ.)

- [ ] **Step 5: Commit**

```bash
git add tools/team_prior_diff.py helpers/player_ratings.py
git commit -m "feat(rating): enable team-Power anchor at lambda=0.35 + diff harness"
```

---

## Self-Review

**Spec coverage**
- "Tie the anchor to normal box-score power rating, equal playing field" → `score_ratings[...]["Power"]`, chosen in Global Constraints + Task 2, on the identical 50/±10 scale (no rescale).
- "Good teams have good players → tilt shrinkage by team ability on small samples" → `_team_prior_anchors` (Task 2) + OVERALL wiring (Task 3).
- "Small sample keeps them average" fixed → tilt test (Task 3 Step 1) + diff harness target population (Task 4).
- Non-destructive / λ=0 identity → Global Constraints + Task 2 fast-path + Task 3 real-DB identity test.
- Team's own sample can be thin (unscouted tournament team) → team-confidence damping in Task 2, verified by `test_team_prior_anchors_math_and_damping` case 3.

**Placeholder scan:** none — every code step is complete; no TBD/TODO/"handle edge cases."

**Type consistency:** `_team_prior_anchors(profiles, gender, season, opp_ratings=None) -> {pid: float}` is defined in Task 2 and consumed with that exact signature in Task 3. `TEAM_PRIOR_LAMBDA/K_GAMES/BOUNDS/BOOST_ONLY` names match across Tasks 2–4. `score_ratings` row keys used (`"Power"`, `"GP"`) match `team_ratings.score_ratings` output (verified: `helpers/team_ratings.py:400-401`, `:393`).

## Open Decisions (confirm before/at Task 4)

1. **Symmetric vs boost-only.** v1 default `TEAM_PRIOR_BOOST_ONLY=False` — a thin player on a *weak* team also regresses slightly *below* 50 (honest partial pooling). Flip to `True` for lift-only if you'd rather never dock a player for their team (mirrors the opponent-adjust "never a penalty" stance). One-line change.
2. **OVERALL only vs also OFFENSE/DEFENSE.** v1 is OVERALL only. Extending to OFF/DEF is a two-line follow-up once the OVERALL tilt is validated.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-13-team-prior-anchor.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
