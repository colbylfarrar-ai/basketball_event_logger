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

from database.db import query, execute

ACTIVE = "Current"            # the active-season sentinel stored on rows
DEFAULT_LABEL = "2025-2026"   # fallback display name if app_settings unset

# Bio fields copied forward when a returning player is carried into the new season
# (identity_id is set separately to the person key; availability resets to Active).
_CARRY_COLS = ("team_id", "name", "number", "height", "wingspan", "weight",
               "handedness", "position", "grad_year")


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


# ── New-Season rollover with grad-year auto-graduate + roster carry-forward ──────
def graduating_year(label) -> int | None:
    """The class year that graduates after a season — the END year of the label
    ('2025-2026' -> 2026). None if the label can't be parsed (then nobody auto-grads)."""
    try:
        return int(str(label).split("-")[-1])
    except (ValueError, AttributeError, IndexError):
        return None


def rollover_plan(outgoing_label=None):
    """Preview a rollover: split the CURRENT roster into who graduates vs who
    returns, by grad_year vs the outgoing season's graduating year.

    Returns {"label","grad_year","graduating":[row],"returning":[row]} where each
    row is {id, team_id, name, number, grad_year}. A player auto-graduates only when
    grad_year is set AND <= the graduating year; NULL grad_year = unknown = returns
    (safe default — the coach can still uncheck them in the UI)."""
    if outgoing_label is None:
        outgoing_label = active_label()
    gy = graduating_year(outgoing_label)
    rows = query(
        "SELECT id, team_id, name, number, grad_year, identity_id FROM players "
        "WHERE archived=0 ORDER BY team_id, number, name")
    grad, ret = [], []
    for r in rows:
        is_grad = (gy is not None and r["grad_year"] is not None
                   and r["grad_year"] <= gy)
        (grad if is_grad else ret).append(r)
    return {"label": outgoing_label, "grad_year": gy,
            "graduating": grad, "returning": ret}


def execute_rollover(new_label, carry_pids, outgoing_label=None):
    """Roll over to `new_label`: stamp+archive the outgoing season, then re-create
    each player in `carry_pids` as a fresh CURRENT-season row, identity-linked to the
    same person (so returners reappear pre-linked and seniors simply aren't carried).

    Snapshots the carry rows BEFORE archiving (their data is about to be stamped).
    Returns the number of players carried forward."""
    if outgoing_label is None:
        outgoing_label = active_label()

    carry = []
    if carry_pids:
        ph = ",".join("?" * len(carry_pids))
        carry = query(
            f"SELECT {', '.join(_CARRY_COLS)}, COALESCE(identity_id, id) AS person "
            f"FROM players WHERE id IN ({ph})", tuple(int(p) for p in carry_pids))

    # stamp the outgoing season onto every current row (same as the legacy rollover)
    execute("UPDATE players  SET archived=1, season=? WHERE archived=0", (outgoing_label,))
    execute("UPDATE schedule SET season=? WHERE season='Current'", (outgoing_label,))
    execute("UPDATE games    SET season=? WHERE season='Current'", (outgoing_label,))

    # re-create the returners as fresh current rows, linked to their person key
    cols = list(_CARRY_COLS) + ["identity_id", "archived", "season", "availability"]
    placeholders = ",".join("?" * len(cols))
    for r in carry:
        vals = [r[c] for c in _CARRY_COLS] + [r["person"], 0, ACTIVE, "Active"]
        execute(f"INSERT INTO players ({', '.join(cols)}) VALUES ({placeholders})",
                tuple(vals))

    execute("INSERT OR REPLACE INTO app_settings (key, value) "
            "VALUES ('active_season', ?)", (new_label,))
    return len(carry)
