# Auto-Tracker (Video → Event Log) — Feasibility Report

> Future-look reference. Not on the near-term roadmap. Written 2026-06; grounded in 2025-26
> SOTA research + a cost/server analysis. Revisit when (a) a coach asks for it, (b) better open
> vision models + cheaper GPUs lower the bar, or (c) the manual-capture bottleneck becomes the
> top blocker to growth.

## Goal

Replace (or pre-fill) the manual courtside tap-logging with a pipeline that ingests a game
**video** and auto-generates the `game_events` log — ideally with (x,y) shot locations and
per-player attribution — so the analytics engine (WPA, RAPM, opponent-adjusted ratings,
shot quality) runs with far less human capture labor.

## Verdict (read this first)

**Realistically possible — but ONLY with a single FIXED camera that frames the WHOLE court.**
A phone on a tripod counts; a phone in someone's hands does not. The two load-bearing
requirements are **fixed (no pan/zoom)** and **full court in frame**. Do NOT wait for a better
LLM (e.g. Fable 5) — this is specialized computer vision, not an LLM task.

Recommended first move: a one-weekend **Phase-1 prototype on a single real game** before
committing any real effort (see "Phased scope" + "Prototype").

## Why fixed + full-court is non-negotiable

Tied to the three CV sub-problems:

1. **Court homography (pixel → court feet).** On a FIXED camera this is *essentially solved*:
   calibrate once from 4+ known court points, reuse all game. This is the one reliable piece —
   and we already own it (`court_geom.py`, the existing tap (x,y) model). A roaming/zooming
   phone re-breaks the mapping every frame → shot coordinates become garbage. **Fixed is what
   makes (x,y) shot locations possible.**
2. **Player tracking / keeping IDs (association).** Camera motion wrecks association; players
   leaving frame spawn fragments. **Full-court framing + a still camera minimizes both.**
3. **Jersey-number attribution.** Depends entirely on tracking, so it inherits #2.

## State of the art (2025-26, sourced) — be honest about the limits

- **No product auto-stats from a roaming handheld phone.** Every working system (Pixellot, Veo,
  Trace, SportsVisio, Hooper, KINEXON) requires a fixed, elevated, full-court camera. This means
  requiring a tripod is **table stakes, not a competitive weakness** — nobody solves handheld.
- **Synergy and Hudl Assist still use HUMAN taggers in 2025-26** (Synergy 100+ loggers; Hudl
  Assist "trained analysts manually tag every play"). The two highest-accuracy basketball
  products on earth have NOT automated. Strongest signal that full auto isn't solved at pro
  accuracy — and that a **human-in-the-loop correction model stays competitive.**
- **Jersey numbers are the brittle link.** Only ~5-6% of player-crop frames have a legible
  number (occlusion, blur, facing away). Best models ~87% *tracklet-level* on soccer, but
  **69-74% in real "challenge" conditions**, and they still hallucinate impossible numbers
  ("011", "3000").
- **Tracking association is mediocre.** AssA (one player = one ID) ~50-62% on SportsMOT; clustered
  occlusion (3+ players) is the named hard case; raw trackers emit **~10× more tracklet fragments
  than players** per game.
- **Made/miss from a single far camera = least-solved piece.** No credible far-cam accuracy
  number exists; the ~89% figures are close/lab setups. Ball is occluded by net/rim/hands exactly
  at the rim.
- **Homography on a fixed camera = solved** (the reliable piece, see above).

Sources: SoccerNet Jersey Number challenge; "A General Framework for Jersey Number Recognition"
(CVPRW'24); SportsMOT (ICCV'23); Basketball-SORT; roboflow basketball pipeline + camera
calibration writeups; Hudl Assist FAQ; Synergy (nbastuffer). Vendor accuracy claims (SportsVisio
95%, Hooper 92%) are self-published, recommended-setup, aggregate-over-game — discount heavily.

## Server + "don't store video" — both answered

- **Can the current droplet handle it?** No. CPU-only on a ~$5 box = hours-to-overnight per game
  and it would peg the box (kill Streamlit). **Keep the droplet as the always-on web/queue host;
  rent a GPU only while a job runs.**
- **Cost:** lean pipeline (YOLO detect + ByteTrack track + sparse jersey OCR) on a burst GPU =
  **~$0.35-0.50/game** (as low as ~$0.10 with frame-skipping + TensorRT). **Avoid SAM2 /
  segmentation** — that path is $3-10/game. At ~50 games/mo ≈ ~$20-25/mo burst, **$0 when idle.**
  Prototype on Modal (free $30/mo credits); steady-state on RunPod serverless L4 (~$0.69/hr) or
  vast.ai 4090 for batch.
- **"Video doesn't save" — correct and recommended.** Only derived events persist. Also lets us
  promise coaches "we never retain footage" — a real selling point for minors' video.

### Architecture (process-then-delete)

```
[coach uploads MP4]
  → presigned PUT to DO Spaces            (video NEVER touches the droplet disk)
  → enqueue job (game_id + storage key)   (droplet runs FastAPI + queue)
  → burst GPU worker pulls video
        ffmpeg frame extract → detect → track → jersey OCR → homography (x,y) → events
  → writes ONLY derived events to SQLite
  → DELETE source video (+ Spaces lifecycle TTL as backstop)
  → worker scales to zero
```

Gotchas: delete on success AND failure + TTL backstop; never pipe video through the droplet
(presigned URLs only); make the worker idempotent/retryable (spot interruptions happen); hard
max-runtime cap per job; log GPU-seconds/job to track real $/game; keep storage + worker in the
same region (egress on multi-GB video can exceed compute cost).

## Jersey backfill — the right method (and its catch)

"Assign a number when first spotted, propagate forward, retro-tag earlier events" IS the standard
method: **tracklet → number association + forward/backward backfill** (what SoccerNet winners do).
Read the number on the rare legible frames, label the whole tracklet both directions.

Catch — **fragmentation**: a player is ~10 tracklet fragments across a game. The number read on
fragment #3 only backfills fragment #3 unless re-ID stitches all fragments — and **re-ID fails on
same-team uniforms.** So: backfill *within* a tracklet = reliable; *across* fragments = needs a
review step. And a single confident misread **poisons the whole tracklet** (forward + back). Use a
confidence threshold + low-confidence review queue.

## Phased scope — play to assets we already own

- **Phase 1 (highest value / lowest risk): fixed cam → auto shot events, shooter left blank.**
  Detect ball+rim → made/miss → map to (x,y) via existing `court_geom` homography. Output = shot
  chart with makes/misses + locations, **shooter unassigned**. Coach assigns each shooter in the
  **Event Editor we already have** (tap a name per shot). Removes most live-tapping burden using
  only our two solved pieces (homography + Event Editor). Skip player-ID entirely in v1.
- **Phase 2:** player tracking + jersey backfill → *auto-suggest* shooter, low-confidence flagged
  for review. Suggestion the coach confirms, not ground truth.
- **Phase 3:** possessions, lineups, assists, turnovers.

### Structural edge nobody else has

Every Event-Editor correction = **labeled training data** wired straight into our analytics engine
+ `guarded_by`/shot-quality model. The CV industry's whole problem is "auto is ~70%, needs human
fix" — and we already built the human-fix surface. Compounding data flywheel, not a feature.

## OSS to bootstrap (all MIT/Apache, usable today)

- `roboflow/sports` — basketball court keypoints + jersey OCR + homography→top-down radar
- `roboflow/trackers` — clean ByteTrack/SORT-family, benchmarked on SportsMOT/SoccerNet
- `mkoshkina/jersey-number-pipeline` — detect → fine-tuned OCR → majority-vote per tracklet
- `SoccerNet/sn-gamestate` — end-to-end game-state architecture, maps ~1:1 to basketball
- Roboflow Universe basketball detectors (warm starts; fine-tune on our footage)
- Datasets: SportsMOT (240 clips incl. basketball, 150k+ frames), SoccerNet family

## Fable 5 / LLM note

Fable 5 is a Claude LLM, not a sports-CV model. It does NOT do frame-level tracking, jersey OCR,
or ball trajectory, and running a frontier multimodal model over ~160k frames/game is absurd cost.
This is a specialized CV pipeline regardless of which LLM exists. Better open vision models +
cheaper GPUs lower the bar over time — but you start scoped now and ride the improvements; you
don't wait. An LLM might later play a narrow role (reasoning over extracted tracks, scoreboard-OCR
sanity check), never the core.

## Effort / risk

Biggest single engineering undertaking in the whole roadmap: months of CV work + ongoing
retraining/maintenance + solo-founder burden. Phase 1 is the only piece worth touching first.

## Prototype (do this before committing)

Mount a phone on a tripod (~12-16 ft, mid-court sideline or elevated corner), whole court framed,
1080p+, don't move it. On Modal free credits: run `roboflow/sports` homography + a basketball
detector + a made/miss heuristic over ONE real game. Measure how close the auto shot-chart lands
and the real $/game. Cost ≈ $0 + a weekend. That experiment tells you more than any further
analysis.

## Realistic minimum ask for a HS coach

Phone on a tall tripod (~12-16 ft — rail mount or tall tripod), mid-court sideline or elevated
corner, whole court in frame, 1080p+, **don't touch it during the game.** Coaches already
fix-mount for Hudl film, so this is a cheap, familiar ask — and it's the table-stakes setup every
auto-stat product requires.
