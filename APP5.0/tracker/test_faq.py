"""
Item 10 — FAQ sync engine (throwaway DB, network mocked).

Run: python tracker/test_faq.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_faq_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.faq as FAQ                          # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


DOC = """Welcome — read this before your first game.

Tracking:

Quick Shot v Full Detail - Quick shot is only MUST HAVE items.

* Shot
   * Shooter (MUST HAVE)
   * Guarded By
      * Be liberal with this field

How do I log a turnover?
Tap TO, pick the player, pick the kind chips, hit LOG TURNOVER.
"""

print("parse (founder Doc shape: ':' categories + outline bullets)")
secs = FAQ.parse_sections(DOC)
qs = [q for q, _a in secs]
ok(qs[0] == "" and "Welcome" in secs[0][1], "preamble kept without a heading")
ok("Tracking" in qs, "':' category becomes a section")
ok("How do I log a turnover?" in qs, "'?' line becomes a section")
_tr = dict(secs)["Tracking"]
ok("**Quick Shot v Full Detail** —" in _tr, "topic-dash one-liner bolded")
ok("- Shot" in _tr and "    - Be liberal with this field" in _tr,
   "outline bullets nest by 3-space indent")

print("cache + ttl + failure fallback")
calls = {"n": 0}


def fake_fetch():
    calls["n"] += 1
    return DOC


d1 = FAQ.get_faq(_fetch=fake_fetch)
ok(calls["n"] == 1 and not d1["stale"] and d1["text"].startswith("Welcome"),
   "first call fetches + caches")
d2 = FAQ.get_faq(_fetch=fake_fetch)
ok(calls["n"] == 1 and not d2["stale"], "within TTL -> served from cache")
d3 = FAQ.get_faq(force=True, _fetch=fake_fetch)
ok(calls["n"] == 2, "force refetches")


def broken_fetch():
    raise OSError("no network")


d4 = FAQ.get_faq(force=True, _fetch=broken_fetch)
ok(d4["text"].startswith("Welcome") and d4["stale"],
   "fetch failure serves cached copy, marked stale")

print("cap")
d5 = FAQ.get_faq(force=True, _fetch=lambda: "x" * (FAQ.MAX_BYTES * 2))
ok(len(d5["text"]) <= FAQ.MAX_BYTES, "stored text capped (DB stays small)")

print(f"\nALL {PASS} CHECKS PASSED")
