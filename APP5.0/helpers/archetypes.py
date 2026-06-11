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
    "SelfCr%",
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
    "creation":    ["SelfCr%"],
}


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


def _choose_k(X, kmin=3, kmax=7, seed=7):
    """Pick k by the highest mean silhouette score (sklearn). Falls back to the
    _suggest_k heuristic without sklearn or on a sample too thin to score.

    kmin starts at 3: silhouette on diffuse HS data almost always maxes at k=2
    (one big split scores highest), but "2 archetypes" is useless for a role
    taxonomy — so we explore 3-7 and take the best within a usable range."""
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
    """Map an axis-score profile to a human archetype name."""
    ranked = sorted(axes.items(), key=lambda kv: kv[1], reverse=True)
    top, tval = ranked[0]
    second = ranked[1][0]

    # nobody stands out → a connector / role player
    if tval < 0.35:
        return "Glue / Role Player"

    if top == "shooting":
        return "Movement Shooter" if axes["creation"] < 0 else "Shot Creator"
    if top == "scoring":
        if axes["shooting"] > 0.4:
            return "Three-Level Scorer"
        return "Slashing Scorer" if axes["rim"] > 0 else "Go-To Scorer"
    if top == "rim":
        return "Interior Force" if axes["rebounding"] > 0.3 else "Rim Runner"
    if top == "rebounding":
        return "Rim Protector" if axes["blocks"] > 0.5 else "Glass Cleaner"
    if top == "playmaking":
        return "Scoring Lead Guard" if axes["scoring"] > 0.3 else "Floor General"
    if top == "blocks":
        return "Rim Protector"
    if top == "steals":
        return "Ball Hawk"
    if top == "efficiency":
        return "Efficient Finisher"
    if top == "creation":
        return "Self-Creator"
    return f"{top.title()} Specialist · {second.title()}"


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
    if n == 0:
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


def style_map(table, features=None, seed=7):
    """2D PCA projection of players in standardized style-space, tagged with the
    archetype each was clustered into — a "map" where neighbours play alike.

    Returns {"points": {pid: {x, y, archetype, cluster, name, team, overall}},
             "evr": [pc1_var, pc2_var]}  (explained-variance ratio per axis).
    The two axes are the directions of greatest style variance, so left/right and
    up/down are the biggest real differences in how these players play. Needs
    scikit-learn; returns empty points without it (caller can hide the chart)."""
    if not _HAVE_SKLEARN:
        return {"points": {}, "evr": None}
    try:
        from sklearn.decomposition import PCA
    except Exception:
        return {"points": {}, "evr": None}
    pids, X, _means, _sds, _feats = build_matrix(table, features)
    if len(pids) < 3:
        return {"points": {}, "evr": None}
    clus = cluster_players(table, features=features, seed=seed)
    pca = PCA(n_components=2)
    XY = pca.fit_transform(X)
    pts = {}
    for i, pid in enumerate(pids):
        r = table.get(pid, {})
        info = clus["players"].get(pid, {})
        pts[pid] = {
            "x": float(XY[i, 0]), "y": float(XY[i, 1]),
            "archetype": info.get("archetype", "—"),
            "cluster": info.get("cluster"),
            "name": r.get("name", str(pid)), "team": r.get("team", ""),
            "overall": r.get("OVERALL"),
        }
    return {"points": pts,
            "evr": [round(float(v), 3) for v in pca.explained_variance_ratio_]}


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
