# Turning on coach login (Streamlit app)

The Streamlit app has a built-in login gate (`helpers/auth.py`, Streamlit's
native `st.login` with Google sign-in). It is **off by default** — the app
runs open until `.streamlit/secrets.toml` contains an `[auth]` block. Do this
before the Streamlit app ever gets a public URL.

## One-time setup (~15 minutes)

1. **Google Cloud Console** — <https://console.cloud.google.com>
   - Create a project (any name, e.g. "APP5").
   - APIs & Services → OAuth consent screen → External → fill in app name +
     your email → add scopes `openid`, `email`, `profile` → save.
     While the consent screen is in "Testing" status, add each coach's Gmail
     under Test users (or click "Publish app" to allow any Google account —
     the app_users allowlist still controls who actually gets in).
   - APIs & Services → Credentials → Create credentials → OAuth client ID →
     type **Web application**.
   - Authorized redirect URIs — add BOTH:
     - `http://localhost:8501/oauth2callback`
     - `https://<your-deployed-domain>/oauth2callback` (when you have one)
   - Copy the **Client ID** and **Client secret**.

2. **Secrets file** — copy `.streamlit/secrets.toml.example` to
   `.streamlit/secrets.toml`, paste the client id/secret, and set
   `cookie_secret` to the output of:

   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Restart Streamlit.** You'll see the sign-in screen. **The first account
   to sign in becomes the admin** (that's you — sign in before sharing any
   URL). Add coaches on the Settings page → Account & users.

## How access works

- Google proves *who* someone is; the `app_users` table in SQLite says *what
  they may do* (`admin` = everything + user management, `coach` = everything
  else). Unknown emails see a "not authorized" screen.
- Sessions last 30 days per browser (Streamlit's identity cookie).
- Remove a coach on the Settings page to revoke access.

## Notes

- The mobile tracker (tracker/) has its own token auth (`TRACKER_TOKEN`) —
  unchanged by this.
- `secrets.toml` is gitignored; never commit it.
- Local dev without secrets.toml keeps working exactly as before (open, you
  are implicitly admin).
