# Living-recal log

Append-only trail of every `tools.living_recal` run (founder batch item 7).
Each line: timestamp · tracked-game count · ADOPTED/held · incumbent→best T6a
walk-forward margin MAE (F+M sum) · reason. Adoption writes the constant set to
`app_settings['model_constants']`; it takes effect on the next process start
(the deploy restart). Full machine-readable history lives in
`app_settings['living_recal:history']`.

Baseline: the 2026-07-18 aggressive recal (see `RECAL_2026-07-18.md`) — the
constants this loop starts from and can only replace on a strict beat-or-tie.

<!-- runs appended below -->
