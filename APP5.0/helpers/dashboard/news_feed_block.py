"""news_feed_block.py — the season feed, rendered.

Reverse-chronological, on the landing page, under the identity header: the
OOTP move that makes a database feel like a season someone lived through.
`helpers/news_feed.py` builds the items; this only draws them.

Two rules it follows and one it deliberately does not.

FOLLOWS: every noun that has a page is a link, and every item states its own
evidence. FOLLOWS: nothing is invented -- a result line is a result, a movement
line is two snapshots subtracted, and neither needs a gate because neither is a
model output.

DOES NOT follow the mock's "Power 66.9 -> 68.2" hanging off a game result. That
attribution is not available from weekly snapshots and pretending otherwise
would put a fabricated cause-and-effect on the most-read screen in the app. See
news_feed's docstring. Movement is its own line, sitting beside the games in
the week it covers.
"""
from __future__ import annotations

import html

import streamlit as st

import helpers.news_feed as NF

_WIN = "#2ecc71"
_LOSS = "#f85149"
_UP = "#2ecc71"
_DOWN = "#f85149"


def _row(stamp, body, accent):
    return (
        f"<div style='display:flex;gap:14px;padding:8px 0;"
        f"border-bottom:1px solid var(--border,#ffffff14)'>"
        f"<div style='flex:0 0 74px;color:var(--subtext);font-size:12px;"
        f"padding-top:2px'>{html.escape(stamp)}</div>"
        f"<div style='flex:0 0 3px;background:{accent};border-radius:2px'></div>"
        f"<div style='flex:1'>{body}</div></div>")


def render(ctx, *, limit=24, season=None, heading="Season feed"):
    """The feed for ctx.team_id.

    `ctx` needs team_id, gender and (optionally) season — the same shape every
    other dashboard block takes.
    """
    tid = getattr(ctx, "team_id", None)
    if not tid:
        return
    season = season or getattr(ctx, "season", "Current")
    gender = getattr(ctx, "gender", None)

    try:
        items = NF.feed(tid, gender, season=season, limit=limit)
        summ = NF.summary(tid, gender, season=season)
    except Exception:
        return

    if not items:
        return

    st.markdown(f"<div class='lab-hdr'>{html.escape(heading)}</div>",
                unsafe_allow_html=True)

    # Season shape first — the feed is the detail under it.
    bits = [f"<b>{summ['wins']}-{summ['losses']}</b>",
            f"{summ['games']} games",
            f"{summ['tracked']} tracked"]
    if summ["power_from"] is not None:
        d = summ["power_to"] - summ["power_from"]
        col = _UP if d >= 0 else _DOWN
        bits.append(
            f"Power <b>{summ['power_from']:.1f} → {summ['power_to']:.1f}</b> "
            f"<span style='color:{col}'>({d:+.1f})</span>")
        if summ["rank_from"] and summ["rank_to"]:
            dr = summ["rank_from"] - summ["rank_to"]
            col = _UP if dr >= 0 else _DOWN
            bits.append(f"#{summ['rank_from']} → <b>#{summ['rank_to']}</b> "
                        f"<span style='color:{col}'>"
                        f"({dr:+d} {'spot' if abs(dr) == 1 else 'spots'})</span>")
    st.markdown(
        f"<div style='color:var(--subtext);font-size:13px;margin:-4px 0 10px'>"
        + " · ".join(bits) + "</div>", unsafe_allow_html=True)

    rows = ""
    for it in items:
        stamp = NF.week_label(it["date"])
        if it["kind"] == "result":
            accent = _WIN if it["win"] else _LOSS
            body = (f"<div style='font-weight:700;color:var(--text)'>"
                    f"{html.escape(it['headline'])}</div>")
            if it["notes"]:
                body += (f"<div style='color:var(--subtext);font-size:12px;"
                         f"margin-top:2px'>"
                         f"{html.escape(' · '.join(it['notes']))}</div>")
        else:
            accent = _UP if it["d_rating"] >= 0 else _DOWN
            body = (f"<div style='color:var(--subtext);font-size:13px'>"
                    f"{html.escape(NF.movement_sentence(it))}</div>")
        rows += _row(stamp, body, accent)
    st.markdown(rows, unsafe_allow_html=True)

    if summ["days"]:
        st.caption(
            f"Board movement is measured between {summ['days']} snapshot days. "
            "Those snapshots are WEEKLY, so a move sits beside the games of the "
            "week it covers rather than being pinned to one of them — a week "
            "with two games has one number, and splitting it would be a guess. "
            "Results come from the game log and need nothing tracked.")
    else:
        st.caption(
            "No rating history for this season yet, so the feed shows results "
            "only. History can be reconstructed for a season already played — "
            "Rankings → Rebuild rating history.")
