# Win-probability calibration — 2025-2026

Generated 2026-07-18 by `python -m tools.backtest --wp-report`.

**Pool**: 29 tracked games, 1449 win-prob curve steps
(one sample per made basket — busy stretches weigh more).

**Brier score: 0.0677** (lower is better; a coin-flip guesser scores 0.2500,
always guessing the pool's home base rate of 45.3% scores
0.2478). First half 0.1166 · second half 0.0164
— late-game confidence should and does score better.

| Predicted | Avg predicted | Observed home-win | n |
|---|---|---|---|
| 0%–10% | 1.7% | 0.0% | 434 |
| 10%–20% | 14.4% | 0.0% | 101 |
| 20%–30% | 25.2% | 3.6% | 83 |
| 30%–40% | 35.2% | 25.6% | 82 |
| 40%–50% | 44.0% | 49.4% | 77 |
| 50%–60% | 53.0% | 61.1% | 131 |
| 60%–70% | 65.2% | 68.3% | 60 |
| 70%–80% | 74.9% | 89.4% | 66 |
| 80%–90% | 85.4% | 100.0% | 62 |
| 90%–100% | 98.4% | 100.0% | 353 |

**Read**: each row is a probability decile — a calibrated model's *observed*
column tracks its *predicted* column. Divergence at the tails on a pool this
size is expected sampling noise; recheck each season as the tracked book grows.
