"""
Shot kinds (depth axis) — the traps this file exists to pin.

1. THE CORNER-3 DEFINITION IS court_geom's, NOT A SECOND ONE. The spec proposed
   a separate |x|>=20 & y<=14 box for this module. Measured on the live book,
   that box disagrees with court_geom.is_corner_three on 101 of the 1,355
   located 3s, so shipping it would have put two definitions of "corner 3" in
   one app and made the shot-kind corner table disagree with every corner-3
   number already on screen. This file pins the delegation.

2. SHARES ARE TRUSTWORTHY, PER-PLAYER KIND RATES ARE NOT. Split-half on the live
   book (odd/even games, Spearman-Brown corrected): player floater SHARE r=.636
   (SB .778), player floater FG% r=.078 (SB .145). A player's floater percentage
   does not predict her own floater percentage. The module must therefore never
   hand back a per-player kind rate at a sample this book can reach, and the
   verdict must speak from shares.

3. A GATE ON SAMPLE IS NOT A GATE ON SIZE. With only the sample gate, five teams
   fired the headline verdict and four of them read "1 more floater than a
   league-average diet -- 1 point left on the floor, about 0.1 a game": teams
   sitting ON the league average being handed a season-changing sentence about
   nothing. Materiality is a separate bar and this file pins it.

4. AN APPROXIMATED COORDINATE IS NOT A LOCATION. mapped_shots() fills unlocated
   legacy shots with the ZONE CENTROID so the maps keep working. A centroid has
   a distance, so it would classify happily -- and a zone-C centroid would
   silently become "rim" for a shot nobody ever placed. Approx shots must
   classify as UNKNOWN.

Run: python tracker/test_shot_kinds.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.shot_kinds as SK                      # noqa: E402
import helpers.court_geom as CG                      # noqa: E402
import helpers.model_constants as MC                 # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def shot(x, y, value=2, make=False, pid=1, tid=1, approx=False):
    return {"x": x, "y": y, "value": value, "make": make, "guarded": False,
            "zone": "C", "player_id": pid, "team_id": tid,
            "dist": (CG.shot_distance(x, y) if x is not None else None),
            "approx": approx}


print("\n-- the depth boundaries ---------------------------------------------")

ok(SK.classify(0.0, CG.HOOP_Y + 1.0, 2) == "rim", "1 ft from the hoop is a rim shot")
ok(SK.classify(0.0, CG.HOOP_Y + 3.9, 2) == "rim", "just inside 4 ft is still rim")
ok(SK.classify(0.0, CG.HOOP_Y + 4.1, 2) == "floater", "just past 4 ft is a floater")
ok(SK.classify(0.0, CG.HOOP_Y + 9.9, 2) == "floater", "just inside 10 ft is a floater")
ok(SK.classify(0.0, CG.HOOP_Y + 10.1, 2) == "mid", "past 10 ft is a midrange")
ok(SK.classify(0.0, CG.HOOP_Y + SK.RIM_FT, 2) == "rim",
   "the rim boundary itself is inclusive on the better side")
ok(SK.classify(0.0, CG.HOOP_Y + SK.FLOATER_FT, 2) == "floater",
   "so is the floater boundary")

print("\n-- trap 1: corner 3s delegate to court_geom -------------------------")

# A point inside the doc's proposed box but NOT a corner under court_geom's
# real-arc geometry: |x| >= 20 and y <= 14, yet above the corner/arc join.
_x, _y = 20.5, 13.0
ok(abs(_x) >= 20.0 and _y <= 14.0, "test point sits inside the spec's 20/14 box")
ok(not CG.is_corner_three(_x, _y), "...but court_geom says it is not a corner")
ok(SK.classify(_x, _y, 3) == "abovebreak3",
   "shot_kinds follows court_geom, not the spec's box")

ok(SK.classify(22.0, CG.HOOP_Y, 3) == "corner3", "a true corner is a corner 3")
ok(SK.classify(0.0, CG.HOOP_Y + 22.0, 3) == "abovebreak3", "top of the key is above-break")
ok("CORNER_X" not in dir(SK) and "CORNER_Y" not in dir(SK),
   "no second corner constant exists in this module")

print("\n-- the 2/3 split comes from the logged tap, not geometry ------------")

# A shot logged as a 3 from inside the arc stays a 3 (the coach's call wins);
# the book is clean -- zero such rows on the live DB -- but the rule must hold.
ok(SK.classify(0.0, CG.HOOP_Y + 15.0, 3) == "abovebreak3",
   "logged as a 3 -> classified as a 3 even inside the arc")
ok(SK.classify(0.0, CG.HOOP_Y + 21.0, 2) == "mid",
   "logged as a 2 -> classified as a 2 even beyond the arc")

print("\n-- trap 4: approximated coordinates are not locations ---------------")

ok(SK.classify_shot(shot(0.0, CG.HOOP_Y + 1.0, approx=True)) == SK.UNKNOWN,
   "a zone-centroid approximation classifies as unknown, not rim")
ok(SK.classify_shot(shot(0.0, CG.HOOP_Y + 1.0)) == "rim",
   "...and a real tap at the same spot still classifies")
ok(SK.classify(None, None, 2) == SK.UNKNOWN, "a missing coordinate is unknown")

print("\n-- unknowns are counted, never silently dropped ---------------------")

t = SK.kind_table([shot(0.0, CG.HOOP_Y + 1.0), shot(None, None), shot(None, None)])
ok(t["_meta"]["total"] == 3, "every shot lands in the table")
ok(t["_meta"]["located"] == 1, "only the located one counts as located")
ok(abs(t["_meta"]["located_share"] - 1 / 3) < 1e-9, "coverage is reported")
ok(t["rim"]["share"] == 1.0,
   "shares are over LOCATED shots -- unknowns do not deflate every share")
ok(t[SK.UNKNOWN]["n"] == 2, "the unlocated shots are still there to report")

print("\n-- trap 2: per-player kind rates are refused ------------------------")

ok(SK.PLAYER_KIND_RATES_ARE_NOISE is True,
   "the module states outright that player kind rates are noise")
thin = SK.kind_table([shot(0.0, CG.HOOP_Y + 6.0, make=(i % 3 == 0))
                      for i in range(30)])
ok(thin["floater"]["n"] == 30, "the count is always returned")
ok(thin["floater"]["share"] == 1.0, "the share is always returned")
ok(thin["floater"]["fg"] is None,
   "the RATE is withheld below MIN_KIND_RATE_ATT")
ok(thin["floater"]["rated"] is False, "and the cell says so")

fat = SK.kind_table([shot(0.0, CG.HOOP_Y + 6.0, make=(i % 3 == 0))
                     for i in range(SK.MIN_KIND_RATE_ATT)])
ok(fat["floater"]["fg"] is not None, "at the gate the rate appears")

print("\n-- the reliability table is documented in the module ----------------")

for token in (".636", ".078", "split-half", "Spearman-Brown"):
    ok(token in SK.__doc__, f"docstring carries {token!r}")

print("\n-- gates are wired to the measurement -------------------------------")

ok(SK.MIN_PLAYER_SHARE_ATT == 20, "player share gate is 20 located attempts")
ok(SK.MIN_TEAM_SHARE_ATT == 80, "team share gate is 80 located attempts")
ok(SK.MIN_KIND_RATE_ATT > SK.MIN_PLAYER_SHARE_ATT,
   "a rate needs more evidence than a share")

_league = SK.kind_table(
    [shot(0.0, CG.HOOP_Y + 1.0, make=(i % 2 == 0)) for i in range(100)]
    + [shot(0.0, CG.HOOP_Y + 6.0, make=(i % 4 == 0)) for i in range(100)])
ok(abs(SK.conversion_value(_league) - (1.0 - 0.5)) < 1e-9,
   "conversion value is the rim/floater PPS gap")

print("\n-- trap 3: materiality is a separate bar from sample ----------------")

# 200 shots -- way past the team gate -- but a diet sitting ON the league share.
_at_league = [shot(0.0, CG.HOOP_Y + 6.0, tid=1) for _ in range(50)] \
    + [shot(0.0, CG.HOOP_Y + 1.0, tid=1) for _ in range(150)] \
    + [shot(0.0, CG.HOOP_Y + 6.0, tid=2) for _ in range(50)] \
    + [shot(0.0, CG.HOOP_Y + 1.0, tid=2) for _ in range(150)]
_d = SK.diet(team_id=1, shots=_at_league)
ok(_d["gated"] is True, "the sample gate passes at 200 located shots")
ok(SK.verdict(team_id=1, shots=_at_league, games=10) == [],
   "but a team AT the league diet is told nothing")

# Same volume, a genuinely bad diet.
_bad = [shot(0.0, CG.HOOP_Y + 6.0, tid=1) for _ in range(140)] \
    + [shot(0.0, CG.HOOP_Y + 1.0, make=True, tid=1) for _ in range(60)] \
    + [shot(0.0, CG.HOOP_Y + 6.0, tid=2) for _ in range(40)] \
    + [shot(0.0, CG.HOOP_Y + 1.0, make=True, tid=2) for _ in range(360)]
_v = SK.verdict(team_id=1, shots=_bad, games=10)
ok(len(_v) == 2, "a team with a real floater problem gets verdict + evidence")
ok(_v[0]["tone"] == "bad" and _v[1]["tone"] == "info",
   "verdict first, evidence under it")
ok("4 feet to the arc" in _v[0]["text"] and "layup" in _v[0]["text"],
   "the verdict is the points-on-the-table sentence, in the band's language")
ok("floater" in SK.verdict(team_id=1, shots=_bad, games=10,
                           taxonomy="kind")[0]["text"],
   "and still speaks 'floater' when asked for the kind taxonomy")
ok("league takes" in _v[1]["text"], "the evidence line carries the league diet")
ok("1 points" not in _v[0]["text"], "no '1 points' -- the plural agrees")

print("\n-- nothing is said below the sample gate ----------------------------")

ok(SK.verdict(team_id=1, shots=[shot(0.0, CG.HOOP_Y + 6.0, tid=1)] * 10) == [],
   "a 10-shot sample says nothing at all")
ok(SK.diet(team_id=1, shots=[shot(0.0, CG.HOOP_Y + 6.0, tid=1)] * 10)["gated"]
   is False, "and the diet reports itself as ungated")

print("\n-- the recal surface is registered ----------------------------------")

ok("shot_kinds.RIM_FT" in MC.REGISTRY, "RIM_FT is recal-able")
ok("shot_kinds.FLOATER_FT" in MC.REGISTRY, "FLOATER_FT is recal-able")
ok(not any(k.startswith("shot_kinds.CORNER") for k in MC.REGISTRY),
   "the corner boundary is NOT recal-able here -- court_geom owns it")

_coerce = MC.REGISTRY["shot_kinds.RIM_FT"][2]
ok(_coerce(4.0) == 4.0, "a sane override is accepted")
for bad in (0.0, 99.0, -3.0):
    try:
        _coerce(bad)
        raise AssertionError(f"FAIL: {bad} should have been rejected")
    except ValueError:
        pass
ok(True, "an out-of-range override is rejected, not applied")
ok("shot_kinds.DEEP_FT" in MC.REGISTRY, "DEEP_FT is recal-able too")

print("\n-- trap 5: the 3-point bands carry NO lower edge ---------------------")
# A corner 3 sits 19.0-19.75 ft from the hoop -- SHORTER than the arc's 19.75
# apex, because the corner is a straight segment nearer the rim. A band floored
# at 19 or 19.75 (as "19-23" reads literally) would contain few corner 3s or
# none, and the corner is the most valuable 3 on the floor. shot_type gates the
# 3-point bands instead, so the floor is unnecessary as well as wrong.
_corner = (CG.CORNER_X + 0.2, CG.HOOP_Y)
ok(CG.is_corner_three(*_corner), "the fixture really is a corner 3")
ok(CG.shot_distance(*_corner) < CG.THREE_R,
   "and it is CLOSER to the hoop than the top of the arc -- the whole trap")
ok(SK.classify_band(*_corner, 3) == "arc3",
   "it still lands in the at-the-arc band, not outside the taxonomy")
ok(SK.classify(*_corner, 3) == "corner3",
   "and the kind cut still calls it a corner 3 -- both cuts stay correct")

print("\n-- the two taxonomies agree where they must -------------------------")

_mixed = ([shot(0.0, CG.HOOP_Y + 1.0) for _ in range(30)]
          + [shot(0.0, CG.HOOP_Y + 6.0) for _ in range(30)]
          + [shot(0.0, CG.HOOP_Y + 14.0) for _ in range(30)]
          + [shot(0.0, CG.HOOP_Y + 21.0, value=3) for _ in range(30)]
          + [shot(0.0, CG.HOOP_Y + 25.0, value=3) for _ in range(30)])
_b, _k = SK.kind_table(_mixed, "band"), SK.kind_table(_mixed, "kind")
ok(_b["rim04"]["n"] == _k["rim"]["n"],
   "the rim cell is the same shot set under both cuts")
ok(_b["two419"]["n"] == _k["floater"]["n"] + _k["mid"]["n"],
   "4ft-to-arc is exactly floater + midrange -- the merge loses nothing")
ok(_b["arc3"]["n"] + _b["deep3"]["n"]
   == _k["corner3"]["n"] + _k["abovebreak3"]["n"],
   "and the 3s repartition without leaking")
ok(_b["_meta"]["located"] == _k["_meta"]["located"],
   "coverage is a property of the shots, not of the cut")
ok(_b["_meta"]["taxonomy"] == "band" and _k["_meta"]["taxonomy"] == "kind",
   "a table says which cut it is, so a renderer cannot mislabel it")
ok(set(SK.both_tables(_mixed)) == {"band", "kind"},
   "both_tables serves both cuts from one shot list")

print("\n-- reliability gates the RATES, attempts alone do not ----------------")

# The load-bearing case: a player with a BIG rim sample. Attempts are not the
# binding constraint -- reliability is. Rim FG% predicts itself at SB .11.
_many_rim = [shot(0.0, CG.HOOP_Y + 1.0, make=(i % 2 == 0), pid=7)
             for i in range(200)]
_pt = SK.player_table(7, shots=_many_rim, taxonomy="band")
_rr = SK.rate_reads(_pt, unit="player")
ok(_pt["rim04"]["n"] == 200, "the player has 200 rim attempts")
ok(_pt["rim04"]["fg"] is not None, "which clears the ATTEMPT gate")
ok(_rr["rim04"]["show"] is False,
   "and the rate is STILL withheld -- attempts cannot buy stability")
ok(_rr["rim04"]["level"] == "withhold", "the level says so explicitly")
ok("does not predict itself" in _rr["rim04"]["caption"],
   "and the refusal carries its reason, not a blank cell")

_many_2 = [shot(0.0, CG.HOOP_Y + 8.0, make=(i % 3 == 0), pid=8)
           for i in range(200)]
_rr2 = SK.rate_reads(SK.player_table(8, shots=_many_2, taxonomy="band"),
                     unit="player")
ok(_rr2["two419"]["show"] is True,
   "the one band that cleared the floor is shown, not hidden")
ok(_rr2["two419"]["level"] == "weak",
   "but hollow -- SB .52 is not a verdict")
ok("r=" in _rr2["two419"]["caption"],
   "and it prints its own r inline so the dot is checkable")

print("\n-- shares are the robust half, and are not gated the same way --------")

_sr = SK.share_reads(SK.player_table(7, shots=_many_rim, taxonomy="band"),
                     unit="player")
ok(_sr["rim04"]["show"] is True,
   "the same player's rim SHARE is shown while her rim RATE is not")
ok(_sr["rim04"]["level"] in ("stable", "fair"),
   "and it is not hedged into invisibility")

print("\n-- the reliability floor cannot be used to undo a refusal ------------")

import helpers.reliability as REL                     # noqa: E402

ok(REL.WEAK_SB > REL.MEASURED_BAND[("player", "fg", "floater")],
   "the floor sits ABOVE the measured floater FG% -- the shipped refusal holds")
ok(REL.WEAK_SB > REL.MEASURED_BAND[("player", "fg", "rim")],
   "and above rim FG%, the most-wanted and least reliable read in the book")
ok(REL.level(None) == "withhold",
   "an UNMEASURED metric is withheld, not waved through")
ok(REL.level(0.95) == "stable" and REL.level(0.65) == "fair",
   "the bands themselves are ordered")
ok(abs(REL.spearman_brown(0.5) - 2 / 3) < 1e-9,
   "Spearman-Brown corrects a half-sample r to the full-sample one")

print(f"\n{PASS} checks passed.\n")
