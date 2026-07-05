"""
14_Hall_of_Fame.py — all-time bests across every season in the program.

Founder spec (Jul 2026): OPEN TO EVERYONE, basics only — season bests
(PPG/RPG/APG), career leaders (Points/Rebounds/Assists, gated 25+ games so a
hot week can't hang a banner), team pantheon (Power rating + best records) —
plus two "teaser" stats that dangle the deep engine without giving it away:
best single-season HoopWAR and the most exciting games ever tracked (GEI).

Box-stat assembly + existing engines only (combined tracked + entered boxes,
score_ratings, war_table, wp_curve). Careers chain players.identity_id across
season rollovers, so a linked player's seasons stack into one line.

Two tabs: RECORDS (the open, box-stat hall above) and TRACKED RATINGS — the
deep-engine OVERALL/OFF/DEF/PLAY/REB board that answers "who is the greatest
ever" from tracked data. Ratings are pool-relative, so each season is rated on
its own field (like the HoopWAR teaser) and then compared. Paid-gated (the
rating engine is a Paid surface per the gating taxonomy); Free sees a teaser.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import pandas as pd
import streamlit as st

from database.db import query
from helpers.ui import page_chrome, page_header, gender_radio, empty_state
import helpers.stats as S
import helpers.seasons as SEAS
import helpers.team_ratings as TR
import helpers.auth as AUTH
import helpers.entitlement as ENT

_cfg, ACCENT = page_chrome("Hall of Fame")

page_header("Hall of Fame",
            sub="The program's all-time bests — season records, career "
                "leaders, the team pantheon, and the most exciting games ever "
                "tracked. Every season in the archive counts.")

SEASON_MIN_GP = 10        # a season line needs a real season behind it
CAREER_MIN_GP = 25        # founder gate: a full season+ before a career banner
TRK_MIN_GP = 5            # a tracked-rating season line needs a real book

g = gender_radio(key="hof_gender")
_SEASONS = ["Current"] + SEAS.archived_labels()


# ── data assembly (all cached; the page is read-only) ────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _player_sums(g):
    """{pid: {gp, PTS, TRB, AST}} over tracked + entered boxes, plus the player
    meta map. One players.id = one season (rollover archives rows), so these
    are naturally single-season lines; careers group them by identity below."""
    meta = {r["id"]: r for r in query(
        """SELECT p.id, p.name, p.number, p.team_id, p.season, p.identity_id,
                  t.name AS team
           FROM players p JOIN teams t ON t.id=p.team_id WHERE t.gender=?""",
        (g,))}
    # ALL seasons' tracked games — the bare default is season='Current' only,
    # which would silently drop every archived season's tracked stats from the
    # career sums (manual boxes below already span all seasons)
    _tgids = [r["id"] for r in query("SELECT id FROM games WHERE tracked=1")]
    _boxes = S.player_game_boxes(game_ids=_tgids) if _tgids else {}
    sums = {}
    for pid, per in _boxes.items():
        if pid not in meta:
            continue
        s = sums.setdefault(pid, {"gp": 0, "PTS": 0, "TRB": 0, "AST": 0})
        for b in per.values():
            s["gp"] += 1
            s["PTS"] += b.get("PTS", 0)
            s["TRB"] += b.get("TRB", 0)
            s["AST"] += b.get("AST", 0)
    # entered boxes (untracked games only — tracked wins; manual_box rule)
    for r in query(
            """SELECT m.player_id pid, COUNT(*) gp,
                      SUM(2*m.fgm + m.tpm + m.ftm) pts,
                      SUM(m.oreb + m.dreb) trb, SUM(m.ast) ast
               FROM manual_player_box m JOIN games gm ON gm.id=m.game_id
               WHERE gm.tracked=0 GROUP BY m.player_id"""):
        if r["pid"] not in meta:
            continue
        s = sums.setdefault(r["pid"], {"gp": 0, "PTS": 0, "TRB": 0, "AST": 0})
        s["gp"] += r["gp"]
        s["PTS"] += r["pts"] or 0
        s["TRB"] += r["trb"] or 0
        s["AST"] += r["ast"] or 0
    return meta, sums


@st.cache_data(ttl=3600, show_spinner=False)
def _team_seasons(g):
    """[{Team, Season, Power, W, L, Win%, GP}] — every (team, season) line."""
    rows = []
    for lbl in _SEASONS:
        try:
            scored = TR.score_ratings(gender=g, season=lbl) or {}
        except Exception:
            continue
        for tid, s in scored.items():
            w, l = s.get("W", 0) or 0, s.get("L", 0) or 0
            gp = w + l
            if not gp:
                continue
            rows.append({"Team": s.get("name", tid), "Season": lbl,
                         "Power": s.get("Power"), "W": w, "L": l, "GP": gp,
                         "Win%": w / gp})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _war_best(g):
    """Best single-season HoopWAR lines across every season (teaser #1)."""
    out = []
    for lbl in _SEASONS:
        try:
            gids = SEAS.game_pool(lbl, gender=g, tracked_only=True)
            if not gids:
                continue
            import helpers.hoopwar as HW
            wt = HW.war_table(gender=g, game_ids=set(gids), season=lbl) or {}
        except Exception:
            continue
        for pid, r in wt.items():
            if pid == "_meta" or not isinstance(r, dict):
                continue
            out.append({"Player": r.get("name", pid), "Team": r.get("team", ""),
                        "Season": lbl, "WAR": r.get("WAR")})
    out = [r for r in out if r["WAR"] is not None]
    out.sort(key=lambda r: -r["WAR"])
    return out[:10]


@st.cache_data(ttl=3600, show_spinner=False)
def _tracked_ratings(g):
    """Per-(player, season) tracked ratings across every season, each computed
    within THAT season's pool (ratings are pool-relative, so a season is rated on
    its own field — same per-season pass as _war_best). Returns
    [{pid, identity, season, name, number, team, OVERALL, OFFENSE, DEFENSE,
    PLAYMAKING, REBOUNDING, GP}], one row per player-season with a real book."""
    import helpers.player_ratings as PR
    idn = {r["id"]: (r["identity_id"] or r["id"]) for r in query(
        "SELECT id, identity_id FROM players")}
    out = []
    for lbl in _SEASONS:
        try:
            gids = SEAS.game_pool(lbl, gender=g, tracked_only=True)
            if not gids:
                continue
            rt = PR.player_ratings(game_ids=set(gids), gender=g)
        except Exception:
            continue
        for pid, r in rt.items():
            if (r.get("GP") or 0) < TRK_MIN_GP or r.get("OVERALL") is None:
                continue
            out.append({
                "pid": pid, "identity": idn.get(pid, pid), "season": lbl,
                "name": r["name"], "number": r["number"], "team": r["team"],
                "OVERALL": r["OVERALL"], "OFFENSE": r["OFFENSE"],
                "DEFENSE": r["DEFENSE"], "PLAYMAKING": r["PLAYMAKING"],
                "REBOUNDING": r["REBOUNDING"], "GP": r["GP"]})
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _gei_best(g):
    """Most exciting games ever tracked — STAKES-ADJUSTED GEI over ALL seasons
    (teaser #2). Same scoring-timeline → win-prob pipeline the box score uses for
    raw GEI, then lifted by helpers.excitement.stakes (team quality + upset) so
    this board MATCHES the Rankings 'most exciting games' board — a marquee
    thriller outranks an equally-frantic bottom-of-the-league game. Stakes use
    each game's OWN season ranks (score_ratings per season)."""
    import helpers.win_probability as WP
    import helpers.gameflow as GF
    import helpers.excitement as EX
    rows = query(
        """SELECT g.id, g.date, g.season, g.team1_id, g.team2_id,
                  g.home_score, g.away_score, t1.name AS n1, t2.name AS n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id
           WHERE g.tracked=1 AND t1.gender=?""", (g,))
    if not rows:
        return []
    ev_by = defaultdict(list)
    for e in S.fetch_events([r["id"] for r in rows]):
        ev_by[e["game_id"]].append(e)
    # per-season team ranks for the stakes lift (cached across the page)
    _scored_by_season = {}
    for lbl in {(r["season"] or "Current") for r in rows}:
        try:
            _scored_by_season[lbl] = TR.score_ratings(gender=g, season=lbl) or {}
        except Exception:
            _scored_by_season[lbl] = {}
    out = []
    for r in rows:
        scoring = [e for e in ev_by.get(r["id"], [])
                   if e["event_type"] in ("shot", "free_throw")
                   and e.get("shot_result") == "make"]
        if len(scoring) < 4:
            continue
        scoring.sort(key=GF.elapsed)
        times, hc, ac, h, a = [0.0], [0], [0], 0, 0
        for e in scoring:
            pts = e["shot_type"] if e["event_type"] == "shot" else 1
            if e["shooter_team_id"] == r["team1_id"]:
                h += pts
            elif e["shooter_team_id"] == r["team2_id"]:
                a += pts
            times.append(GF.elapsed(e)); hc.append(h); ac.append(a)
        end_t = times[-1] or WP.GAME_SECONDS
        times.append(end_t); hc.append(h); ac.append(a)
        curve = WP.wp_curve(list(zip(times, [x - y for x, y in zip(hc, ac)])),
                            total_secs=end_t)
        if len(curve) < 2:
            continue
        summ = WP.summarize(curve)
        _lbl = r["season"] or "Current"
        _stk, _q, _u = EX.stakes(_scored_by_season.get(_lbl, {}),
                                 r["team1_id"], r["team2_id"],
                                 r["home_score"], r["away_score"])
        out.append({"Date": r["date"], "Season": _lbl,
                    "Matchup": f'{r["n1"]} vs {r["n2"]}',
                    "Score": f'{r["home_score"]}-{r["away_score"]}',
                    "GEI": summ["gei"], "AdjGEI": summ["gei"] * (1 + _stk),
                    "Stakes": _stk, "Feel": summ["label"]})
    out.sort(key=lambda d: -d["AdjGEI"])
    return out[:10]


meta, sums = _player_sums(g)
if not sums:
    empty_state("No player data yet",
                "The Hall of Fame fills in from tracked games and entered box "
                "scores — play some games first.")
    st.stop()


def _who(m):
    return f"#{m['number']} {m['name']}"


def _season_lbl(m):
    return m["season"] or "Current"


def _board(rows, cols, key):
    st.dataframe(pd.DataFrame(rows, columns=cols), hide_index=True,
                 width="stretch", key=key)


tab_records, tab_tracked = st.tabs(["Records", "Tracked ratings"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — RECORDS  (open to everyone; box-stat halls + two engine teasers)
# ══════════════════════════════════════════════════════════════════════════════
with tab_records:
    # ── season bests (per game) ──────────────────────────────────────────────
    st.markdown(f"### 🏅 Season bests — per game (min {SEASON_MIN_GP} games)")
    _season_rows = [
        {"pid": pid, **s} for pid, s in sums.items() if s["gp"] >= SEASON_MIN_GP]
    if not _season_rows:
        st.info(f"No player has {SEASON_MIN_GP}+ games in a season yet.")
    else:
        c1, c2, c3 = st.columns(3)
        for col, (lbl, key, per) in zip(
                (c1, c2, c3),
                (("PPG", "PTS", True), ("RPG", "TRB", True), ("APG", "AST", True))):
            top = sorted(_season_rows, key=lambda r: -(r[key] / r["gp"]))[:10]
            with col:
                st.markdown(f"**{lbl}**")
                _board([{
                    "Player": _who(meta[r["pid"]]),
                    "Team": meta[r["pid"]]["team"],
                    "Season": _season_lbl(meta[r["pid"]]),
                    lbl: round(r[key] / r["gp"], 1), "GP": r["gp"],
                } for r in top], ["Player", "Team", "Season", lbl, "GP"],
                    f"hof_s_{lbl}")

    # ── career leaders (identity chains, totals) ─────────────────────────────
    st.markdown(f"### 🏛️ Career leaders — totals (min {CAREER_MIN_GP} games)")
    st.caption("Careers stack a player's seasons through the identity link "
               "(New Season → Returning players). A career shorter than "
               f"{CAREER_MIN_GP} games doesn't hang a banner yet.")
    _careers = {}
    for pid, s in sums.items():
        m = meta[pid]
        key = m["identity_id"] or pid
        c = _careers.setdefault(key, {"gp": 0, "PTS": 0, "TRB": 0, "AST": 0,
                                      "seasons": 0, "rep": m})
        c["gp"] += s["gp"]; c["PTS"] += s["PTS"]
        c["TRB"] += s["TRB"]; c["AST"] += s["AST"]
        c["seasons"] += 1
        # newest season's row fronts the career ('Current' sorts above archives)
        if SEAS.is_current(m["season"]) or ((m["season"] or "") >
                                            (c["rep"]["season"] or "")):
            c["rep"] = m
    _career_rows = [c for c in _careers.values() if c["gp"] >= CAREER_MIN_GP]
    if not _career_rows:
        st.info(f"No career has reached {CAREER_MIN_GP} games yet — link returning "
                "players at New Season so their seasons stack.")
    else:
        c1, c2, c3 = st.columns(3)
        for col, (lbl, key) in zip((c1, c2, c3),
                                   (("Points", "PTS"), ("Rebounds", "TRB"),
                                    ("Assists", "AST"))):
            top = sorted(_career_rows, key=lambda c: -c[key])[:10]
            with col:
                st.markdown(f"**{lbl}**")
                _board([{
                    "Player": _who(c["rep"]), "Team": c["rep"]["team"],
                    lbl: c[key], "GP": c["gp"], "Szn": c["seasons"],
                } for c in top], ["Player", "Team", lbl, "GP", "Szn"],
                    f"hof_c_{lbl}")

    # ── team pantheon ────────────────────────────────────────────────────────
    st.markdown("### 🏆 Team pantheon")
    _teams = _team_seasons(g)
    if not _teams:
        st.info("No finished team seasons yet.")
    else:
        t1, t2 = st.columns(2)
        with t1:
            st.markdown("**Best seasons — Power rating** (min 10 games)")
            _pw = sorted([t for t in _teams if t["Power"] is not None
                          and t["GP"] >= 10], key=lambda t: -t["Power"])[:10]
            _board([{"Team": t["Team"], "Season": t["Season"],
                     "Power": round(t["Power"], 1),
                     "Record": f"{t['W']}–{t['L']}"} for t in _pw],
                   ["Team", "Season", "Power", "Record"], "hof_t_power")
        with t2:
            st.markdown("**Best records** (min 15 games)")
            _rc = sorted([t for t in _teams if t["GP"] >= 15],
                         key=lambda t: (-t["Win%"], -t["GP"]))[:10]
            _board([{"Team": t["Team"], "Season": t["Season"],
                     "Record": f"{t['W']}–{t['L']}",
                     "Win%": f"{t['Win%'] * 100:.0f}%"} for t in _rc],
                   ["Team", "Season", "Record", "Win%"], "hof_t_rec")

    # ── the two teasers ──────────────────────────────────────────────────────
    st.markdown("### ✨ From the deep engine")
    st.caption("Two dangles from the analytics engine — **HoopWAR** (wins a player "
               "added over a replacement-level body, from lineup possession data) "
               "and **GEI** (how exciting a game's win-probability ride was). The "
               "full versions live in the Team Dashboard and box scores.")
    z1, z2 = st.columns(2)
    with z1:
        st.markdown("**Best single-season HoopWAR**")
        _wr = _war_best(g)
        if not _wr:
            st.info("Needs tracked lineup data — fills in as seasons are tracked.")
        else:
            _board([{"Player": r["Player"], "Team": r["Team"],
                     "Season": r["Season"], "WAR": f"+{r['WAR']:.1f}"}
                    for r in _wr], ["Player", "Team", "Season", "WAR"], "hof_war")
    with z2:
        st.markdown("**Most exciting games ever tracked**")
        _ge = _gei_best(g)
        if not _ge:
            st.info("Needs tracked games — a win-probability curve can't be built "
                    "from a final score alone.")
        else:
            _board([{"Date": r["Date"], "Matchup": r["Matchup"],
                     "Score": r["Score"], "Adj GEI": round(r["AdjGEI"], 1),
                     "GEI": round(r["GEI"], 1),
                     "Stakes": (f"+{r['Stakes'] * 100:.0f}%" if r["Stakes"] > 0.005
                                else "—"),
                     "Feel": r["Feel"]} for r in _ge],
                   ["Date", "Matchup", "Score", "Adj GEI", "GEI", "Stakes",
                    "Feel"], "hof_gei")
            st.caption("**Adj GEI** = raw GEI lifted by the stakes (the two teams' "
                       "quality + an upset kicker) — the same ranking the "
                       "Rankings › Most-exciting board uses, so a marquee thriller "
                       "outranks a frantic bottom-of-the-table game.")

    st.caption("Open to every account — season bests need "
               f"{SEASON_MIN_GP}+ games, careers {CAREER_MIN_GP}+. Entered box "
               "scores count everywhere a tracked game isn't required.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — TRACKED RATINGS  (the deep engine: greatest-ever by OVERALL)
# ══════════════════════════════════════════════════════════════════════════════
with tab_tracked:
    st.markdown("### 🐐 Greatest ever — by tracked rating")
    st.caption("The deep engine's verdict: every player's **OVERALL** and the "
               "component ratings (Offense / Defense / Playmaking / Rebounding), "
               "from tracked play-by-play. Each season is rated on its own field "
               f"(min {TRK_MIN_GP} tracked games); the boards below stack every "
               "season in the archive to answer who's truly been the best.")

    # Gate: the rating engine is a Paid surface (gating taxonomy — individual
    # event-derived analytics). Free sees the teaser + upsell, not the board.
    if not ENT.has_paid_plan(AUTH.current_user()):
        st.info("🔒 **Tracked ratings are a Paid feature.** The 0–100 OVERALL and "
                "the Offense / Defense / Playmaking / Rebounding engine come from "
                "tracked play-by-play. Upgrade to see the all-time rating board — "
                "who's genuinely been the greatest, not just the highest scorer.")
    else:
        _trk = _tracked_ratings(g)
        if not _trk:
            st.info(f"No player has {TRK_MIN_GP}+ tracked games in a season yet — "
                    "the board fills in as seasons are tracked play-by-play.")
        else:
            # best single-season OVERALL fronts the GOAT tile
            _goat = max(_trk, key=lambda r: r["OVERALL"])
            gg = st.columns(4)
            gg[0].metric("Best OVERALL season", f"{_goat['OVERALL']:.0f}")
            gg[0].caption(f"{_who(_goat)} · {_goat['team']} · {_goat['season']}")
            for col, cat in zip(gg[1:], ("OFFENSE", "DEFENSE", "PLAYMAKING")):
                _b = max(_trk, key=lambda r: r[cat])
                col.metric(f"Best {cat.title()}", f"{_b[cat]:.0f}")
                col.caption(f"{_who(_b)} · {_b['season']}")

            st.markdown("#### 🏅 Best single-season OVERALL")
            st.caption("Top rated player-seasons of all time. GP is that season's "
                       "tracked book; the rating is regressed by games, so a short "
                       "book can't post a phantom 90.")
            _top = sorted(_trk, key=lambda r: -r["OVERALL"])[:15]
            _tdf = pd.DataFrame([{
                "Player": _who(r), "Team": r["team"], "Season": r["season"],
                "OVR": round(r["OVERALL"], 0), "OFF": round(r["OFFENSE"], 0),
                "DEF": round(r["DEFENSE"], 0), "PLY": round(r["PLAYMAKING"], 0),
                "REB": round(r["REBOUNDING"], 0), "GP": r["GP"],
            } for r in _top])
            st.dataframe(
                _tdf, hide_index=True, width="stretch", key="hof_trk_ovr",
                column_config={"OVR": st.column_config.ProgressColumn(
                    "OVR", format="%.0f", min_value=0, max_value=100)})

            # ── category single-season leaders ───────────────────────────────
            st.markdown("#### 🎯 Category leaders — single season")
            c1, c2, c3, c4 = st.columns(4)
            for col, (lbl, key) in zip(
                    (c1, c2, c3, c4),
                    (("Offense", "OFFENSE"), ("Defense", "DEFENSE"),
                     ("Playmaking", "PLAYMAKING"), ("Rebounding", "REBOUNDING"))):
                top = sorted(_trk, key=lambda r: -r[key])[:10]
                with col:
                    st.markdown(f"**{lbl}**")
                    _board([{"Player": _who(r), "Season": r["season"],
                             lbl[:3].upper(): round(r[key], 0)} for r in top],
                           ["Player", "Season", lbl[:3].upper()],
                           f"hof_trk_{key}")

            # ── career: best average OVERALL by identity ─────────────────────
            st.markdown("#### 🏛️ Career — best average OVERALL")
            st.caption("Player-seasons stacked through the identity link, ranked "
                       "by mean OVERALL across a career (min 2 rated seasons). "
                       "Peak = their single best season.")
            _car = {}
            for r in _trk:
                c = _car.setdefault(r["identity"], {"ovr": [], "gp": 0, "rep": r,
                                                    "peak": r})
                c["ovr"].append(r["OVERALL"]); c["gp"] += r["GP"]
                if r["OVERALL"] > c["peak"]["OVERALL"]:
                    c["peak"] = r
                # newest season fronts the name
                if SEAS.is_current(r["season"]) or (
                        (r["season"] or "") > (c["rep"]["season"] or "")):
                    c["rep"] = r
            _crows = [c for c in _car.values() if len(c["ovr"]) >= 2]
            if not _crows:
                st.info("No multi-season tracked career yet — link returning "
                        "players at New Season so their rated seasons stack.")
            else:
                _crows.sort(key=lambda c: -sum(c["ovr"]) / len(c["ovr"]))
                _board([{
                    "Player": _who(c["rep"]), "Team": c["rep"]["team"],
                    "Avg OVR": round(sum(c["ovr"]) / len(c["ovr"]), 1),
                    "Peak": round(c["peak"]["OVERALL"], 0),
                    "Szn": len(c["ovr"]), "GP": c["gp"],
                } for c in _crows[:12]],
                    ["Player", "Team", "Avg OVR", "Peak", "Szn", "GP"],
                    "hof_trk_career")

            st.caption("Ratings are pool-relative and regressed by games played — "
                       "50 is average, ~76+ is elite. Cross-season comparisons "
                       "rate each season on its own field, then stack.")
