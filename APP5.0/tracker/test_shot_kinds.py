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
ok("floater" in _v[0]["text"] and "layup" in _v[0]["text"],
   "the verdict is the points-on-the-table sentence")
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

print(f"\n{PASS} checks passed.\n")
