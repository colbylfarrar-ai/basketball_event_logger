"""Re-runs every empirical claim in the officials-rating spec against whatever
DB APP5_DATA_DIR points at. Read-only."""
import collections, statistics, random, math
import helpers.stats as S, helpers.late_game as LG, helpers.officials as O
import helpers.runs as R
from database.db import query

MIN_GAMES = 3
MIN_LIVE = 6

G = {r["id"]: r for r in query(
    "SELECT id,team1_id,team2_id,home_score,away_score FROM games WHERE tracked=1")}
gids = list(G)
ev = S.fetch_events(gids)
strat = LG.strategic_foul_event_ids(ev)
by = collections.defaultdict(list)
for e in ev:
    by[e["game_id"]].append(e)

crew = collections.defaultdict(set)
for r in query("SELECT game_id g, official_id o FROM game_lineup_officials"):
    if r["g"] in G:
        crew[r["g"]].add(r["o"])

names = {r["id"]: r["name"] for r in query("SELECT id,name FROM officials")}
p_team = {r["id"]: r["team_id"] for r in query("SELECT id, team_id FROM players")}

live = collections.defaultdict(lambda: collections.defaultdict(int))   # game -> off -> n
raw = collections.defaultdict(lambda: collections.defaultdict(int))
ha = collections.defaultdict(lambda: [0, 0])
gfouls_all = collections.Counter()
n_strat = n_garb = 0
for gid, evs in by.items():
    evs.sort(key=lambda e: (S.elapsed(e["quarter"], e["time"]), e.get("id") or 0))
    t1 = None
    m = 0
    for e in evs:
        if t1 is None and e.get("shooter_team_id"):
            t1 = e["shooter_team_id"]
        if e["event_type"] == "foul":
            gfouls_all[gid] += 1
            o = e["official_id"]
            if o is not None:
                raw[gid][o] += 1
                t = p_team.get(e["secondary_player_id"])
                if t is not None:
                    ha[o][0 if t == G[gid]["team1_id"] else 1] += 1
                if e["id"] in strat:
                    n_strat += 1
                elif (e["quarter"] or 0) >= 4 and abs(m) >= R.GARBAGE_MARGIN:
                    n_garb += 1
                else:
                    live[gid][o] += 1
        et = e["event_type"]
        if ((et == "shot" and e["shot_result"] == "make")
                or (et == "free_throw" and e["shot_result"] == "make")):
            pts = (3 if e["shot_type"] == 3 else 2) if et == "shot" else 1
            if e["shooter_team_id"] == t1:
                m += pts
            elif e["shooter_team_id"] is not None:
                m -= pts

worked = collections.defaultdict(set)
for g, cr in crew.items():
    for o in cr:
        worked[o].add(g)
pool = [o for o, gs in worked.items() if len(gs) >= MIN_GAMES]


def pear(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def splithalf(valfn, sub, iters=3000, seed=11):
    random.seed(seed)
    rs = []
    for _ in range(iters):
        a, b = [], []
        for o in sub:
            g = list(worked[o])
            random.shuffle(g)
            h = len(g) // 2
            if h == 0:
                continue
            va, vb = valfn(o, g[:h]), valfn(o, g[h:2 * h])
            if va is None or vb is None:
                continue
            a.append(va)
            b.append(vb)
        if len(a) >= 3:
            rs.append(pear(a, b))
    rs = [r for r in rs if r == r]
    return statistics.mean(rs) if rs else float("nan")


print("=" * 72)
print(f"{len(G)} tracked games | {len(names)} officials | pool>={MIN_GAMES}: {len(pool)} refs")
gs = [len(v) for v in worked.values()]
print("games/ref:", dict(collections.Counter(sorted(gs))), " max:", max(gs))
print("crew sizes:", dict(collections.Counter(len(v) for v in crew.values())))
tot_raw = sum(sum(v.values()) for v in raw.values())
tot_live = sum(sum(v.values()) for v in live.values())
print(f"attributed fouls {tot_raw} -> live {tot_live}  "
      f"(strategic {n_strat}, garbage Q4/|m|>={R.GARBAGE_MARGIN} {n_garb})")

print("\n-- 1. SPLIT-HALF RELIABILITY (is any ref-level rate a stable trait?) --")
fpg = lambda o, g: sum(raw[x].get(o, 0) for x in g) / len(g)
def share(o, g):
    num = sum(raw[x].get(o, 0) for x in g)
    den = sum(gfouls_all[x] for x in g)
    return num / den if den else None
print(f"  FPG         r={splithalf(fpg, pool):+.3f}")
print(f"  foul_share  r={splithalf(share, pool):+.3f}")
big = [o for o in pool if len(worked[o]) >= 5]
print(f"  FPG (n>=5, {len(big)} refs)        r={splithalf(fpg, big):+.3f}")
print(f"  foul_share (n>=5, {len(big)} refs) r={splithalf(share, big):+.3f}")

print("\n-- 2. ha_diff vs binomial null (home cooking) --")
obs = statistics.mean(abs(ha[o][0] - ha[o][1]) for o in pool)
random.seed(3)
null = []
for _ in range(5000):
    t = []
    for o in pool:
        n = ha[o][0] + ha[o][1]
        h = sum(1 for _ in range(n) if random.random() < .5)
        t.append(abs(h - (n - h)))
    null.append(statistics.mean(t))
print(f"  mean |ha_diff| obs {obs:.2f} vs null {statistics.mean(null):.2f} "
      f"(p={sum(1 for x in null if x>=obs)/len(null):.3f})")

print("\n-- 3. SHARE: is 40% meaningful? expected TOP share under random dealing --")
random.seed(5)
for size in sorted({len(v) for v in crew.values()}):
    line = f"  crew {size}: "
    for n in (12, 18, 24, 30):
        sims = [max(collections.Counter(random.randrange(size)
                for _ in range(n)).get(i, 0) for i in range(size)) / n
                for _ in range(6000)]
        line += f"{n}calls={statistics.mean(sims)*100:.0f}%  "
    print(line)
obs_t, exp_t = [], []
for g, cr in crew.items():
    n = sum(live[g].values())
    k = len(cr)
    if k < 2 or n < MIN_LIVE:
        continue
    obs_t.append(max(live[g].get(o, 0) for o in cr) / n)
    sims = [max(collections.Counter(random.randrange(k) for _ in range(n)).get(i, 0)
            for i in range(k)) / n for _ in range(1500)]
    exp_t.append(statistics.mean(sims))
print(f"  real games (n={len(obs_t)}): observed top share {statistics.mean(obs_t)*100:.1f}%"
      f"  vs matched null {statistics.mean(exp_t)*100:.1f}%")

print("\n-- 4. WORST SINGLE GAMES (does the 90% case exist here?) --")
worst = []
for g, cr in crew.items():
    n = sum(live[g].values())
    k = len(cr)
    if k < 2 or n < MIN_LIVE:
        continue
    p = 1 / k
    mu, sd = n * p, math.sqrt(n * p * (1 - p))
    for o in cr:
        cnt = live[g].get(o, 0)
        worst.append(((cnt - mu) / sd if sd else 0.0, cnt / n, cnt, n, k, g, names.get(o, "?")))
worst.sort(reverse=True)
for z, sh, cnt, n, k, g, nm in worst[:10]:
    print(f"  z={z:+5.2f}  {sh*100:>3.0f}% ({cnt}/{n} live, crew {k})  game {g:<6} {nm}")

print("\n-- 5. ENVIRONMENT: does ref identity explain the game? --")
poss = O._possessions_by_game(gids)
pace = {g: poss.get(g, 0.0) for g in G}
ppp = {g: (((G[g]["home_score"] or 0) + (G[g]["away_score"] or 0)) / poss[g])
       if poss.get(g) else None for g in G}
gf = {g: float(gfouls_all[g]) for g in G}


def team_adjust(metric):
    tg = collections.defaultdict(list)
    for g, v in metric.items():
        if v is None:
            continue
        tg[G[g]["team1_id"]].append(v)
        tg[G[g]["team2_id"]].append(v)
    bl = {t: statistics.mean(v) for t, v in tg.items() if len(v) >= 2}
    out = {}
    for g, v in metric.items():
        if v is None:
            continue
        b = [bl[t] for t in (G[g]["team1_id"], G[g]["team2_id"]) if t in bl]
        if len(b) == 2:
            out[g] = v - statistics.mean(b)
    return out


def analyse(label, metric):
    for form, m in (("raw", metric), ("team-adj", team_adjust(metric))):
        vals = {g: v for g, v in m.items() if v is not None}
        per = {o: statistics.mean([vals[g] for g in worked[o] if g in vals])
               for o in pool if any(g in vals for g in worked[o])}
        obs = statistics.pstdev(list(per.values()))
        random.seed(2)
        gl = list(vals)
        null = []
        for _ in range(3000):
            sh = gl[:]
            random.shuffle(sh)
            mp = dict(zip(gl, sh))
            null.append(statistics.pstdev(
                [statistics.mean([vals[mp[g]] for g in worked[o] if g in vals])
                 for o in per]))
        p = sum(1 for x in null if x >= obs) / len(null)
        r = splithalf(lambda o, g: (statistics.mean([vals[x] for x in g if x in vals])
                                    if any(x in vals for x in g) else None),
                      list(per), iters=1500, seed=9)
        print(f"  {label:<11} {form:<9} SD {obs:7.3f} vs null {statistics.mean(null):7.3f}"
              f"  (p={p:.3f})   split-half r={r:+.3f}")


analyse("PACE", pace)
analyse("PPP", ppp)
analyse("GAME FOULS", gf)

print("\n-- 6. CLUTCH --")
cg = collections.defaultdict(lambda: collections.defaultdict(int))
import helpers.gameflow as GF
for gid, evs in by.items():
    evs.sort(key=lambda e: O._elapsed_safe(e, GF))
    m = 0
    t1 = O._game_team1(gid)
    for e in evs:
        if (e["event_type"] == "foul" and (e["quarter"] or 0) >= 4
                and abs(m) <= O.CLUTCH_MARGIN and e["official_id"] is not None):
            cg[e["official_id"]][gid] += 1
        et = e["event_type"]
        if ((et == "shot" and e["shot_result"] == "make")
                or (et == "free_throw" and e["shot_result"] == "make")):
            pts = (3 if e["shot_type"] == 3 else 2) if et == "shot" else 1
            if e["shooter_team_id"] == t1:
                m += pts
            elif e["shooter_team_id"] is not None:
                m -= pts
tot_c = sum(sum(v.values()) for v in cg.values())
r = splithalf(lambda o, g: statistics.mean([cg[o].get(x, 0) for x in g]), pool)
zero = sum(1 for o in pool if sum(cg[o].get(g, 0) for g in worked[o]) == 0)
print(f"  {tot_c} clutch calls / {len(G)} games ({tot_c/len(G):.1f} per game, all crews)")
print(f"  clutch_pg split-half r={r:+.3f};  {zero}/{len(pool)} rated refs have zero")

print("\n-- 7. PLACEHOLDER NAMES --")
import re
PAT = re.compile(r"^\s*unknown\b", re.I)
unk = [o for o in names if PAT.match(names[o] or "")]
print(f"  matched by /^\\s*unknown\\b/i : {len(unk)} of {len(names)} officials")
print(f"  in rated pool: {sum(1 for o in pool if o in set(unk))} of {len(pool)}")
print("  samples:", sorted({names[o] for o in unk})[:8])
print("=" * 72)
