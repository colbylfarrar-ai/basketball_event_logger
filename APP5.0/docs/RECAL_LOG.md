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
- 2026-07-19T15:57:07 · games=40 · ADOPTED · incumbent T6a=20.27 → best=20.13 · adopted: T6a 20.27→20.13 (F 10.08, M 10.19)
- 2026-07-24T03:25:56 · games=51 · ADOPTED · incumbent T6a=20.13 → best=20.07 · adopted: T6a 20.13→20.07 (F 10.05, M 10.08)
- 2026-07-31T03:31:39 · games=55 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-07-31T19:56:53 · games=56 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-08-09T22:29:03 · games=59 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-08-11T22:50:56 · games=60 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-08-18T18:02:12 · games=62 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-08-28T18:22:22 · games=62 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-08-31T14:15:32 · games=62 · held · incumbent T6a=20.07 → best=20.07 · held: no candidate beat incumbent by >0.01
- 2026-09-06T14:47:52 · games=63 · ADOPTED · incumbent T6a=20.27 → best=20.13 · adopted: T6a 20.27→20.13 (F 10.08, M 10.19)
