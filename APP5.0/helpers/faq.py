"""
faq.py — in-app FAQ synced from the founder's Google Doc.

The founder keeps the FAQ as a Google Doc (easy for him to edit, grows over
time); the app pulls the doc's plain-text export and renders it natively so
every coach can read it in-app without a Docs round-trip. Design (spec item
10, 2026-07-18):

  * fetch  — the published/link-shared doc's `export?format=txt` endpoint
             (no auth needed for link-shared docs), 15s timeout, capped at
             MAX_BYTES so the DB stays small.
  * cache  — app_settings `faq:content` + `faq:fetched_at` (compact text, no
             blobs). TTL 6h; a fetch failure serves the cached copy with
             stale=True instead of an empty page.
  * parse  — heading heuristics into (question, answer) sections: a line
             ending in '?' or a short title-ish line starts a section; body
             lines until the next question form the answer.

Streamlit-free; network isolated in fetch_doc_text so tests mock it.
"""
from __future__ import annotations

import datetime as _dt
import os
import re

from database.db import query, execute

#: Set by the offline demo launcher (`run.py`). This is the ONLY page in the app
#: that reaches the network on a page load, so on a laptop with no connection it
#: is the only page that hangs: the 6h TTL expires, `urlopen` waits out its full
#: 15s timeout, and the coach watches a spinner before the cached copy he was
#: always going to get renders anyway. Offline, skip the call and say so.
OFFLINE_ENV = "APP5_OFFLINE"


def offline() -> bool:
    return (os.environ.get(OFFLINE_ENV) or "").strip().lower() in ("1", "true", "yes")

# The founder's FAQ doc (link-shared). Swap the id here if he ever recreates it.
DOC_ID = "1yW__An6OErdOjwtZoDA-6yTZ3gfQHQGhwfctD4jRaFg"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/edit"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

MAX_BYTES = 100_000          # DB-stays-small cap on the cached text
TTL_HOURS = 6

_K_CONTENT, _K_FETCHED = "faq:content", "faq:fetched_at"


def _setting(key):
    r = query("SELECT value FROM app_settings WHERE key=?", (key,))
    return r[0]["value"] if r else None


def _put(key, value):
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value))


def fetch_doc_text(timeout=15):
    """Raw text from the doc's export endpoint (raises on any failure)."""
    from urllib.request import urlopen, Request
    req = Request(EXPORT_URL, headers={"User-Agent": "app5-faq-sync"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
    # The export is normally UTF-8, but smart quotes have shown up as cp1252
    # bytes — fall back rather than litter the page with U+FFFD.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    # Docs txt export starts with a BOM; normalize newlines.
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def get_faq(force=False, _fetch=None):
    """{text, fetched_at, stale, source_url} — cached with a 6h TTL.

    `force` refetches regardless of age (the admin Refresh button). `_fetch`
    is a test seam (defaults to fetch_doc_text). A failed fetch never wipes
    the cache: the last good copy is served with stale=True.

    Offline (see OFFLINE_ENV) no fetch is attempted at all — not even on
    `force`, which would otherwise spend 15s proving what the env var already
    said. The returned dict carries `offline` so the page can name the reason
    instead of implying the Doc is broken."""
    _off = offline()
    fetch = _fetch or fetch_doc_text
    cached = _setting(_K_CONTENT)
    fetched_at = _setting(_K_FETCHED)
    fresh = False
    if _off:
        return {"text": cached or "", "fetched_at": fetched_at,
                "stale": True, "offline": True, "source_url": DOC_URL}
    if cached is not None and fetched_at and not force:
        try:
            age = (_dt.datetime.utcnow()
                   - _dt.datetime.fromisoformat(fetched_at))
            fresh = age.total_seconds() < TTL_HOURS * 3600
        except ValueError:
            fresh = False
    if not fresh:
        try:
            text = (fetch() or "").strip()[:MAX_BYTES]
            if text:
                _put(_K_CONTENT, text)
                fetched_at = _dt.datetime.utcnow().isoformat(timespec="seconds")
                _put(_K_FETCHED, fetched_at)
                cached = text
                fresh = True
        except Exception:
            pass                        # keep serving the cached copy
    return {"text": cached or "", "fetched_at": fetched_at,
            "stale": not fresh, "offline": False, "source_url": DOC_URL}


# ── parsing ──────────────────────────────────────────────────────────────────
# The founder's Doc structure (observed 2026-07-18): top-level CATEGORY lines
# ending in ':' ("Tracking:"), free paragraphs, "Topic - explanation" one-
# liners, and Docs outline bullets exported as "* item" / "   * sub" (3 spaces
# per level). Sections = categories; bodies convert to markdown.


def _is_heading(line):
    """A line that starts a new FAQ section: a short category ending in ':',
    or a short standalone question ending in '?'."""
    s = line.strip()
    if not s or len(s) > 80 or s.startswith("*"):
        return False
    if s.endswith(":") and len(s.split()) <= 8:
        return True
    return s.endswith("?") and len(s.split()) <= 14


def _to_markdown(lines):
    """Docs txt-export outline → markdown: '* ' bullets nest by 3-space
    indent; bare paragraphs pass through with a blank line so Streamlit
    doesn't glue them together."""
    out = []
    for ln in lines:
        stripped = ln.lstrip(" ")
        if stripped.startswith("* "):
            depth = (len(ln) - len(stripped)) // 3
            out.append("  " * depth + "- " + stripped[2:].strip())
        elif not stripped:
            out.append("")
        else:
            # bold the "Topic - explanation" lead so one-liner Q&As scan
            m = re.match(r"^([^-–]{3,60}?)\s[-–]\s(.+)$", stripped)
            out.append(f"**{m.group(1).strip()}** — {m.group(2)}" if m
                       else stripped)
    md = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def parse_sections(text):
    """[(section_title, markdown_body)] — one section per Doc category (the
    ':'-ended headings). Preamble before the first heading lands under a ''
    title (rendered un-collapsed)."""
    sections = []
    q, buf = "", []
    for line in (text or "").split("\n"):
        if _is_heading(line):
            if q or [b for b in buf if b.strip()]:
                sections.append((q, _to_markdown(buf)))
            q, buf = line.strip().rstrip(":"), []
        else:
            buf.append(line)
    if q or [b for b in buf if b.strip()]:
        sections.append((q, _to_markdown(buf)))
    # merge heading-with-no-body runs into the next section's title
    out = []
    for qq, aa in sections:
        if out and not out[-1][1] and out[-1][0]:
            out[-1] = (out[-1][0] + " — " + qq, aa) if qq else (out[-1][0], aa)
        else:
            out.append((qq, aa))
    return [(qq, aa) for qq, aa in out if qq or aa]


# ══════════════════════════════════════════════════════════════════════════════
#  WHAT WE MEASURED AND REFUSED
# ══════════════════════════════════════════════════════════════════════════════
#
# The app's single most credible asset, and until now no coach could see any of
# it. `reliability.py` holds measured split-half reliabilities and a metric that
# was KILLED on record; `stats.py` holds an out-of-sample model bake-off; two
# whole features were refused after measurement and the refusals are written
# down. Not one site a college analyst reads publishes the reliability of its
# own metric, and several would not survive doing so.
#
# A college analyst has been burned by a black box. A number they cannot
# interrogate is one they will not stake a rotation change on, and the fastest
# way to earn that trust is to hand them the things this app declined to ship.
#
# WHY IT LIVES IN faq.py. This module is already the "explain the app to a
# coach" layer and it is already Streamlit-free, which is what this data wants
# to be — `pages/15_FAQ.py` renders it, `tracker/test_refusals.py` checks the
# citations, and nothing needs a new page. It has nothing to do with the Google
# Doc sync above; the two share a file and no code.
#
# THE RULE FOR THIS LIST: every entry is already true and already in the repo,
# and every number carries the file that computes it. Do NOT add an entry
# without a citation, and do not round a number to make a sentence read better.
# An invented entry here would cost more than the whole surface earns.

#: (id, claim, measurement, verdict, source) — the three-line shape is the
#: point: what somebody wanted to build, what the book said when asked, and
#: what shipped instead.
REFUSALS = [
    (
        "onoff",
        "A card that says the offense is better with this player on the floor.",
        "Raw on/off for offense, same players' odd games against their even "
        "games: **r = −0.096**, Spearman-Brown stepped up to **SB = −0.21**. It "
        "ANTI-correlates — a player above average in one half of the season is "
        "slightly below it in the other. It was also the single most-fired card "
        "in the app, on 37 of 242 players.",
        "**Killed and rewired.** The card now fires only when ORAPM — the same "
        "quantity with teammates and opponents partialled out — agrees in sign, "
        "and the adjusted number leads the sentence. A metric killed by "
        "evidence, on the record.",
        "reliability.MEASURED (\"player\", \"onoff_off\") · insights.py:930",
    ),
    (
        "xppp",
        "Forecast games from expected shot quality alone — take make/miss out "
        "entirely, because shooting is the noisy part.",
        "True at the PLAYER level (rim FG% SB .11 against band share SB .81), "
        "and false at the TEAM level, which is where a game prediction lives. "
        "Cross-predicting random halves: expected PPS predicts future actual "
        "scoring at **r = .176**; past actual scoring predicts it at "
        "**r = .655**. Past scoring forecasts future scoring nearly four times "
        "better than shot quality does. Each metric predicts ITSELF at ~.62–.66 "
        "and the other at .176, symmetrically — they are two nearly orthogonal, "
        "individually stable traits, not a signal and its noise.",
        "**Refused.** The forecasting surface would have been strictly worse "
        "than the scoring margin already in the app. What shipped instead is "
        "descriptive: the \"deserved result\", which splits a played game's "
        "margin into volume, quality, making and free throws and agrees with "
        "the scoreboard winner on 38 of 52 games out of sample. It describes a "
        "game that happened and is never phrased as a claim about a rematch.",
        "reliability.py, block SHOT QUALITY DOES NOT FORECAST SCORING · "
        "deserved.py",
    ),
    (
        "quarters",
        "Quarter-by-quarter team reads — \"this team shoots worse in the third\".",
        "200 random half-splits of the production book over the 5 teams with "
        "6+ tracked games, each team's four quarters demeaned against its own "
        "other three. Tempo repeats: **SB .596**. Shooting does not: quarter "
        "eFG% **SB −0.135**. Ball security does not: quarter turnover rate "
        "**SB .082**.",
        "**Mostly refused.** The quarter axis ships for pace and for nothing "
        "else. A quarter shooting split is a description of four games' worth "
        "of shots, not a trait, and the half-by-half version could not be "
        "resolved at all.",
        "reliability.MEASURED (\"team\", \"quarter_pace\" / \"quarter_efg\" / "
        "\"quarter_tov\") · helpers/quarters.py",
    ),
    (
        "defensive-shares",
        "Port the offensive play-type share reads across to defense — who "
        "guards the iso, who takes the post.",
        "The same estimator, run on `guarded_by_id` assignments: **SB .17–.64**, "
        "against **.70–.92** for the offensive shares it was copied from. A "
        "single action (iso share) comes back at **−0.15**. The coarse "
        "interior/perimeter split (**.643**) and DLOAD%, the share of tagged "
        "contests (**.574**), are the only two that clear the floor.",
        "**Half refused, and the reason is basketball rather than sample size.** "
        "A player chooses their own shot diet; the OPPONENT chooses who they "
        "guard. The fine assignment cut is withheld and the coarse one ships.",
        "reliability.MEASURED_DEFENDER_NOTE · helpers/defense_profile.py",
    ),
    (
        "shot-bands",
        "Replace the shot-difficulty model's location term with the shot-KIND "
        "taxonomy that the shot-QUALITY model had just won with.",
        "Fit on odd games and scored on even, and the reverse, over 3,246 "
        "girls' 2025-26 shots:\n\n"
        "| location term | log loss | Brier |\n|---|---|---|\n"
        "| zone (was) | 0.64798 | 0.21869 |\n"
        "| kind (the proposal) | 0.65120 | 0.21340 |\n"
        "| depth bands (adopted) | **0.63416** | **0.21226** |\n\n"
        "The proposal is WORSE than the thing it would have replaced. The key "
        "already carries the 2/3 split, so a kind cut spends its cells "
        "re-encoding what the key knows. The sample floor was swept as well "
        "(5 → .63416, 10 → .63341, 15 → .63297, 40 → .63549) and is flat, so "
        "the change moves exactly one thing.",
        "**Refused, and the depth bands adopted instead** — they split where "
        "this key was blind, 0–4 ft against everything out to the arc, and win "
        "on both metrics at every floor tested. 22 players at 40+ attempts move "
        "a mean 2.93 points of Shot Rating.",
        "stats.py:1439 (`_sd_loc`)",
    ),
    (
        "garbage-time",
        "Strip garbage time out of the ratings, the way Cleaning the Glass "
        "does — it is the first thing an analyst asks this app.",
        "Two thresholds already carry the name and NEITHER excludes anything "
        "from a rating: `situational.GARBAGE = 15` only SPLITS a player's "
        "scoring into decided-vs-close, and `runs.GARBAGE_MARGIN = 20` filters "
        "4th-quarter runs. Team ratings, player ratings, RAPM, lineups, shot "
        "quality and OVERALL are all computed over every possession, including "
        "a 29-point fourth quarter. So it was measured — 43 tracked girls' "
        "games, 5,510 possessions, three definitions:\n\n"
        "| cut | possessions cut | median ΔNetRtg | mean ΔOVERALL | biggest mover |\n"
        "|---|---|---|---|---|\n"
        "| ≥ 15 margin, any quarter | 38.6% | 5.06 /100 | 2.27 | −12.9 |\n"
        "| ≥ 20 margin, 4th quarter | 12.5% | 2.73 /100 | 1.10 | −7.2 |\n"
        "| win probability past 97% | 39.2% | 1.96 /100 | 2.28 | −12.4 |\n\n"
        "The third row is the interesting one. The win-probability cut throws "
        "away MORE possessions than the flat 15-point rule and moves the "
        "ratings LESS than half as far, because it knows the clock: the two "
        "rules disagree about 648 events (Jaccard .80) — 233 the margin rule "
        "discards from games that were still live, and 415 it keeps from games "
        "that were already over.",
        "**Measured, published, and NOT applied.** Moving every headline "
        "rating three weeks before handing the app to five analysts is what a "
        "freeze forbids, and a 5-point-per-100 shift on the most-read number "
        "in the product is not a quiet change. The honest answer is this "
        "table. If exclusion is ever adopted it should be the win-probability "
        "cut and not either margin constant, and that decision wants a full "
        "walk-forward gate rather than a tidier-looking leaderboard.",
        "tools/measure_garbage.py · situational.py:535 · runs.py:37",
    ),
]


def refusals():
    """The measured-and-refused list. Plain data; `pages/15_FAQ.py` renders it."""
    return list(REFUSALS)
