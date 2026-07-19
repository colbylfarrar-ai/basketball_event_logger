"""
living_recal.py — the "living MLM" loop (founder batch item 7).

Re-runs the gate battery as tracked games land and adopts an aggressive
constant ONLY when it beats-or-ties the incumbent on the out-of-sample gates.
Gates stay mandatory; every run is logged whether or not it adopts.

Design (conservative by construction):
  * TRIGGER — only when at least ``MIN_NEW_GAMES`` new tracked games have
    landed since the last run (state in app_settings), unless ``force``.
  * CANDIDATES — a small grid AROUND the current effective constants (not a
    full sweep): the loop nudges the six registered constants and scores each
    config on the T6 walk-forward margin MAE (F+M sum), the primary OOS gate.
  * BEAT-OR-TIE — a candidate is adopted only if its T6a sum is LOWER than the
    incumbent's by more than ``TIE_EPS`` (a tie keeps the incumbent, so noise
    never flips constants). Adoption writes app_settings via model_constants;
    it takes effect on the next process start (deploy restart), never mid-run.
  * LOG — every run appends to ``living_recal:history`` (capped) and a human
    line to docs/RECAL_LOG.md.

Usage:  python -m tools.living_recal [--force] [--json]
Scheduled: deploy/app5-living-recal.timer (weekly).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from database.db import query, execute
import tools.backtest as BT
import helpers.model_constants as MC

MIN_NEW_GAMES = 3        # don't bother re-gating for fewer new tracked games
TIE_EPS = 0.01           # T6a-sum improvement smaller than this = a tie (hold)
HISTORY_CAP = 40         # app_settings living_recal:history ring size
_LOG = Path(__file__).resolve().parent.parent / "docs" / "RECAL_LOG.md"

_K_LAST_GAMES = "living_recal:last_run_games"
_K_HISTORY = "living_recal:history"


# ── small candidate grid around the current effective constants ───────────────
# Each candidate is a full {dotted_name: value} config scored end-to-end. Kept
# deliberately small (bounded cost for a weekly job); the values bracket the
# adopted 2026-07-18 aggressive set so the loop can drift with the data without
# a full sweep.
def _candidate_grid(base):
    reg0 = base["team_ratings.DEFAULT_REG"]
    sos0 = base["team_ratings.DEFAULT_SOS_WEIGHT"]
    k0 = base["player_ratings.RATING_K_GAMES"]
    grid = [dict(base)]                                   # incumbent first
    for reg in {max(0.15, reg0 * 0.5), reg0, reg0 * 1.5}:
        for sos in {sos0, min(2.0, sos0 * 1.25)}:
            for k in {max(1, k0 - 1), k0, k0 + 1}:
                cfg = dict(base)
                cfg["team_ratings.DEFAULT_REG"] = round(reg, 3)
                cfg["team_ratings.DEFAULT_SOS_WEIGHT"] = round(sos, 3)
                cfg["player_ratings.RATING_K_GAMES"] = int(k)
                if cfg not in grid:
                    grid.append(cfg)
    return grid


def _t6_sum(cfg):
    """T6a walk-forward margin MAE summed over F+M under `cfg` — the primary
    OOS gate. Lower is better; None-safe."""
    with BT.override({k: v for k, v in cfg.items() if k in BT.REGISTRY}):
        f = BT.t6_walkforward("F",
                              reg=cfg["team_ratings.DEFAULT_REG"],
                              sos_weight=cfg["team_ratings.DEFAULT_SOS_WEIGHT"])["t6a"]
        m = BT.t6_walkforward("M",
                              reg=cfg["team_ratings.DEFAULT_REG"],
                              sos_weight=cfg["team_ratings.DEFAULT_SOS_WEIGHT"])["t6a"]
    return round((f["mae"] or 99) + (m["mae"] or 99), 3), f, m


def _effective_base():
    """The current effective constants (code defaults with any adopted overrides
    applied) as a full config dict over the registered surface."""
    MC.apply()                                   # fold in adopted overrides
    return BT.snapshot_constants()


def _new_game_count():
    r = query("SELECT COUNT(*) n FROM games WHERE tracked=1")
    return int(r[0]["n"] or 0)


def _get(key):
    r = query("SELECT value FROM app_settings WHERE key=?", (key,))
    return r[0]["value"] if r else None


def _put(key, value):
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value))


def _log_history(entry):
    try:
        hist = json.loads(_get(_K_HISTORY) or "[]")
    except (ValueError, TypeError):
        hist = []
    hist.append(entry)
    hist = hist[-HISTORY_CAP:]
    _put(_K_HISTORY, json.dumps(hist, separators=(",", ":")))
    line = (f"- {entry['at']} · games={entry['games']} · "
            f"{'ADOPTED' if entry['adopted'] else 'held'} · "
            f"incumbent T6a={entry['incumbent_t6a']} → "
            f"best={entry['best_t6a']}"
            + (f" · {entry['reason']}" if entry.get("reason") else ""))
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def run(force=False):
    """Run one living-recal cycle. Returns a report dict (also logged)."""
    now = _dt.datetime.utcnow().isoformat(timespec="seconds")
    games = _new_game_count()
    try:
        last = int(_get(_K_LAST_GAMES) or 0)
    except (ValueError, TypeError):
        last = 0

    if not force and (games - last) < MIN_NEW_GAMES:
        return {"ran": False, "games": games, "new_since_last": games - last,
                "reason": f"only {games - last} new tracked games "
                          f"(< {MIN_NEW_GAMES})"}

    base = _effective_base()
    inc_sum, inc_f, inc_m = _t6_sum(base)

    best_cfg, best_sum = base, inc_sum
    scored = []
    for cfg in _candidate_grid(base):
        if cfg == base:
            s, f, m = inc_sum, inc_f, inc_m
        else:
            s, f, m = _t6_sum(cfg)
        scored.append({"reg": cfg["team_ratings.DEFAULT_REG"],
                       "sos": cfg["team_ratings.DEFAULT_SOS_WEIGHT"],
                       "k": cfg["player_ratings.RATING_K_GAMES"], "t6a": s})
        if s < best_sum - TIE_EPS:           # strict beat (a tie holds)
            best_cfg, best_sum = cfg, s

    adopted = best_cfg is not base and best_sum < inc_sum - TIE_EPS
    changes = {}
    if adopted:
        for name in MC.REGISTRY:
            if best_cfg.get(name) != base.get(name):
                v = best_cfg[name]
                changes[name] = list(v) if name.endswith("_OVERALL_PARTS") else v
        MC.set_constants(changes)

    _put(_K_LAST_GAMES, str(games))
    report = {
        "ran": True, "at": now, "games": games,
        "new_since_last": games - last,
        "incumbent_t6a": inc_sum, "best_t6a": best_sum,
        "adopted": adopted, "changes": changes,
        "reason": ("adopted: T6a "
                   f"{inc_sum}→{best_sum} (F {inc_f['mae']}, M {inc_m['mae']})"
                   if adopted else
                   f"held: no candidate beat incumbent by >{TIE_EPS}"),
        "candidates": scored,
    }
    _log_history({"at": now, "games": games, "adopted": adopted,
                  "incumbent_t6a": inc_sum, "best_t6a": best_sum,
                  "changes": changes, "reason": report["reason"]})
    return report


def history():
    try:
        return json.loads(_get(_K_HISTORY) or "[]")
    except (ValueError, TypeError):
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--force", action="store_true",
                    help="run even if too few new games have landed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = run(force=args.force)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    elif not rep["ran"]:
        print(f"living_recal: skipped — {rep['reason']}")
    else:
        print(f"living_recal: {'ADOPTED' if rep['adopted'] else 'held'} · "
              f"incumbent T6a {rep['incumbent_t6a']} → {rep['best_t6a']}")
        if rep["adopted"]:
            for k, v in rep["changes"].items():
                print(f"  {k} -> {v}")


if __name__ == "__main__":
    main()
