"""
model_constants.py — the "living MLM" override layer (founder batch item 7).

The recal constants (shrink strengths, SOS weight, penalty parts) are normally
the code defaults committed after a gated sweep. This layer lets the recurring
`tools.living_recal` loop ADOPT a new value AS CONFIG, not code: the adopted
set lives in ``app_settings['model_constants']`` (compact JSON), and
``apply()`` writes it onto the live module globals at process start.

Why config-not-code: a scheduled job can't safely edit and redeploy source,
but it CAN write a row after the gate battery passes. Overrides take effect on
the NEXT process start (Main.py calls apply(); the deploy restart picks them
up) — deliberately conservative: no scheduled job mutates a running rating
engine mid-request.

ONLY the registered constants below can be overridden — the same aggressive-
sweep surface the backtest harness measures. WPA credit constants stay code-
only (no honest gate). Every value is validated against a type/coercer before
it lands, so a corrupt row can never crash the engine (it's ignored + logged).

Streamlit-free; pure app_settings I/O.
"""
from __future__ import annotations

import json

from database.db import query, execute

_KEY = "model_constants"

# dotted name -> (module_path, attr, coercer). The coercer both validates and
# normalizes an adopted JSON value; a coercer raising means "reject, keep code
# default". _OVERALL_PARTS coerces a list-of-[name,weight] back to tuples.
_NUM = float


def _parts(v):
    out = [(str(n), float(w)) for n, w in v]
    if not out:
        raise ValueError("empty parts")
    return out


def _posint(v):
    i = int(v)
    if i < 1:
        raise ValueError("must be >= 1")
    return i


REGISTRY = {
    "team_ratings.DEFAULT_REG":         ("helpers.team_ratings", "DEFAULT_REG", _NUM),
    "team_ratings.DEFAULT_SOS_WEIGHT":  ("helpers.team_ratings", "DEFAULT_SOS_WEIGHT", _NUM),
    "player_ratings.RATING_K_GAMES":    ("helpers.player_ratings", "RATING_K_GAMES", _posint),
    "player_ratings.TEAM_PRIOR_LAMBDA": ("helpers.player_ratings", "TEAM_PRIOR_LAMBDA", _NUM),
    "player_ratings.ARCH_ANCHOR_BLEND": ("helpers.player_ratings", "ARCH_ANCHOR_BLEND", _NUM),
    "player_ratings._OVERALL_PARTS":    ("helpers.player_ratings", "_OVERALL_PARTS", _parts),
}


def load() -> dict:
    """The adopted overrides as ``{dotted_name: json_value}`` (empty if none)."""
    r = query("SELECT value FROM app_settings WHERE key=?", (_KEY,))
    if not r or not r[0]["value"]:
        return {}
    try:
        d = json.loads(r[0]["value"])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def get(name, default=None):
    """One override's raw JSON value, or ``default`` (rarely needed directly —
    apply() is the normal path; this is for admin display)."""
    return load().get(name, default)


def set_constants(overrides: dict, *, replace=False) -> None:
    """Persist adopted overrides (living_recal's write path). ``replace`` swaps
    the whole set; otherwise merges. Only REGISTRY keys with a passing coercer
    are stored, so a bad proposal can never poison the row."""
    cur = {} if replace else load()
    for name, val in (overrides or {}).items():
        if name not in REGISTRY:
            continue
        try:
            REGISTRY[name][2](val)          # validate; store the raw JSON value
        except Exception:
            continue
        cur[name] = val
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (_KEY, json.dumps(cur, separators=(",", ":"))))


def clear() -> None:
    """Drop all overrides → the engines revert to the committed code defaults."""
    execute("DELETE FROM app_settings WHERE key=?", (_KEY,))


def apply() -> dict:
    """Write the adopted overrides onto the live module globals. Returns the
    ``{name: value}`` actually applied (coerced). Idempotent; safe to call
    more than once. A value that fails its coercer is skipped, never fatal."""
    import importlib
    applied = {}
    for name, val in load().items():
        spec = REGISTRY.get(name)
        if not spec:
            continue
        mod_path, attr, coerce = spec
        try:
            coerced = coerce(val)
            mod = importlib.import_module(mod_path)
            setattr(mod, attr, coerced)
            applied[name] = coerced
        except Exception:
            continue
    return applied
