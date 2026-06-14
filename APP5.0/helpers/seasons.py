"""
seasons.py — season partition helpers (model A).

The DB uses 'Current' as the ACTIVE-season sentinel on players / schedule / games
(rows for the season being played right now). app_settings.active_season holds the
friendly DISPLAY name of that active season (e.g. "2025-2026"). When you roll over
(Input Hub → New Season) the outgoing 'Current' rows are stamped with their real
label and the active_season name advances, so stats never blend across seasons.

Read rules for the app's gating: the CURRENT season is the live, monetized edge
(paid depth + Solo/League-wide co-op). PREVIOUS seasons are an OPEN ARCHIVE — free,
full depth, to everyone (last year's roster has turned over, so there's no
competitive edge left to protect; it's a funnel, not a leak). Streamlit-free + pure.
"""
from __future__ import annotations

from database.db import query

ACTIVE = "Current"            # the active-season sentinel stored on rows
DEFAULT_LABEL = "2025-2026"   # fallback display name if app_settings unset


def active_label() -> str:
    """Friendly name of the active ('Current') season, e.g. '2025-2026'."""
    r = query("SELECT value FROM app_settings WHERE key='active_season'")
    v = (r[0]["value"] if r else "") or ""
    return v.strip() or DEFAULT_LABEL


def archived_labels() -> list[str]:
    """Distinct past-season labels that have games, newest first."""
    return [r["season"] for r in query(
        "SELECT DISTINCT season FROM games "
        "WHERE season != ? ORDER BY season DESC", (ACTIVE,))]


def is_current(season) -> bool:
    """A season selection that means 'the active season' (None / '' / 'Current')."""
    return season in (None, "", ACTIVE)


def archive_open(season) -> bool:
    """True when ``season`` is a past (archived) season — an OPEN ARCHIVE: free,
    full tracked depth, visible to everyone regardless of plan/pool. False for the
    active ('Current') season, where the normal entitlement gating applies. Pages
    use this to decide whether to bypass the paid/pool gates for the chosen season.
    """
    return not is_current(season)


def season_options() -> list[tuple[str, str]]:
    """[(value, label)] for a season picker — active first, then archives.
    The value is what you pass to the season-scoped engines ('Current' or a label).
    """
    opts = [(ACTIVE, f"{active_label()} (current)")]
    opts += [(s, s) for s in archived_labels()]
    return opts
