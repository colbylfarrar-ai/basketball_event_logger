"""
roster_import.py — parse + plan for the Input Hub roster CSV import.

PURE engine (no Streamlit, no DB): `parse_roster` turns a pasted block or an
uploaded CSV's text into normalized player rows, `plan_import` diffs them
against the team's existing roster into per-row verdicts (add / update / skip).
The page applies the plan through the SAME insert/update path the roster
editor uses (season stamping, identity auto-link, grad-year default), so this
module never writes anything itself.

Tolerances (coaches paste from anywhere):
- header row optional — sniffed by alias match; positional fallback is
  name, number, height, grad_year
- comma / tab / semicolon delimited; extra columns ignored
- heights as 71, 5'11, 5'11", 5-11, 5 ft 11 (all → inches)
- "Last, First" names flipped when the whole file looks that way
- blank numbers / grad years allowed (page fills the grad-year default)
"""
from __future__ import annotations

import csv
import io
import re

# header-cell aliases (lowercased, stripped of punctuation) → canonical field
_ALIASES = {
    "name": {"name", "player", "playername", "fullname", "playerfullname"},
    "number": {"number", "no", "num", "jersey", "jerseynumber", "uniform", "uni"},
    "height": {"height", "ht", "heightin", "heightinches"},
    "grad_year": {"gradyear", "grad", "gradyr", "graduation", "graduationyear",
                  "classof", "year", "class", "yr"},
}
_CANON = {a: k for k, al in _ALIASES.items() for a in al}

_FIELDS = ("name", "number", "height", "grad_year")


def _norm_cell(s):
    return re.sub(r"[^a-z0-9]", "", str(s).strip().lower())


def norm_name(s: str) -> str:
    """Match key for dedup — case/whitespace-insensitive."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def parse_height(v) -> float | None:
    """Height → inches. Accepts 71, 71.5, 5'11, 5'11\", 5-11, 5 ft 11, 5ft11.
    Bare numbers: >=36 reads as inches, 4-8 reads as feet. Returns None when
    it can't be read confidently."""
    if v is None:
        return None
    s = str(v).strip().replace("”", '"').replace("’", "'")
    if not s:
        return None
    m = re.fullmatch(r"(\d)\s*(?:'|-|ft\.?|feet)\s*(\d{1,2}(?:\.\d+)?)\s*(?:\"|in\.?|inches)?",
                     s, flags=re.I)
    if m:
        ft, inch = int(m.group(1)), float(m.group(2))
        if inch < 12:
            return ft * 12 + inch
        return None
    m = re.fullmatch(r"(\d)\s*(?:'|ft\.?|feet)\s*", s, flags=re.I)
    if m:                                     # "6'" — a round six feet
        return int(m.group(1)) * 12.0
    try:
        x = float(s.rstrip('"').rstrip("in").rstrip())
    except ValueError:
        return None
    if 36 <= x <= 96:
        return x                              # already inches
    if 4 <= x < 9 and x == int(x):
        return x * 12                         # a bare feet value
    return None


def _parse_int(v, lo, hi):
    try:
        x = float(str(v).strip())
    except (ValueError, TypeError):
        return None
    if x != int(x):
        return None
    x = int(x)
    return x if lo <= x <= hi else None


def _split_rows(text: str):
    """Delimiter-sniffed rows from a CSV/paste block (never raises)."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        delim = "\t" if "\t" in sample else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return [r for r in rows if any(str(c).strip() for c in r)]


def _detect_header(row) -> dict | None:
    """{column index: canonical field} when the row reads as a header."""
    hits = {}
    for i, cell in enumerate(row):
        f = _CANON.get(_norm_cell(cell))
        if f and f not in hits.values():
            hits[i] = f
    return hits if "name" in hits.values() else None


def parse_roster(text: str):
    """→ (rows, warnings). Each row: {name, number, height, grad_year}
    (number/height/grad_year may be None). Warnings are human sentences —
    show them above the preview, never block on them."""
    raw = _split_rows(text)
    warnings = []
    if not raw:
        return [], []
    colmap = _detect_header(raw[0])
    body = raw[1:] if colmap else raw
    if not colmap:
        # positional: name, number, height, grad_year
        colmap = {i: f for i, f in enumerate(_FIELDS)}
        # …unless col 0 is numeric on most rows → number-first paste
        num_first = sum(1 for r in body if r and _parse_int(r[0], 0, 999) is not None)
        if body and num_first >= max(2, (len(body) + 1) // 2) and any(len(r) > 1 for r in body):
            colmap = {0: "number", 1: "name", 2: "height", 3: "grad_year"}
            warnings.append("No header row — read columns as number, name, "
                            "height, grad year.")
        else:
            warnings.append("No header row — read columns as name, number, "
                            "height, grad year.")

    rows = []
    for ln, r in enumerate(body, start=(2 if _detect_header(raw[0]) else 1)):
        vals = {f: (r[i].strip() if i < len(r) else "")
                for i, f in colmap.items()}
        name = re.sub(r"\s+", " ", vals.get("name", "").strip())
        if not name or _norm_cell(name) in ("tbd", "na", "n/a"):
            warnings.append(f"Line {ln}: no player name — row skipped.")
            continue
        num = _parse_int(vals.get("number"), 0, 999)
        if vals.get("number", "").strip() and num is None:
            warnings.append(f"Line {ln}: couldn't read number "
                            f"'{vals['number']}' for {name} — left blank.")
        ht = parse_height(vals.get("height"))
        if vals.get("height", "").strip() and ht is None:
            warnings.append(f"Line {ln}: couldn't read height "
                            f"'{vals['height']}' for {name} — left blank.")
        gy = _parse_int(vals.get("grad_year"), 2000, 2100)
        if vals.get("grad_year", "").strip() and gy is None:
            warnings.append(f"Line {ln}: couldn't read grad year "
                            f"'{vals['grad_year']}' for {name} — left blank.")
        rows.append({"name": name, "number": num, "height": ht, "grad_year": gy})

    # "Last, First" flip — only when the file is consistent about it (every
    # multi-part name carries exactly one comma), so a stray comma never flips
    # one row of a normal file.
    commas = [r for r in rows if "," in r["name"]]
    if rows and commas and len(commas) == len([r for r in rows if " " in r["name"] or "," in r["name"]]):
        for r in rows:
            if "," in r["name"]:
                last, _, first = r["name"].partition(",")
                if first.strip():
                    r["name"] = f"{first.strip()} {last.strip()}"
        warnings.append('Names looked like "Last, First" — flipped to '
                        '"First Last".')
    return rows, warnings


def plan_import(rows, existing):
    """Diff parsed `rows` against `existing` roster dicts (id, name, number,
    height, grad_year) → per-row plan entries:
        {row, verdict: add|update|skip, pid, changes, reason}
    update = same name already rostered and the file fills/changes
    number/height/grad_year; skip = already rostered with nothing new, or a
    duplicate line within the file itself."""
    by_name = {norm_name(e["name"]): e for e in existing}
    seen_in_file = set()
    plan = []
    for r in rows:
        key = norm_name(r["name"])
        if key in seen_in_file:
            plan.append({"row": r, "verdict": "skip", "pid": None, "changes": {},
                         "reason": "duplicate row in file"})
            continue
        seen_in_file.add(key)
        ex = by_name.get(key)
        if ex is None:
            plan.append({"row": r, "verdict": "add", "pid": None, "changes": {},
                         "reason": "new player"})
            continue
        changes = {}
        for f in ("number", "height", "grad_year"):
            v = r.get(f)
            if v is not None and v != ex.get(f):
                changes[f] = v
        if changes:
            plan.append({"row": r, "verdict": "update", "pid": ex["id"],
                         "changes": changes,
                         "reason": "updates " + ", ".join(changes)})
        else:
            plan.append({"row": r, "verdict": "skip", "pid": ex["id"],
                         "changes": {}, "reason": "already on roster"})
    return plan
