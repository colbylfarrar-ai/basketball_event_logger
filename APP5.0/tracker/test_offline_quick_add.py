"""
Offline quick-add (N2) — a gym with no signal is the normal case.

Adding a player or an official used to bail with "Needs connection" while every
other write in the tracker queued and flushed. They now queue too: the row goes
on the roster under a LOCAL id (negative, so it can never collide with a server
AUTOINCREMENT id) and `drainAdds` swaps that id for the server's before the taps
naming it are sent.

Two guards, matching test_tov_capture's shape:

  1. Server contract — both add endpoints are IDEMPOTENT. That is what makes
     queue-then-flush safe: a request that half-landed before the signal died is
     replayed on the next flush and must return the SAME id, not a twin.
  2. Static client check — every id-bearing field in SERVER_FIELDS is listed in
     EVENT_ID_FIELDS. A field missed there is a local id that sails past
     hasTempIds into the batch, and flush DEQUEUES rejected events, so the tap
     is lost for good.

Run: python -m pytest tracker/test_offline_quick_add.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_offadd_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient            # noqa: E402

from database.db import execute, query               # noqa: E402
from tracker.api import app                          # noqa: E402

_SRC = (Path(__file__).resolve().parent / "static" / "app.js").read_text(
    encoding="utf-8")

_HOME = execute("INSERT INTO teams (name, class, gender) VALUES ('Home','3A','M')")
_AWAY = execute("INSERT INTO teams (name, class, gender) VALUES ('Away','3A','M')")
_GID = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?,'2026-02-01')",
               (_HOME, _AWAY))
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('c@test','coach','C','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})


# ── 1. the server contract the queue leans on ───────────────────────────────

def test_player_add_is_idempotent():
    """A replayed add returns the same id — no twin on the roster."""
    body = {"team_id": _HOME, "name": "Queued Kid", "number": 44,
            "handedness": "right"}
    first = client.post(f"/api/games/{_GID}/players", json=body).json()
    again = client.post(f"/api/games/{_GID}/players", json=body).json()
    assert first["created"] is True
    assert again["created"] is False, "a replay created a second player"
    assert again["id"] == first["id"]
    assert len(query("SELECT id FROM players WHERE team_id=? AND name='Queued Kid'",
                     (_HOME,))) == 1


def test_official_add_is_idempotent():
    body = {"name": "Queued Ref", "official_id": 8080, "game_id": _GID}
    first = client.post("/api/officials", json=body).json()
    again = client.post("/api/officials", json=body).json()
    assert again["id"] == first["id"], "a replay created a second official"
    assert len(query("SELECT id FROM officials WHERE official_id=8080")) == 1


def test_a_local_id_is_refused_rather_than_silently_stored():
    """The belt to remapEvent's braces: if a negative id ever did reach the
    server it must be rejected, not written as a dangling reference."""
    r = client.post(f"/api/games/{_GID}/events", json={"events": [{
        "uuid": "local-id-leak", "event_type": "shot", "quarter": 1,
        "time": "5:00", "primary_player_id": -7, "shot_result": "make",
        "shot_type": 2, "zone": "C"}]})
    assert r.status_code == 200, r.text
    results = r.json().get("results", [])
    assert results and results[0]["status"] == "rejected", results
    assert not query("SELECT id FROM game_events WHERE primary_player_id=-7")


# ── 2. the client whitelist ─────────────────────────────────────────────────

def _js_list(name):
    m = re.search(r"const " + name + r" = \[(.*?)\];", _SRC, re.S)
    assert m is not None, f"{name} not found in app.js"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_event_id_fields_cover_every_id_in_server_fields():
    server = _js_list("SERVER_FIELDS")
    remapped = _js_list("EVENT_ID_FIELDS")
    missing = sorted({f for f in server if f.endswith("_id")} - remapped - {"uuid"})
    assert not missing, (
        "these id fields are sent to the server but never have their local id "
        f"swapped for the real one: {missing}")


def test_the_id_bearing_arrays_are_checked_too():
    """on_court / officials_on / official_slots carry ids as well, and they are
    lists rather than scalars so EVENT_ID_FIELDS cannot cover them."""
    m = re.search(r"function hasTempIds\(ev\) \{(.*?)\n\}", _SRC, re.S)
    assert m is not None, "hasTempIds not found in app.js"
    for arr in ("on_court", "officials_on", "official_slots"):
        assert arr in m.group(1), f"hasTempIds ignores {arr}"


def test_quick_add_no_longer_bails_offline():
    for fn in ("quickAddPlayer", "quickAddOfficial"):
        m = re.search(r"async function " + fn + r"\((.*?)\n\}", _SRC, re.S)
        assert m is not None, f"{fn} not found in app.js"
        body = m.group(1)
        assert "queueAdd(" in body, f"{fn} does not queue when offline"
        assert "'Needs connection'" not in body, (
            f"{fn} still refuses to work offline")


def test_pending_adds_are_durable():
    """An add held only in memory dies with the tab iOS just reclaimed, which is
    the same failure the event queue exists to prevent."""
    assert "objectStoreNames.contains('adds')" in _SRC, "no IndexedDB store for adds"
    assert re.search(r"indexedDB\.open\('tracker', 2\)", _SRC), (
        "the adds store needs a version bump to be created on existing installs")
    assert re.search(r"S\.pendingAdds = await aLoad\(", _SRC), (
        "queued adds are never reloaded, so they would never be sent")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
