"""
player_edge.py (dashboard) — shared renderer for the player-edge leaderboards.

Draws the boards from helpers.player_edge.edge_boards in a responsive grid so the
Rankings League Lab and the Players Lab tab show the SAME tables from one source.
Streamlit UI only; all data comes in via `boards`.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


def _col_config(board):
    cfg = {}
    for c in board.get("signed", []):
        cfg[c] = st.column_config.NumberColumn(c, format="%+.2f")
    for c in board.get("pct", []):
        cfg[c] = st.column_config.NumberColumn(c, format="%d%%")
    return cfg


def render(boards, per_row=3, key_prefix="pe"):
    """Render the player-edge boards in a grid, `per_row` tables per row. Each board
    that has no qualifying players shows a graceful note instead of an empty table."""
    if not boards:
        return
    for i in range(0, len(boards), per_row):
        chunk = boards[i:i + per_row]
        cols = st.columns(len(chunk))
        for col, board in zip(cols, chunk):
            with col:
                st.markdown(f"<div class='lab-hdr'>{board['title']}</div>",
                            unsafe_allow_html=True)
                st.caption(board["caption"])
                rows = board.get("rows") or []
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True,
                                 width="stretch", column_config=_col_config(board),
                                 key=f"{key_prefix}_{board['key']}")
                else:
                    st.caption("Not enough tracked sample yet.")
