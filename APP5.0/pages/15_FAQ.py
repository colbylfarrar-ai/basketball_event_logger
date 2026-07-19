"""
15_FAQ.py — the founder's FAQ, synced from his Google Doc (spec item 10).

The founder keeps writing in the Doc (his workflow, unchanged); the app pulls
the plain-text export on a 6h TTL and renders it natively — searchable,
expander-per-question, with the source Doc linked. Open to every signed-in
role (it's the "how do I track this" manual, mostly tracker-focused).
Admins get a Refresh-now button for right-after-he-edits moments.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from helpers.ui import page_chrome, page_header
import helpers.auth as AUTH
import helpers.faq as FAQ

_cfg, ACCENT = page_chrome("FAQ")

page_header("FAQ",
            sub="How to track, tag and read the numbers — straight from the "
                "founder's playbook. Mostly tracker-focused; it grows as "
                "questions come in.")


@st.cache_data(ttl=600, show_spinner=False)
def _faq_bundle(force_nonce=0):
    data = FAQ.get_faq(force=bool(force_nonce))
    return data, FAQ.parse_sections(data["text"])


_ident = AUTH.current_user() or {}
_is_admin = (_ident.get("role") == "admin")

_force = 0
if _is_admin:
    if st.button("↻ Refresh from the Doc now", key="faq_refresh",
                 help="Pulls the Doc immediately instead of waiting out the "
                      "6-hour cache."):
        _force = 1
        st.cache_data.clear()

_data, _sections = _faq_bundle(_force)

if not _data["text"]:
    st.info("The FAQ hasn't synced yet — check your connection, or read it "
            f"directly: [open the Doc]({_data['source_url']}).")
    st.stop()

if _data["stale"]:
    st.caption("⚠ Showing the last synced copy — the Doc couldn't be reached "
               "just now.")

_qtext = st.text_input("Search the FAQ", key="faq_search",
                       placeholder="e.g. turnover, play type, live link…")
_q = (_qtext or "").strip().lower()

_shown = 0
for _question, _answer in _sections:
    if _q and _q not in _question.lower() and _q not in _answer.lower():
        continue
    _shown += 1
    if not _question:                       # preamble before the first heading
        st.markdown(_answer)
        continue
    with st.expander(_question, expanded=bool(_q)):
        st.markdown(_answer if _answer else "_(see the Doc for this one)_")

if not _shown:
    st.caption("No FAQ entries match that search.")

st.divider()
_when = (_data["fetched_at"] or "—").replace("T", " ")
st.caption(f"Synced from [the founder's Doc]({_data['source_url']}) · last "
           f"pull {_when} UTC · updates land automatically within "
           f"{FAQ.TTL_HOURS} h of an edit.")
