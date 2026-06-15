/* court.js — half-court geometry + SVG rendering (units: feet, hoop-end half court) */
(function () {
  'use strict';

  const X_MIN = -25, X_MAX = 25, Y_MIN = -1, Y_MAX = 38;
  const HOOP_Y = 5.25, THREE_R = 19.75, CORNER_X = 19.0;
  const CBREAK = Math.sqrt(THREE_R * THREE_R - CORNER_X * CORNER_X); // ~5.389
  const LANE_HW = 6, LANE_D = 19, FT_R = 6, RA_R = 4;

  function shotDistance(x, y) { return Math.hypot(x, y - HOOP_Y); }

  function isThree(x, y) {
    return (Math.abs(x) >= CORNER_X && (y - HOOP_Y) <= CBREAK) || shotDistance(x, y) >= THREE_R;
  }

  function shotValue(x, y) { return isThree(x, y) ? 3 : 2; }

  function inPaint(x, y) { return Math.abs(x) <= LANE_HW && y <= LANE_D; }

  function zoneFromXY(x, y) {
    if (inPaint(x, y)) return 'C';
    let deg = Math.atan2(x, Math.max(y - HOOP_Y, 1e-4)) * 180 / Math.PI;
    deg = Math.max(-90, Math.min(90, deg));
    if (deg < -54) return 'LC';
    if (deg < -18) return 'LW';
    if (deg < 18) return 'C';
    if (deg < 54) return 'RW';
    return 'RC'; // 54..90 incl. clamped >=90
  }

  /* ---- SVG rendering ---- */

  const NS = 'http://www.w3.org/2000/svg';
  let svg = null, group = null, marker = null;

  function el(name, attrs) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function drawCourt(container, onTap) {
    svg = el('svg', {
      viewBox: X_MIN + ' ' + Y_MIN + ' ' + (X_MAX - X_MIN) + ' ' + (Y_MAX - Y_MIN),
      class: 'court-svg',
      'aria-label': 'half court'
    });
    // Orient the way a coach reads it: half-court at the BOTTOM, rim at the TOP,
    // and screen-left = court-left (tap left -> LW/LC, tap right -> RW/RC). This is
    // the natural feet frame with NO y-flip: svg-y grows downward, so feet y=0
    // (baseline) sits at the top and y grows toward half-court at the bottom — and
    // feet-x maps straight to screen-x. Because there's no reflection, the arcs
    // below use sweep-flag 1 (the un-flipped bulge direction). Tap->feet is direct:
    // getScreenCTM().inverse() with no group transform yields feet coordinates.
    group = el('g', {});

    const line = (x1, y1, x2, y2, cls) =>
      group.appendChild(el('line', { x1: x1, y1: y1, x2: x2, y2: y2, class: cls || 'court-line' }));

    // boundary: baseline (bottom), sidelines, half-court line (top)
    line(X_MIN, 0, X_MAX, 0);
    line(X_MIN, 0, X_MIN, Y_MAX);
    line(X_MAX, 0, X_MAX, Y_MAX);
    line(X_MIN, Y_MAX, X_MAX, Y_MAX);

    // paint + free-throw circle
    group.appendChild(el('rect', { x: -LANE_HW, y: 0, width: LANE_HW * 2, height: LANE_D, class: 'court-line' }));
    group.appendChild(el('circle', { cx: 0, cy: LANE_D, r: FT_R, class: 'court-line' }));

    // restricted-area semicircle opening away from the baseline toward half-court
    // (+y bulge => sweep 1 in the un-flipped frame)
    group.appendChild(el('path', {
      d: 'M ' + (-RA_R) + ' ' + HOOP_Y + ' A ' + RA_R + ' ' + RA_R + ' 0 0 1 ' + RA_R + ' ' + HOOP_Y,
      class: 'court-line'
    }));

    // backboard (6 ft wide, 1.25 ft below hoop center) + rim, both gold
    line(-3, HOOP_Y - 1.25, 3, HOOP_Y - 1.25, 'court-gold');
    group.appendChild(el('circle', { cx: 0, cy: HOOP_Y, r: 0.75, class: 'court-gold' }));

    // corner-3 verticals + arc between the corner joins
    const joinY = HOOP_Y + CBREAK;
    line(-CORNER_X, 0, -CORNER_X, joinY);
    line(CORNER_X, 0, CORNER_X, joinY);
    group.appendChild(el('path', {
      d: 'M ' + (-CORNER_X) + ' ' + joinY + ' A ' + THREE_R + ' ' + THREE_R + ' 0 0 1 ' + CORNER_X + ' ' + joinY,
      class: 'court-line'
    }));

    // tap marker (hidden until set)
    marker = el('circle', { cx: 0, cy: 0, r: 0.9, class: 'court-marker', visibility: 'hidden' });
    group.appendChild(marker);

    svg.appendChild(group);
    container.appendChild(svg);

    // Tap -> feet via inverse CTM of the flipped group (yields feet coords directly)
    svg.addEventListener('pointerdown', function (e) {
      const ctm = group.getScreenCTM();
      if (!ctm) return;
      let pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      pt = pt.matrixTransform(ctm.inverse());
      if (pt.x < X_MIN || pt.x > X_MAX || pt.y < Y_MIN || pt.y > Y_MAX) return;
      if (onTap) onTap(pt.x, pt.y);
    });

    return svg;
  }

  function setMarker(x, y) {
    if (!marker) return;
    marker.setAttribute('cx', x);
    marker.setAttribute('cy', y);
    marker.setAttribute('visibility', 'visible');
  }

  function clearMarker() {
    if (marker) marker.setAttribute('visibility', 'hidden');
  }

  window.Court = {
    X_MIN: X_MIN, X_MAX: X_MAX, Y_MIN: Y_MIN, Y_MAX: Y_MAX,
    HOOP_Y: HOOP_Y, THREE_R: THREE_R, CORNER_X: CORNER_X, CBREAK: CBREAK,
    LANE_HW: LANE_HW, LANE_D: LANE_D, FT_R: FT_R, RA_R: RA_R,
    shotDistance: shotDistance, isThree: isThree, shotValue: shotValue,
    inPaint: inPaint, zoneFromXY: zoneFromXY,
    drawCourt: drawCourt, setMarker: setMarker, clearMarker: clearMarker
  };
})();
