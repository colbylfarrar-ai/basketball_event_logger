"""
test_shot_clock.py — shot-clock state, the read `possession_secs` was carrying
all along.

The field is on 100% of rows and was read only as a mean. Bucketed, it says the
first seven seconds are worth ~0.14 points per possession more than any point
after them, and that nothing after seven seconds differs at all.

Most of what can go wrong here is the denominator: a possession with no clock
and a possession whose clock never reset are both "not a short possession", and
counting either as one would manufacture the effect the read exists to report.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.shot_clock as SC
import helpers.reliability as RL
import helpers.insights_severity as SEV


# ── bucketing: the denominator is the whole game ─────────────────────────────

def test_bucket_edges_are_the_documented_knee():
    assert SC.bucket(0.5) == "early"
    assert SC.bucket(SC.EARLY_MAX - 0.1) == "early"
    assert SC.bucket(SC.EARLY_MAX) == "mid"          # 7s is NOT early
    assert SC.bucket(SC.MID_MAX) == "mid"
    assert SC.bucket(SC.MID_MAX + 1) == "late"
    assert SC.bucket(SC.SANE_MAX) == "late"


def test_unusable_clocks_leave_the_denominator():
    """None, 0 and a clock that never reset are not short possessions."""
    for bad in (None, 0, -3, SC.SANE_MAX + 0.1, 999, "", "abc"):
        assert SC.bucket(bad) is None, bad


def _ev(secs, pts=0, team=1, kind="shot", play=None):
    return {"event_type": kind, "shooter_team_id": team,
            "possession_secs": secs,
            "shot_result": "make" if pts else "miss",
            "shot_type": 3 if pts == 3 else 2,
            "play_type": play}


def test_profile_counts_possessions_and_points():
    ev = [_ev(3, 2), _ev(4, 0), _ev(10, 3), _ev(20, 0),
          _ev(5, 0, kind="turnover")]
    p = SC.clock_profile(ev)
    assert p["early"]["poss"] == 3 and p["early"]["pts"] == 2
    assert p["mid"]["poss"] == 1 and p["mid"]["pts"] == 3
    assert p["late"]["poss"] == 1
    assert p["poss"] == 5
    assert abs(p["early"]["PPP"] - 2 / 3) < 1e-9
    assert abs(p["early"]["share"] - 3 / 5) < 1e-9


def test_profile_scopes_to_one_team():
    ev = [_ev(3, 2, team=1), _ev(3, 2, team=2), _ev(3, 0, team=2)]
    assert SC.clock_profile(ev, team_id=1)["poss"] == 1
    assert SC.clock_profile(ev, team_id=2)["poss"] == 2
    assert SC.clock_profile(ev)["poss"] == 3


def test_transition_exclusion_is_the_confound_check():
    ev = [_ev(2, 2, play="transition"), _ev(2, 0), _ev(20, 0)]
    assert SC.clock_profile(ev)["early"]["poss"] == 2
    assert SC.clock_profile(ev, exclude_transition=True)["early"]["poss"] == 1


def test_free_throws_and_fouls_never_count_as_possessions():
    """Only shots and turnovers are possessions under the app's locked rule."""
    ev = [_ev(3, 2), _ev(3, 2, kind="ft"), _ev(3, 0, kind="foul")]
    assert SC.clock_profile(ev)["poss"] == 1


def test_empty_profile_reports_none_not_zero():
    p = SC.clock_profile([])
    assert p["poss"] == 0
    assert p["early"]["PPP"] is None and p["early"]["share"] is None


# ── the league share pool that a team's z is read against ────────────────────

def test_league_shares_drop_teams_too_thin_to_be_a_tempo():
    ev = ([_ev(2, 0, team=1)] * 40 + [_ev(20, 0, team=1)] * 40   # 80 poss
          + [_ev(2, 0, team=2)] * 5)                             # 5 poss
    sh = SC.league_early_shares(ev, min_poss=60)
    assert set(sh) == {1}, sh
    assert abs(sh[1] - 0.5) < 1e-9
    assert SC.league_early_counts(ev, min_poss=60)[1] == (40, 80)


# ── the z charges a thin book for being thin ─────────────────────────────────

def _pool(spec):
    """{team: (early, total)} from {team: (share, poss)}."""
    return {t: (round(s * n), n) for t, (s, n) in spec.items()}


def test_a_thin_book_needs_a_bigger_gap_than_a_long_one():
    """Same share, different sample: the two-game team must read as less
    extreme. Under a plain (x-mean)/sd both would score identically, which is
    how a read ends up reporting sample size and calling it style."""
    counts = _pool({i: (0.20 + 0.01 * i, 400) for i in range(10)})
    counts["long"] = (int(0.40 * 1700), 1700)
    counts["short"] = (int(0.40 * 95), 95)
    z_long, _ = SC.early_z(0.40, 1700, counts)
    z_short, _ = SC.early_z(0.40, 95, counts)
    assert z_long > z_short, (z_long, z_short)


def test_z_returns_the_pool_mean_it_measured_against():
    counts = _pool({i: (0.25, 300) for i in range(6)})
    counts["x"] = (int(0.45 * 300), 300)
    z, mu = SC.early_z(0.45, 300, counts)
    assert 0.25 <= mu <= 0.30
    assert z > 0


def test_z_declines_on_a_pool_too_small_to_describe_a_field():
    assert SC.early_z(0.4, 200, _pool({1: (0.3, 200), 2: (0.2, 200)})) is None
    assert SC.early_z(0.4, 0, _pool({i: (0.3, 200) for i in range(8)})) is None


def test_identical_teams_produce_no_finding():
    """No spread and no sampling error left over means nothing to report."""
    counts = _pool({i: (0.25, 400) for i in range(8)})
    z, _ = SC.early_z(0.25, 400, counts)
    assert abs(z) < 1e-9


# ── the read is registered, measured, and routed ─────────────────────────────

def test_the_clock_read_carries_a_real_measurement():
    """A verdict may not ship on an unmeasured metric — the house rule the
    reliability book exists to enforce."""
    r = SEV.reliability_of("Shot clock")
    assert r is not None, "Shot clock must be in METRIC_RELIABILITY"
    assert RL.shows_verdict(r), f"SB {r} does not permit a prose claim"
    assert RL.measured("team", "clock_share") == r


def test_the_read_is_routed_to_a_section_and_its_evidence():
    assert SEV.METRIC_SECTION.get("Shot clock") == SEV.S_WHY
    assert SEV.METRIC_EVIDENCE.get("Shot clock") == ("Charts", "Situational")


def test_the_generator_is_registered():
    import helpers.team_insights as TI
    assert TI._t_clock in TI._TEAM_GENERATORS


def test_generator_stays_quiet_without_a_league_to_compare_against():
    import helpers.team_insights as TI
    ev = [_ev(2, 0)] * 100
    d = dict(TI.clock_extra(1, events=ev, league_events=ev), trk_gp=10)
    # one team in the pool means no spread, so no z and no claim
    assert TI._t_clock(1, {}, {}, {}, d) is None
