"""
whiteboard_component.py — the whiteboard's component handle.

`components.declare_component` inspects its caller's MODULE to register the
component; Streamlit pages run via `st.navigation` are exec'd scripts with no
module, so the declaration MUST live in an importable module like this one
(calling it from pages/10_Whiteboard.py raises "module is None").

The frontend is assets/whiteboard/index.html — a no-build plain-JS component
(canvas board + the streamlit:render / setComponentValue protocol).
"""
from pathlib import Path

import streamlit.components.v1 as components

whiteboard = components.declare_component(
    "app5_whiteboard",
    path=str(Path(__file__).resolve().parent.parent / "assets" / "whiteboard"))
