# Overnight run — 2026-09-13 · the sicko layer

Branch `overnight-2026-09-13-sicko`, **unmerged**, seven commits on top of
`ef4481b`. Production still runs `66359ee`. Nothing pushed, nothing deployed,
no ssh, no book modified.

Governed by `THE_SICKO_BOOK_2026-09-12.md` §12–§15, inside `THE_BOOK_2026-09.md`
§18's fourteen rulings.

---

## SUITES — nothing regressed

| suite | baseline (measured first, on this branch point) | final |
|---|---|---|
| `pytest -q` | **498 passed** | **PENDING** |
| `tracker/run_all.py` | **107 passed · 0 failed · 0 timeout** | **PENDING** |
| `tools/freeze_smoke.py` | 45 renders / 0 exceptions (per the freeze book) | **PENDING** |

Both baselines were measured on this branch before anything was touched, and
both came in exactly where the prompt predicted. `run_all` was run WITHOUT
`APP5_DATA_DIR` exported, against `%LOCALAPPDATA%\APP5`, per its own contract.

Two new pytest files were added, so the final pytest count is expected to RISE:
`tracker/test_heat_table.py` (11) and `tracker/test_refusals.py` (24).
`tracker/_test_kinds.script_files()` still returns 107, so `run_all`'s
denominator is unchanged.

---

## PENDING-TASK1

---

## What shipped

PENDING-SHIPPED

---

## Not done, and why

PENDING-NOTDONE

---

## Assumptions

PENDING-ASSUMPTIONS

---

## Contradictions and retractions

PENDING-RETRACTIONS
