"""
test_identity.py — unit tests for the Tier-3 cross-season player identity engine
(helpers/identity.py). query/execute are stubbed so the match scoring, prior-identity
collapse, and link/unlink behavior are checked exactly, no DB.
"""
import helpers.identity as IDN


def _install(current, archived):
    """Stub IDN.query to branch by SQL; returns (restore_fn)."""
    def q(sql, params=()):
        if "archived=0" in sql:
            return current
        if "archived=1" in sql:
            return archived
        if "COALESCE(identity_id, id)=" in sql:
            key = params[0]
            return [r for r in (current + archived)
                    if (r.get("identity_id") or r["id"]) == key]
        return []
    orig = IDN.query
    IDN.query = q
    return orig


def _restore(orig):
    IDN.query = orig


def test_norm():
    assert IDN._norm("J. Smith") == "jsmith"
    assert IDN._norm("") == "" and IDN._norm(None) == ""


def test_suggest_matches_picks_same_person():
    current = [
        {"id": 50, "name": "John Smith", "number": 5, "identity_id": None},
        {"id": 51, "name": "New Kid", "number": 99, "identity_id": None},
    ]
    archived = [
        {"id": 10, "name": "John Smith", "number": 5, "season": "2024-2025", "identity_id": None},
        {"id": 11, "name": "Bobby Jones", "number": 11, "season": "2024-2025", "identity_id": None},
    ]
    orig = _install(current, archived)
    try:
        sug = {s["pid"]: s for s in IDN.suggest_matches(50 and 1)}  # team id arbitrary
    finally:
        _restore(orig)
    john = sug[50]
    assert john["candidates"][0]["identity_key"] == 10      # exact name+number
    assert john["candidates"][0]["score"] >= 0.95
    assert john["linked_to"] is None
    assert sug[51]["candidates"] == []                      # no plausible prior


def test_linked_to_reported():
    current = [{"id": 50, "name": "John Smith", "number": 5, "identity_id": 10}]
    archived = [{"id": 10, "name": "John Smith", "number": 5, "season": "2024-2025", "identity_id": None}]
    orig = _install(current, archived)
    try:
        s = IDN.suggest_matches(1)[0]
    finally:
        _restore(orig)
    assert s["linked_to"] == 10


def test_prior_identities_collapse_to_newest():
    # identity 10 appears in two seasons (id 10 in 2023, id 12 linked to 10 in 2024)
    archived = [
        {"id": 10, "name": "Jane Doe", "number": 4, "season": "2023-2024", "identity_id": None},
        {"id": 12, "name": "Jane Doe", "number": 4, "season": "2024-2025", "identity_id": 10},
    ]
    orig = _install([], archived)
    try:
        pri = IDN.prior_identities(1)
    finally:
        _restore(orig)
    assert len(pri) == 1
    assert pri[0]["_key"] == 10 and pri[0]["season"] == "2024-2025"


def test_link_unlink_calls():
    calls = []
    orig_e = IDN.execute
    IDN.execute = lambda sql, params=(): calls.append((sql, params))
    try:
        IDN.link(50, 10)
        IDN.unlink(50)
    finally:
        IDN.execute = orig_e
    assert calls[0][1] == (10, 50) and "identity_id=?" in calls[0][0]
    assert calls[1][1] == (50,) and "identity_id=NULL" in calls[1][0]


def test_identity_history_sorted():
    current = [{"id": 50, "name": "John", "number": 5, "season": "Current",
                "archived": 0, "identity_id": 10, "team_id": 1}]
    archived = [{"id": 10, "name": "John", "number": 5, "season": "2024-2025",
                 "archived": 1, "identity_id": None, "team_id": 1}]
    orig = _install(current, archived)
    try:
        hist = IDN.identity_history(10)
    finally:
        _restore(orig)
    assert [h["id"] for h in hist] == [10, 50]   # 2024-2025 before Current


def test_person_key_sql():
    assert IDN.person_key_sql("p") == "COALESCE(p.identity_id, p.id)"
