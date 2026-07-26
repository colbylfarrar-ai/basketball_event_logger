"""insights_lineups.py — Insights section 4, "Who to play together".

THE LARGEST GAP THIS REDESIGN CLOSES. The most decision-useful cluster in the
app — five-man units with confidence bands, trios and quads, chemistry pairs,
synergy, the finisher finder, star-coverage gaps — lived under Lab → Impact
Lab, and Insights emitted `Lineups` and `Chemistry` as single sentences and
nothing else. A coach reading "who is helping" on one page had to change views
to answer "so who do I play together".

Lab keeps every one of these panels. This is a copy around the question.

PERFORMANCE IS THE DESIGN CONSTRAINT HERE, NOT AN AFTERTHOUGHT
--------------------------------------------------------------
Prod is 1 vCPU / 2 GB with no swap. `networks.chemistry_network` measures
~16.5 s on this book; `lineups.unit_ratings`, `networks.group_units` and
`finisher_finder` are each their own possession walk. So this section is lazy
TWICE:

  * the section itself only computes when a coach opens it (the `_seg`
    switcher, not `st.tabs`, which would execute every body on every rerun);
  * inside it, units / trios / quads / rotation render immediately, and
    chemistry + synergy + the finisher finder sit behind their own button.

That is the difference between a section that costs nothing until it is wanted
and one that puts 20 s on every Insights render.
"""
from __future__ import annotations

import streamlit as st

from helpers.cards import dense_table, verdict_card
from helpers.dashboard import insights_brief as BR

#: session flag for the on-demand half of the section
HEAVY_KEY = "_ins_lineups_heavy"


@st.cache_data(ttl=6 * 3600, show_spinner="Rating the five-man units…")
def _units(team_id, tids, fp=None):
    import helpers.lineups as LU
    return LU.unit_ratings(team_id, game_ids=list(tids)) if tids else []


@st.cache_data(ttl=6 * 3600, show_spinner="Grouping trios and quads…")
def _groups(team_id, tids, fp=None):
    import helpers.networks as NW
    return NW.group_units(team_id, sizes=(3, 4),
                          game_ids=list(tids)) if tids else {}


@st.cache_data(ttl=6 * 3600, show_spinner="Reading the rotation plan…")
def _rotation(team_id, tids, fp=None):
    import helpers.rotation_plan as RP
    if not tids:
        return {}, []
    gids = list(tids)
    try:
        cov = RP.star_coverage(team_id, game_ids=gids)
    except Exception:
        cov = {}
    try:
        prone = RP.foul_prone(team_id, game_ids=gids)
    except Exception:
        prone = []
    return cov, prone


@st.cache_data(ttl=6 * 3600, show_spinner="Walking every shared possession…")
def _chemistry(team_id, tids, fp=None):
    """Chemistry + synergy + the best fifth, off ONE opt-in click.

    All three are separate possession walks and all three are behind the same
    button, because a coach who wants one of them wants the others in the same
    breath — and paying 16.5 s three times in three clicks is worse than once.
    """
    import helpers.networks as NW
    if not tids:
        return {}, {}, []
    gids = list(tids)
    chem = NW.chemistry_network(team_id, game_ids=gids)
    syn = NW.group_synergy(team_id, sizes=(2, 3, 4), game_ids=gids)
    fin = []
    # the finisher finder needs a CORE to fill; the best observed four is the
    # only core the data itself nominates, so nothing here is hand-picked.
    quads = (NW.group_units(team_id, sizes=(4,), game_ids=gids) or {}).get(4) or []
    if quads:
        try:
            fin = NW.finisher_finder(team_id, quads[0]["players"],
                                     game_ids=gids)
        except Exception:
            fin = []
    return chem, syn, (fin or [])


def _fmt_units(units):
    return [{
        "Lineup": " · ".join(u.get("names") or []),
        "Adj Net": f"{u.get('AdjNet') or 0:+.1f}",
        "±95%": f"±{u.get('ci95') or 0:.0f}",
        "Net (raw)": f"{u.get('Net') or 0:+.1f}",
        "ORtg": f"{u.get('AdjORtg') or 0:.0f}",
        "DRtg": f"{u.get('AdjDRtg') or 0:.0f}",
        "Poss": u.get("poss"),
        "≈games": u.get("games_eq"),
    } for u in units]


def render(ctx, *, table, fp=None):
    """Section 4 — Who to play together."""
    tid = getattr(ctx, "team_id", None)
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tid or not tids:
        st.caption("Lineup reads need tracked games with on-floor snapshots.")
        return
    names = {pid: (row or {}).get("name") or f"#{pid}"
             for pid, row in (table or {}).items()}

    # ── the five-man table ───────────────────────────────────────────────────
    BR._hdr("Five-man units — observed, opponent-adjusted",
            "Every exact five that shared the floor for enough possessions. "
            "Adj Net corrects each possession for the quality of the opposing "
            "FIVE, so beating a good team's bench unit does not inflate a "
            "lineup. Trust the sign before the size — a narrow ±95% is the "
            "only thing that makes the size readable.")
    try:
        units = _units(tid, tids, fp=fp)
    except Exception as exc:
        units = []
        st.caption(f"Unit ratings unavailable — {type(exc).__name__}: {exc}")
    if units:
        st.markdown(dense_table(_fmt_units(units)), unsafe_allow_html=True)
        if not any(u.get("adjusted") for u in units):
            st.caption("⚠ Not enough rated-opponent possessions to fit the "
                       "adjustment yet — Adj Net currently equals raw net.")
    else:
        st.caption("No 5-man unit cleared the minimum possessions yet.")

    # ── trios and quads: where rotation decisions actually live ─────────────
    BR._hdr("Trios & quads — the missing middle",
            "Fives are often too specific to have a usable sample and pairs "
            "too vague to act on. NetAdj shrinks the raw net by sample size, "
            "so a 25-possession group at +40 cannot outrank a 120-possession "
            "group at +12.")
    try:
        grp = _groups(tid, tids, fp=fp)
    except Exception as exc:
        grp = {}
        st.caption(f"Group ratings unavailable — {type(exc).__name__}: {exc}")
    for k, label in ((3, "Trios"), (4, "Quads")):
        rows = (grp or {}).get(k) or []
        st.markdown(f"**{label}**")
        if not rows:
            st.caption(f"No {k}-man group cleared the possession gate yet.")
            continue
        st.markdown(dense_table([{
            "Group": " · ".join(r.get("names")
                                or [names.get(p, str(p))
                                    for p in r.get("players", [])]),
            "NetAdj": f"{r.get('NetAdj') or 0:+.1f}",
            "Net": f"{r.get('Net') or 0:+.1f}",
            "ORtg": f"{r.get('ORtg') or 0:.0f}",
            "DRtg": f"{r.get('DRtg') or 0:.0f}",
            "Poss": r.get("poss"), "Weight": r.get("cred"),
        } for r in rows]), unsafe_allow_html=True)

    # ── rotation: star coverage + the foul-prone constraint ─────────────────
    cov, prone = _rotation(tid, tids, fp=fp)
    lines = []
    if cov and cov.get("uncovered_min_share") is not None:
        bleed = cov.get("bleed")
        lines.append((
            "Star coverage", cov.get("uncovered_poss"),
            f"<b>{cov['uncovered_min_share'] * 100:.0f}%</b> of floor time has "
            f"none of the top rotation players on it"
            + (f", and the team is <b>{bleed:+.1f}</b> per 100 in those "
               f"minutes." if bleed is not None else ".")
            + (f" Star minutes overlap on "
               f"<b>{cov['overlap_min_share'] * 100:.0f}%</b> of the clock — "
               f"stagger them and the gap closes."
               if cov.get("overlap_min_share") else "")))
    for r in (prone or [])[:]:
        if not r.get("prone"):
            continue
        lines.append((
            "Foul-prone", r.get("min"),
            f"<b>{r['name']}</b> fouls at <b>{r['pf32']:.1f}</b> per 32 "
            f"minutes — a rotation constraint before it is a discipline note."))
    if lines:
        BR._hdr("Rotation — coverage and constraints")
        st.markdown(verdict_card(lines), unsafe_allow_html=True)

    # ── the on-demand half ──────────────────────────────────────────────────
    BR._hdr("Chemistry, synergy and the best fifth",
            "Three more possession walks — about 20 seconds on this server — "
            "so they run on request rather than on every visit.")
    if not st.session_state.get(HEAVY_KEY):
        if st.button("Run the chemistry pass", key="ins_lu_heavy",
                     help="Pairwise chemistry, group synergy and the finisher "
                          "finder. Cached once it has run."):
            st.session_state[HEAVY_KEY] = True
            st.rerun(scope="fragment")
        st.caption("Pairwise net with teammate and opponent quality removed · "
                   "whether a group beats the sum of its parts · which fifth "
                   "fits the best observed four.")
        return

    try:
        chem, syn, fin = _chemistry(tid, tids, fp=fp)
    except Exception as exc:
        st.caption(f"Chemistry pass unavailable — {type(exc).__name__}: {exc}")
        return

    edges = (chem or {}).get("edges") or []
    if edges:
        st.markdown("**Chemistry pairs** — adjusted for who else was out there")
        st.markdown(dense_table([{
            "Pair": " + ".join(e.get("names") or []),
            "Adj Net": f"{e.get('adj_net', e.get('net')) or 0:+.1f}",
            "Net (raw)": f"{e.get('net') or 0:+.1f}",
            "Poss": e.get("poss"),
        } for e in sorted(edges, key=lambda e: -(e.get("adj_net")
                                                 or e.get("net") or 0))]),
            unsafe_allow_html=True)
        if not (chem.get("totals") or {}).get("adjusted"):
            st.caption("⚠ The sample could not support the quality fit — the "
                       "adjusted column equals the raw one.")
    else:
        st.caption("Not enough shared-floor possessions to draw chemistry "
                   "pairs yet.")

    if any((syn or {}).get(k) for k in (2, 3, 4)):
        import helpers.networks as NW
        st.markdown("**Synergy** — better, or worse, than the sum of its parts")
        try:
            sv = NW.synergy_verdict(syn, names=names)
        except Exception:
            sv = []
        if sv:
            st.markdown(verdict_card(sv), unsafe_allow_html=True)
        for k, label in ((2, "Pairs"), (3, "Trios"), (4, "Quads")):
            rows = (syn or {}).get(k) or []
            if not rows:
                continue
            st.markdown(f"*{label}*")
            st.markdown(dense_table([{
                "Group": " · ".join(names.get(p, str(p))
                                    for p in r.get("players", [])),
                "Synergy (adj)": f"{r.get('syn_adj') or 0:+.1f}",
                "Synergy (raw)": f"{r.get('synergy') or 0:+.1f}",
                "Net": f"{r.get('Net') or 0:+.1f}",
                "Expected": f"{r.get('expected') or 0:+.1f}",
                "Poss": r.get("poss"), "Weight": r.get("syn_cred"),
            } for r in rows]), unsafe_allow_html=True)

    if fin:
        st.markdown("**The best fifth** — every candidate beside the best "
                    "observed four")
        st.markdown(dense_table([{
            "Candidate": r.get("name") or names.get(r.get("pid"),
                                                    str(r.get("pid"))),
            "Unit NetAdj": f"{r.get('NetAdj') or 0:+.1f}",
            "Δ vs core": f"{r.get('delta_vs_core') or 0:+.1f}",
            "Poss": r.get("poss"),
        } for r in fin]), unsafe_allow_html=True)
        st.caption("The COMBINED five's net, not the candidate's own — the "
                   "question is which five works. Δ vs core credits what the "
                   "candidate adds instead of the core's own quality.")
