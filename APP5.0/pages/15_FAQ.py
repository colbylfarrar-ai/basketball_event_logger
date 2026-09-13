"""
15_FAQ.py — the founder's FAQ, synced from his Google Doc (spec item 10).

The founder keeps writing in the Doc (his workflow, unchanged); the app pulls
the plain-text export on a 6h TTL and renders it natively — searchable,
expander-per-question, with the source Doc linked. Open to every signed-in
role (it's the "how do I track this" manual, mostly tracker-focused).
Admins get a Refresh-now button for right-after-he-edits moments.

It also carries the one section that is NOT synced: "What we measured and
refused" (`faq.REFUSALS`), the reads this app declined to ship and the
measurements that killed them. That is code, not a fetch, so it renders even
when the Doc is unreachable — and it leads the page, because for an analyst who
has been burned by a black box "why should I believe any of this" is the first
question, not the last.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from helpers.ui import page_chrome, page_header
import helpers.auth as AUTH
import helpers.faq as FAQ
import helpers.ui as _uimod          # clear_data() — see its docstring

_cfg, ACCENT = page_chrome("FAQ")

page_header("FAQ",
            sub="How to track, tag and read the numbers — straight from the "
                "founder's playbook. Mostly tracker-focused; it grows as "
                "questions come in.")


def _render_refusals(filter_q=""):
    """"What we measured and refused" — the app's most credible asset, finally
    on a screen a coach can reach.

    Placed ABOVE the synced Doc sections deliberately. The Doc answers "how do
    I tag a play type"; this answers "why should I believe any of this", and for
    an analyst who has been burned by a black box that is the first question,
    not the last. It is also the only part of the FAQ that cannot go stale
    without somebody editing code, so it leads.
    """
    rows = FAQ.refusals()
    if filter_q:
        rows = [r for r in rows
                if any(filter_q in str(x).lower() for x in r)]
    if not rows:
        return 0
    st.markdown("<div class='lab-hdr'>What we measured and refused</div>",
                unsafe_allow_html=True)
    st.caption(
        "Every number in this app that carries a sentence has been measured "
        "against itself first — and some of them failed. These are the reads "
        "this app declined to ship, what the measurement said, and what "
        "shipped instead. Nothing here is a hypothetical; each entry names the "
        "file that computes it.")
    for _id, claim, measurement, verdict, source in rows:
        with st.expander(claim, expanded=bool(filter_q)):
            st.markdown(f"**What we measured**\n\n{measurement}")
            st.markdown(f"**Verdict**\n\n{verdict}")
            st.caption(f"Source: `{source}`")
    st.divider()
    return len(rows)


@st.cache_data(ttl=600, show_spinner=False)
def _faq_bundle(force_nonce=0):
    data = FAQ.get_faq(force=bool(force_nonce))
    return data, FAQ.parse_sections(data["text"])


_ident = AUTH.current_user() or {}
_is_admin = (_ident.get("role") == "admin")

_force = 0
# Offline (the demo launcher), the Refresh button can only spend 15s failing —
# so it is not offered rather than offered and broken.
if _is_admin and not FAQ.offline():
    if st.button("↻ Refresh from the Doc now", key="faq_refresh",
                 help="Pulls the Doc immediately instead of waiting out the "
                      "6-hour cache."):
        _force = 1
        _uimod.clear_data()

_data, _sections = _faq_bundle(_force)

if not _data["text"]:
    # The Doc half can be unreachable; the measured half never is. It is code,
    # not a network fetch, so a page that stopped here would hide the one
    # section that cannot go stale — and hide it precisely on the laptop with
    # no connection, which is a gym.
    _render_refusals()
    st.info("The rest of the FAQ hasn't synced yet — check your connection, or "
            f"read it directly: [open the Doc]({_data['source_url']}).")
    st.stop()

if _data.get("offline"):
    _when = (_data["fetched_at"] or "—").split("T")[0]
    st.caption(f"Offline — showing the copy synced {_when}.")
elif _data["stale"]:
    st.caption("⚠ Showing the last synced copy — the Doc couldn't be reached "
               "just now.")

_qtext = st.text_input("Search the FAQ", key="faq_search",
                       placeholder="e.g. turnover, play type, live link…")
_q = (_qtext or "").strip().lower()


_ref_hits = _render_refusals(_q)

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

if not _shown and not _ref_hits:
    st.caption("No FAQ entries match that search.")
elif not _shown and _ref_hits:
    st.caption(f"No synced FAQ entries match that search — "
               f"{_ref_hits} above, under what we measured and refused.")

st.divider()
_when = (_data["fetched_at"] or "—").replace("T", " ")
_tail = ("this copy is frozen until the app is back online."
         if _data.get("offline") else
         f"updates land automatically within {FAQ.TTL_HOURS} h of an edit.")
st.caption(f"Synced from [the founder's Doc]({_data['source_url']}) · last "
           f"pull {_when} UTC · {_tail}")
