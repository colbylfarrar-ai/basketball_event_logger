"""Theme-reactive chart tokens (backlog item 18).

Verifies helpers.ui resolves CARD_BG / GRID / HEAT / DIVERGE (and the _TOK
extended tokens) from the ACTIVE style preset via refresh_theme_tokens(),
and that style_fig / gauge carry those colours into the figure at call time.
Script-style: run directly (python tracker/test_theme_tokens.py).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_theme_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database
initialize_database()

from helpers import ui
from helpers.settings_utils import STYLE_PRESETS, set_setting

FAILS = []


def check(label, cond):
    print(("PASS" if cond else "FAIL"), label)
    if not cond:
        FAILS.append(label)


# ── default (no setting stored) = Dark preset ────────────────────────────────
ui.refresh_theme_tokens()
dark = STYLE_PRESETS["Dark"]
check("default CARD_BG is Dark card_bg", ui.CARD_BG == dark["card_bg"])
check("default GRID is Dark track", ui.GRID == dark["track"])
check("default HEAT anchored on CARD_BG", ui.HEAT[0][1] == dark["card_bg"])

# ── switch preset globally → tokens follow ───────────────────────────────────
set_setting("app_style", "Forest")
ui.refresh_theme_tokens()
forest = STYLE_PRESETS["Forest"]
check("Forest CARD_BG", ui.CARD_BG == forest["card_bg"])
check("Forest GRID", ui.GRID == forest["track"])
check("Forest HEAT low anchor", ui.HEAT[0][1] == forest["card_bg"])
check("Forest DIVERGE midpoint", ui.DIVERGE[1][1] == forest["track"])
check("Forest _TOK text", ui._TOK["text"] == forest["text"])
check("Forest _TOK border", ui._TOK["border"] == forest["card_border"])
check("Forest _TOK body_bg", ui._TOK["body_bg"] == forest["body_bg"])

# ── style_fig picks the tokens up at call time ───────────────────────────────
import plotly.graph_objects as go
fig = ui.style_fig(go.Figure(go.Bar(x=[1], y=[1])))
check("style_fig font colour = preset text",
      fig.layout.font.color == forest["text"])
check("style_fig hover bg = preset body_bg",
      fig.layout.hoverlabel.bgcolor == forest["body_bg"])
check("style_fig x grid = preset track",
      fig.layout.xaxis.gridcolor == forest["track"])

g = ui.gauge(50, title="t")
check("gauge number colour = preset text",
      g.data[0].number.font.color == forest["text"])

# ── unknown preset name falls back to Dark ───────────────────────────────────
set_setting("app_style", "NotARealPreset")
ui.refresh_theme_tokens()
check("unknown preset falls back to Dark", ui.CARD_BG == dark["card_bg"])

# ── back to Dark, leave the throwaway DB in the default state ────────────────
set_setting("app_style", "Dark")
ui.refresh_theme_tokens()
check("Dark restored", ui.GRID == dark["track"])

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_theme_tokens: ALL PASS")
