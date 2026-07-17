# APP5 — Laptop → Online Host (runbook)

This is the **last step**: take the app off your laptop and put it on a small
always-on server so other coaches can reach it from a URL (and the mobile tracker
can sync from any gym). It is deliberately the *cheapest viable* path from the
scaling roadmap: **one small VPS + Caddy (auto-HTTPS) + systemd + Litestream
backups**, keeping SQLite. DB-per-org / managed Postgres is a later step you do
not need yet.

> ⚠️ I (the assistant) prepared every file and command below, but I **cannot
> provision a server or read your DNS/OAuth secrets** — you run these steps. They
> are exact; copy/paste in order. Everything here was written against the app's
> real entrypoints: `Main.py` (Streamlit) and `tracker/api.py` (FastAPI), with the
> DB path driven by `APP5_DATA_DIR` (see `database/db.py`).

Config files referenced live in [`deploy/`](deploy/):
`Caddyfile`, `app5-web.service`, `app5-tracker.service`, `litestream.yml`,
`app5-litestream.service`, `bootstrap.sh`.

> `bootstrap.sh` is an optional shortcut for **steps 2–3 only** — it stops before
> systemd/secrets/Caddy on purpose. Either run it then jump to step 4, or skip it
> and follow the numbered steps. Don't do both.

---

## Pre-flight (on the laptop, before the server clones)

**1. Commit the staged DB deletion, then verify it's gone from the repo.**
`database/analytics.db` (≈1.7 MB of stale data) is still in the last commit; the
deletion is only *staged*. `.gitignore` does **not** untrack an already-committed
file. If you push without committing that delete, the server's `git clone` ships
the stale DB and the app self-seeds from it on first start (then your real-DB copy
collides with it). After `git commit && git push`, confirm:

```powershell
git ls-tree HEAD database/analytics.db   # must print NOTHING
```

**2. Know where your real DB actually is on THIS laptop.** You run Microsoft Store
Python, which sandbox-redirects `%LOCALAPPDATA%`, so the live DB is **not** at
`%LOCALAPPDATA%\APP5`. It's at the packaged path (498 games as of writing):

```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\Local\APP5\analytics.db
```

You'll scp from there in step 3 — not from `%LOCALAPPDATA%\APP5`.

---

## 0. What you're building

```
            Internet (HTTPS 443)
                  │
              ┌───▼────┐   auto-TLS, reverse proxy, websockets
              │ Caddy  │
              └─┬────┬─┘
   app.yourdomain │    │ track.yourdomain
        ┌─────────▼┐  ┌▼───────────────┐
        │ Streamlit│  │ FastAPI tracker│   both bind 127.0.0.1 only
        │ Main.py  │  │ tracker/api.py │
        └────┬─────┘  └──────┬─────────┘
             └──────┬────────┘
              one SQLite DB  (/var/lib/app5/analytics.db, WAL)
                     │
              ┌──────▼──────┐ continuous replication
              │ Litestream  ├──► S3 / Backblaze B2 / Hetzner box
              └─────────────┘
```

Both processes share **one SQLite file** (WAL is already enabled in
`database/db.py`, with a 5 s busy-timeout) — fine for a small coach cohort on a
single box. Litestream is your disaster-recovery copy, not a second node.

---

## 1. Provision the box (~5 min, ~€4–5/mo)

Any Ubuntu 24.04 VPS works (Hetzner CX22, DigitalOcean, Vultr, Lightsail…).

```bash
ssh root@YOUR_SERVER_IP
adduser app5 && usermod -aG sudo app5          # non-root user
# point DNS first: A records app.yourdomain + track.yourdomain → YOUR_SERVER_IP
```

Firewall — only 80/443 are public; the app/tracker ports stay loopback-only:

```bash
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw enable
```

**Verify DNS resolves to this box before you reach Caddy (step 7)** — Caddy issues
TLS on first run via the ACME HTTP-01 challenge, which fails if the names don't yet
point here. New A records can take minutes to hours:

```bash
dig +short app.yourdomain track.yourdomain   # both must return YOUR_SERVER_IP
```

## 2. Get the code + Python env

A fresh Ubuntu 24.04 box has `python3` but **not** the venv/pip packages — install
the prereqs first or `python3 -m venv` errors with "ensurepip is not available":

```bash
sudo apt update
# python3-dev + libcairo2-dev + pkg-config are REQUIRED for the PDF-export chain:
# xhtml2pdf → svglib → rlpycairo → pycairo ships NO wheel and builds from source,
# so a clean box without these fails `pip install` while compiling pycairo.
sudo apt install -y python3-venv python3-pip git build-essential \
                    python3-dev libcairo2-dev pkg-config
sudo -iu app5
git clone https://github.com/colbylfarrar-ai/basketball_event_logger.git ~/app5
cd ~/app5/APP5.0          # ← the app lives in this subfolder; every step below runs here
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 3. The data directory (do NOT use a synced folder)

```bash
sudo install -d -o app5 -g app5 /var/lib/app5
```

`APP5_DATA_DIR=/var/lib/app5` is set in both systemd units below, so the live DB
+ its WAL sidecars live on a real disk (never OneDrive/Dropbox — a mid-write sync
corrupts SQLite). On first start the app creates `analytics.db` there.

> ⚠️ **Order matters: scp the DB BEFORE you start any service (step 6).** If the
> app boots first it creates an empty `analytics.db` and holds it open in WAL mode;
> scp'ing on top of an open SQLite file produces orphaned `-wal`/`-shm` sidecars
> and a torn header → "database disk image is malformed". To replace the DB later:
> `systemctl stop app5-web app5-tracker`, copy, delete any `analytics.db-wal` /
> `analytics.db-shm`, then start.

To carry your laptop's existing data over (WAL checkpointed first), run this in
**PowerShell**. Note the path: Microsoft Store Python sandboxes `%LOCALAPPDATA%`,
so the live DB is under `...\Packages\...\LocalCache\Local\APP5`, *not*
`%LOCALAPPDATA%\APP5`:

```powershell
$live = "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\Local\APP5\analytics.db"
$env:LIVE = $live
python -c "import sqlite3,os; c=sqlite3.connect(os.environ['LIVE']); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
scp "$live" app5@YOUR_SERVER_IP:/var/lib/app5/analytics.db
```

Then on the server confirm it's YOUR data, not an empty file:
`ls -l /var/lib/app5/analytics.db` (expect ~1.7 MB, not a few KB).

## 4. Turn ON coach login BEFORE the URL is public  🔒

Follow [`AUTH_SETUP.md`](AUTH_SETUP.md) to create the Google OAuth client, then:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
python -c "import secrets; print(secrets.token_hex(32))"   # → cookie_secret
nano .streamlit/secrets.toml
```

**Two places must match (this is the #1 thing that breaks first sign-in):**
1. In `.streamlit/secrets.toml`, set `redirect_uri = "https://app.yourdomain/oauth2callback"`.
   Streamlit sends *this exact value* to Google — it is **not** derived from the
   request host. The example ships `http://localhost:8501/oauth2callback`; leaving
   it there → Google `redirect_uri_mismatch` / bounce to a dead localhost page.
2. In the Google console (project `app5-499205`), add that same production URI to
   the OAuth client's Authorized redirect URIs (keep localhost too for dev).

`secrets.toml` is gitignored — never commit it. Without an `[auth]` block the app
runs **open** (implicit admin to anyone who reaches the URL) with no warning, so
this must be done before exposing it. **After Caddy is up (step 7), verify auth is
live:** load `https://app.yourdomain` and confirm you get the *Sign in* screen, not
the dashboard.

## 5. Tracker token

The mobile tracker authenticates with a per-coach token (issued on the Settings
page) or the `TRACKER_TOKEN` env master. Set a strong master for bootstrap:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # → TRACKER_TOKEN
```

Put it in `deploy/app5-tracker.service` (`Environment=TRACKER_TOKEN=…`) **now,
before you copy the unit in step 6** — the file ships as `CHANGE_ME`, a
known-credential backdoor if left. If you edit it *after* `sudo cp`, change the
**installed** copy at `/etc/systemd/system/app5-tracker.service` (or
`systemctl edit app5-tracker`) then `daemon-reload && systemctl restart
app5-tracker`; editing the repo copy post-copy has no effect on the running service.

## 6. systemd services

Both units hard-code `WorkingDirectory` + `ExecStart` at `/home/app5/app5/APP5.0`
(the app lives in the `APP5.0/` subfolder of the clone). If you cloned elsewhere,
fix those paths first. Edit the **repo copies**, *then* copy them in — so the
installed units carry your edits:

```bash
nano ~/app5/APP5.0/deploy/app5-tracker.service  # set a real TRACKER_TOKEN (not CHANGE_ME)
nano ~/app5/APP5.0/deploy/app5-web.service      # confirm paths
sudo cp ~/app5/APP5.0/deploy/app5-web.service      /etc/systemd/system/
sudo cp ~/app5/APP5.0/deploy/app5-tracker.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now app5-web app5-tracker
systemctl status app5-web app5-tracker     # both → active (running)
```

(Only do `enable --now` here once the DB is in place from step 3 and `secrets.toml`
has its `[auth]` block from step 4.)

## 7. Caddy (HTTPS + reverse proxy, websockets)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp ~/app5/APP5.0/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile           # set your real domains + email
sudo systemctl reload caddy
```

Visit `https://app.yourdomain` → Google sign-in. **The first account to sign in
becomes the admin (you).** Then add coaches on Settings → Account & users.

## 8. Litestream (continuous backup)

```bash
curl -sL https://github.com/benbjohnson/litestream/releases/latest/download/litestream-linux-amd64.deb -o /tmp/ls.deb
sudo dpkg -i /tmp/ls.deb
sudo cp ~/app5/APP5.0/deploy/litestream.yml /etc/litestream.yml
sudo nano /etc/litestream.yml            # set bucket + credentials (B2/S3/…)
sudo cp ~/app5/APP5.0/deploy/app5-litestream.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now app5-litestream
```

**Restore drill** (do it once so you trust it):

```bash
sudo systemctl stop app5-web app5-tracker app5-litestream
sudo mv /var/lib/app5/analytics.db /var/lib/app5/analytics.db.bak
sudo -u app5 litestream restore -config /etc/litestream.yml /var/lib/app5/analytics.db
sudo systemctl start app5-litestream app5-web app5-tracker
```

## 9. Cold-start the Coaches' Co-op (GTM, not code)

The co-op is **Solo by default**, so on day one the shared pool is empty and
scouting shows neutral "hasn't shared" everywhere. Seed it: in **Settings →
Account & users**, comp a **founding cohort** of coaches to **League-wide** (and
Paid). The moment ≥2 coaches are League-wide and have tracked a game, scouting
lights up for all of them. This is the network-effect flywheel — pitch it as
"join the co-op, share to scout."

To connect a phone, each coach needs **two** things: the tracker address
**`https://track.yourdomain`** (open it in the phone browser → Add to Home Screen)
and the per-coach **token** issued in Settings. The Settings page shows the token
but not the URL, so include the URL when you hand out tokens. *(Optional follow-up:
surface the URL next to the token in `pages/12_Settings.py` via an `APP5_TRACKER_URL`
env on `app5-web.service` — small code change, not done here.)*

---

## Updates / operations

**The box (provisioned):** `app5@107.170.27.154` — hostname `hooptracks`, serving
`app.hooptracks.com` / `track.hooptracks.com` / `live.hooptracks.com` via Caddy.
Auth is the laptop's `~/.ssh/id_ed25519` key (no password); the `app5` user has
passwordless sudo for systemctl. One-shot deploy from the laptop:

```bash
git push origin main
ssh app5@107.170.27.154 "cd ~/app5/APP5.0 && git pull --ff-only && sudo systemctl restart app5-web"
# restart app5-tracker too only when tracker/ changed;
# add `pip install -r requirements.txt` (in the venv) only when requirements changed
```

Full update sequence (deps changed, or in doubt):

```bash
cd ~/app5/APP5.0 && git pull && . .venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart app5-web app5-tracker
```

- **Logs:** `journalctl -u app5-web -f` (or `app5-tracker`, `app5-litestream`).
- **DB migrations** run automatically on startup (`database/db.py`,
  idempotent) — including the one-time per-coach `shares_pool` backfill.
- **Health:** `curl -sI https://app.yourdomain | head -1` → `200`. (Note: an
  *open* app also returns 200 — confirm you see the Sign-in screen, not the
  dashboard, to know `[auth]` is active.)
- **PWA updates:** if a `git pull` changes anything under `tracker/static/`
  (`app.js`, `court.js`, `style.css`, `index.html`), bump `CACHE` in
  `tracker/static/sw.js` (e.g. `tracker-v3` → `v4`) in the same change, or
  installed phones keep serving the old cached shell.

## When to graduate off this box (later — not now)

This single-box/SQLite setup comfortably carries the near-term goal (2–10 coaches,
scaling toward ~100 light users). Move up only when you actually hit it:
managed Postgres + DB-per-org, and the Stripe `paid_until` poll for self-serve
billing (both already noted in the scaling roadmap as deferred).
