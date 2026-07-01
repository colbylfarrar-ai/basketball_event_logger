"""
10_Whiteboard.py — draw plays on a half or full court. Nothing is stored.

A pure client-side canvas whiteboard: the court is drawn in JavaScript (vector,
crisp at any size) from the same geometry constants the shot-chart model uses
(helpers/court_geom.py), and every stroke lives only in the browser. No DB, no
API, no session state — refreshing the page wipes the board, by design. The one
escape hatch is a "PNG" button that composites the court + drawing and saves to
the coach's own device via canvas.toDataURL (still nothing server-side).

Why not streamlit-drawable-canvas: it round-trips every stroke through Python
(laggy freehand) and the project is stale against current Streamlit. A ~300-line
inline component needs no new dependency and keeps drawing at 60fps.

Coaching notation implemented (standard playbook symbols):
  pen        freehand
  cut        solid arrow            — player movement
  pass       dashed arrow           — the ball moving
  dribble    zigzag arrow           — player moving with the ball
  screen     line with a T-bar end  — pick/screen
  O / X      numbered offense circles / defense X's (auto-number 1-5)

Drawing coordinates are stored in FEET (canvas px / scale), so strokes survive
window resizes; each court mode (half/full) keeps its own op list, so toggling
courts doesn't destroy work in the other mode.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit.components.v1 as components

import helpers.court_geom as CG
from helpers.ui import page_chrome

_cfg, ACCENT = page_chrome("Whiteboard")

st.title("Whiteboard")
st.caption(
    "Sketch plays on a half or full court — solid arrow = cut, dashed = pass, "
    "zigzag = dribble, T-bar = screen, numbered O/X = players. **Nothing is "
    "saved**: leaving or refreshing the page clears the board. Use PNG to keep "
    "a copy on your device."
)

# Court geometry, single-sourced from the shot-location model. The whiteboard
# adds the one real-world constant court_geom doesn't need: a high-school court
# is 84 ft long, so a true half court is 42 ft baseline-to-midcourt (court_geom's
# Y_MAX=38 is the shot-extent window, not the physical half court).
_GEOM = json.dumps({
    "courtW": CG.X_MAX - CG.X_MIN,        # 50 ft sideline to sideline
    "halfLen": 42.0,                      # baseline → midcourt (84 ft court)
    "laneHW": CG.LANE_HW, "laneD": CG.LANE_D,
    "ftR": CG.FT_R, "raR": CG.RA_R,
    "hoopY": CG.HOOP_Y, "rimR": 0.75, "boardY": CG.HOOP_Y - 1.25,
    "threeR": CG.THREE_R, "cornerX": CG.CORNER_X, "cbreak": CG.CBREAK,
    "centerR": CG.FT_R,                   # center circle, 6 ft radius
})

_HTML = r"""
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: transparent; overflow: hidden; }
  body { font-family: 'Segoe UI Variable Display','Segoe UI',-apple-system,
         BlinkMacSystemFont,Inter,Roboto,sans-serif; }
  #wrap { display: flex; flex-direction: column; height: 100%; gap: 8px; }
  #bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
         background: #161b22; border: 1px solid #21262d; border-radius: 10px;
         padding: 7px 9px; }
  .grp { display: flex; align-items: center; gap: 4px; }
  .sep { width: 1px; height: 22px; background: #21262d; margin: 0 4px; }
  button { background: #0d1117; color: #9aa0aa; border: 1px solid #21262d;
           border-radius: 7px; padding: 5px 10px; font-size: 12.5px;
           cursor: pointer; font-family: inherit; line-height: 1.2;
           white-space: nowrap; }
  button:hover { border-color: #3a4048; color: #e6edf3; }
  button.on { background: __ACCENT__22; border-color: __ACCENT__;
              color: __ACCENT__; font-weight: 600; }
  .swatch { width: 22px; height: 22px; border-radius: 50%; padding: 0;
            border: 2px solid transparent; }
  .swatch.on { border-color: #e6edf3; }
  #stage { flex: 1; display: flex; justify-content: center; align-items: center;
           min-height: 0; }
  #frame { position: relative; background: #12141e; border: 1px solid #21262d;
           border-radius: 12px; overflow: hidden; }
  canvas { position: absolute; inset: 0; display: block; }
  #draw { touch-action: none; cursor: crosshair; }
</style>

<div id="wrap">
  <div id="bar">
    <div class="grp">
      <button id="m-half" class="on">Half court</button>
      <button id="m-full">Full court</button>
    </div>
    <div class="sep"></div>
    <div class="grp" id="tools">
      <button data-t="pen" class="on" title="Freehand">Pen</button>
      <button data-t="cut" title="Solid arrow — player cut">Cut &#8594;</button>
      <button data-t="pass" title="Dashed arrow — pass">Pass &#8674;</button>
      <button data-t="dribble" title="Zigzag arrow — dribble">Dribble &#8767;</button>
      <button data-t="screen" title="T-bar — screen">Screen &#8869;</button>
      <button data-t="O" title="Tap to place numbered offense marker">O</button>
      <button data-t="X" title="Tap to place numbered defense marker">X</button>
    </div>
    <div class="sep"></div>
    <div class="grp" id="colors"></div>
    <div class="sep"></div>
    <div class="grp">
      <button id="undo">Undo</button>
      <button id="clear">Clear</button>
      <button id="save" title="Download the board as an image">PNG</button>
    </div>
  </div>
  <div id="stage"><div id="frame">
    <canvas id="court"></canvas>
    <canvas id="draw"></canvas>
  </div></div>
</div>

<script>
(function () {
  const G = __GEOM__;
  const ACCENT = "__ACCENT__";
  const LINE = "#9aa0aa", GOLD = "#e6be64";           // court palette (court_geom)
  const COLORS = [ACCENT, "#e6edf3", "#58a6ff", "#3fb950", "#ff7b72"];
  const M = 1.5;                                       // out-of-bounds margin, feet

  const frame = document.getElementById("frame");
  const stage = document.getElementById("stage");
  const courtCv = document.getElementById("court");
  const drawCv = document.getElementById("draw");
  const cctx = courtCv.getContext("2d");
  const dctx = drawCv.getContext("2d");

  // ── state ─────────────────────────────────────────────────────────────────
  let mode = "half";                    // 'half' | 'full'
  let tool = "pen";
  let color = COLORS[0];
  const ops = { half: [], full: [] };   // per-mode strokes, coords in FEET
  let cur = null;                       // stroke in progress
  let scale = 10;                       // px per foot (set by layout)

  // feet-extent of the visible board per mode. Half court: portrait-ish,
  // baseline at the BOTTOM (matches the app's shot charts). Full court:
  // landscape, baselines left and right.
  function extent() {
    return mode === "half"
      ? { w: G.courtW + 2 * M, h: G.halfLen + 2 * M }
      : { w: 2 * G.halfLen + 2 * M, h: G.courtW + 2 * M };
  }

  // ── layout: fit the court into the stage, resize both canvases ───────────
  function layout() {
    const e = extent();
    const availW = stage.clientWidth, availH = stage.clientHeight;
    scale = Math.min(availW / e.w, availH / e.h);
    const w = Math.round(e.w * scale), h = Math.round(e.h * scale);
    const dpr = window.devicePixelRatio || 1;
    frame.style.width = w + "px";
    frame.style.height = h + "px";
    for (const cv of [courtCv, drawCv]) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
      cv.style.width = w + "px";
      cv.style.height = h + "px";
      cv.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    drawCourt(cctx);
    render();
  }

  // ── court rendering (vector, in feet via canvas transforms) ──────────────
  // One half court is drawn in a local frame: x across the court (-25..25),
  // y up from the baseline (0..42), hoop at (0, hoopY). setTransform maps that
  // frame onto the canvas per end; arcs/lines all inherit the mapping.
  function halfCourtPaths(ctx) {
    const yj = G.hoopY + G.cbreak;                 // corner-3 / arc join height
    const tj = Math.atan2(G.cbreak, G.cornerX);    // arc start angle
    const hw = G.courtW / 2;
    ctx.lineWidth = 0.18;
    ctx.strokeStyle = LINE;
    ctx.beginPath();                               // boundary (3 sides; midcourt
    ctx.moveTo(-hw, G.halfLen);                    //  line drawn by caller)
    ctx.lineTo(-hw, 0);
    ctx.lineTo(hw, 0);
    ctx.lineTo(hw, G.halfLen);
    ctx.stroke();
    ctx.strokeRect(-G.laneHW, 0, 2 * G.laneHW, G.laneD);       // lane
    ctx.beginPath();                                            // FT circle
    ctx.arc(0, G.laneD, G.ftR, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.beginPath();                                            // restricted arc
    ctx.arc(0, G.hoopY, G.raR, 0, Math.PI);
    ctx.stroke();
    ctx.beginPath();                                            // corner 3s + arc
    ctx.moveTo(-G.cornerX, 0); ctx.lineTo(-G.cornerX, yj);
    ctx.moveTo(G.cornerX, 0); ctx.lineTo(G.cornerX, yj);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, G.hoopY, G.threeR, tj, Math.PI - tj);
    ctx.stroke();
    ctx.strokeStyle = GOLD;                                     // backboard + rim
    ctx.lineWidth = 0.28;
    ctx.beginPath();
    ctx.moveTo(-3, G.boardY); ctx.lineTo(3, G.boardY);
    ctx.stroke();
    ctx.lineWidth = 0.22;
    ctx.beginPath();
    ctx.arc(0, G.hoopY, G.rimR, 0, 2 * Math.PI);
    ctx.stroke();
  }

  function drawCourt(ctx) {
    const e = extent();
    ctx.save();
    ctx.clearRect(0, 0, e.w * scale, e.h * scale);
    const s = scale;
    if (mode === "half") {
      // local x → screen x, local y (up) → screen y (down), baseline at bottom
      ctx.setTransform(ctx.getTransform().multiply(
        new DOMMatrix([s, 0, 0, -s, (M + G.courtW / 2) * s, (M + G.halfLen) * s])));
      halfCourtPaths(ctx);
      ctx.beginPath();                            // midcourt line + center circle
      ctx.lineWidth = 0.18; ctx.strokeStyle = LINE;
      ctx.moveTo(-G.courtW / 2, G.halfLen); ctx.lineTo(G.courtW / 2, G.halfLen);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, G.halfLen, G.centerR, Math.PI, 2 * Math.PI);  // half circle in view
      ctx.stroke();
    } else {
      const cy = (M + G.courtW / 2) * s;
      // left end: local y runs toward +screen-x, local x down the screen
      ctx.save();
      ctx.setTransform(ctx.getTransform().multiply(
        new DOMMatrix([0, s, s, 0, M * s, cy])));
      halfCourtPaths(ctx);
      ctx.restore();
      // right end: mirrored
      ctx.save();
      ctx.setTransform(ctx.getTransform().multiply(
        new DOMMatrix([0, s, -s, 0, (M + 2 * G.halfLen) * s, cy])));
      halfCourtPaths(ctx);
      ctx.restore();
      ctx.lineWidth = 0.18 * s; ctx.strokeStyle = LINE;         // midcourt (screen px)
      const mx = (M + G.halfLen) * s;
      ctx.beginPath();
      ctx.moveTo(mx, M * s); ctx.lineTo(mx, (M + G.courtW) * s);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(mx, cy, G.centerR * s, 0, 2 * Math.PI);
      ctx.stroke();
    }
    ctx.restore();
  }

  // ── stroke rendering (screen px, points stored in feet) ──────────────────
  const px = (f) => f * scale;

  function arrowHead(ctx, x1, y1, x2, y2) {
    const a = Math.atan2(y2 - y1, x2 - x1), L = px(1.3), w = 0.5;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - L * Math.cos(a - w), y2 - L * Math.sin(a - w));
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - L * Math.cos(a + w), y2 - L * Math.sin(a + w));
    ctx.stroke();
  }

  function renderOp(ctx, o) {
    ctx.strokeStyle = o.c; ctx.fillStyle = o.c;
    ctx.lineWidth = px(0.32);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.setLineDash([]);
    if (o.t === "pen") {
      if (o.pts.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(px(o.pts[0][0]), px(o.pts[0][1]));
      for (const p of o.pts) ctx.lineTo(px(p[0]), px(p[1]));
      ctx.stroke();
      return;
    }
    if (o.t === "O" || o.t === "X") {
      const x = px(o.x), y = px(o.y), r = px(1.15);
      ctx.lineWidth = px(0.28);
      ctx.font = "600 " + px(1.5) + "px 'Segoe UI',sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      if (o.t === "O") {
        ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.stroke();
        ctx.fillText(String(o.n), x, y + px(0.08));
      } else {
        ctx.beginPath();
        ctx.moveTo(x - r * 0.8, y - r * 0.8); ctx.lineTo(x + r * 0.8, y + r * 0.8);
        ctx.moveTo(x + r * 0.8, y - r * 0.8); ctx.lineTo(x - r * 0.8, y + r * 0.8);
        ctx.stroke();
        ctx.font = "600 " + px(1.05) + "px 'Segoe UI',sans-serif";
        ctx.fillText(String(o.n), x + r * 1.25, y - r * 0.85);
      }
      return;
    }
    // two-point tools
    const x1 = px(o.x1), y1 = px(o.y1), x2 = px(o.x2), y2 = px(o.y2);
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
    if (len < 2) return;
    if (o.t === "pass") ctx.setLineDash([px(0.9), px(0.65)]);
    if (o.t === "dribble") {
      // zigzag: perpendicular triangle wave along the segment, arrowhead at end
      const ux = dx / len, uy = dy / len, nx = -uy, ny = ux;
      const amp = px(0.55), wave = px(1.5);
      const straight = Math.min(px(1.2), len * 0.2);   // flat tail before the head
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      let d = wave / 2, k = 0;
      while (d < len - straight) {
        const sgn = (k % 2 === 0) ? 1 : -1;
        ctx.lineTo(x1 + ux * d + nx * amp * sgn, y1 + uy * d + ny * amp * sgn);
        d += wave; k++;
      }
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);
      arrowHead(ctx, x1, y1, x2, y2);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash([]);
    if (o.t === "cut" || o.t === "pass") arrowHead(ctx, x1, y1, x2, y2);
    if (o.t === "screen") {                      // T-bar perpendicular to the end
      const ux = dx / len, uy = dy / len, half = px(1.1);
      ctx.beginPath();
      ctx.moveTo(x2 - uy * half, y2 + ux * half);
      ctx.lineTo(x2 + uy * half, y2 - ux * half);
      ctx.stroke();
    }
  }

  function render() {
    const e = extent();
    dctx.clearRect(0, 0, e.w * scale, e.h * scale);
    for (const o of ops[mode]) renderOp(dctx, o);
    if (cur) renderOp(dctx, cur);
  }

  // ── pointer input ─────────────────────────────────────────────────────────
  function pos(ev) {
    const r = drawCv.getBoundingClientRect();
    return [(ev.clientX - r.left) / scale, (ev.clientY - r.top) / scale];
  }

  function nextNum(t) {                     // O/X auto-number, cycling 1-5
    return ops[mode].filter((o) => o.t === t).length % 5 + 1;
  }

  drawCv.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    drawCv.setPointerCapture(ev.pointerId);
    const [fx, fy] = pos(ev);
    if (tool === "O" || tool === "X") {
      ops[mode].push({ t: tool, c: color, x: fx, y: fy, n: nextNum(tool) });
      render();
      return;
    }
    cur = tool === "pen"
      ? { t: "pen", c: color, pts: [[fx, fy]] }
      : { t: tool, c: color, x1: fx, y1: fy, x2: fx, y2: fy };
  });
  drawCv.addEventListener("pointermove", (ev) => {
    if (!cur) return;
    const [fx, fy] = pos(ev);
    if (cur.t === "pen") cur.pts.push([fx, fy]);
    else { cur.x2 = fx; cur.y2 = fy; }
    render();
  });
  const finish = () => {
    if (!cur) return;
    const trivial = cur.t !== "pen" && Math.hypot(cur.x2 - cur.x1, cur.y2 - cur.y1) < 0.3;
    if (!trivial && !(cur.t === "pen" && cur.pts.length < 2)) ops[mode].push(cur);
    cur = null;
    render();
  };
  drawCv.addEventListener("pointerup", finish);
  drawCv.addEventListener("pointercancel", () => { cur = null; render(); });

  // ── toolbar ───────────────────────────────────────────────────────────────
  const toolBtns = document.querySelectorAll("#tools button");
  toolBtns.forEach((b) => b.addEventListener("click", () => {
    tool = b.dataset.t;
    toolBtns.forEach((x) => x.classList.toggle("on", x === b));
  }));

  const colGrp = document.getElementById("colors");
  COLORS.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === 0 ? " on" : "");
    b.style.background = c;
    b.title = i === 0 ? "Accent" : c;
    b.addEventListener("click", () => {
      color = c;
      colGrp.querySelectorAll(".swatch").forEach((x) => x.classList.toggle("on", x === b));
    });
    colGrp.appendChild(b);
  });

  const mHalf = document.getElementById("m-half");
  const mFull = document.getElementById("m-full");
  function setMode(m) {
    mode = m;
    mHalf.classList.toggle("on", m === "half");
    mFull.classList.toggle("on", m === "full");
    layout();
  }
  mHalf.addEventListener("click", () => setMode("half"));
  mFull.addEventListener("click", () => setMode("full"));

  document.getElementById("undo").addEventListener("click", () => {
    ops[mode].pop();
    render();
  });

  const clearBtn = document.getElementById("clear");
  let armed = null;
  clearBtn.addEventListener("click", () => {   // two-tap clear, no confirm() popup
    if (armed) {
      clearTimeout(armed); armed = null;
      clearBtn.textContent = "Clear";
      ops[mode] = [];
      render();
    } else {
      clearBtn.textContent = "Sure?";
      armed = setTimeout(() => { armed = null; clearBtn.textContent = "Clear"; }, 2000);
    }
  });

  document.getElementById("save").addEventListener("click", () => {
    const out = document.createElement("canvas");
    out.width = courtCv.width; out.height = courtCv.height;
    const octx = out.getContext("2d");
    octx.fillStyle = "#12141e";
    octx.fillRect(0, 0, out.width, out.height);
    octx.drawImage(courtCv, 0, 0);
    octx.drawImage(drawCv, 0, 0);
    const a = document.createElement("a");
    a.download = "hooptracks_play.png";
    a.href = out.toDataURL("image/png");
    a.click();
  });

  window.addEventListener("resize", layout);
  layout();
})();
</script>
"""

components.html(
    _HTML.replace("__GEOM__", _GEOM).replace("__ACCENT__", ACCENT),
    height=780,
    scrolling=False,
)
