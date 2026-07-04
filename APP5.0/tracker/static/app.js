/* app.js — screens, state, IndexedDB queue, offline-first sync */
(function () {
'use strict';

/* ---------- storage keys / helpers ---------- */

const LS = {
  token: 'tracker_token',
  games: 'tracker_games',
  genderFilter: 'tracker_gender_filter',   // '' = All, 'M' = Boys, 'F' = Girls
  state: 'tracker_state',
  roster: function (gid) { return 'tracker_roster_' + gid; },
  game: function (gid) { return 'tracker_game_' + gid; },   // per-game lineup/quarter/clock
  live: function (gid) { return 'tracker_live_' + gid; },   // last server live snapshot
  lastDefense: 'tracker_last_defense'                       // most-recent defense (new-game default)
};

function $(id) { return document.getElementById(id); }
function lsGet(k, fb) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fb; } catch (e) { return fb; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

/* "Assistant scorer" deep link: ?t=<token> saves the token (raw string, same as
   the manual token field), then strips it from the URL so it isn't left in the
   address bar or bookmarked. Runs at load, before the first API call. */
(function () {
  try {
    var t = new URLSearchParams(location.search).get('t');
    if (t) {
      localStorage.setItem(LS.token, t);
      history.replaceState(null, '', location.pathname);
    }
  } catch (e) {}
})();

function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 3 | 8)).toString(16);
  });
}

/* ---------- app state ---------- */

const EMPTY_LIVE = { home_pts: 0, away_pts: 0, home_poss: 0, away_poss: 0, quarters: {}, events: [] };

const S = {
  gameId: null,
  game: null,                                   // /api/games/{gid} payload (roster)
  lineup: { home: [], away: [], officials: [] },
  quarter: 1,
  clockMin: 8,
  clockSec: 0,
  clockRunning: false,                          // running game clock (never persisted across reload)
  defense: null,                                // sticky "current defense" tag (see DEFENSES)
  playType: null,                               // sticky "current set call" (see PLAY_TYPES) — stamps shots, TOs AND fouls
  lastLive: Object.assign({}, EMPTY_LIVE),      // last synced server state (never includes queue)
  queue: [],                                    // unsynced events for current game, oldest first
  flushing: false,
  courtDrawn: false,
  flow: null,
  wakeLock: null
};

let clockTimer = null;   // setInterval handle for the running game clock

// Quick-mode shot entry (default ON): tap shooter + make/miss only. Persisted so a
// coach's preference sticks across games; toggled on the tracker screen.
function quickModeOn() { return lsGet('tracker_quickmode', true); }
function setQuickMode(v) { lsSet('tracker_quickmode', !!v); }

/* ---------- fetch wrapper ---------- */

function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  let token = null;
  try { token = localStorage.getItem(LS.token); } catch (e) {}
  if (token) headers['Authorization'] = 'Bearer ' + token;
  return fetch(path, Object.assign({}, opts, { headers: headers }))
    .then(function (res) { _lastReached = Date.now(); return res; });
}

// navigator.onLine is unreliable on iOS standalone PWAs — it can report offline
// while the network works fine, which greys the status dot and makes every
// online-gated action refuse with "Needs connection". Trust onLine when true;
// otherwise treat a real server reply within the last 60s as online.
let _lastReached = 0;
function isOnline() {
  return navigator.onLine || (Date.now() - _lastReached) < 60000;
}

/* ---------- IndexedDB queue ---------- */

let dbPromise = null;
function idb() {
  if (!dbPromise) {
    dbPromise = new Promise(function (resolve, reject) {
      const req = indexedDB.open('tracker', 1);
      req.onupgradeneeded = function () {
        const db = req.result;
        if (!db.objectStoreNames.contains('queue')) {
          const st = db.createObjectStore('queue', { keyPath: 'uuid' });
          st.createIndex('gameId', 'gameId');
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }
  return dbPromise;
}

function qLoad(gameId) {
  return idb().then(function (db) {
    return new Promise(function (resolve, reject) {
      const req = db.transaction('queue', 'readonly').objectStore('queue').index('gameId').getAll(gameId);
      req.onsuccess = function () {
        resolve((req.result || []).sort(function (a, b) { return a.ts - b.ts; }));
      };
      req.onerror = function () { reject(req.error); };
    });
  });
}

function qPut(item) {
  return idb().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction('queue', 'readwrite');
      tx.objectStore('queue').put(item);
      tx.oncomplete = resolve;
      tx.onerror = function () { reject(tx.error); };
    });
  });
}

function qDelete(uuids) {
  return idb().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction('queue', 'readwrite');
      const st = tx.objectStore('queue');
      uuids.forEach(function (u) { st.delete(u); });
      tx.oncomplete = resolve;
      tx.onerror = function () { reject(tx.error); };
    });
  });
}

/* ---------- sync engine ---------- */

const SERVER_FIELDS = ['uuid', 'event_type', 'quarter', 'time', 'primary_player_id', 'shot_result',
  'shot_x', 'shot_y', 'shot_type', 'zone', 'pass_from_id', 'shot_created_by_id', 'rebound_by_id',
  'blocked_by_id', 'guarded_by_id', 'secondary_player_id', 'official_id', 'stolen_by_id',
  'play_type', 'defense', 'on_court', 'officials_on'];

function toServer(item) {
  const o = {};
  SERVER_FIELDS.forEach(function (f) { o[f] = item[f] !== undefined ? item[f] : null; });
  return o;
}

function setSyncStatus(msg) { $('sync-status').textContent = msg; }

async function flush() {
  if (S.flushing || !S.gameId || !S.queue.length) { updateSyncUI(); return; }
  S.flushing = true;
  const batch = S.queue.slice(); // snapshot; events logged mid-flight stay queued
  let ok = false;
  try {
    const res = await api('/api/games/' + S.gameId + '/events', {
      method: 'POST',
      body: JSON.stringify({ events: batch.map(toServer) })
    });
    if (res.ok) {
      const data = await res.json();
      // per-event status: rejected events are dequeued too (the server will
      // never accept them) but the user is told instead of a silent drop
      const results = data.results || [];
      const done = results.length
        ? results.map(function (r) { return r.uuid; })
        : batch.map(function (b) { return b.uuid; });
      const rejected = results.filter(function (r) { return r.status === 'rejected'; }).length;
      try { await qDelete(done); } catch (e) {}
      S.queue = S.queue.filter(function (q) { return done.indexOf(q.uuid) < 0; });
      // server live now includes the batch; queue no longer holds it -> no double count
      if (data.live) {
        Object.assign(S.lastLive, data.live);
        lsSet(LS.live(S.gameId), S.lastLive);
      }
      if (rejected) toast(rejected + ' event(s) rejected by server');
      setSyncStatus('Synced');
      ok = true;
    } else {
      setSyncStatus('Sync failed (HTTP ' + res.status + ') — will retry');
    }
  } catch (e) {
    setSyncStatus('Offline — events queued');
  } finally {
    S.flushing = false;
    renderScore();
    renderPBP();
    updateSyncUI();
    if (ok) refreshLive(); // pick up fresh event rows for play-by-play
  }
}

async function refreshLive() {
  if (!S.gameId || S.flushing) return;
  try {
    const res = await api('/api/games/' + S.gameId + '/live');
    if (res.ok) {
      S.lastLive = await res.json();
      lsSet(LS.live(S.gameId), S.lastLive);
      renderScore();
      renderPBP();
    }
  } catch (e) { /* offline — cached state stands */ }
}

/* ---------- roster lookups / local score ---------- */

function playerById(id) {
  if (!S.game) return null;
  return (S.game.players || []).find(function (p) { return p.id === id; }) || null;
}

function pLabel(id) {
  if (id == null) return '—';
  const p = playerById(id);
  return p ? '#' + p.number + ' ' + p.name : '#' + id;
}

function oLabel(id) {
  if (id == null) return '—';
  const o = ((S.game && S.game.officials) || []).find(function (o) { return o.id === id; });
  return o ? o.name : 'Official ' + id;
}

function teamSide(playerId) {
  const p = playerById(playerId);
  if (!p || !S.game) return null;
  return p.team_id === S.game.home.id ? 'home' : 'away';
}

function onCourtIds() { return S.lineup.home.concat(S.lineup.away); }

// Local score = last server live + queued (unsynced) events applied on top.
function localTotals() {
  const t = {
    home_pts: S.lastLive.home_pts || 0, away_pts: S.lastLive.away_pts || 0,
    home_poss: S.lastLive.home_poss || 0, away_poss: S.lastLive.away_poss || 0
  };
  S.queue.forEach(function (ev) {
    const side = teamSide(ev.primary_player_id);
    if (!side) return;
    if (ev.event_type === 'shot') {
      t[side + '_poss']++;
      if (ev.shot_result === 'make') t[side + '_pts'] += (ev.shot_type || 2);
    } else if (ev.event_type === 'free_throw') {
      if (ev.shot_result === 'make') t[side + '_pts'] += 1;
    } else if (ev.event_type === 'turnover') {
      t[side + '_poss']++;
    }
  });
  return t;
}

/* ---------- screens ---------- */

function showScreen(name) {
  if (name !== 'tracker') stopClock();   // never let the clock run off-screen
  ['setup', 'lineup', 'tracker', 'editor'].forEach(function (n) {
    $('screen-' + n).hidden = (n !== name);
  });
  lsSet(LS.state, { screen: name, gameId: S.gameId });
  if (name === 'tracker') acquireWakeLock();
}

/* ----- setup screen ----- */

let allGames = [];

// Boys/Girls/All filter for the setup screen — narrows the resume-game list AND
// the new-game team picker for coaches who staff both genders. Persisted; '' = All.
const GENDERS = [['', 'All'], ['M', 'Boys'], ['F', 'Girls']];

function genderFilter() { return lsGet(LS.genderFilter, ''); }

function renderGenderFilter() {
  const box = $('gender-filter');
  if (!box) return;
  box.innerHTML = '';
  const cur = genderFilter();
  GENDERS.forEach(function (g) {
    box.appendChild(flowBtn(g[1], 'chip' + (cur === g[0] ? ' sel' : ''), function () {
      lsSet(LS.genderFilter, g[0]);
      renderGenderFilter();
      applyGameFilter();
      if (NG.open) renderNewGame();    // refilter the new-game team chips too
    }));
  });
}

function _genderKeep(g, gf) {
  // stale-cache games may lack gender — never hide those.
  return !(gf && g.gender && g.gender !== gf);
}

let _searchTimer = null;
function applyGameFilter() {
  const el = $('game-search');
  const raw = ((el && el.value) || '').trim();
  const gf = genderFilter();
  if (raw.length >= 2) {
    // Server-side search so ANY team's games are reachable — the default list
    // is intentionally bounded (current-season tracked/recent), so type a team
    // name to pull that team's games from the full schedule.
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(function () { searchGames(raw); }, 250);
    return;
  }
  renderGames(allGames.filter(function (g) { return _genderKeep(g, gf); }));
}

async function searchGames(raw) {
  const gf = genderFilter();
  $('setup-status').textContent = 'Searching…';
  try {
    // Scope the search to the season the picker is browsing — without this the
    // server defaults to 'Current', so a past-season search "only showed current".
    const res = await api('/api/games?q=' + encodeURIComponent(raw)
      + '&season=' + encodeURIComponent(currentSeason || 'Current'));
    if (res.ok) {
      const data = await res.json();
      const list = (data.games || []).filter(function (g) { return _genderKeep(g, gf); });
      renderGames(list);
      $('setup-status').textContent = list.length ? '' : 'No games match “' + raw + '”';
    } else if (res.status === 401) {
      const tb = $('token-box'); if (tb) tb.open = true;
      $('setup-status').textContent = 'Enter your tracker token above to search.';
    } else {
      $('setup-status').textContent = 'Search failed';
    }
  } catch (e) {
    // offline — fall back to filtering whatever's already loaded
    const ql = raw.toLowerCase();
    renderGames(allGames.filter(function (g) {
      return _genderKeep(g, gf) &&
        ((g.home || '') + ' ' + (g.away || '') + ' ' + (g.date || ''))
          .toLowerCase().indexOf(ql) !== -1;
    }));
    $('setup-status').textContent = 'Offline — searching loaded games only';
  }
}

/* season the game picker browses ('Current' = active season). Past seasons let
   a coach retro-track old games; the server scopes lists + rosters to it. */
let currentSeason = 'Current';

function seasonCacheKey() {
  return currentSeason === 'Current' ? LS.games : LS.games + '_' + currentSeason;
}

async function loadSeasons() {
  const sel = $('season-select');
  if (!sel) return;
  try {
    const res = await api('/api/seasons');
    if (!res.ok) return;
    const data = await res.json();
    const seasons = data.seasons || [];
    if (seasons.length < 2) { sel.hidden = true; return; }  // nothing to switch
    sel.innerHTML = '';
    seasons.forEach(function (s) {
      const o = document.createElement('option');
      o.value = s.value; o.textContent = s.label;
      sel.appendChild(o);
    });
    sel.value = currentSeason;
    sel.hidden = false;
  } catch (e) { /* offline: keep hidden, current-season cache still works */ }
}

async function loadGames() {
  let games = lsGet(seasonCacheKey(), null);
  // A pre-fix cache could hold thousands of schedule games (OSSAA import) and
  // freeze the list on render — drop an oversize cache and refetch the bounded set.
  if (games && games.length > 400) { games = null; try { localStorage.removeItem(seasonCacheKey()); } catch (e) {} }
  if (games) { allGames = games; applyGameFilter(); }
  try {
    const url = currentSeason === 'Current'
      ? '/api/games'
      : '/api/games?season=' + encodeURIComponent(currentSeason);
    const res = await api(url);
    if (res.ok) {
      const data = await res.json();
      games = data.games || [];
      lsSet(seasonCacheKey(), games);
      allGames = games;
      applyGameFilter();
      $('setup-status').textContent = '';
    } else if (res.status === 401) {
      // No / wrong token (iOS keeps the installed app's storage separate from
      // Safari, and can evict it after ~7 idle days). Open the box and say so
      // plainly instead of a scary "server error".
      const tb = $('token-box'); if (tb) tb.open = true;
      $('setup-status').textContent = 'Enter your tracker token above to load games.';
    } else {
      $('setup-status').textContent = games ? 'Server error — showing cached games' : 'Server error loading games';
    }
  } catch (e) {
    $('setup-status').textContent = games ? 'Offline — showing cached games' : 'Offline and no cached games yet';
  }
}

function renderGames(games) {
  const ul = $('game-list');
  ul.innerHTML = '';
  if (!games.length) {
    var raw = (($('game-search') || {}).value || '').trim();
    ul.innerHTML = '<li class="empty">' + (raw
      ? 'No games match “' + raw + '”'
      : 'No tracked games yet — search a team above to find a game to track.') + '</li>';
    return;
  }
  // Hard cap the DOM so a large list (or a poisoned cache) can never freeze the
  // phone — the search box narrows it down past the cap.
  var CAP = 250;
  var shown = games.length > CAP ? games.slice(0, CAP) : games;
  shown.forEach(function (g) {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'game-item';
    const date = document.createElement('span'); date.className = 'g-date'; date.textContent = g.date;
    const names = document.createElement('span'); names.className = 'g-names'; names.textContent = g.home + ' vs ' + g.away;
    btn.appendChild(date);
    btn.appendChild(names);
    if (g.tracked) { const t = document.createElement('span'); t.className = 'g-tracked'; t.textContent = 'tracked'; btn.appendChild(t); }
    btn.addEventListener('click', function () { selectGame(g.id); });
    li.appendChild(btn);
    ul.appendChild(li);
  });
  if (games.length > CAP) {
    var more = document.createElement('li'); more.className = 'empty';
    more.textContent = 'Showing ' + CAP + ' of ' + games.length + ' — type to search.';
    ul.appendChild(more);
  }
}

async function selectGame(gid) {
  let roster = lsGet(LS.roster(gid), null);
  try {
    const res = await api('/api/games/' + gid);
    if (res.ok) {
      roster = await res.json();
      lsSet(LS.roster(gid), roster);
    }
  } catch (e) { /* fall back to cache */ }
  if (!roster) { toast('Offline — no cached roster for this game'); return; }

  S.gameId = gid;
  S.game = roster;
  const prefs = lsGet(LS.game(gid), {});
  S.lineup = prefs.lineup || { home: [], away: [], officials: [] };
  S.quarter = prefs.quarter || 1;
  S.clockMin = prefs.clockMin != null ? prefs.clockMin : 8;
  S.clockSec = prefs.clockSec != null ? prefs.clockSec : 0;
  // Sticky D: keep this game's saved scheme if it has one; a fresh game defaults
  // to the most-recently-used scheme (carried across games via LS.lastDefense).
  S.defense = ('defense' in prefs) ? prefs.defense : lsGet(LS.lastDefense, null);
  // Sticky set call survives a mid-game reload but never carries between games
  // (set calls change possession to possession, unlike a defense).
  S.playType = ('playType' in prefs) ? prefs.playType : null;
  S.lastLive = lsGet(LS.live(gid), Object.assign({}, EMPTY_LIVE));
  try { S.queue = await qLoad(gid); } catch (e) { S.queue = []; }
  resetFlow('shot');
  renderLineup();
  showScreen('lineup');
  refreshLive(); // background
}

/* ----- new game / new team (setup, online-only) ----- */

const TEAM_CLASSES = ['B2', 'B1', 'A', '2A', '3A', '4A', '5A', '6A', 'N/A'];

const NG = {
  open: false,
  teams: [],          // [{id,name,class,gender}]
  loaded: false,
  date: '',
  sel: { home: null, away: null },
  search: { home: '', away: '' },
  sub: { home: false, away: false },  // "+ new team" subform open per side
  status: ''
};

function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
    '-' + String(d.getDate()).padStart(2, '0');
}

function teamName(id) {
  const t = NG.teams.find(function (t) { return t.id === id; });
  return t ? t.name : '';
}

function toggleNewGame() {
  NG.open = !NG.open;
  $('btn-new-game').textContent = NG.open ? '− New game' : '+ New game';
  if (!NG.open) { renderNewGame(); return; }
  NG.date = todayStr();
  NG.sel = { home: null, away: null };
  NG.search = { home: '', away: '' };
  NG.sub = { home: false, away: false };
  NG.status = '';
  renderNewGame();
  loadTeams();
}

async function loadTeams() {
  if (!isOnline()) { NG.loaded = false; NG.status = 'Needs connection'; renderNewGame(); return; }
  try {
    const res = await api('/api/teams');
    if (res.ok) {
      const data = await res.json();
      NG.teams = data.teams || [];
      NG.loaded = true;
      NG.status = '';
    } else {
      NG.status = 'Failed to load teams (HTTP ' + res.status + ')';
    }
  } catch (e) {
    NG.loaded = false;
    NG.status = 'Needs connection';
  }
  renderNewGame();
}

function renderNewGame() {
  const wrap = $('new-game-form');
  wrap.hidden = !NG.open;
  wrap.innerHTML = '';
  if (!NG.open) return;

  // date
  const dRow = document.createElement('div');
  dRow.className = 'ng-row';
  const dLab = document.createElement('span');
  dLab.className = 'chip-label';
  dLab.textContent = 'Date';
  const dIn = document.createElement('input');
  dIn.type = 'date';
  dIn.value = NG.date;
  dIn.addEventListener('change', function () { NG.date = dIn.value; });
  dRow.appendChild(dLab);
  dRow.appendChild(dIn);
  wrap.appendChild(dRow);

  ['home', 'away'].forEach(function (side) { wrap.appendChild(teamPicker(side)); });

  const st = document.createElement('p');
  st.className = 'status';
  st.id = 'ng-status';
  st.textContent = NG.status;
  wrap.appendChild(st);
  wrap.appendChild(flowBtn('Create game', 'btn primary big', createGame));
}

function teamPicker(side) {
  const box = document.createElement('div');
  box.className = 'ng-side';
  const lab = document.createElement('span');
  lab.className = 'chip-label';
  lab.textContent = (side === 'home' ? 'Home team' : 'Away team') +
    (NG.sel[side] != null ? ': ' + teamName(NG.sel[side]) : '');
  box.appendChild(lab);

  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Search teams';
  search.autocomplete = 'off';          // no saved-names autofill bar over the chips
  search.value = NG.search[side];
  search.addEventListener('input', function () {
    NG.search[side] = search.value;
    fillTeamChips(side, chips); // chips only — keep keyboard focus on the input
  });
  box.appendChild(search);

  const chips = document.createElement('div');
  chips.className = 'chips team-pick';
  fillTeamChips(side, chips);
  box.appendChild(chips);

  if (NG.sub[side]) box.appendChild(newTeamForm(side));
  return box;
}

function fillTeamChips(side, box) {
  box.innerHTML = '';
  const q = NG.search[side].trim().toLowerCase();
  const gf = genderFilter();
  NG.teams.filter(function (t) {
    return (!gf || t.gender === gf) && (!q || t.name.toLowerCase().indexOf(q) >= 0);
  })
    .forEach(function (t) {
      box.appendChild(flowBtn(t.name, 'chip' + (NG.sel[side] === t.id ? ' sel' : ''), function () {
        NG.sel[side] = NG.sel[side] === t.id ? null : t.id;
        renderNewGame();
      }));
    });
  box.appendChild(flowBtn('+ new team', 'chip', function () {
    NG.sub[side] = !NG.sub[side];
    renderNewGame();
  }));
}

function newTeamForm(side) {
  const f = document.createElement('div');
  f.className = 'inline-form';
  const name = document.createElement('input');
  name.type = 'text';
  name.placeholder = 'Team name';
  name.autocomplete = 'off';            // no autofill bar over the inline form
  name.autocapitalize = 'words';
  const cls = document.createElement('select');
  cls.setAttribute('aria-label', 'Class');
  TEAM_CLASSES.forEach(function (c) {
    const o = document.createElement('option');
    o.value = c; o.textContent = c;
    if (c === 'N/A') o.selected = true;
    cls.appendChild(o);
  });
  const gen = document.createElement('select');
  gen.setAttribute('aria-label', 'Gender');
  // value stays 'M'/'F' for the API; label reads Boys/Girls (app convention).
  [['M', 'Boys'], ['F', 'Girls']].forEach(function (g) {
    const o = document.createElement('option');
    o.value = g[0]; o.textContent = g[1];
    gen.appendChild(o);
  });
  const stat = document.createElement('p');
  stat.className = 'status';
  const btn = flowBtn('Create team', 'btn primary', async function () {
    const nm = name.value.trim();
    if (!nm) { stat.textContent = 'Name required'; return; }
    if (!isOnline()) { stat.textContent = 'Needs connection'; return; }
    try {
      const res = await api('/api/teams', {
        method: 'POST',
        body: JSON.stringify({ name: nm, 'class': cls.value, gender: gen.value })
      });
      if (!res.ok) { stat.textContent = 'Failed (HTTP ' + res.status + ')'; return; }
      const d = await res.json();
      if (!NG.teams.some(function (t) { return t.id === d.id; })) {
        NG.teams.push({ id: d.id, name: nm, 'class': cls.value, gender: gen.value });
        NG.teams.sort(function (a, b) { return a.name.localeCompare(b.name); });
      }
      NG.sel[side] = d.id;
      NG.sub[side] = false;
      renderNewGame();
    } catch (e) {
      stat.textContent = 'Needs connection';
    }
  });
  f.appendChild(name);
  f.appendChild(cls);
  f.appendChild(gen);
  f.appendChild(btn);
  f.appendChild(stat);
  return f;
}

async function createGame() {
  const st = $('ng-status');
  if (NG.sel.home == null || NG.sel.away == null) { st.textContent = 'Pick both teams'; return; }
  if (NG.sel.home === NG.sel.away) { st.textContent = 'Home and away must differ'; return; }
  if (!NG.date) { st.textContent = 'Pick a date'; return; }
  if (!isOnline()) { st.textContent = 'Needs connection'; return; }
  try {
    // browsing a past season → stamp the new game there; else let the server
    // infer from the date (Oct 1 cutoff).
    const body = { team1_id: NG.sel.home, team2_id: NG.sel.away, date: NG.date };
    if (currentSeason && currentSeason !== 'Current') body.season = currentSeason;
    const res = await api('/api/games', {
      method: 'POST',
      body: JSON.stringify(body)
    });
    if (!res.ok) { st.textContent = 'Failed (HTTP ' + res.status + ')'; return; }
    const d = await res.json();
    NG.open = false;
    $('btn-new-game').textContent = '+ New game';
    renderNewGame();
    toast('Game created');
    loadGames();          // refresh list cache in background
    selectGame(d.id);     // straight to the lineup screen
  } catch (e) {
    st.textContent = 'Needs connection';
  }
}

/* ----- lineup screen ----- */

function savePrefs() {
  if (!S.gameId) return;
  lsSet(LS.game(S.gameId), {
    lineup: S.lineup, quarter: S.quarter, clockMin: S.clockMin, clockSec: S.clockSec,
    defense: S.defense, playType: S.playType
  });
}

function toggleSel(arr, id, max, what) {
  const i = arr.indexOf(id);
  if (i >= 0) arr.splice(i, 1);
  else if (arr.length >= max) { toast('Max ' + max + ' ' + what); return; }
  else arr.push(id);
  savePrefs();
  renderLineup();
}

function lineupChip(label, selected, onTap) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'chip' + (selected ? ' sel' : '');
  b.textContent = label;
  b.addEventListener('click', onTap);
  return b;
}

function renderLineup() {
  if (!S.game) return;
  $('lineup-home-name').textContent = S.game.home.name + ' (' + S.lineup.home.length + '/5)';
  $('lineup-away-name').textContent = S.game.away.name + ' (' + S.lineup.away.length + '/5)';
  $('lineup-officials-name').textContent = 'Officials (' + S.lineup.officials.length + '/3)';

  ['home', 'away'].forEach(function (side) {
    const box = $('chips-' + side);
    box.innerHTML = '';
    const teamId = S.game[side].id;
    // archived players can't take the floor — editor pickers still show them
    (S.game.players || []).filter(function (p) { return p.team_id === teamId && !p.archived; })
      .forEach(function (p) {
        box.appendChild(lineupChip('#' + p.number + ' ' + p.name,
          S.lineup[side].indexOf(p.id) >= 0,
          function () { toggleSel(S.lineup[side], p.id, 5, 'players'); }));
      });
  });

  const ob = $('chips-officials');
  ob.innerHTML = '';
  // archived refs can't be assigned — editor pickers still resolve them via oLabel
  (S.game.officials || []).filter(function (o) { return !o.archived; })
    .forEach(function (o) {
      ob.appendChild(lineupChip(o.name,
        S.lineup.officials.indexOf(o.id) >= 0,
        function () { toggleSel(S.lineup.officials, o.id, 3, 'officials'); }));
    });

  renderHands('home');
  renderHands('away');
}

/* ----- per-team shooting-hand editor (revealed table; keeps the roster
   chips clean — each player is one row name + an R/L segmented toggle) ----- */

function renderHands(side) {
  const box = $('hands-' + side);
  if (!box || !S.game) return;
  box.innerHTML = '';
  const teamId = S.game[side].id;
  const players = (S.game.players || [])
    .filter(function (p) { return p.team_id === teamId && !p.archived; });
  if (!players.length) {
    const e = document.createElement('p');
    e.className = 'status';
    e.textContent = 'No players yet.';
    box.appendChild(e);
    return;
  }
  players.forEach(function (p) { box.appendChild(handRow(p, side)); });
}

function handRow(p, side) {
  const row = document.createElement('div');
  row.className = 'hand-row';
  const nm = document.createElement('span');
  nm.className = 'hand-row-name';
  nm.textContent = '#' + p.number + ' ' + p.name;
  row.appendChild(nm);
  const cur = (p.handedness === 'left') ? 'left' : 'right';
  const seg = document.createElement('div');
  seg.className = 'hand-seg';
  [['right', 'R'], ['left', 'L']].forEach(function (opt) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip hand-opt' + (cur === opt[0] ? ' sel' : '');
    b.textContent = opt[1];
    b.addEventListener('click', function () { setHandedness(p, opt[0], side); });
    seg.appendChild(b);
  });
  row.appendChild(seg);
  return row;
}

async function setHandedness(p, value, side) {
  if (((p.handedness === 'left') ? 'left' : 'right') === value) return;  // no-op
  if (!isOnline()) { toast('Needs connection to change hand'); return; }
  try {
    const res = await api('/api/games/' + S.gameId + '/players/' + p.id + '/handedness', {
      method: 'POST', body: JSON.stringify({ handedness: value })
    });
    if (!res.ok) { toast('Failed to update hand'); return; }
    p.handedness = value;
    lsSet(LS.roster(S.gameId), S.game);
    toast('#' + p.number + ' ' + p.name + ' → ' + value + '-handed');
    renderHands(side);
  } catch (e) { toast('Needs connection'); }
}

/* ----- quick-add player / official (lineup, online-only) ----- */

async function quickAddPlayer(side) {
  if (!S.game) return;
  const nameIn = $('add-' + side + '-name');
  const numIn = $('add-' + side + '-number');
  const st = $('add-' + side + '-status');
  st.textContent = '';
  const name = nameIn.value.trim();
  const num = parseInt(numIn.value, 10) || 0;
  const handIn = $('add-' + side + '-hand');
  const hand = (handIn && handIn.value === 'left') ? 'left' : 'right';
  if (!name) { st.textContent = 'Name required'; return; }
  if (!isOnline()) { st.textContent = 'Needs connection'; return; }
  try {
    const res = await api('/api/games/' + S.gameId + '/players', {
      method: 'POST',
      body: JSON.stringify({ team_id: S.game[side].id, name: name, number: num, handedness: hand })
    });
    if (!res.ok) { st.textContent = 'Failed (HTTP ' + res.status + ')'; return; }
    const d = await res.json();
    if (!playerById(d.id)) {
      S.game.players = (S.game.players || []).concat([
        { id: d.id, name: name, number: num, team_id: S.game[side].id, handedness: hand }
      ]);
    }
    lsSet(LS.roster(S.gameId), S.game);  // cached roster includes the new player
    nameIn.value = '';
    numIn.value = '';
    if (handIn) handIn.value = 'right';
    $('add-' + side + '-form').hidden = true;
    toast('Added #' + num + ' ' + name);
    renderLineup();
  } catch (e) {
    st.textContent = 'Needs connection';
  }
}

async function quickAddOfficial() {
  if (!S.game) return;
  const nameIn = $('add-official-name');
  const idIn = $('add-official-id');
  const st = $('add-official-status');
  st.textContent = '';
  const name = nameIn.value.trim();
  const oid = parseInt(idIn.value, 10);
  if (!name) { st.textContent = 'Name required'; return; }
  if (isNaN(oid)) { st.textContent = 'Official ID required'; return; }
  if (!isOnline()) { st.textContent = 'Needs connection'; return; }
  try {
    const res = await api('/api/officials', {
      method: 'POST',
      body: JSON.stringify({ name: name, official_id: oid })
    });
    if (!res.ok) { st.textContent = 'Failed (HTTP ' + res.status + ')'; return; }
    const d = await res.json();
    // server returns the STORED name — differs from the input when this
    // official_id already existed under another name
    const oname = d.name || name;
    if (d.id != null && !(S.game.officials || []).some(function (o) { return o.id === d.id; })) {
      S.game.officials = (S.game.officials || []).concat([{ id: d.id, name: oname }]);
    }
    lsSet(LS.roster(S.gameId), S.game);
    nameIn.value = '';
    idIn.value = '';
    $('add-official-form').hidden = true;
    toast('Added ' + oname);
    renderLineup();
  } catch (e) {
    st.textContent = 'Needs connection';
  }
}

/* ----- tracker screen ----- */

function qlabel(q) { return q <= 4 ? 'Q' + q : 'OT' + (q - 4); }
function clockStr() { return S.clockMin + ':' + String(S.clockSec).padStart(2, '0'); }

function enterTracker() {
  if (!S.courtDrawn) {
    Court.drawCourt($('court-wrap'), onCourtTap);
    S.courtDrawn = true;
  }
  showScreen('tracker');
  syncHeaderInputs();
  setClockBtn();
  setQuickBtn();
  // subs panel starts collapsed every time the tracker opens
  const sp = $('subs-panel');
  if (sp) sp.hidden = true;
  const sb = $('btn-subs');
  if (sb) sb.classList.remove('active');
  setMode(S.flow ? S.flow.mode : 'shot');
  renderScore();
  renderPBP();
  updateSyncUI();
  updateNetUI();
}

function syncHeaderInputs() {
  $('q-label').textContent = qlabel(S.quarter);
  $('clock-min').value = S.clockMin;
  $('clock-sec').value = S.clockSec;
  if (S.game) {
    $('score-home-name').textContent = S.game.home.name;
    $('score-away-name').textContent = S.game.away.name;
  }
}

// +/- steppers adjust minute and second INDEPENDENTLY (no borrow) — the point is
// to drop just the minute between possessions without retyping. Each field clamps
// to its own range (minutes ≤20 = HS ceiling, seconds ≤59).
function nudgeMin(delta) {
  S.clockMin = Math.max(0, Math.min(20, S.clockMin + delta));
  $('clock-min').value = S.clockMin;
  savePrefs();
}
function nudgeSec(delta) {
  S.clockSec = Math.max(0, Math.min(59, S.clockSec + delta));
  $('clock-sec').value = S.clockSec;
  savePrefs();
}

/* ----- running game clock -----
   A real start/stop clock so MIN, +/-, and the live win-prob the second screen
   draws aren't built on a clock the coach hand-winds. Every event stamps
   time = clockStr(), so a running clock keeps that accurate automatically. The +/-
   steppers + manual entry stay; this just adds an optional auto-tick. The clock is
   NEVER persisted as running — a reload restores it stopped. */
function setClockBtn() {
  const b = $('clk-toggle');
  if (!b) return;
  b.innerHTML = S.clockRunning ? '&#9208;' : '&#9654;';   // ⏸ / ▶
  b.classList.toggle('running', S.clockRunning);
  b.setAttribute('aria-label', S.clockRunning ? 'Stop clock' : 'Start clock');
}

function tickClock() {
  let total = S.clockMin * 60 + S.clockSec - 1;
  if (total <= 0) {
    total = 0;
    stopClock();
    toast('Clock at 0:00');
  }
  S.clockMin = Math.floor(total / 60);
  S.clockSec = total % 60;
  const mi = $('clock-min'); if (mi) mi.value = S.clockMin;
  const se = $('clock-sec'); if (se) se.value = S.clockSec;
  if (total % 10 === 0) savePrefs();   // throttle writes; final stop saves too
}

function startClock() {
  if (S.clockRunning) return;
  if (S.clockMin * 60 + S.clockSec <= 0) { toast('Set the clock first'); return; }
  S.clockRunning = true;
  clockTimer = setInterval(tickClock, 1000);
  setClockBtn();
}

function stopClock() {
  if (!S.clockRunning && !clockTimer) return;
  S.clockRunning = false;
  if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
  setClockBtn();
  savePrefs();
}

function toggleClock() { if (S.clockRunning) stopClock(); else startClock(); }

function renderScore() {
  if ($('screen-tracker').hidden) return;
  const t = localTotals();
  $('score-home').textContent = t.home_pts;
  $('score-away').textContent = t.away_pts;
}

function updateSyncUI() {
  const n = S.queue.length;
  const b = $('sync-badge');
  b.textContent = n;
  b.className = 'badge' + (n === 0 ? ' ok' : '');
}

function updateNetUI() {
  const cls = 'dot ' + (isOnline() ? 'on' : 'off');
  ['net-dot', 'net-dot2'].forEach(function (id) { const d = $(id); if (d) d.className = cls; });
}

/* ----- event logging flows ----- */

function resetFlow(mode) {
  S.flow = {
    mode: mode,
    x: null, y: null,
    noLoc: false, manualType: 2, manualZone: null,  // location-less shot entry
    expand: false,                                  // quick-mode: details revealed for this entry
    shooter: null,
    details: { pass_from_id: null, shot_created_by_id: null, rebound_by_id: null, blocked_by_id: null, guarded_by_id: null, play_type: null },
    fouled: null, fouler: null, official: null,
    player: null, stolen: null, tovKind: null
  };
  if (window.Court) Court.clearMarker();
  const cap = $('shot-caption');
  if (cap) cap.textContent = '';
}

function setMode(m) {
  resetFlow(m);
  document.querySelectorAll('#mode-row .mode').forEach(function (b) {
    b.classList.toggle('active', b.dataset.mode === m);
  });
  renderFlow();
}

function onCourtTap(x, y) {
  if (S.flow.mode !== 'shot') setMode('shot'); // a court tap always means a shot
  S.flow.noLoc = false; // a tap always reverts to tap-derived value/zone
  // The court is drawn from the coach's half-court->rim angle (left/right symmetric),
  // so flip x for the STORED coordinate + zone only: tap left -> LW/LC, tap right ->
  // RW/RC. The marker keeps the raw tapped x so it lands exactly where you touched.
  const sx = -x;
  S.flow.x = sx;
  S.flow.y = y;
  Court.setMarker(x, y);
  const v = Court.shotValue(sx, y);
  const z = Court.zoneFromXY(sx, y);
  const d = Math.round(Court.shotDistance(sx, y));
  $('shot-caption').textContent = (v === 3 ? '3PT' : '2PT') + ' · ' + z + ' · ' + d + ' ft';
  renderFlow();
}

/* flow UI builders */

function flowHint(text) {
  const p = document.createElement('p');
  p.className = 'hint';
  p.textContent = text;
  return p;
}

function flowBtn(text, cls, onTap) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = text;
  b.addEventListener('click', onTap);
  return b;
}

// single-select chip row; re-tapping the selected chip clears it
function chipRow(label, ids, selected, onPick, opts) {
  opts = opts || {};
  const labelFn = opts.labelFn || pLabel;
  const row = document.createElement('div');
  row.className = 'chip-row';
  const lab = document.createElement('span');
  lab.className = 'chip-label';
  lab.textContent = label;
  row.appendChild(lab);
  const box = document.createElement('div');
  box.className = 'chips' + (opts.scroll ? ' scroll' : '');
  if (opts.allowNone) {
    box.appendChild(flowBtn('—', 'chip' + (selected == null ? ' sel' : ''), function () { onPick(null); }));
  }
  const playerRow = !opts.labelFn; // default pLabel rows hold player ids
  ids.forEach(function (id) {
    const side = teamSide(id);
    const p = playerRow ? playerById(id) : null;
    const arch = !!(p && p.archived);   // archived: pickable but dimmed
    const b = flowBtn(labelFn(id) + (arch ? ' (archived)' : ''),
      'chip' + (selected === id ? ' sel' : '') + (side ? ' ' + side : '') + (arch ? ' archived' : ''),
      function () { onPick(selected === id ? null : id); });
    box.appendChild(b);
  });
  row.appendChild(box);
  return row;
}

function makeMissRow(onResult) {
  const row = document.createElement('div');
  row.className = 'mm-row';
  row.appendChild(flowBtn('MAKE', 'btn make', function () { onResult('make'); }));
  row.appendChild(flowBtn('MISS', 'btn miss', function () { onResult('miss'); }));
  return row;
}

const SHOT_DETAILS = [
  ['pass_from_id', 'Pass from'],
  ['shot_created_by_id', 'Set up by'],
  ['rebound_by_id', 'Rebound by'],
  ['blocked_by_id', 'Blocked by'],
  ['guarded_by_id', 'Guarded by']
];

// Optional one-tap "play call" tag — the literal set call (nullable). Separate
// from the inferred tempo/creation play types computed in helpers/playtypes.py.
const PLAY_TYPES = [
  ['pnr', 'Pick & roll'], ['iso', 'Isolation'], ['post', 'Post-up'],
  ['spot', 'Spot-up'], ['cut', 'Cut'], ['offscreen', 'Off screen'],
  ['dho', 'DHO'], ['duckin', 'Duck in'],
  ['slob', 'SLOB'], ['blob', 'BLOB'],
  ['transition', 'Transition'], ['putback', 'Putback'], ['other', 'Other']
];
const PLAY_TYPE_KEYS = PLAY_TYPES.map(function (p) { return p[0]; });
const PLAY_TYPE_LABEL = PLAY_TYPES.reduce(function (m, p) { m[p[0]] = p[1]; return m; }, {});
function ptLabel(k) { return PLAY_TYPE_LABEL[k] || k; }

// Turnover KIND (optional; detailed mode + editor only — hidden in quick mode).
// Keep in lockstep with helpers/turnovers.TURNOVER_TYPES (server folds unknown
// -> 'other'). Orthogonal to play_type — the set call stays the extra layer.
const TOV_TYPES = [
  ['pass', 'Bad pass'], ['drive', 'Drive'], ['held', 'Held ball'],
  ['shot_clock', 'Shot clock'], ['travel', 'Travel']
];

// Sticky "current defense" the opponent is in. Unlike play_type (per-shot), a
// defense holds for stretches, so this is set ONCE on the always-visible bar and
// every event logged inherits S.defense until it's changed. Keep this list in
// lockstep with helpers/defenses.DEFENSES (the server folds unknown -> 'other').
const DEFENSES = [
  ['man', 'Man'], ['man_press', 'Man press'],
  ['zone_23', '2-3'], ['zone_32', '3-2'], ['zone_131', '1-3-1'], ['zone_122', '1-2-2'],
  ['matchup', 'Match-up'], ['trap_23', '2-3 trap'], ['trap_131', '1-3-1 trap'],
  ['press_221', '2-2-1 press'], ['press_131', '1-3-1 press'], ['press_1211', '1-2-1-1 press'],
  ['box1', 'Box-1'], ['triangle2', 'Triangle-2'], ['diamond1', 'Diamond-1'],
  ['scramble', 'Scramble'], ['other', 'Other']
];
const DEFENSE_KEYS = DEFENSES.map(function (d) { return d[0]; });
const DEFENSE_LABEL = DEFENSES.reduce(function (m, d) { m[d[0]] = d[1]; return m; }, {});
function defLabel(k) { return DEFENSE_LABEL[k] || k; }

// Always-visible sticky defense selector (its own bar, above the flow, so it's
// reachable in any mode and before a shot is started). Tapping sets S.defense
// for every subsequent event; re-tapping the selected scheme clears it.
function renderDefenseBar() {
  const bar = $('defense-bar');
  if (!bar) return;
  bar.innerHTML = '';
  if (!S.game) return;
  const lab = document.createElement('span');
  lab.className = 'chip-label';
  lab.textContent = 'Defense';
  bar.appendChild(lab);
  const box = document.createElement('div');
  box.className = 'chips scroll';
  function pickDefense(k) {
    S.defense = k;
    lsSet(LS.lastDefense, k);   // remember across games -> new-game default
    savePrefs();
    renderDefenseBar();
  }
  box.appendChild(flowBtn('—', 'chip' + (S.defense == null ? ' sel' : ''),
    function () { pickDefense(null); }));
  DEFENSE_KEYS.forEach(function (k) {
    box.appendChild(flowBtn(defLabel(k), 'chip' + (S.defense === k ? ' sel' : ''),
      function () { pickDefense(S.defense === k ? null : k); }));
  });
  bar.appendChild(box);
}

// Sticky "current set call" — the play_type twin of the defense bar, in the
// same always-visible area so it works in quick AND detailed mode. Tapping sets
// S.playType for every subsequent event (shots, TURNOVERS and FOULS inherit it
// via baseEvent); the detailed shot flow's own Play-type chips override it for
// that one shot. Re-tapping the selected call clears it.
function renderPlayTypeBar() {
  const bar = $('playtype-bar');
  if (!bar) return;
  bar.innerHTML = '';
  if (!S.game) return;
  const lab = document.createElement('span');
  lab.className = 'chip-label';
  lab.textContent = 'Set call';
  bar.appendChild(lab);
  const box = document.createElement('div');
  box.className = 'chips scroll';
  function pickPlayType(k) {
    S.playType = k;
    savePrefs();
    renderPlayTypeBar();
    renderFlow();               // shot-flow chips preview the sticky pick
  }
  box.appendChild(flowBtn('—', 'chip' + (S.playType == null ? ' sel' : ''),
    function () { pickPlayType(null); }));
  PLAY_TYPE_KEYS.forEach(function (k) {
    box.appendChild(flowBtn(ptLabel(k), 'chip' + (S.playType === k ? ' sel' : ''),
      function () { pickPlayType(S.playType === k ? null : k); }));
  });
  bar.appendChild(box);
}

/* ----- in-place subs (tracker screen) -----
   Swap the on-court five without leaving the tracker. Minutes and +/- key off the
   lineup snapshot stamped on every event (baseEvent.on_court), so keeping subs here
   — instead of bouncing to the lineup screen mid-run — is what keeps those honest. */
function toggleOnCourt(side, id) {
  const arr = S.lineup[side];
  const i = arr.indexOf(id);
  if (i >= 0) arr.splice(i, 1);
  else if (arr.length >= 5) { toast('Max 5 on the floor — sub one out first'); return; }
  else arr.push(id);
  savePrefs();
  renderSubsPanel();
  renderFlow();   // shooter / detail rows follow the new on-court five
}

function renderSubsPanel() {
  const wrap = $('subs-panel');
  if (!wrap || wrap.hidden || !S.game) return;
  wrap.innerHTML = '';
  ['home', 'away'].forEach(function (side) {
    const grp = document.createElement('div');
    grp.className = 'subs-group';
    const h = document.createElement('span');
    h.className = 'chip-label';
    h.textContent = S.game[side].name + ' (' + S.lineup[side].length + '/5)';
    grp.appendChild(h);
    const box = document.createElement('div');
    box.className = 'chips';
    const teamId = S.game[side].id;
    (S.game.players || []).filter(function (p) { return p.team_id === teamId && !p.archived; })
      .forEach(function (p) {
        const sel = S.lineup[side].indexOf(p.id) >= 0;
        box.appendChild(flowBtn('#' + p.number + ' ' + p.name, 'chip' + (sel ? ' sel' : ''),
          function () { toggleOnCourt(side, p.id); }));
      });
    grp.appendChild(box);
    wrap.appendChild(grp);
  });
  const foot = document.createElement('div');
  foot.className = 'subs-foot';
  foot.appendChild(flowBtn('Full lineup / add players ›', 'btn ghost small', function () {
    renderLineup();
    showScreen('lineup');
  }));
  wrap.appendChild(foot);
}

function toggleSubsPanel(force) {
  const wrap = $('subs-panel');
  if (!wrap) return;
  const show = (typeof force === 'boolean') ? force : wrap.hidden;
  wrap.hidden = !show;
  const b = $('btn-subs');
  if (b) b.classList.toggle('active', show);
  if (show) renderSubsPanel();
}

/* ----- quick-mode toggle ----- */
function setQuickBtn() {
  const b = $('quick-toggle');
  if (!b) return;
  const on = quickModeOn();
  b.textContent = on ? '⚡ Quick shot' : '📋 Full detail';
  b.classList.toggle('active', on);
  b.title = on
    ? 'Quick: tap shooter, then make/miss. Tap “+ details” on any shot for more.'
    : 'Full detail: assist / rebound / play-type rows on every shot.';
}

function renderFlow() {
  const wrap = $('flow');
  if (!wrap) return;
  renderDefenseBar();          // sticky D bar lives outside #flow — refresh every pass
  renderPlayTypeBar();         // sticky set-call bar, same area (quick + detailed)
  wrap.innerHTML = '';
  if (!S.game || !S.flow) return;
  const f = S.flow;
  const players = onCourtIds();
  if (!players.length) { wrap.appendChild(flowHint('No players on the floor — tap Subs to set the lineup')); return; }

  if (f.mode === 'shot') {
    if (f.x == null && !f.noLoc) {
      wrap.appendChild(flowHint('Tap the court to mark a shot'));
      wrap.appendChild(flowBtn('No court spot', 'btn ghost small no-loc', function () {
        f.noLoc = true;
        renderFlow();
      }));
      return;
    }
    if (f.x == null) {
      // location-less shot: explicit value + zone instead of tap-derived
      wrap.appendChild(optRow('Value', [{ v: 2, label: '2' }, { v: 3, label: '3' }],
        f.manualType, function (v) { f.manualType = v; renderFlow(); }, true));
      wrap.appendChild(optRow('Zone',
        [{ v: null, label: '—' }].concat(EDIT_ZONES.map(function (z) { return { v: z, label: z }; })),
        f.manualZone, function (v) { f.manualZone = v; renderFlow(); }, true));
    }
    wrap.appendChild(chipRow('Shooter', players, f.shooter, function (id) { f.shooter = id; renderFlow(); }));
    if (f.shooter != null) {
      if (!quickModeOn() || f.expand) {
        SHOT_DETAILS.forEach(function (d) {
          wrap.appendChild(chipRow(d[1], players, f.details[d[0]],
            function (id) { f.details[d[0]] = id; renderFlow(); }, { allowNone: true, scroll: true }));
        });
        // previews the sticky bar's pick until the coach overrides per-shot
        wrap.appendChild(chipRow('Play type',
          PLAY_TYPE_KEYS, f.details.play_type != null ? f.details.play_type : S.playType,
          function (k) { f.details.play_type = k; renderFlow(); },
          { allowNone: true, scroll: true, labelFn: ptLabel }));
      } else {
        wrap.appendChild(flowBtn('+ details', 'btn ghost small flow-more',
          function () { f.expand = true; renderFlow(); }));
      }
      wrap.appendChild(makeMissRow(logShot));
    }

  } else if (f.mode === 'ft') {
    wrap.appendChild(chipRow('Shooter', players, f.shooter, function (id) { f.shooter = id; renderFlow(); }));
    if (f.shooter != null) {
      if (!quickModeOn() || f.expand) {
        wrap.appendChild(chipRow('Rebound by', players, f.details.rebound_by_id,
          function (id) { f.details.rebound_by_id = id; renderFlow(); }, { allowNone: true, scroll: true }));
      } else {
        wrap.appendChild(flowBtn('+ details', 'btn ghost small flow-more',
          function () { f.expand = true; renderFlow(); }));
      }
      wrap.appendChild(makeMissRow(logFT));
    }

  } else if (f.mode === 'foul') {
    wrap.appendChild(chipRow('Fouled', players, f.fouled, function (id) { f.fouled = id; renderFlow(); }));
    wrap.appendChild(chipRow('Fouler', players, f.fouler, function (id) { f.fouler = id; renderFlow(); }));
    const offIds = S.lineup.officials.length
      ? S.lineup.officials
      : ((S.game.officials || []).filter(function (o) { return !o.archived; })
          .map(function (o) { return o.id; }));
    if (offIds.length) {
      wrap.appendChild(chipRow('Official', offIds, f.official,
        function (id) { f.official = id; renderFlow(); }, { allowNone: true, labelFn: oLabel }));
    }
    if (f.fouled != null && f.fouler != null) {
      wrap.appendChild(flowBtn('LOG FOUL', 'btn primary big', logFoul));
    }

  } else if (f.mode === 'tov') {
    wrap.appendChild(chipRow('Player', players, f.player, function (id) { f.player = id; renderFlow(); }));
    if (f.player != null) {
      if (!quickModeOn() || f.expand) {
        wrap.appendChild(chipRow('Stolen by',
          players.filter(function (id) { return id !== f.player; }),
          f.stolen, function (id) { f.stolen = id; renderFlow(); }, { allowNone: true }));
        wrap.appendChild(optRow('TO kind',
          TOV_TYPES.map(function (t) { return { v: t[0], label: t[1] }; }),
          f.tovKind, function (v) { f.tovKind = v; renderFlow(); }));
      } else {
        // quick mode: steal chips stay one tap away, TO kind hides behind it too
        wrap.appendChild(chipRow('Stolen by',
          players.filter(function (id) { return id !== f.player; }),
          f.stolen, function (id) { f.stolen = id; renderFlow(); }, { allowNone: true }));
        wrap.appendChild(flowBtn('+ details', 'btn ghost small flow-more',
          function () { f.expand = true; renderFlow(); }));
      }
      wrap.appendChild(flowBtn('LOG TURNOVER', 'btn primary big', logTov));
    }
  }
}

/* event builders */

function baseEvent(type) {
  return {
    uuid: uuid(),
    event_type: type,
    quarter: S.quarter,
    time: clockStr(),
    primary_player_id: null,
    shot_result: null,
    shot_x: null, shot_y: null, shot_type: null, zone: null,
    pass_from_id: null, shot_created_by_id: null, rebound_by_id: null,
    blocked_by_id: null, guarded_by_id: null,
    play_type: S.playType,                       // sticky current set call (see PLAY_TYPES)
    secondary_player_id: null, official_id: null, stolen_by_id: null,
    defense: S.defense,                          // sticky current defense (see DEFENSES)
    on_court: onCourtIds(),
    officials_on: S.lineup.officials.slice()
  };
}

async function queueEvent(ev) {
  const item = Object.assign({}, ev, { gameId: S.gameId, ts: Date.now() });
  S.queue.push(item);
  try { await qPut(item); } catch (e) { /* in-memory queue still works this session */ }
  renderScore();
  renderPBP();
  updateSyncUI();
  flush();
}

async function logShot(result) {
  const f = S.flow;
  const ev = baseEvent('shot');
  ev.primary_player_id = f.shooter;
  ev.shot_result = result;
  if (f.x != null) {
    // round first, derive from the rounded values — matches what the server
    // re-derives from the payload, so exact-arc shots can't disagree
    ev.shot_x = Math.round(f.x * 100) / 100;
    ev.shot_y = Math.round(f.y * 100) / 100;
    ev.shot_type = Court.shotValue(ev.shot_x, ev.shot_y);
    ev.zone = Court.zoneFromXY(ev.shot_x, ev.shot_y);
  } else {
    // no-location shot: coordinates stay null, value/zone are explicit
    ev.shot_type = f.manualType || 2;
    ev.zone = f.manualZone;
  }
  Object.assign(ev, f.details);
  // the per-shot chip overrides the sticky set call; untouched (null) falls
  // back to the bar's current pick
  if (ev.play_type == null) ev.play_type = S.playType;
  await queueEvent(ev);
  toast((ev.shot_type === 3 ? '3PT ' : '2PT ') + result + ' — ' + pLabel(ev.primary_player_id));
  resetFlow('shot');
  renderFlow();
}

async function logFT(result) {
  const f = S.flow;
  const ev = baseEvent('free_throw');
  ev.primary_player_id = f.shooter;
  ev.shot_result = result;
  ev.rebound_by_id = f.details.rebound_by_id;
  await queueEvent(ev);
  toast('FT ' + result + ' — ' + pLabel(ev.primary_player_id));
  resetFlow('ft');
  renderFlow();
}

async function logFoul() {
  const f = S.flow;
  const ev = baseEvent('foul');
  ev.primary_player_id = f.fouled;     // fouled player
  ev.secondary_player_id = f.fouler;   // fouler
  ev.official_id = f.official;
  // the picked official may come from the all-officials fallback list — make
  // sure the event's snapshot includes them so the lineup row gets written
  if (f.official != null && ev.officials_on.indexOf(f.official) < 0) {
    ev.officials_on.push(f.official);
  }
  await queueEvent(ev);
  toast('Foul — ' + pLabel(f.fouler) + ' on ' + pLabel(f.fouled));
  resetFlow('foul');
  renderFlow();
}

async function logTov() {
  const f = S.flow;
  const ev = baseEvent('turnover');
  ev.primary_player_id = f.player;
  ev.stolen_by_id = f.stolen;
  ev.turnover_type = f.tovKind;
  await queueEvent(ev);
  toast('Turnover — ' + pLabel(f.player));
  resetFlow('tov');
  renderFlow();
}

/* ----- undo / finish ----- */

async function undo() {
  if (S.flushing) {
    // a batch is in flight — popping now would "remove" an event that still
    // lands server-side; make the user wait out the flush
    toast('Syncing — try again in a second');
    return;
  }
  if (S.queue.length) {
    const item = S.queue.pop(); // newest queued (never sent)
    try { await qDelete([item.uuid]); } catch (e) {}
    toast('Removed queued event');
  } else {
    try {
      const res = await api('/api/games/' + S.gameId + '/undo', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.live) {
          Object.assign(S.lastLive, data.live);
          lsSet(LS.live(S.gameId), S.lastLive);
        }
        if (data.deleted_event_id != null) {
          S.lastLive.events = (S.lastLive.events || []).filter(function (e) { return e.id !== data.deleted_event_id; });
          toast('Undid last event');
        } else {
          toast('Nothing to undo');
        }
      } else {
        toast('Undo failed (HTTP ' + res.status + ')');
      }
    } catch (e) {
      toast('Offline — nothing queued to undo');
    }
  }
  renderScore();
  renderPBP();
  updateSyncUI();
}

async function finishGame() {
  if (!window.confirm('End game and save the final score?')) return;
  await flush();
  if (S.queue.length) {
    toast(S.queue.length + ' events still queued — get online, then try again');
    return;
  }
  try {
    const res = await api('/api/games/' + S.gameId + '/finish', { method: 'POST' });
    if (res.ok) {
      const d = await res.json();
      toast('Final: ' + d.home + ' – ' + d.away);
      S.gameId = null;
      S.game = null;
      showScreen('setup');
      loadGames();
    } else {
      toast('Finish failed (HTTP ' + res.status + ')');
    }
  } catch (e) {
    toast('Offline — try again when connected');
  }
}

// Leave a game WITHOUT finishing it. Queued events stay in IndexedDB (per game),
// so the game can be reopened later from the list with no data loss.
async function leaveGame() {
  if (!window.confirm('Leave this game? Your tracked events are saved — reopen it '
                      + 'any time from the games list.')) return;
  try { await flush(); } catch (e) { /* offline: events stay queued locally */ }
  S.gameId = null;
  S.game = null;
  showScreen('setup');
  loadGames();
}

/* ----- play-by-play ----- */

function evBody(ev) {
  const who = pLabel(ev.primary_player_id);
  if (ev.event_type === 'shot') {
    return who + ' ' + (ev.shot_type === 3 ? '3PT' : '2PT') + ' ' + (ev.shot_result || '') +
      (ev.zone ? ' · ' + ev.zone : '');
  }
  if (ev.event_type === 'free_throw') return who + ' FT ' + (ev.shot_result || '');
  if (ev.event_type === 'foul') return 'Foul by ' + pLabel(ev.secondary_player_id) + ' on ' + who;
  if (ev.event_type === 'turnover') {
    return who + ' turnover' + (ev.stolen_by_id ? ' (stl ' + pLabel(ev.stolen_by_id) + ')' : '');
  }
  return ev.event_type;
}

function describeEvent(ev) {
  return qlabel(ev.quarter) + ' ' + (ev.time || '') + ' · ' + evBody(ev);
}

function renderPBP() {
  const ul = $('pbp');
  if (!ul || $('screen-tracker').hidden) return;
  ul.innerHTML = '';
  const queued = S.queue.slice().reverse(); // newest first
  const synced = S.lastLive.events || [];   // already newest first
  const rows = queued.map(function (e) { return { ev: e, q: true }; })
    .concat(synced.map(function (e) { return { ev: e, q: false }; }))
    .slice(0, 10);
  if (!rows.length) { ul.innerHTML = '<li class="empty">No events yet</li>'; return; }
  rows.forEach(function (r) {
    const li = document.createElement('li');
    li.textContent = (r.q ? '⏳ ' : '') + describeEvent(r.ev);
    if (r.q) li.className = 'pbp-queued';
    ul.appendChild(li);
  });
}

/* ----- event editor (online-only) ----- */

const TYPE_LABELS = { shot: 'Shot', free_throw: 'FT', foul: 'Foul', turnover: 'TOV' };
const EDIT_ZONES = ['LC', 'LW', 'C', 'RW', 'RC'];

const ED = { events: [], filter: 0, openId: null, form: null, from: 'tracker' };  // filter 0 = all

function rosterIds() {
  return ((S.game && S.game.players) || []).map(function (p) { return p.id; });
}

async function loadEditorEvents() {
  const res = await api('/api/games/' + S.gameId + '/events');
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  ED.events = data.events || [];
}

async function openEditor() {
  if (!S.gameId) return;
  const from = $('screen-lineup').hidden ? 'tracker' : 'lineup';
  if (S.queue.length) {
    await flush();
    if (S.queue.length) {
      toast('Sync your queued events first (needs connection)');
      return;
    }
  }
  try {
    await loadEditorEvents();
  } catch (e) {
    toast(/^HTTP/.test(e && e.message) ? 'Load failed (' + e.message + ')' : 'Needs connection');
    return;
  }
  ED.filter = 0;
  ED.openId = null;
  ED.form = null;
  ED.from = from;  // Back returns to whichever screen opened the editor
  $('btn-editor-back').textContent = '‹ ' + (from === 'lineup' ? 'Lineup' : 'Tracker');
  setDrift(false);
  renderEditor();
  showScreen('editor');
}

function formFromEvent(ev) {
  const t = String(ev.time || '0:00').split(':');
  return {
    event_type: ev.event_type,
    quarter: ev.quarter || 1,
    min: parseInt(t[0], 10) || 0,
    sec: parseInt(t[1], 10) || 0,
    primary_player_id: ev.primary_player_id != null ? ev.primary_player_id : null,
    shot_result: ev.shot_result || null,
    shot_type: ev.shot_type || null,
    zone: ev.zone || null,
    pass_from_id: ev.pass_from_id != null ? ev.pass_from_id : null,
    shot_created_by_id: ev.shot_created_by_id != null ? ev.shot_created_by_id : null,
    rebound_by_id: ev.rebound_by_id != null ? ev.rebound_by_id : null,
    blocked_by_id: ev.blocked_by_id != null ? ev.blocked_by_id : null,
    guarded_by_id: ev.guarded_by_id != null ? ev.guarded_by_id : null,
    secondary_player_id: ev.secondary_player_id != null ? ev.secondary_player_id : null,
    official_id: ev.official_id != null ? ev.official_id : null,
    stolen_by_id: ev.stolen_by_id != null ? ev.stolen_by_id : null,
    play_type: ev.play_type || null,
    defense: ev.defense || null,
    turnover_type: ev.turnover_type || null
  };
}

// chip row over fixed options; re-tapping the selected chip clears it unless noClear
function optRow(label, options, selected, onPick, noClear) {
  const row = document.createElement('div');
  row.className = 'chip-row';
  const lab = document.createElement('span');
  lab.className = 'chip-label';
  lab.textContent = label;
  row.appendChild(lab);
  const box = document.createElement('div');
  box.className = 'chips';
  options.forEach(function (o) {
    box.appendChild(flowBtn(o.label, 'chip' + (selected === o.v ? ' sel' : ''), function () {
      if (selected === o.v) { if (!noClear) onPick(null); }
      else onPick(o.v);
    }));
  });
  row.appendChild(box);
  return row;
}

function numInput(val, min, max, aria, onChange) {
  const i = document.createElement('input');
  i.type = 'number';
  i.min = min;
  i.max = max;
  i.value = val;
  i.inputMode = 'numeric';
  i.setAttribute('aria-label', aria);
  i.addEventListener('change', function () {
    let v = parseInt(i.value, 10);
    if (isNaN(v)) v = min;
    v = Math.max(min, Math.min(max, v));
    i.value = v;
    onChange(v);
  });
  return i;
}

function renderEditor() {
  const fb = $('ed-filters');
  fb.innerHTML = '';
  const qs = [1, 2, 3, 4];
  ED.events.forEach(function (e) {
    if (e.quarter > 4 && qs.indexOf(e.quarter) < 0) qs.push(e.quarter);
  });
  qs.sort(function (a, b) { return a - b; });
  fb.appendChild(flowBtn('All', 'chip' + (ED.filter === 0 ? ' sel' : ''), function () {
    ED.filter = 0; renderEditor();
  }));
  qs.forEach(function (q) {
    fb.appendChild(flowBtn(qlabel(q), 'chip' + (ED.filter === q ? ' sel' : ''), function () {
      ED.filter = q; ED.openId = null; ED.form = null; renderEditor();
    }));
  });

  const ul = $('ed-list');
  ul.innerHTML = '';
  const rows = ED.events.slice().reverse()  // newest first
    .filter(function (e) { return ED.filter === 0 || e.quarter === ED.filter; });
  if (!rows.length) { ul.innerHTML = '<li class="empty">No events</li>'; return; }
  rows.forEach(function (ev) {
    const li = document.createElement('li');
    const btn = flowBtn(
      qlabel(ev.quarter) + ' ' + (ev.time || '') + ' · ' +
      (TYPE_LABELS[ev.event_type] || ev.event_type) + ' · ' + evBody(ev),
      'ev-row',
      function () {
        if (ED.openId === ev.id) { ED.openId = null; ED.form = null; }
        else { ED.openId = ev.id; ED.form = formFromEvent(ev); }
        renderEditor();
      });
    li.appendChild(btn);
    if (ED.openId === ev.id && ED.form) li.appendChild(buildEditForm(ev));
    ul.appendChild(li);
  });
}

function buildEditForm(ev) {
  const f = ED.form;
  const box = document.createElement('div');
  box.className = 'ev-edit';
  const roster = rosterIds();
  function rerender() { renderEditor(); }
  function pickRow(label, field, ids, opts) {
    return chipRow(label, ids, f[field], function (id) { f[field] = id; rerender(); },
      Object.assign({ allowNone: true, scroll: true }, opts || {}));
  }

  box.appendChild(optRow('Type', [
    { v: 'shot', label: 'Shot' }, { v: 'free_throw', label: 'FT' },
    { v: 'foul', label: 'Foul' }, { v: 'turnover', label: 'TOV' }
  ], f.event_type, function (v) { f.event_type = v; rerender(); }, true));

  const qt = document.createElement('div');
  qt.className = 'ed-qt';
  const qLab = document.createElement('span'); qLab.className = 'chip-label'; qLab.textContent = 'Q';
  qt.appendChild(qLab);
  qt.appendChild(numInput(f.quarter, 1, 10, 'Quarter', function (v) { f.quarter = v; }));
  const tLab = document.createElement('span'); tLab.className = 'chip-label'; tLab.textContent = 'Time';
  qt.appendChild(tLab);
  qt.appendChild(numInput(f.min, 0, 99, 'Minutes', function (v) { f.min = v; }));
  const colon = document.createElement('span'); colon.textContent = ':';
  qt.appendChild(colon);
  qt.appendChild(numInput(f.sec, 0, 59, 'Seconds', function (v) { f.sec = v; }));
  box.appendChild(qt);

  if (f.event_type === 'shot') {
    box.appendChild(pickRow('Shooter', 'primary_player_id', roster));
    box.appendChild(optRow('Result', [{ v: 'make', label: 'Make' }, { v: 'miss', label: 'Miss' }],
      f.shot_result, function (v) { f.shot_result = v; rerender(); }));
    box.appendChild(optRow('Value', [{ v: 2, label: '2PT' }, { v: 3, label: '3PT' }],
      f.shot_type, function (v) { f.shot_type = v; rerender(); }));
    box.appendChild(optRow('Zone', EDIT_ZONES.map(function (z) { return { v: z, label: z }; }),
      f.zone, function (v) { f.zone = v; rerender(); }));
    SHOT_DETAILS.forEach(function (d) {
      box.appendChild(pickRow(d[1], d[0], roster));
    });
    box.appendChild(optRow('Play type', PLAY_TYPES.map(function (p) { return { v: p[0], label: p[1] }; }),
      f.play_type, function (v) { f.play_type = v; rerender(); }));
    box.appendChild(optRow('Defense', DEFENSES.map(function (d) { return { v: d[0], label: d[1] }; }),
      f.defense, function (v) { f.defense = v; rerender(); }));
  } else if (f.event_type === 'free_throw') {
    box.appendChild(pickRow('Shooter', 'primary_player_id', roster));
    box.appendChild(optRow('Result', [{ v: 'make', label: 'Make' }, { v: 'miss', label: 'Miss' }],
      f.shot_result, function (v) { f.shot_result = v; rerender(); }));
    box.appendChild(pickRow('Rebound by', 'rebound_by_id', roster));
  } else if (f.event_type === 'foul') {
    box.appendChild(pickRow('Fouled', 'primary_player_id', roster));
    box.appendChild(pickRow('Fouler', 'secondary_player_id', roster));
    const offIds = ((S.game && S.game.officials) || []).map(function (o) { return o.id; });
    box.appendChild(pickRow('Official', 'official_id', offIds, { labelFn: oLabel }));
    box.appendChild(optRow('Play type', PLAY_TYPES.map(function (p) { return { v: p[0], label: p[1] }; }),
      f.play_type, function (v) { f.play_type = v; rerender(); }));
    box.appendChild(optRow('Defense', DEFENSES.map(function (d) { return { v: d[0], label: d[1] }; }),
      f.defense, function (v) { f.defense = v; rerender(); }));
  } else if (f.event_type === 'turnover') {
    box.appendChild(pickRow('Player', 'primary_player_id', roster));
    box.appendChild(pickRow('Stolen by', 'stolen_by_id', roster));
    box.appendChild(optRow('TO kind', TOV_TYPES.map(function (t) { return { v: t[0], label: t[1] }; }),
      f.turnover_type, function (v) { f.turnover_type = v; rerender(); }));
    box.appendChild(optRow('Play type', PLAY_TYPES.map(function (p) { return { v: p[0], label: p[1] }; }),
      f.play_type, function (v) { f.play_type = v; rerender(); }));
    box.appendChild(optRow('Defense', DEFENSES.map(function (d) { return { v: d[0], label: d[1] }; }),
      f.defense, function (v) { f.defense = v; rerender(); }));
  }

  const actions = document.createElement('div');
  actions.className = 'ed-actions';
  actions.appendChild(flowBtn('Save', 'btn primary', function () { saveEdit(ev.id); }));
  actions.appendChild(flowBtn('Delete', 'btn danger', function () { deleteEdit(ev.id); }));
  box.appendChild(actions);
  return box;
}

function applyEditLive(live) {
  if (!live) return;
  Object.assign(S.lastLive, live);
  lsSet(LS.live(S.gameId), S.lastLive);
}

function setDrift(on) {
  const el = $('ed-drift');
  if (el) el.hidden = !on;
}

// explicit re-freeze of the stored score from the event log (online-only)
async function rescoreGame() {
  if (!S.gameId) return;
  if (!isOnline()) { toast('Needs connection'); return; }
  try {
    const res = await api('/api/games/' + S.gameId + '/rescore', { method: 'POST' });
    if (!res.ok) { toast('Recompute failed (HTTP ' + res.status + ')'); return; }
    const d = await res.json();
    applyEditLive(d.live);
    setDrift(false);
    toast('Score recomputed: ' + d.home + ' – ' + d.away);
  } catch (e) {
    toast('Needs connection');
  }
}

async function saveEdit(eid) {
  const f = ED.form;
  if (!f) return;
  const body = {
    event_type: f.event_type,
    quarter: f.quarter,
    time: f.min + ':' + String(f.sec).padStart(2, '0'),
    primary_player_id: f.primary_player_id,
    shot_result: f.shot_result,
    shot_type: f.shot_type,
    zone: f.zone,
    pass_from_id: f.pass_from_id,
    shot_created_by_id: f.shot_created_by_id,
    rebound_by_id: f.rebound_by_id,
    blocked_by_id: f.blocked_by_id,
    guarded_by_id: f.guarded_by_id,
    secondary_player_id: f.secondary_player_id,
    official_id: f.official_id,
    stolen_by_id: f.stolen_by_id,
    play_type: f.play_type,
    defense: f.defense,
    turnover_type: f.turnover_type
  };
  try {
    const res = await api('/api/games/' + S.gameId + '/events/' + eid, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    if (!res.ok) { toast('Save failed (HTTP ' + res.status + ')'); return; }
    const data = await res.json();
    applyEditLive(data.live);
    setDrift(!!data.drift);
    toast('Saved');
    ED.openId = null;
    ED.form = null;
    // local fallback so the list is right even if the refresh fetch fails
    const i = ED.events.findIndex(function (e) { return e.id === eid; });
    if (i >= 0) Object.assign(ED.events[i], body);
    try { await loadEditorEvents(); } catch (e) { /* keep local copy */ }
    renderEditor();
  } catch (e) {
    toast('Needs connection');
  }
}

async function deleteEdit(eid) {
  if (!window.confirm('Delete this event?')) return;
  try {
    const res = await api('/api/games/' + S.gameId + '/events/' + eid, { method: 'DELETE' });
    if (!res.ok) { toast('Delete failed (HTTP ' + res.status + ')'); return; }
    const data = await res.json();
    applyEditLive(data.live);
    setDrift(!!data.drift);
    toast('Deleted');
    ED.openId = null;
    ED.form = null;
    ED.events = ED.events.filter(function (e) { return e.id !== eid; });
    try { await loadEditorEvents(); } catch (e) { /* keep local copy */ }
    renderEditor();
  } catch (e) {
    toast('Needs connection');
  }
}

/* ----- toast / wake lock ----- */

let toastTimer = null;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.hidden = true; }, 1800);
}

async function acquireWakeLock() {
  try {
    if (navigator.wakeLock) S.wakeLock = await navigator.wakeLock.request('screen');
  } catch (e) { /* not critical */ }
}

/* ---------- init / restore ---------- */

function bindUI() {
  // token
  try { $('token-input').value = localStorage.getItem(LS.token) || ''; } catch (e) {}
  $('token-save').addEventListener('click', function () {
    const v = $('token-input').value.trim();
    try {
      if (v) localStorage.setItem(LS.token, v);
      else localStorage.removeItem(LS.token);
    } catch (e) {}
    toast(v ? 'Token saved' : 'Token cleared');
    loadGames();
  });

  // setup: new game / new team
  $('btn-new-game').addEventListener('click', toggleNewGame);
  $('game-search').addEventListener('input', applyGameFilter);
  $('season-select').addEventListener('change', function () {
    currentSeason = this.value || 'Current';
    loadGames();
  });
  renderGenderFilter();

  // lineup
  $('btn-lineup-back').addEventListener('click', function () { showScreen('setup'); loadGames(); });

  // lineup: quick-add player / official
  ['home', 'away'].forEach(function (side) {
    $('btn-add-' + side).addEventListener('click', function () {
      const f = $('add-' + side + '-form');
      f.hidden = !f.hidden;
    });
    $('add-' + side + '-save').addEventListener('click', function () { quickAddPlayer(side); });
    $('btn-hands-' + side).addEventListener('click', function () {
      const t = $('hands-' + side);
      t.hidden = !t.hidden;
      if (!t.hidden) renderHands(side);
    });
  });
  $('btn-add-official').addEventListener('click', function () {
    const f = $('add-official-form');
    f.hidden = !f.hidden;
  });
  $('add-official-save').addEventListener('click', quickAddOfficial);
  $('btn-start').addEventListener('click', function () {
    if (!onCourtIds().length) { toast('Select players first'); return; }
    savePrefs();
    enterTracker();
  });
  $('btn-lineup-edit-log').addEventListener('click', openEditor);

  // tracker header
  $('btn-subs').addEventListener('click', function () { toggleSubsPanel(); });
  // courtside whiteboard overlay (wb.js) — same tap-in/tap-out feel as Subs
  $('btn-board').addEventListener('click', function () {
    if (window.WB) window.WB.toggle();
  });
  $('quick-toggle').addEventListener('click', function () {
    setQuickMode(!quickModeOn());
    setQuickBtn();
    if (S.flow) S.flow.expand = false;
    renderFlow();
  });
  $('q-minus').addEventListener('click', function () {
    S.quarter = Math.max(1, S.quarter - 1);
    $('q-label').textContent = qlabel(S.quarter);
    savePrefs();
  });
  $('q-plus').addEventListener('click', function () {
    S.quarter = Math.min(10, S.quarter + 1);
    $('q-label').textContent = qlabel(S.quarter);
    savePrefs();
  });
  // Focusing a clock field while the clock is running pauses it first, so the tick
  // can't overwrite what you type. Manual entry + steppers stay fully available.
  ['clock-min', 'clock-sec'].forEach(function (id) {
    $(id).addEventListener('focus', function () { if (S.clockRunning) stopClock(); });
  });
  $('clock-min').addEventListener('change', function () {
    S.clockMin = Math.max(0, Math.min(20, parseInt(this.value, 10) || 0));
    this.value = S.clockMin;
    savePrefs();
  });
  $('clock-sec').addEventListener('change', function () {
    S.clockSec = Math.max(0, Math.min(59, parseInt(this.value, 10) || 0));
    this.value = S.clockSec;
    savePrefs();
  });
  $('clk-toggle').addEventListener('click', toggleClock);
  $('clk-min-minus').addEventListener('click', function () { nudgeMin(-1); });
  $('clk-min-plus').addEventListener('click', function () { nudgeMin(1); });
  $('clk-sec-minus').addEventListener('click', function () { nudgeSec(-1); });
  $('clk-sec-plus').addEventListener('click', function () { nudgeSec(1); });

  // modes / actions
  document.querySelectorAll('#mode-row .mode').forEach(function (b) {
    b.addEventListener('click', function () { setMode(b.dataset.mode); });
  });
  $('btn-undo').addEventListener('click', undo);
  $('btn-edit-log').addEventListener('click', openEditor);
  $('btn-leave').addEventListener('click', leaveGame);
  $('btn-finish').addEventListener('click', finishGame);

  // event editor
  $('btn-editor-back').addEventListener('click', function () {
    if (ED.from === 'lineup') {
      renderLineup();
      showScreen('lineup');
    } else {
      enterTracker();
    }
    refreshLive(); // play-by-play + score reflect the edits
  });
  $('btn-rescore').addEventListener('click', rescoreGame);

  // sync triggers
  window.addEventListener('online', function () { updateNetUI(); flush(); });
  window.addEventListener('offline', updateNetUI);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      flush();
      if (!$('screen-tracker').hidden) acquireWakeLock();
    }
  });
  setInterval(flush, 20000);
}

// Controls whose endpoints a guest "assistant scorer" link can't call.
const GUEST_HIDE_IDS = ['btn-new-game', 'btn-add-home', 'btn-add-away',
  'btn-add-official', 'btn-finish', 'btn-edit-log', 'btn-lineup-edit-log',
  'btn-hands-home', 'btn-hands-away'];

async function applyGuestMode() {
  // A guest link is log-only — hide create/finish/edit/add controls so the
  // assistant only sees logging. The server enforces this regardless.
  try {
    const r = await api('/api/me');
    if (!r.ok) return;
    S.isGuest = !!(await r.json()).guest;
  } catch (e) { return; }
  if (!S.isGuest) return;
  GUEST_HIDE_IDS.forEach(function (id) { const el = $(id); if (el) el.hidden = true; });
  const s = $('setup-status');
  if (s) s.textContent = 'Assistant mode — log events only.';
}

async function init() {
  bindUI();
  await applyGuestMode();
  updateNetUI();

  // restore mid-game state after reload
  const st = lsGet(LS.state, null);
  if (st && st.screen === 'editor') st.screen = 'tracker'; // editor never restores cold
  if (st && st.gameId && (st.screen === 'tracker' || st.screen === 'lineup')) {
    const roster = lsGet(LS.roster(st.gameId), null);
    if (roster) {
      S.gameId = st.gameId;
      S.game = roster;
      const prefs = lsGet(LS.game(st.gameId), {});
      S.lineup = prefs.lineup || { home: [], away: [], officials: [] };
      S.quarter = prefs.quarter || 1;
      S.clockMin = prefs.clockMin != null ? prefs.clockMin : 8;
      S.clockSec = prefs.clockSec != null ? prefs.clockSec : 0;
      S.lastLive = lsGet(LS.live(st.gameId), Object.assign({}, EMPTY_LIVE));
      try { S.queue = await qLoad(st.gameId); } catch (e) { S.queue = []; }
      resetFlow('shot');
      if (st.screen === 'tracker') {
        enterTracker();
        refreshLive();
        flush();
      } else {
        renderLineup();
        showScreen('lineup');
      }
      loadGames(); // refresh cache in background
      loadSeasons();
      return;
    }
  }

  showScreen('setup');
  loadSeasons();
  loadGames();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();

})();
