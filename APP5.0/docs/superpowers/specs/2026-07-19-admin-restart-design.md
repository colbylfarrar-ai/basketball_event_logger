# Admin restart control — design (2026-07-19)

## Problem

Two admin surfaces already end with "takes effect on the next app restart":
living-recal constant adoption (`helpers/model_constants.py`) and reverting to
committed defaults. There is no way to *cause* that restart from the app — the
founder has to open an SSH session. With the first outside coach onboarding,
the admin panel should close its own loop.

## Constraints (verified on the box, 2026-07-19)

`sudo -n -l` as `app5` grants NOPASSWD on exactly three command strings:

```
/usr/bin/systemctl restart app5-web app5-tracker
/usr/bin/systemctl restart app5-web
/usr/bin/systemctl restart app5-tracker
```

Consequences that drive the design:

- **The argv must match one of those strings exactly.** sudoers matches the full
  command line; appending `--no-block` (or any flag) stops matching, falls
  through to the `(ALL : ALL) ALL` rule, and blocks on a password prompt that
  nothing can answer. The regression is silent until someone clicks the button.
- `app5-litestream` is **not** covered, so it is out of scope.
- Restarting `app5-web` from inside `app5-web` kills the calling process — same
  cgroup. systemd accepts the restart job over dbus *before* it stops the unit,
  so the restart still completes, but our process does not survive it. Anything
  that must be recorded has to be written **before** the call, and the return
  code is not observable.

## Design

### `helpers/server_control.py` (new, Streamlit-free)

Pure + headless-testable, following the `model_constants.py` idiom.

| Function | Behavior |
|---|---|
| `restart_available() -> (bool, str)` | True only on Linux with `/usr/bin/systemctl` present. The string is a human reason ("not a systemd host — local dev") so the UI can disable with an explanation instead of hiding. |
| `live_games() -> list[dict]` | Today's games with `tracked=0` **and** at least one event, with both team names. Mirrors the app's own live definition (`public_feed.py:664`: `tracked` = final, events-without-tracked = live). Date-restricted so an abandoned half-tracked game from last month never trips the warning. |
| `record_restart(email)` | Writes `app_settings['server:last_restart']` = `{"at": iso, "by": email}` and an `audit_log` row. Called *before* the command fires. |
| `last_restart() -> dict \| None` | Reads it back for the panel's "last restart" line. |
| `RESTART_ARGV` | Module constant: `["sudo", "systemctl", "restart", "app5-web", "app5-tracker"]`. Frozen and asserted by a test. |
| `do_restart()` | `subprocess.Popen(RESTART_ARGV, start_new_session=True)`. No shell, no added flags. |

### UI — `pages/12_Settings.py`

A `♻️ Restart the app` expander inside the existing `role == "admin"` block,
placed directly after the living-recal expander (the surface whose changes it
applies).

1. Caption: this is how adopted recal constants take effect; drops every
   connected session for ~10 seconds.
2. `Last restart: <ts> by <email>`, or "No restart recorded yet."
3. If `live_games()` is non-empty, an `st.warning` naming each game: the coach's
   session will stall. Events are not lost — the PWA queues offline and retries —
   but the interruption is real.
4. Two-step confirm: a checkbox ("I understand this drops every connected
   session"), then a `Restart now` primary button that stays `disabled` until
   the box is checked. The live-game warning informs the click; it does not
   block it, so a wedged app can still be fixed.
5. On click: `record_restart(email)` → render "Restarting — this page will
   reconnect in ~10s." → `do_restart()`. Streamlit's built-in auto-reconnect
   brings the page back, and the refreshed panel showing a newer timestamp is
   the confirmation the process itself could never render.

When `restart_available()` is False the button is disabled and the reason shown,
so the panel is honest on a local Windows dev box instead of erroring.

### Testing — `tracker/test_server_control.py`

Standalone-script style (sets `APP5_DATA_DIR` before importing `database.db`),
matching the other 84 tests; `pytest` collection is not used.

- `RESTART_ARGV` equals the sudoers string exactly — the guard against a future
  `--no-block` silently breaking the button.
- `restart_available()` returns `(False, reason)` on a non-systemd host.
- `live_games()` finds a `tracked=0`-with-events game dated today, and ignores
  both a tracked game and an untracked game with no events.
- `record_restart` → `last_restart()` round-trips and leaves an `audit_log` row.
- `do_restart()` invokes `Popen` with `RESTART_ARGV` and `start_new_session=True`
  (monkeypatched — the test never restarts anything).

## Out of scope

- Restarting `app5-litestream` (no sudo grant).
- A health-check/status readout after reconnect. The "last restart" timestamp is
  the proof; polling `systemctl is-active` for three units is more moving parts
  than the confirmation needs.
- Separate per-service buttons. One "restart the app" action matches the deploy
  flow and is one thing to explain to a coach-turned-admin.
