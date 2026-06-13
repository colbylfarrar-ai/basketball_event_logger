"""
helpers/dashboard — the Team Dashboard's tabs, one module per top tab.

pages/6_Team_Dashboard.py grew to ~5,600 lines; each tab is being carved out
into a module here (Big Bet 5, part 2). The page stays the orchestrator: it
computes the shared per-team state once (bundle, ratings, game log, theme
constants), packs it into a SimpleNamespace `ctx`, and each module's
``render(ctx)`` — an @st.fragment — draws its tab from that.

Convention: modules import their own libraries (streamlit/pandas/plotly/
helpers); everything TEAM-SPECIFIC or THEME-SPECIFIC rides in on ctx:
    ctx.bundle   TA.team_bundle(...) dict        ctx.team_id  selected team
    ctx.scored   TR.score_ratings(gender)        ctx.rec      bundle["record"]
    ctx.tracked  TR.tracked_ratings(gender)      ctx.log      bundle["game_log"]
    ctx.GOOD / ctx.BAD                           ctx.style    style_fig wrapper
(extend per-module as tabs move over — keep the names identical to the page's).
"""
