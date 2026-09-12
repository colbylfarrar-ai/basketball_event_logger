"""
The three October counters (THE BOOK §21 Phase 1) — helpers/telemetry.py.

What is actually worth asserting here is not "a row got written". It is the two
properties the counter has to hold on a 1 vCPU box in front of five new coaches:

  · the WRITE RATE is bounded by human navigation, not by Streamlit reruns —
    page_chrome and empty_state both run on every rerun, so without the dedup
    this table grows by hundreds of rows an hour and the box feels it;
  · a telemetry failure can NEVER reach the page. Every public function is
    wrapped, so a broken counter is a missing number, not a broken app.

Plus: the kill switch works, the retention prune is bounded, a co-op no-op save
is not recorded as a decision, and the audit hook does NOT double-write.

Run: python tracker/test_telemetry.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_telemetry_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query                      # noqa: E402
import helpers.telemetry as TEL                             # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def rows(kind=None):
    if kind:
        return query("SELECT * FROM telemetry WHERE kind=? ORDER BY id", (kind,))
    return query("SELECT * FROM telemetry ORDER BY id")


def clear():
    execute("DELETE FROM telemetry")
    TEL.reset_dedup()


# ── the table exists and the schema is scalar ────────────────────────────────
print("schema")
_cols = {c["name"] for c in query("PRAGMA table_info(telemetry)")}
ok(_cols == {"id", "ts", "kind", "actor", "name", "detail"},
   f"telemetry has exactly the six scalar columns (got {sorted(_cols)})")
ok(any(i["name"] == "idx_telemetry_ts"
       for i in query("PRAGMA index_list(telemetry)")),
   "one index, on (kind, ts) — every read is 'the last N days'")

# ── 1a · page views: a rerun is not a page view ──────────────────────────────
print("page views — dedup on the transition, not on time")
clear()
for _ in range(40):                      # 40 reruns on one page
    TEL.page_view("Team Dashboard", "a@x")
ok(len(rows("page")) == 1,
   "40 reruns on the same page write ONE row (this is the whole rate budget)")

TEL.page_view("Scout", "a@x")
TEL.page_view("Team Dashboard", "a@x")
ok([r["name"] for r in rows("page")]
   == ["Team Dashboard", "Scout", "Team Dashboard"],
   "returning to a page IS a new row — ordering survives the dedup")

TEL.page_view("Team Dashboard", "b@x")
ok(len(rows("page")) == 4 and rows("page")[-1]["actor"] == "b@x",
   "the dedup is per coach — B's first open is not swallowed by A's")

# ── 1b · empty states: identified by WHERE, not by what they say ─────────────
print("empty states")
clear()
for _ in range(25):
    TEL.empty_hit("No tracked games yet", "a@x", "defense_tab.py:290")
ok(len(rows("empty")) == 1,
   "an empty state that stays empty across 25 reruns is ONE hit")

TEL.empty_hit("No tracked games yet", "a@x", "playstyle_tab.py:279")
_e = rows("empty")
ok(len(_e) == 2 and {r["name"] for r in _e}
   == {"defense_tab.py:290", "playstyle_tab.py:279"},
   "same title in two tabs = two distinct dead ends (titles collide; sites do not)")
ok(all(r["detail"] == "No tracked games yet" for r in _e),
   "the human-readable title rides along in detail")


def _site_probe():
    return TEL.caller_site(1)


ok(_site_probe().startswith("test_telemetry.py:"),
   "caller_site names the calling module and line")

# ── 1c · co-op toggle: every flip, old and new; no-ops are not decisions ─────
print("co-op toggle")
clear()
TEL.coop_toggle("coach", False, True, actor="a@x", target="2 teams")
TEL.coop_toggle("coach", True, True, actor="a@x")       # re-save, no change
TEL.coop_toggle("coach", True, False, actor="a@x", target="2 teams")
_c = rows("coop")
ok(len(_c) == 2, "a re-save that changes nothing is not recorded as a decision")
ok(_c[0]["detail"].startswith("0->1") and _c[1]["detail"].startswith("1->0"),
   "old and new value are both on the row")

# ── the audit hook must not double-write ─────────────────────────────────────
print("no double-write")
_before = len(query("SELECT id FROM audit_log"))
clear()
TEL.page_view("Rankings", "a@x")
ok(len(query("SELECT id FROM audit_log")) == _before,
   "a telemetry row writes NO audit_log row (it is already a log)")

# ── the kill switch ──────────────────────────────────────────────────────────
print("kill switch")
clear()
TEL.set_enabled(False)
ok(not TEL.enabled(), "set_enabled(False) takes effect in this process at once")
TEL.page_view("Players", "a@x")
TEL.empty_hit("nothing here", "a@x", "x.py:1")
TEL.coop_toggle("coach", False, True, actor="a@x")
ok(len(rows()) == 0, "every writer is off — no deploy, no restart")
TEL.set_enabled(True)
TEL.page_view("Players", "a@x")
ok(len(rows()) == 1, "and back on again")

# ── never raises into a page ─────────────────────────────────────────────────
print("a broken counter is not a broken page")
clear()
_real = TEL._write
TEL._write = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db is gone"))
try:
    TEL.page_view("Scout", "a@x")
    TEL.empty_hit("nope", "a@x", "x.py:1")
    TEL.coop_toggle("coach", False, True, actor="a@x")
    ok(True, "all three writers swallow a hard DB failure")
finally:
    TEL._write = _real
TEL.reset_dedup()

_real_q = TEL.query
TEL.query = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db is gone"))
try:
    ok(TEL.enabled() is False,
       "an unreadable kill switch fails CLOSED — losing a counter beats "
       "an exception on every page load")
    ok(TEL.summary(30)["total"] == 0, "summary() degrades to empty, not to a traceback")
finally:
    TEL.query = _real_q
    TEL.reset_dedup()

# ── retention is bounded ─────────────────────────────────────────────────────
print("retention")
clear()
execute("INSERT INTO telemetry (ts, kind, actor, name) "
        "VALUES (datetime('now', '-400 days'), 'page', 'a@x', 'Old')")
execute("INSERT INTO telemetry (ts, kind, actor, name) "
        "VALUES (datetime('now', '-2 days'), 'page', 'a@x', 'Recent')")
TEL._pruned_day["day"] = ""
TEL.page_view("New", "z@x")
_names = {r["name"] for r in rows()}
ok("Old" not in _names, f"rows past RETAIN_DAYS={TEL.RETAIN_DAYS} are deleted")
ok({"Recent", "New"} <= _names, "rows inside the window survive the prune")

# ── the read surface ─────────────────────────────────────────────────────────
print("summary")
clear()
for p in ("Team Dashboard", "Scout", "Team Dashboard", "Rankings"):
    TEL.page_view(p, "a@x")
TEL.page_view("Rankings", "b@x")
TEL.empty_hit("No shots", "a@x", "analyze.py:262")
TEL.coop_toggle("coach", False, True, actor="b@x")
_s = TEL.summary(30)
ok(_s["total"] == 7, f"summary counts every row in the window (got {_s['total']})")
ok(_s["pages"][0]["name"] == "Team Dashboard" and _s["pages"][0]["hits"] == 2,
   "pages are ranked by opens")
ok(any(r["coaches"] == 2 for r in _s["pages"] if r["name"] == "Rankings"),
   "distinct coaches per page")
_firsts = {r["name"]: r["hits"] for r in _s["first"]}
ok(_firsts.get("Team Dashboard") == 1 and _firsts.get("Rankings") == 1,
   "'opened first' is one row per coach-day, not per open")
ok(_s["empties"][0]["name"] == "analyze.py:262"
   and _s["empties"][0]["title"] == "No shots", "empties carry site and title")
ok(len(_s["coop"]) == 1, "co-op flips are listed newest-first")

print(f"\n{PASS} checks passed")
