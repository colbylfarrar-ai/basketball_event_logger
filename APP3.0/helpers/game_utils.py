import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
from Database.db import query


def games_for_team(tid, tracked_only=False):
    cond = "AND g.tracked=1" if tracked_only else ""
    rows = query(f"""
        SELECT g.*, t1.name AS t1_name, t2.name AS t2_name
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        WHERE (g.team1_id=? OR g.team2_id=?) {cond}
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
    """, (tid, tid))
    return sorted(rows, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce"), reverse=True)


def win_loss(game, tid):
    my   = game["home_score"] if game["team1_id"]==tid else game["away_score"]
    opp  = game["away_score"] if game["team1_id"]==tid else game["home_score"]
    return ("W" if my>opp else "L"), my, opp


def opponent_name(game, tid):
    return game["t2_name"] if game["team1_id"]==tid else game["t1_name"]


def home_away(game, tid):
    return "Home" if game["team1_id"]==tid else "Away"


def record_from_games(games_list, tid):
    w=l=pf=pa=0
    for g in games_list:
        res,my,opp = win_loss(g, tid)
        pf+=my; pa+=opp
        if res=="W": w+=1
        else:        l+=1
    return w,l,pf,pa


def streak(results: list) -> str:
    if not results:
        return "—"
    cur, cnt = ("W" if results[0] else "L"), 0
    for r in results:
        if ("W" if r else "L") == cur:
            cnt += 1
        else:
            break
    return f"{cur}{cnt}"


def record_str(w, l) -> str:
    return f"{w}-{l}"


def normalize(s: pd.Series, higher_is_better=True) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series(0.5, index=s.index)
    n = (s - lo) / (hi - lo)
    return n if higher_is_better else 1 - n
