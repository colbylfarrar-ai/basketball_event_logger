"""
test_rollover.py — Tier-3 grad-year rollover + transfer search.
Stubs query/execute so the carry-forward split, the rollover writes, and the
cross-team transfer lookup are checked exactly, no DB.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.seasons as SZ
import helpers.identity as IDN


def test_graduating_year():
    assert SZ.graduating_year("2025-2026") == 2026
    assert SZ.graduating_year("bad") is None
    assert SZ.graduating_year(None) is None


def test_rollover_plan_splits_by_grad_year():
    players = [
        {"id": 1, "team_id": 7, "name": "Senior A", "number": 1, "grad_year": 2026, "identity_id": None},
        {"id": 2, "team_id": 7, "name": "Junior B", "number": 2, "grad_year": 2027, "identity_id": None},
        {"id": 3, "team_id": 7, "name": "Unknown C", "number": 3, "grad_year": None, "identity_id": None},
    ]
    orig = SZ.query
    SZ.query = lambda sql, params=(): players if "archived=0" in sql else []
    try:
        plan = SZ.rollover_plan("2025-2026")
    finally:
        SZ.query = orig
    assert plan["grad_year"] == 2026
    assert [r["id"] for r in plan["graduating"]] == [1]              # senior grads
    assert sorted(r["id"] for r in plan["returning"]) == [2, 3]      # junior + NULL carry


def test_execute_rollover_archives_and_carries():
    carry_rows = [{"team_id": 7, "name": "Junior B", "number": 2, "height": None,
                   "wingspan": None, "weight": None, "handedness": "right",
                   "position": "", "grad_year": 2027, "person": 2}]
    calls = []
    origq, orige = SZ.query, SZ.execute
    SZ.query = lambda sql, params=(): carry_rows if "IN (" in sql else []
    SZ.execute = lambda sql, params=(): calls.append((sql, params))
    try:
        n = SZ.execute_rollover("2026-2027", [2], outgoing_label="2025-2026")
    finally:
        SZ.query, SZ.execute = origq, orige
    assert n == 1
    sqls = " ".join(c[0] for c in calls)
    assert "UPDATE players  SET archived=1" in sqls          # outgoing archived
    assert "active_season" in sqls                            # new label set
    ins = [c for c in calls if c[0].startswith("INSERT INTO players")]
    assert len(ins) == 1
    assert 2 in ins[0][1]            # identity person key carried into the new row
    assert "Current" in ins[0][1] and 0 in ins[0][1]          # fresh current row


def test_execute_rollover_no_carry_still_archives():
    calls = []
    origq, orige = SZ.query, SZ.execute
    SZ.query = lambda sql, params=(): []
    SZ.execute = lambda sql, params=(): calls.append((sql, params))
    try:
        n = SZ.execute_rollover("2026-2027", [], outgoing_label="2025-2026")
    finally:
        SZ.query, SZ.execute = origq, orige
    assert n == 0
    sqls = " ".join(c[0] for c in calls)
    assert "UPDATE players  SET archived=1" in sqls and "INSERT INTO players" not in sqls


def test_transfer_search_cross_team():
    archived = [
        {"id": 10, "name": "Mike Trout", "number": 5, "season": "2024-2025", "identity_id": None, "team": "Old High", "team_id": 3},
        {"id": 11, "name": "Other Guy", "number": 9, "season": "2024-2025", "identity_id": None, "team": "Old High", "team_id": 3},
        {"id": 12, "name": "Mike Trout", "number": 5, "season": "2024-2025", "identity_id": None, "team": "This High", "team_id": 7},
    ]
    orig = IDN.query
    IDN.query = lambda sql, params=(): archived
    try:
        hits = IDN.transfer_search("mike trout", exclude_team_id=7)
    finally:
        IDN.query = orig
    keys = [h["identity_key"] for h in hits]
    assert 10 in keys and 12 not in keys           # other team in, this team excluded
    assert hits[0]["identity_key"] == 10 and hits[0]["score"] >= 0.9
    assert hits[0]["team"] == "Old High"
