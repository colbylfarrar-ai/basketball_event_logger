#!/usr/bin/env bash
# APP5 server bootstrap — OPTIONAL shortcut for DEPLOY.md steps 2-3 ONLY.
# It installs system prereqs, the Python venv + deps, creates the data dir, and
# sanity-checks the DB. It deliberately STOPS before touching systemd, secrets,
# Caddy or Litestream — do those by hand per DEPLOY.md steps 4-8 so you don't
# start the web app OPEN (no [auth]) or before TLS exists. Idempotent; re-runnable.
# Run it in an INTERACTIVE shell as the app5 user (it uses password sudo).
# Read DEPLOY.md for the full story.
set -euo pipefail

REPO="${REPO:-$HOME/app5}"
DATA_DIR="${APP5_DATA_DIR:-/var/lib/app5}"

echo "==> System prereqs (python venv/pip, git, build tools)"
sudo -v   # pre-authenticate sudo so later steps don't hang waiting for a password
sudo apt update
sudo apt install -y python3-venv python3-pip git build-essential

echo "==> Python venv + deps"
cd "$REPO"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Data dir $DATA_DIR"
sudo install -d -o "$USER" -g "$USER" "$DATA_DIR"

echo "==> Sanity: DB initializes + entitlement test passes"
APP5_DATA_DIR="$DATA_DIR" python -c "from database.db import initialize_database; initialize_database(); print('db ok')"
python tracker/test_entitlement.py >/dev/null && echo "entitlement test ok"

cat <<'NEXT'

==> Steps 2-3 done. STOP HERE and continue MANUALLY (DEPLOY.md):
    4. scp your real analytics.db to /var/lib/app5/analytics.db  (BEFORE any service start)
    4. .streamlit/secrets.toml  -> set [auth] incl. redirect_uri = https://app.<domain>/oauth2callback
    5. set a real TRACKER_TOKEN in the INSTALLED unit (not the repo copy)
    6. install + enable the systemd units
    7. install + configure Caddy (auto-HTTPS)
    8. install Litestream + run the restore drill once
   Do NOT `systemctl enable app5-web` until secrets.toml [auth] is set and Caddy is up.
NEXT
