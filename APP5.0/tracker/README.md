# APP5 Mobile Tracker

Offline-first courtside game logger (PWA) + FastAPI sync layer. Writes to the
same SQLite database as the Streamlit app, through the same shared write path
(`helpers/game_events.py`), so stats never drift between the two.

## Run

Easiest — server + public HTTPS tunnel in one window:

```
powershell -File tracker\start_tracker.ps1
```

It prints an `https://....trycloudflare.com` URL — open that on any phone,
anywhere, then Safari → Share → **Add to Home Screen** to install. HTTPS is
required for the full PWA powers (offline app shell, wake lock). The quick
tunnel URL changes each restart; a permanent URL needs a named Cloudflare
tunnel + your own domain.

Manual / same-wifi only:

```
python -m uvicorn tracker.api:app --host 0.0.0.0 --port 8500
```

Open `http://<laptop-ip>:8500` on a phone on the same wifi. Works for logging,
but plain HTTP blocks the offline app shell and wake lock (no secure context).

## Auth

Unset = open (localhost/LAN only). Before exposing to the internet
(Cloudflare Tunnel, VPS), set a token:

```
$env:TRACKER_TOKEN = "long-random-string"     # PowerShell, before uvicorn
```

Coaches enter the same token once on the app's setup screen (stored on device).

## How offline works

Every tap is queued in the phone's IndexedDB with a client UUID, then synced in
order whenever wifi exists. The server dedupes by UUID (`game_events.client_uuid`),
so retries after flaky-wifi dropouts can never double-log an event. Score and
play-by-play are computed locally on the phone, so the app keeps working with
zero connectivity for a whole game.

## Pieces

- `api.py` — FastAPI: game list/rosters, batched idempotent event sync, undo,
  finish, live scoreboard; serves the PWA shell.
- `static/` — the PWA (vanilla JS: court SVG tap capture, event flow,
  IndexedDB queue, service worker, manifest).
- `make_icons.py` — regenerates the home-screen icons.
- `test_api.py` — smoke test against a throwaway DB (`python tracker/test_api.py`).

## Note for dashboards

The API bumps `app_settings.data_version` on finishes, undos, edits and
creates; `page_chrome()` (helpers/ui.py) watches it and clears `st.cache_data`
when it moves, so phone writes reach the Streamlit dashboards on the next page
interaction. Individual live events don't bump it (mirrors the Streamlit
tracker, which also only clears caches at End Game / undo / quick-add) — every
cache also carries `ttl=600` as a backstop.

## Deliberate Streamlit-only features

Score-only game entry (results without play-by-play), schedule management,
CSV import, team admin/archiving, and team scouting notes stay in the
Streamlit Input Hub — desk work, not courtside work.
