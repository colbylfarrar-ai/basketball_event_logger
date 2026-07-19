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
import re

from database.db import query, execute

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
    the cache: the last good copy is served with stale=True."""
    fetch = _fetch or fetch_doc_text
    cached = _setting(_K_CONTENT)
    fetched_at = _setting(_K_FETCHED)
    fresh = False
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
            "stale": not fresh, "source_url": DOC_URL}


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
