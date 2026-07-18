# Win-probability calibration — 2025-2026

Generated 2026-07-18 by `python -m tools.backtest --wp-report`.

**Pool**: 39 tracked games, 1989 win-prob curve steps
(one sample per made basket — busy stretches weigh more).

**Brier score: 0.094** (lower is better; a coin-flip guesser scores 0.2500,
always guessing the pool's home base rate of 48.4% scores
0.2497). First half 0.1423 · second half 0.0468
— late-game confidence should and does score better.

| Predicted | Avg predicted | Observed home-win | n |
|---|---|---|---|
| 0%–10% | 1.7% | 1.6% | 512 |
| 10%–20% | 14.4% | 9.0% | 133 |
| 20%–30% | 25.2% | 13.6% | 125 |
| 30%–40% | 35.4% | 31.7% | 142 |
| 40%–50% | 43.9% | 47.7% | 132 |
| 50%–60% | 53.1% | 61.5% | 221 |
| 60%–70% | 64.8% | 68.3% | 101 |
| 70%–80% | 75.1% | 92.4% | 105 |
| 80%–90% | 85.3% | 97.8% | 92 |
| 90%–100% | 98.3% | 100.0% | 426 |

**Read**: each row is a probability decile — a calibrated model's *observed*
column tracks its *predicted* column. Divergence at the tails on a pool this
size is expected sampling noise; recheck each season as the tracked book grows.
