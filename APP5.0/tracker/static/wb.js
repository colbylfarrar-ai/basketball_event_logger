/* wb.js — courtside whiteboard overlay (the PWA twin of the app's Whiteboard page).
   Deliberately minimal per the founder's spec: draw (one color), erase, half/full
   court, draggable numbered X/O pieces + one gold ball. NO save, NO export —
   tap Board to open, Close to get back to tracking (mirrors the Subs panel).
   Court geometry mirrors helpers/court_geom.py (NFHS arc, 84 ft court -> 42 ft
   half). Everything lives in this closure; app.js only calls WB.toggle(). */
(function () {
  'use strict';

  var G = {
    courtW: 50, halfLen: 42, laneHW: 6, laneD: 19, ftR: 6, raR: 4,
    hoopY: 5.25, rimR: 0.75, boardY: 4.0, threeR: 19.75, cornerX: 19,
    cbreak: Math.sqrt(19.75 * 19.75 - 19 * 19), centerR: 6
  };
  var M = 1.5;                     // out-of-bounds margin, feet
  var LINE = '#9aa0aa', GOLD = '#e6be64', INK = '#3fb950', BG = '#12141e';

  var mode = 'half', tool = 'pen';
  var ops = { half: [], full: [] };      // strokes + pieces, coords in FEET
  var cur = null, erasing = false, dragOp = null, scale = 10;

  function $(id) { return document.getElementById(id); }

  function extent() {
    return mode === 'half'
      ? { w: G.courtW + 2 * M, h: G.halfLen + 2 * M }
      : { w: 2 * G.halfLen + 2 * M, h: G.courtW + 2 * M };
  }

  function layout() {
    var stage = $('wb-stage'), frame = $('wb-frame');
    var courtCv = $('wb-court'), drawCv = $('wb-draw');
    if (!stage || !frame) return;
    if ($('wb-overlay').hidden) return;
    if (!stage.clientWidth || !stage.clientHeight) {
      // opened this frame — the flex layout hasn't resolved yet; retry next
      // paint (guarded by the hidden check above so it can't spin forever)
      requestAnimationFrame(layout);
      return;
    }
    var e = extent();
    scale = Math.min(stage.clientWidth / e.w, stage.clientHeight / e.h);
    var w = Math.round(e.w * scale), h = Math.round(e.h * scale);
    var dpr = window.devicePixelRatio || 1;
    frame.style.width = w + 'px';
    frame.style.height = h + 'px';
    [courtCv, drawCv].forEach(function (cv) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
      cv.style.width = w + 'px';
      cv.style.height = h + 'px';
      cv.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
    });
    drawCourt(courtCv.getContext('2d'));
    render();
  }

  /* one half court in a local frame: x across (-25..25), y up from baseline */
  function halfCourtPaths(ctx) {
    var yj = G.hoopY + G.cbreak;
    var tj = Math.atan2(G.cbreak, G.cornerX);
    var hw = G.courtW / 2;
    ctx.lineWidth = 0.18;
    ctx.strokeStyle = LINE;
    ctx.beginPath();
    ctx.moveTo(-hw, G.halfLen); ctx.lineTo(-hw, 0);
    ctx.lineTo(hw, 0); ctx.lineTo(hw, G.halfLen);
    ctx.stroke();
    ctx.strokeRect(-G.laneHW, 0, 2 * G.laneHW, G.laneD);
    ctx.beginPath(); ctx.arc(0, G.laneD, G.ftR, 0, 2 * Math.PI); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, G.hoopY, G.raR, 0, Math.PI); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-G.cornerX, 0); ctx.lineTo(-G.cornerX, yj);
    ctx.moveTo(G.cornerX, 0); ctx.lineTo(G.cornerX, yj);
    ctx.stroke();
    ctx.beginPath(); ctx.arc(0, G.hoopY, G.threeR, tj, Math.PI - tj); ctx.stroke();
    ctx.strokeStyle = GOLD;
    ctx.lineWidth = 0.28;
    ctx.beginPath(); ctx.moveTo(-3, G.boardY); ctx.lineTo(3, G.boardY); ctx.stroke();
    ctx.lineWidth = 0.22;
    ctx.beginPath(); ctx.arc(0, G.hoopY, G.rimR, 0, 2 * Math.PI); ctx.stroke();
  }

  function drawCourt(ctx) {
    var e = extent(), s = scale;
    ctx.save();
    ctx.clearRect(0, 0, e.w * s, e.h * s);
    if (mode === 'half') {
      ctx.setTransform(ctx.getTransform().multiply(
        new DOMMatrix([s, 0, 0, -s, (M + G.courtW / 2) * s, (M + G.halfLen) * s])));
      halfCourtPaths(ctx);
      ctx.beginPath();
      ctx.lineWidth = 0.18; ctx.strokeStyle = LINE;
      ctx.moveTo(-G.courtW / 2, G.halfLen); ctx.lineTo(G.courtW / 2, G.halfLen);
      ctx.stroke();
      ctx.beginPath(); ctx.arc(0, G.halfLen, G.centerR, Math.PI, 2 * Math.PI); ctx.stroke();
    } else {
      var cy = (M + G.courtW / 2) * s;
      ctx.save();
      ctx.setTransform(ctx.getTransform().multiply(new DOMMatrix([0, s, s, 0, M * s, cy])));
      halfCourtPaths(ctx);
      ctx.restore();
      ctx.save();
      ctx.setTransform(ctx.getTransform().multiply(
        new DOMMatrix([0, s, -s, 0, (M + 2 * G.halfLen) * s, cy])));
      halfCourtPaths(ctx);
      ctx.restore();
      ctx.lineWidth = 0.18 * s; ctx.strokeStyle = LINE;
      var mx = (M + G.halfLen) * s;
      ctx.beginPath(); ctx.moveTo(mx, M * s); ctx.lineTo(mx, (M + G.courtW) * s); ctx.stroke();
      ctx.beginPath(); ctx.arc(mx, cy, G.centerR * s, 0, 2 * Math.PI); ctx.stroke();
    }
    ctx.restore();
  }

  function px(f) { return f * scale; }

  function renderOp(ctx, o) {
    if (o.t === 'pen') {
      if (o.pts.length < 2) return;
      ctx.strokeStyle = INK;
      ctx.lineWidth = px(0.32);
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(px(o.pts[0][0]), px(o.pts[0][1]));
      for (var i = 1; i < o.pts.length; i++) ctx.lineTo(px(o.pts[i][0]), px(o.pts[i][1]));
      ctx.stroke();
      return;
    }
    if (o.t === 'ball') {
      var bx = px(o.x), by = px(o.y);
      ctx.fillStyle = GOLD;
      ctx.beginPath(); ctx.arc(bx, by, px(0.75), 0, 2 * Math.PI); ctx.fill();
      ctx.strokeStyle = BG; ctx.lineWidth = px(0.12); ctx.stroke();
      return;
    }
    var x = px(o.x), y = px(o.y), r = px(1.15);
    ctx.strokeStyle = INK; ctx.fillStyle = INK;
    ctx.lineWidth = px(0.28);
    ctx.font = '600 ' + px(1.5) + "px -apple-system,'Segoe UI',sans-serif";
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    if (o.t === 'O') {
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.stroke();
      ctx.fillText(String(o.n), x, y + px(0.08));
    } else {
      ctx.beginPath();
      ctx.moveTo(x - r * 0.8, y - r * 0.8); ctx.lineTo(x + r * 0.8, y + r * 0.8);
      ctx.moveTo(x + r * 0.8, y - r * 0.8); ctx.lineTo(x - r * 0.8, y + r * 0.8);
      ctx.stroke();
      ctx.font = '600 ' + px(1.05) + "px -apple-system,'Segoe UI',sans-serif";
      ctx.fillText(String(o.n), x + r * 1.25, y - r * 0.85);
    }
  }

  function render() {
    var cv = $('wb-draw');
    if (!cv) return;
    var ctx = cv.getContext('2d'), e = extent();
    ctx.clearRect(0, 0, e.w * scale, e.h * scale);
    ops[mode].forEach(function (o) { renderOp(ctx, o); });
    if (cur) renderOp(ctx, cur);
  }

  function pos(ev) {
    var r = $('wb-draw').getBoundingClientRect();
    return [(ev.clientX - r.left) / scale, (ev.clientY - r.top) / scale];
  }

  function markerAt(fx, fy) {
    var arr = ops[mode];
    for (var i = arr.length - 1; i >= 0; i--) {
      var o = arr[i];
      if ((o.t === 'O' || o.t === 'X' || o.t === 'ball')
          && Math.hypot(o.x - fx, o.y - fy) < 1.9) return o;
    }
    return null;
  }

  function segDist(px_, py_, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
    if (L2 === 0) return Math.hypot(px_ - x1, py_ - y1);
    var t = Math.max(0, Math.min(1, ((px_ - x1) * dx + (py_ - y1) * dy) / L2));
    return Math.hypot(px_ - (x1 + t * dx), py_ - (y1 + t * dy));
  }

  function eraseAt(fx, fy) {
    var kept = ops[mode].filter(function (o) {
      if (o.t === 'O' || o.t === 'X' || o.t === 'ball')
        return Math.hypot(o.x - fx, o.y - fy) >= 1.7;
      for (var i = 1; i < o.pts.length; i++)
        if (segDist(fx, fy, o.pts[i - 1][0], o.pts[i - 1][1],
                    o.pts[i][0], o.pts[i][1]) < 1.2) return false;
      return true;
    });
    if (kept.length !== ops[mode].length) { ops[mode] = kept; render(); }
  }

  function nextNum(t) {
    return ops[mode].filter(function (o) { return o.t === t; }).length % 5 + 1;
  }

  function onDown(ev) {
    ev.preventDefault();
    $('wb-draw').setPointerCapture(ev.pointerId);
    var p = pos(ev), fx = p[0], fy = p[1];
    if (tool === 'erase') { erasing = true; eraseAt(fx, fy); return; }
    var m = markerAt(fx, fy);              // pieces drag with any tool
    if (m) { dragOp = m; return; }
    if (tool === 'ball') {                 // singleton: re-placing moves it
      var b = null;
      ops[mode].forEach(function (o) { if (o.t === 'ball') b = o; });
      if (!b) { b = { t: 'ball', x: fx, y: fy }; ops[mode].push(b); }
      b.x = fx; b.y = fy;
      dragOp = b;
      render();
      return;
    }
    if (tool === 'O' || tool === 'X') {
      var nm = { t: tool, x: fx, y: fy, n: nextNum(tool) };
      ops[mode].push(nm);
      dragOp = nm;                         // place-and-drag in one gesture
      render();
      return;
    }
    cur = { t: 'pen', pts: [[fx, fy]] };
  }

  function onMove(ev) {
    if (dragOp) {
      var p = pos(ev);
      dragOp.x = p[0]; dragOp.y = p[1];
      render();
      return;
    }
    if (erasing) { var q = pos(ev); eraseAt(q[0], q[1]); return; }
    if (!cur) return;
    var r = pos(ev);
    cur.pts.push(r);
    render();
  }

  function onUp() {
    erasing = false;
    dragOp = null;
    if (cur) {
      if (cur.pts.length >= 2) ops[mode].push(cur);
      cur = null;
      render();
    }
  }

  function setMode(m) {
    mode = m;
    $('wb-half').className = 'btn small' + (m === 'half' ? '' : ' ghost');
    $('wb-full').className = 'btn small' + (m === 'full' ? '' : ' ghost');
    layout();
  }

  function setTool(t) {
    tool = t;
    var btns = document.querySelectorAll('#wb-bar .wb-tool');
    Array.prototype.forEach.call(btns, function (b) {
      b.className = 'btn small wb-tool' + (b.getAttribute('data-t') === t ? '' : ' ghost');
    });
  }

  var wired = false;
  function wire() {
    if (wired) return;
    wired = true;
    var cv = $('wb-draw');
    cv.addEventListener('pointerdown', onDown);
    cv.addEventListener('pointermove', onMove);
    cv.addEventListener('pointerup', onUp);
    cv.addEventListener('pointercancel', onUp);
    $('wb-half').addEventListener('click', function () { setMode('half'); });
    $('wb-full').addEventListener('click', function () { setMode('full'); });
    Array.prototype.forEach.call(document.querySelectorAll('#wb-bar .wb-tool'),
      function (b) {
        b.addEventListener('click', function () { setTool(b.getAttribute('data-t')); });
      });
    $('wb-clear').addEventListener('click', function () {
      ops[mode] = []; render();
    });
    $('wb-close').addEventListener('click', function () { window.WB.toggle(false); });
    window.addEventListener('resize', function () {
      if (!$('wb-overlay').hidden) layout();
    });
  }

  window.WB = {
    toggle: function (force) {
      var ov = $('wb-overlay');
      if (!ov) return;
      var show = force !== undefined ? !!force : ov.hidden;
      ov.hidden = !show;
      if (show) { wire(); setTool(tool); setMode(mode); }
    }
  };
})();
