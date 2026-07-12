"""
archetypes.py — Data-driven player archetypes + similarity engine.

Basketball-Index sells role/archetype auto-classification; APP5.0 only had a
rule-based scouting label. This learns archetypes from the data instead: it
z-scores every player on a basketball-meaningful feature set, runs k-means to
group similar players, then *names* each group from the statistical signature of
its centroid (a cluster that shoots a ton of efficient threes becomes
"Movement Shooter"; one that lives at the rim and rebounds becomes "Interior Force").
It also answers "who plays like X?" via cosine similarity in the same space.

Clustering uses scikit-learn's KMeans with a silhouette-chosen k when available
(data-driven cluster count instead of a rule of thumb); if sklearn is missing it
falls back to the bundled numpy k-means++ so the feature never hard-breaks.
Cosine similarity is numpy. Pure data layer: feed it the rows from
player_ratings.player_stat_table; no streamlit, no DB access here.
"""
from __future__ import annotations

import numpy as np

try:
    from sklearn.cluster import KMeans as _SKKMeans
    from sklearn.metrics import silhouette_score as _silhouette
    _HAVE_SKLEARN = True
except Exception:
    _HAVE_SKLEARN = False


# Features the clustering / similarity run on. Keys match player_stat_table.
# Chosen to span scoring volume, shot profile, efficiency, playmaking, rebounding
# and defense so the learned groups separate on playing STYLE, not just quality.
DEFAULT_FEATURES = [
    "PPG", "RPG", "APG", "SPG", "BPG",
    "3PA/G", "3P%", "TS%",
    "RimFGA%", "3PR",
    "AST/TOV", "USG%",
    "OREB/G", "DREB/G",
    # shot-creation SOURCE mix (shares of own shots): self-made vs assisted (pass
    # into the shot) vs screen-assist (freed a teammate). Splits the old single
    # SelfCr% so centroids resolve Self-Creator vs Spot-Up vs Screen Setter.
    "SelfCr%", "SCPass%", "SCCreated%",
    # two-way QUALITY composites (0-100). SPG/BPG alone barely represent defense,
    # so a group never separated on "good D / bad O" vs "good O / bad D". Adding the
    # OFFENSE/DEFENSE ratings lets k-means find those two-way profiles, and lets the
    # namer emit Two-Way Star / Offensive Engine / Defensive Anchor / Flamethrower.
    "OFFENSE", "DEFENSE",
]

# Feature → archetype "axis" weights, used to read a centroid's personality.
# Each axis averages the standardized values of its member features.
_AXES = {
    "shooting":    ["3P%", "3PA/G", "3PR"],
    "scoring":     ["PPG", "USG%"],
    "rim":         ["RimFGA%", "OREB/G"],
    "efficiency":  ["TS%"],
    "playmaking":  ["APG", "AST/TOV"],
    "rebounding":  ["RPG", "DREB/G", "OREB/G"],
    "steals":      ["SPG"],
    "blocks":      ["BPG"],
    "creation":    ["SelfCr%"],     # self-made (off the dribble, no pass/screen)
    "spot_up":     ["SCPass%"],     # assisted — catch-and-shoot / drive-and-kick
    "screen_assist": ["SCCreated%"],  # frees shooters by screening (connector big)
    # two-way QUALITY axes — the OFFENSE/DEFENSE composites. Read separately from
    # the style axes above (the namer checks these first for the two-way profile,
    # then falls back to style), so they don't compete for "top style axis".
    "offense_q":   ["OFFENSE"],
    "defense_q":   ["DEFENSE"],
}
# The quality axes are a separate read from playing STYLE — excluded from the
# top-style-axis ranking in _name_for.
_QUALITY_AXES = ("offense_q", "defense_q")


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE MATRIX  (z-scored, missing → column mean = 0)
# ══════════════════════════════════════════════════════════════════════════════

def build_matrix(table, features=None):
    """
    Build a standardized feature matrix from a player_stat_table mapping.

    Returns (pids, X, means, sds, features) where X is (n_players × n_features),
    z-scored per column. None values are imputed to the column mean (so they sit
    at z = 0 — neutral, not penalised). Columns with zero variance collapse to 0.
    """
    if features is None:
        features = DEFAULT_FEATURES
    pids = list(table)
    if not pids:
        return [], np.zeros((0, len(features))), {}, {}, features

    raw = np.full((len(pids), len(features)), np.nan, dtype=float)
    for i, pid in enumerate(pids):
        row = table[pid]
        for j, f in enumerate(features):
            v = row.get(f)
            if v is not None:
                raw[i, j] = float(v)

    means, sds = {}, {}
    X = np.zeros_like(raw)
    for j, f in enumerate(features):
        col = raw[:, j]
        present = col[~np.isnan(col)]
        mean = present.mean() if present.size else 0.0
        sd = present.std() if present.size else 0.0
        means[f], sds[f] = float(mean), float(sd)
        filled = np.where(np.isnan(col), mean, col)
        X[:, j] = (filled - mean) / sd if sd > 1e-9 else 0.0
    return pids, X, means, sds, features


# ══════════════════════════════════════════════════════════════════════════════
#  K-MEANS  (k-means++ seeding, numpy only, deterministic)
# ══════════════════════════════════════════════════════════════════════════════

def _kmeans(X, k, iters=80, seed=7):
    """Return (labels, centroids). Deterministic via `seed`."""
    n = X.shape[0]
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)

    # k-means++ initialisation
    centroids = [X[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min([((X - c) ** 2).sum(axis=1) for c in centroids], axis=0)
        total = d2.sum()
        probs = d2 / total if total > 0 else np.full(n, 1 / n)
        centroids.append(X[rng.choice(n, p=probs)])
    C = np.array(centroids)

    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dists = np.linalg.norm(X[:, None, :] - C[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            labels = new_labels
            break
        labels = new_labels
        for c in range(k):
            members = X[labels == c]
            if members.size:
                C[c] = members.mean(axis=0)
            else:  # re-seed an empty cluster on the worst-fit point
                C[c] = X[dists.min(axis=1).argmax()]
    return labels, C


def _suggest_k(n):
    """A sane default cluster count for n players (numpy-fallback heuristic)."""
    if n < 6:
        return max(2, n // 2)
    return int(max(3, min(7, round(n / 5))))


def _fit_kmeans(X, k, seed=7):
    """(labels, centroids) via sklearn KMeans when available, else numpy k-means++.
    X is already standardized, so Euclidean KMeans is appropriate."""
    if _HAVE_SKLEARN and X.shape[0] >= k:
        km = _SKKMeans(n_clusters=k, random_state=seed, n_init=10)
        labels = km.fit_predict(X)
        return labels, km.cluster_centers_
    return _kmeans(X, k, seed=seed)


def _choose_k(X, kmin=4, kmax=8, seed=7):
    """Pick k by the highest mean silhouette score (sklearn). Falls back to the
    _suggest_k heuristic without sklearn or on a sample too thin to score.

    kmin starts at 4: silhouette on diffuse HS data almost always maxes at the
    smallest k (one big split scores highest), but a 2-3 group split is too coarse
    for a role taxonomy — the two-way profiles (Offensive Engine / Defensive Anchor
    / Flamethrower) only resolve once the field is cut a bit finer — so we explore
    4-8 and take the best within that usable range. kmax is capped at n-1 below."""
    n = X.shape[0]
    if not _HAVE_SKLEARN or n < 5:
        return _suggest_k(n)
    best_k, best_s = None, -1.0
    for k in range(kmin, min(kmax, n - 1) + 1):
        try:
            labels = _SKKMeans(n_clusters=k, random_state=seed,
                               n_init=10).fit_predict(X)
            if len(set(labels)) < 2:
                continue
            s = _silhouette(X, labels)
        except Exception:
            continue
        if s > best_s:
            best_k, best_s = k, s
    return best_k or _suggest_k(n)


# ══════════════════════════════════════════════════════════════════════════════
#  ARCHETYPE NAMING  (read a centroid's statistical personality)
# ══════════════════════════════════════════════════════════════════════════════

def _axis_scores(centroid, features):
    """Average standardized value of each archetype axis for one centroid."""
    idx = {f: j for j, f in enumerate(features)}
    out = {}
    for axis, feats in _AXES.items():
        vals = [centroid[idx[f]] for f in feats if f in idx]
        out[axis] = float(np.mean(vals)) if vals else 0.0
    return out


def _name_for(axes):
    """Map an axis-score profile to a human archetype name.

    Two reads, in order: first the TWO-WAY QUALITY split (from the OFFENSE/DEFENSE
    composite z-scores) — a clear good-O/bad-D, good-D/bad-O, elite-both, or
    elite-shooting-that-defends profile earns a role name; otherwise fall back to
    the playing-STYLE signature (top style axis)."""
    o = axes.get("offense_q", 0.0)
    d = axes.get("defense_q", 0.0)
    # top STYLE axis (quality axes excluded so they never masquerade as a style).
    style = {a: v for a, v in axes.items() if a not in _QUALITY_AXES}
    ranked = sorted(style.items(), key=lambda kv: kv[1], reverse=True)
    top, tval = ranked[0]
    second = ranked[1][0]

    # thresholds are on the standardized (z) scale, matching the style cuts below.
    STRONG, TILT, WEAK = 0.5, 0.4, -0.3
    # ── two-way QUALITY read first ────────────────────────────────────────────
    if o >= STRONG and d >= STRONG:
        return "Two-Way Star"
    if o >= TILT and d <= WEAK:
        return "Offensive Engine"          # carries the offense, a liability on D
    if d >= TILT and o <= WEAK:
        return "Defensive Anchor"          # locks it up, offense is a passenger
    # elite shooting that IS the calling card AND holds up on D → the 3&D scorer.
    if top == "shooting" and tval >= 0.5 and d >= -0.1:
        return "Flamethrower"

    # ── otherwise NAME BY STYLE, in the BADGE-ARCHETYPE vocabulary ────────────
    # One shared taxonomy with badges.badge_archetype (founder ask): both lenses
    # on Players → Lab → Archetypes now speak the same names, so "the badges
    # call them a Scorer — does the style cluster agree?" is a direct read.
    # nobody stands out → a connector / role player
    if tval < 0.35:
        return "Role Player"

    if top in ("shooting", "spot_up"):
        return "Sharpshooter"
    if top in ("scoring", "rim", "creation"):
        return "Scorer"
    if top == "rebounding":
        return "Interior Anchor" if axes["blocks"] > 0.5 else "Rebounder"
    if top == "playmaking":
        return "Floor General"
    if top == "blocks":
        return "Interior Anchor"
    if top == "steals":
        return "Defensive Specialist"
    if top in ("efficiency", "screen_assist"):
        return "Glue Guy"
    _ = second     # ranked axes still feed the cluster signature elsewhere
    return "Role Player"


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC: CLUSTER PLAYERS  +  SIMILARITY
# ══════════════════════════════════════════════════════════════════════════════

def cluster_players(table, k=None, features=None, seed=7):
    """
    Assign every player a data-driven archetype.

    Returns a dict:
      players   {pid: {"cluster": int, "archetype": str,
                       "fit": float (0-1, how central to its cluster)}}
      clusters  [{"id", "archetype", "size", "members": [pid,...],
                  "avg_overall", "axes": {axis: z}, "signature": [(axis, z)...]}]
      k, features

    `k` defaults to a size-appropriate value. Archetype names come from the
    centroid's statistical signature (see _name_for). `fit` is 1/(1+distance to
    own centroid) — higher = a purer example of that archetype.
    """
    pids, X, means, sds, feats = build_matrix(table, features)
    n = len(pids)
    if n < 5:
        # k-means on a handful of players is noise dressed as taxonomy — suppress
        # rather than emit degenerate "archetypes". Callers render "—" gracefully.
        return {"players": {}, "clusters": [], "k": 0, "features": feats}
    if k is None:
        k = _choose_k(X, seed=seed)
    k = max(1, min(k, n))

    labels, C = _fit_kmeans(X, k, seed=seed)

    # name each cluster, de-duplicating identical names with a numeric suffix
    axis_by_c = {c: _axis_scores(C[c], feats) for c in range(k)}
    names, used = {}, {}
    for c in range(k):
        base = _name_for(axis_by_c[c])
        used[base] = used.get(base, 0) + 1
        names[c] = base if used[base] == 1 else f"{base} {used[base]}"

    players = {}
    for i, pid in enumerate(pids):
        c = int(labels[i])
        dist = float(np.linalg.norm(X[i] - C[c]))
        players[pid] = {"cluster": c, "archetype": names[c],
                        "fit": round(1.0 / (1.0 + dist), 3)}

    clusters = []
    for c in range(k):
        members = [pids[i] for i in range(n) if labels[i] == c]
        if not members:
            continue
        overalls = [table[p].get("OVERALL") for p in members
                    if table[p].get("OVERALL") is not None]
        sig = sorted(axis_by_c[c].items(), key=lambda kv: kv[1], reverse=True)
        clusters.append({
            "id": c, "archetype": names[c], "size": len(members),
            "members": members,
            "avg_overall": round(sum(overalls) / len(overalls), 1) if overalls else None,
            "axes": {a: round(v, 2) for a, v in axis_by_c[c].items()},
            "signature": [(a, round(v, 2)) for a, v in sig[:3]],
        })
    clusters.sort(key=lambda d: -(d["avg_overall"] or 0))
    return {"players": players, "clusters": clusters, "k": k, "features": feats}


def _team_axis_scores(centroid, features):
    """Axis scores for one team/centroid vector, inversions applied."""
    idx = {f: j for j, f in enumerate(features)}
    out = {}
    for axis, feats in _TEAM_AXES.items():
        vals = [centroid[idx[f]] for f in feats if f in idx]
        v = float(np.mean(vals)) if vals else 0.0
        out[axis] = -v if axis in _TEAM_INVERTED else v
    return out


def _team_name_for(axes):
    """Map a team's axis profile to a style archetype. Priority rules first
    (the combo identities), then the strongest single axis, then Balanced."""
    a = axes
    if a["tempo"] >= 0.5 and a["pressure"] >= 0.5:
        return "Press & Run"
    if a["tempo"] >= 0.5 and a["three"] >= 0.35:
        return "Pace & Space"
    if a["three"] >= 0.8:
        return "Bombs Away"
    if a["tempo"] <= -0.5 and a["def_q"] >= 0.35:
        return "Grind & Guard"
    if a["def_q"] >= 0.8:
        return "Lockdown"
    if a["paint"] >= 0.6 and a["crash"] >= 0.3:
        return "Bully Ball"
    if a["paint"] >= 0.6:
        return "Paint-First"
    if a["crash"] >= 0.8:
        return "Glass Crashers"
    if a["move"] >= 0.7:
        return "Ball Movers"
    if a["line"] >= 0.8:
        return "Downhill Attack"
    if a["tempo"] <= -0.8:
        return "Slow Grind"
    ranked = sorted(a.items(), key=lambda kv: kv[1], reverse=True)
    top, tval = ranked[0]
    if tval < 0.35:
        return "Balanced"
    return {
        "tempo": "Up-Tempo", "three": "Perimeter-Oriented", "paint": "Paint-First",
        "line": "Downhill Attack", "move": "Ball Movers", "crash": "Glass Crashers",
        "glass_d": "Board & Run", "pressure": "Havoc Defense",
        "shoot_q": "Efficient Halfcourt", "def_q": "Defense-First",
        "security": "Mistake-Free",
    }.get(top, "Balanced")


def team_style_tags(ts_all, features=None, min_teams=5):
    """{team_id: {"tag", "axes", "signature"}} — a data-driven style identity per
    team, z-scored vs the league's tracked field. Rule-based naming on the team's
    OWN standardized profile (no clustering), so it works at any league size the
    z-scores support. ``ts_all`` = league_analytics.team_tracked_pack()["ts"].
    ``signature`` = the 2 strongest style bits as readable text. {} below
    ``min_teams`` (z vs a 3-team pool is noise)."""
    if not ts_all or len(ts_all) < min_teams:
        return {}
    feats = features or TEAM_FEATURES
    tids, X, _m, _s, feats = build_matrix(ts_all, feats)
    out = {}
    for i, tid in enumerate(tids):
        axes = _team_axis_scores(X[i], feats)
        ranked = sorted(axes.items(), key=lambda kv: kv[1], reverse=True)
        sig = [_TEAM_AXIS_LABEL[a] for a, v in ranked[:2] if v >= 0.5]
        out[tid] = {"tag": _team_name_for(axes),
                    "axes": {a: round(v, 2) for a, v in axes.items()},
                    "signature": " · ".join(sig)}
    return out


def similar_players(table, player_id, features=None, n=6):
    """
    Most stylistically similar players to `player_id` via cosine similarity in
    the standardized feature space. Returns [{"pid","name","team","similarity"},
    ...] (0-1, excluding the player themselves), most similar first.
    """
    pids, X, means, sds, feats = build_matrix(table, features)
    if player_id not in pids:
        return []
    i = pids.index(player_id)
    v = X[i]
    nv = np.linalg.norm(v)
    out = []
    for j, pid in enumerate(pids):
        if pid == player_id:
            continue
        w = X[j]
        nw = np.linalg.norm(w)
        cos = float(v @ w / (nv * nw)) if nv > 1e-9 and nw > 1e-9 else 0.0
        sim = max(0.0, (cos + 1) / 2)  # map [-1,1] → [0,1]
        out.append({"pid": pid, "name": table[pid].get("name", str(pid)),
                    "team": table[pid].get("team", ""),
                    "similarity": round(sim, 3)})
    out.sort(key=lambda d: -d["similarity"])
    return out[:n]
