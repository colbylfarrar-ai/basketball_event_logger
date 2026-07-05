"""
advanced_ratings.py — one shared "Impact & Splits" surface for the rebuilt player
rating engine (see [[app5-rating-rebuild]]). Renders the NEW rating dimensions that
the classic five-rating table doesn't show, so every player surface (Players
rankings, Team Dashboard roster, Scout, Player Profile) can drop in the same tab
and stay consistent:

    Impact       pure-RAPM points per 100 possessions (opponent + teammate
                 adjusted) — the possession-value pillar folded into OVERALL.
    RimDef /     the DEFENSE rating split into rim protection vs perimeter
    PerimDef     containment (0-100 each).
    OREBrtg /    the REBOUNDING rating split into offensive vs defensive glass.
    DREBrtg
    AST% +       playmaking depth: on-court assist rate + passer completion
    passer       (FG% / Open% of the shots a player's passes create).
    depth        tracked vs hand-entered-box games + the confidence tier, so a
                 box-heavy rating reads as the softer number it is.

Every value comes straight from player_ratings.player_stat_table rows — this
module only presents them (pure display, no re-derivation). Two entry points:

    leaderboard(rows, paid, key)  — a sortable pool table + leaders strip
                                    (Players / Team Dashboard / Scout).
    player_panel(P, paid)         — a one-player section (Player Profile card).

All the columns here are EVENT-DERIVED (player_ratings.EVENT_DERIVED_STATS), so
both entry points gate behind `paid` and show the upsell line when locked.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import helpers.cards as C


LOCK_MSG = ("Impact, defense/rebounding splits and passer quality are built from "
            "tracked play-by-play events — available on a paid plan.")

# 0-100 split sub-ratings shown as progress bars (all scaled 50 = avg, +10 = 1 SD).
_SPLIT_COLS = ["RimDef", "PerimDef", "OREBrtg", "DREBrtg"]


def _has_any(rows, keys):
    return any(r.get(k) is not None for r in rows for k in keys)


def leaderboard(rows, paid, key="adv"):
    """Pool-wide 'Impact & Splits' tab body. `rows` = player_stat_table values
    (list or dict-values); `paid` gates the event-derived numbers; `key` namespaces
    the widgets so several instances (Players + Scout + TD) never collide."""
    rows = list(rows.values()) if isinstance(rows, dict) else list(rows)
    if not paid:
        st.info(LOCK_MSG)
        return
    if not rows:
        st.caption("No rated players in this pool yet.")
        return

    st.caption(
        "**Beyond the five ratings.** **Impact** is pure RAPM — points per 100 "
        "possessions a player adds vs an average player, holding teammates AND "
        "opponents constant. **RimDef/PerimDef** and **OREB/DREB** split the "
        "Defense and Rebounding ratings; **AST%** and **Pass FG%/Open%** read "
        "playmaking depth. **Conf** flags how much game evidence backs the number "
        "— *(box)* means mostly hand-entered box scores, not tracked film.")

    df = pd.DataFrame([{
        "Rank": r.get("Rank"), "Player": r.get("name"),
        "Team": C.team_short(r.get("team", "")), "Cls": r.get("class"),
        "GP": r.get("GP"), "Box": r.get("ManualGP", 0) or 0,
        "Conf": r.get("Confidence"),
        "Impact": r.get("Impact"),
        "OVERALL": r.get("OVERALL"), "DEFENSE": r.get("DEFENSE"),
        "RimDef": r.get("RimDef"), "PerimDef": r.get("PerimDef"),
        "REBOUNDING": r.get("REBOUNDING"),
        "OREBrtg": r.get("OREBrtg"), "DREBrtg": r.get("DREBrtg"),
        "AST%": r.get("AST%"), "PassFG%": r.get("PassFG%"),
        "PassOpen%": r.get("PassOpen%"),
    } for r in rows])
    df = df.sort_values("Impact", ascending=False, na_position="last")

    prog = ["OVERALL", "DEFENSE", "RimDef", "PerimDef",
            "REBOUNDING", "OREBrtg", "DREBrtg"]
    cfg = {c: st.column_config.ProgressColumn(c, format="%.1f", min_value=0,
                                              max_value=100) for c in prog}
    cfg["Impact"] = st.column_config.NumberColumn(
        "Impact", format="%.1f", help="Pure RAPM — points/100 vs an average "
        "player (opponent + teammate adjusted).")
    for c in ("AST%", "PassFG%", "PassOpen%"):
        cfg[c] = st.column_config.NumberColumn(c, format="%.1f")
    cfg["Box"] = st.column_config.NumberColumn(
        "Box", help="Hand-entered box-score games behind the rating (count 0.35x "
        "a tracked game toward confidence).")
    st.dataframe(df, hide_index=True, width="stretch",
                 height=min(720, 60 + 34 * len(df)), column_config=cfg,
                 key=f"{key}_adv_df")

    # ── leaders strip: who tops each new dimension ───────────────────────────
    def _lead(col, fmt="{:.1f}", hi=True):
        cand = [r for r in rows if r.get(col) is not None]
        if not cand:
            return None
        r = (max if hi else min)(cand, key=lambda x: x[col])
        return C.glass(col, fmt.format(r[col]), r["name"],
                       color=C.tier(r["OVERALL"])[0] if r.get("OVERALL") else "var(--text)")

    st.markdown("<div class='pl-hdr'>Leaders</div>", unsafe_allow_html=True)
    tiles = [("Impact", "{:+.1f}"), ("RimDef", "{:.1f}"), ("PerimDef", "{:.1f}"),
             ("OREBrtg", "{:.1f}"), ("DREBrtg", "{:.1f}"), ("AST%", "{:.1f}%")]
    cols = st.columns(len(tiles))
    for col, (name, fmt) in zip(cols, tiles):
        h = _lead(name, fmt)
        if h:
            col.markdown(h, unsafe_allow_html=True)


def _bar(label, val, hue=None):
    """One 0-100 split-rating row: label · track · value (matches the Players
    'Top 10' banner grammar). None → a muted em-dash row."""
    if val is None:
        return (f"<div style='display:flex;align-items:center;gap:10px;"
                f"padding:3px 0'><div style='flex:1;font-size:12px;color:#8b949e'>"
                f"{label}</div><div style='color:#8b949e'>—</div></div>")
    hue = hue or C.tier(val)[0]
    v = max(0.0, min(100.0, float(val)))
    return (f"<div style='display:flex;align-items:center;gap:10px;padding:3px 0'>"
            f"<div style='width:78px;font-size:12px;color:#c9d1d9'>{label}</div>"
            f"<div style='flex:1;position:relative;height:7px;border-radius:4px;"
            f"background:#161b22'><div style='position:absolute;height:7px;"
            f"border-radius:4px;width:{v}%;background:{hue}'></div></div>"
            f"<div style='width:34px;text-align:right;font-size:13px;font-weight:800;"
            f"color:{hue}'>{val:.1f}</div></div>")


def player_panel(P, paid):
    """One-player 'Impact & Splits' section for the Player Profile card. `P` = the
    player's player_stat_table row. Gates on `paid` (all event-derived)."""
    st.markdown("<div class='lab-hdr'>Impact & rating splits</div>",
                unsafe_allow_html=True)
    if not paid:
        st.info(LOCK_MSG)
        return

    # headline: possession impact + the confidence/depth read
    imp = P.get("Impact")
    conf = P.get("Confidence") or "—"
    gp, box = P.get("GP") or 0, P.get("ManualGP", 0) or 0
    c1, c2, c3 = st.columns(3)
    c1.markdown(C.glass(
        "Impact (RAPM)", f"{imp:+.1f}" if imp is not None else "—",
        "pts / 100 poss",
        color=("#3fb950" if (imp or 0) > 0 else "#f85149") if imp is not None
        else "var(--text)"), unsafe_allow_html=True)
    c2.markdown(C.glass("Confidence", conf,
                        f"{gp} tracked" + (f" · {box} box" if box else "")),
                unsafe_allow_html=True)
    c3.markdown(C.glass(
        "OVERALL", f"{P['OVERALL']:.0f}" if P.get("OVERALL") is not None else "—",
        "rating",
        color=C.tier(P["OVERALL"])[0] if P.get("OVERALL") is not None
        else "var(--text)"), unsafe_allow_html=True)

    # the two rating splits, side by side
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Defense**")
        st.markdown(_bar("Overall", P.get("DEFENSE")) + _bar("Rim", P.get("RimDef"))
                    + _bar("Perimeter", P.get("PerimDef")), unsafe_allow_html=True)
    with rc:
        st.markdown("**Rebounding**")
        st.markdown(_bar("Overall", P.get("REBOUNDING")) + _bar("Offensive", P.get("OREBrtg"))
                    + _bar("Defensive", P.get("DREBrtg")), unsafe_allow_html=True)

    # passer / playmaking depth line (only when the player creates enough shots)
    ast, pfg, popen = P.get("AST%"), P.get("PassFG%"), P.get("PassOpen%")
    pxfg = P.get("PassxFG%")
    if any(v is not None for v in (ast, pfg, popen)):
        bits = []
        if ast is not None:
            bits.append(f"**AST%** {ast:.1f}")
        if pfg is not None:
            xtra = f" (xFG {pxfg:.0f}%)" if pxfg is not None else ""
            bits.append(f"**Pass FG%** {pfg:.1f}{xtra}")
        if popen is not None:
            bits.append(f"**Open%** {popen:.1f}")
        st.caption("Playmaking — " + " · ".join(bits) +
                   "  \n_AST% = share of teammate FGs assisted while on court; "
                   "Pass FG%/Open% = how the shots this player's passes create "
                   "resolve._")
