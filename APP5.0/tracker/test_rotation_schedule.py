"""
test_rotation_schedule.py — unit tests for the Suggested Rotation scheduler.

The lineup projector is INJECTED (a fake that returns a line/Net per five), so
the whole scheduler runs db-free: budget conservation, the frame (anchor opens
each half and closes), preset repair, and signature coverage are all checkable
without a database or a real rotation sample.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.rotation_schedule as RS


GOALS = [
    {"key": "eFG",  "label": "eFG%", "target": 0.50, "win_high": True,  "fmt": "pct"},
    {"key": "TOVr", "label": "TOV%", "target": 0.15, "win_high": False, "fmt": "pct"},
]
D_BY_KEY = {"eFG": 1.4, "TOVr": 1.0}


def _ctx(pids):
    return {
        "players": {p: {"name": f"P{p}", "obs_min": 20.0} for p in pids},
        "goals": GOALS, "d_by_key": D_BY_KEY, "stars": pids[:2],
        "game_ids": [], "table": {},
    }


def _opt(minutes):
    return {"minutes": dict(minutes)}


def _fake_project(hit_efg_five=None, hit_tov_five=None):
    """Projector where a specific five hits eFG and another hits TOV%."""
    a = frozenset(hit_efg_five or ())
    b = frozenset(hit_tov_five or ())

    def project(five):
        k = frozenset(five)
        line = {"eFG": 0.45, "TOVr": 0.20}
        if k == a:
            line["eFG"] = 0.55
        if k == b:
            line["TOVr"] = 0.10
        return {"line": line, "net_blended": float(sum(five)) / 10.0}
    return project


# ── budget ────────────────────────────────────────────────────────────────────

def test_blocks_from_minutes_sums_to_every_slot():
    b = RS.blocks_from_minutes({1: 28, 2: 26, 3: 24, 4: 22, 5: 20,
                                6: 16, 7: 12, 8: 8, 9: 4})
    assert sum(b.values()) == RS.N_BLOCKS * RS.SLOTS == 80
    assert b[1] == 14 and b[9] == 2


def test_blocks_from_minutes_repairs_a_bad_total():
    # 150 minutes, not 160 — the scheduler still needs exactly 80 slots
    b = RS.blocks_from_minutes({1: 30, 2: 30, 3: 30, 4: 30, 5: 30})
    assert sum(b.values()) == 80


# ── the schedule ──────────────────────────────────────────────────────────────

def _run(presets=None, project=None):
    pids = [1, 2, 3, 4, 5, 6, 7, 8]
    minutes = {1: 28, 2: 26, 3: 24, 4: 22, 5: 20, 6: 18, 7: 12, 8: 10}
    return RS.suggest_rotation(
        99, _ctx(pids), _opt(minutes),
        presets=presets if presets is not None else [
            {"pids": [1, 2, 3, 4, 5], "labels": ["Best overall"]},
            {"pids": [4, 5, 6, 7, 8], "labels": ["Best defense"]},
            {"pids": [1, 3, 5, 7, 8], "labels": ["Best 3-pt shooting"]},
        ],
        project=project or _fake_project(hit_efg_five=[1, 3, 5, 7, 8],
                                         hit_tov_five=[4, 5, 6, 7, 8]))


def test_schedule_spends_every_slot_and_honors_the_budget():
    s = _run()
    assert len(s["blocks"]) == RS.N_BLOCKS
    assert all(len(b["five"]) == RS.SLOTS for b in s["blocks"])
    # scheduled minutes match the optimizer's recommendation exactly
    assert s["minutes"] == {p: float(m) for p, m in s["target_minutes"].items()}
    assert sum(s["minutes"].values()) == RS.GAME_MIN * RS.SLOTS == 160


def test_frame_anchors_both_halves_and_the_close():
    s = _run()
    anchor = frozenset(s["anchor"])
    assert anchor == frozenset([1, 2, 3, 4, 5])          # top-5 by minutes
    for i in (0, 1, 8, 9, 14, 15):
        assert frozenset(s["blocks"][i]["five"]) == anchor, i
    assert s["blocks"][0]["role"] == RS.ANCHOR
    assert s["blocks"][15]["role"] == RS.CLOSE


def test_free_blocks_chase_the_least_covered_signature_stat():
    s = _run()
    # both signature stats get real floor time — neither is left at zero
    assert s["coverage"]["eFG"] > 0
    assert s["coverage"]["TOVr"] > 0
    assert s["uncovered"] == []
    # a covering five actually shows up in the free window
    free = [b for b in s["blocks"] if b["role"] == RS.FREE]
    assert any(b["goals_hit"] for b in free)
    assert all(b["why"] for b in s["blocks"])


def test_reasoning_does_not_repeat_itself():
    """The old per-block rule named the strongest signature stat every time and
    printed one identical sentence down the whole table. Each stint has to say
    something the one before it didn't."""
    s = _run()
    whys = [g["why"] for g in s["segments"]]
    assert len(set(whys)) == len(whys), whys
    for a, b in zip(whys, whys[1:]):
        assert a != b
    # the anchor lines distinguish the tip from coming out of the half
    anchors = [g["why"] for g in s["segments"] if g["role"] == RS.ANCHOR]
    assert len(set(anchors)) == len(anchors)


def test_shared_surnames_are_disambiguated():
    ctx = _ctx([1, 2, 3, 4, 5, 6])
    ctx["players"][1]["name"] = "Ali Schwerdfeger"
    ctx["players"][2]["name"] = "Kodi Schwerdfeger"
    short = RS.short_names(ctx, [1, 2, 3])
    assert short[1] == "A. Schwerdfeger" and short[2] == "K. Schwerdfeger"
    assert short[3] == "P3"                      # unique surname stays bare


def test_uncovered_stat_is_reported_not_hidden():
    # a projector where NO five ever hits either goal
    s = _run(project=lambda five: {"line": {"eFG": 0.40, "TOVr": 0.25},
                                   "net_blended": 1.0})
    assert set(s["uncovered"]) == {"eFG", "TOVr"}
    assert all(b["goals_hit"] == [] for b in s["blocks"])


def test_presets_are_repaired_not_dropped_when_budget_runs_out():
    s = _run()
    # every block is a five of budgeted players, and the labels stay preset-shaped
    labels = {b["label"] for b in s["blocks"]}
    assert any(l != "Rotation five" for l in labels)
    # no player is ever scheduled past their budget
    budget = RS.blocks_from_minutes(s["target_minutes"])
    used = {}
    for b in s["blocks"]:
        for p in b["five"]:
            used[p] = used.get(p, 0) + 1
    assert all(used[p] <= budget[p] for p in used)


def test_no_presets_still_produces_a_runnable_schedule():
    s = _run(presets=[])
    assert len(s["blocks"]) == RS.N_BLOCKS
    assert all(len(b["five"]) == RS.SLOTS for b in s["blocks"])


def test_segments_merge_and_stints_cover_the_game():
    s = _run()
    segs = s["segments"]
    assert segs[0]["start"] == 0.0 and segs[-1]["end"] == RS.GAME_MIN
    # segments are contiguous and non-overlapping
    for a, b in zip(segs, segs[1:]):
        assert a["end"] == b["start"]
    # per-player stint minutes equal the scheduled minutes
    for r in s["stints"]:
        assert sum(e - st for st, e, _ in r["segments"]) == r["minutes"]
        assert r["minutes"] == s["minutes"][r["pid"]]
        # a colour change around a player is not a substitution: trips onto the
        # floor never exceed the drawn bars, and a coach subs a handful of times
        assert 1 <= r["entries"] <= len(r["segments"])


def test_continuity_keeps_the_floor_from_churning_every_block():
    s = _run()
    # nobody is asked to check in more than a handful of times in 32 minutes
    assert max(r["entries"] for r in s["stints"]) <= 6
    # and the plan is stints, not 16 different fives
    assert len(s["segments"]) < RS.N_BLOCKS


def test_top_heavy_budget_still_fills_every_block():
    # four 30-minute starters and a 8-minute bench: the fifth starter can't cover
    # the six framed blocks alone, so the pool split has to lend the shortfall to
    # the bench. Every block still gets five players and totals still match.
    pids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    minutes = {1: 30, 2: 30, 3: 30, 4: 30, 5: 8, 6: 8, 7: 8, 8: 8, 9: 8}
    s = RS.suggest_rotation(
        1, _ctx(pids), _opt(minutes),
        presets=[{"pids": [1, 2, 3, 4, 5], "labels": ["Best overall"]}],
        project=lambda f: {"line": {"eFG": 0.55}, "net_blended": 1.0})
    assert len(s["blocks"]) == RS.N_BLOCKS
    assert all(len(b["five"]) == RS.SLOTS for b in s["blocks"])
    assert s["minutes"] == {p: float(m) for p, m in minutes.items()}


def test_thin_rotation_is_gated():
    ctx = _ctx([1, 2, 3])
    out = RS.suggest_rotation(1, ctx, _opt({1: 32, 2: 32, 3: 32}),
                              presets=[], project=lambda f: {"line": {},
                                                             "net_blended": 0})
    assert out.get("gated")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print("PASS", f.__name__)
    print(f"--- {len(fns)}/{len(fns)} rotation-schedule tests pass ---")
