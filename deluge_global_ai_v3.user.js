// ==UserScript==
// @name         DelugeRPG Global 49-Map DQN V3
// @namespace    DelugeRPG.AI.GlobalV3
// @version      1.0.0
// @description  Local supervised browser inference using the trained V3 190-feature / 11-action DQN.
// @match        https://www.delugerpg.com/*
// @match        https://m.delugerpg.com/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function () {
  'use strict';

  const DB_NAME = 'DelugeAI_DB';
  const DB_STORE = 'weights';
  const DB_VERSION = 1;
  const WEIGHTS_KEY = 'global_49map_dqn_v3';
  const ACTION_NAMES = [
    'Local_NW', 'Local_NE', 'Local_Center', 'Local_SW', 'Local_SE',
    'Warp_North', 'Warp_South', 'Warp_West', 'Warp_East',
    'Dungeon_Enter_Ascend', 'Dungeon_Exit_Descend'
  ];
  const DIR_OFFSETS = [
    [-1, 0, 'n'], [1, 0, 's'], [0, -1, 'w'], [0, 1, 'e'],
    [-1, -1, 'nw'], [-1, 1, 'ne'], [1, -1, 'sw'], [1, 1, 'se']
  ];
  const DIR_BITS = { n: 1, s: 2, w: 4, e: 8, nw: 16, ne: 32, sw: 64, se: 128 };
  const INFINITE = 1000000;

  let model = null;
  let isRunning = false;
  let isPaused = false;
  let debug = false;
  let timer = null;
  let pendingMove = null;
  let pendingMoveTimeout = null;
  let targetMap = null;
  let targetSector = 2;
  let macroStep = 0;
  let encounterCount = 0;
  let encounterWasVisible = false;
  let visitedMaps = new Set();
  let mapVisitCounts = {};
  let recentMaps = [];
  let recentActions = [];
  let localVisitedTiles = new Set();
  let lastAction = null;
  let currentPath = [];
  let pathIndex = 0;
  const macroReverseCache = new Map();
  let macroIncomingCache = null;
  const pathCache = new Map();
  const relevantCoordCache = new Map();

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = function (event) {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(DB_STORE)) db.createObjectStore(DB_STORE);
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error); };
    });
  }

  async function loadWeights() {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readonly');
      const req = tx.objectStore(DB_STORE).get(WEIGHTS_KEY);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async function saveWeights(weights) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readwrite');
      const req = tx.objectStore(DB_STORE).put(weights, WEIGHTS_KEY);
      req.onsuccess = () => resolve(true);
      req.onerror = () => reject(req.error);
    });
  }

  function validateWeights(weights) {
    if (!weights || weights.model_version !== 'Global49MapDQN-v3') return 'Unexpected model version';
    if (weights.checkpoint !== 'global_49map_dqn_v3_best.pt') return 'Unexpected checkpoint';
    if (weights.checkpoint_episode !== 4400) return 'Unexpected checkpoint episode';
    if (weights.input_dim !== 190 || weights.output_dim !== 11) return 'Unexpected dimensions';
    if (!weights.parameters || !weights.map_names || !weights.walkgrids || !weights.transition_registry) {
      return 'Incomplete browser weight metadata';
    }
    if (!Array.isArray(weights.macro_edges) || !weights.macro_edges.length) {
      return 'Weights lack the exact planner graph. Re-import the latest browser weights JSON.';
    }
    return null;
  }

  function detectMap() {
    const match = location.pathname.match(/\/map\/([a-zA-Z0-9]+)/);
    if (!match) return null;
    const mapName = match[1];
    return model && model.map_names.indexOf(mapName) >= 0 ? mapName : null;
  }

  function getPlayerPos() {
    const sprite = document.getElementById('usersprite');
    if (!sprite || !sprite.parentElement) return null;
    const parent = sprite.parentElement;
    const top = parseInt(parent.style.top || '', 10);
    const left = parseInt(parent.style.left || '', 10);
    if (!Number.isFinite(top) || !Number.isFinite(left)) return null;
    const x = Math.round((top + 17) / 16) + 1;
    const y = Math.round((left + 9 - 2) / 16) + 1;
    if (x < 1 || x > 31 || y < 1 || y > 31) return null;
    return { x, y, top, left };
  }

  function decodeWalkgrid(mapName) {
    const b64 = model.walkgrids[mapName];
    if (!b64) return null;
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function getTile(mapName, x, y) {
    const bytes = decodeWalkgrid(mapName);
    if (!bytes || x < 0 || x >= 33 || y < 0 || y >= 33) return null;
    const idx = (x * 33 + y) * 2;
    return {
      walkable: Boolean(bytes[idx] & 1),
      allowed: {
        n: Boolean(bytes[idx + 1] & DIR_BITS.n),
        s: Boolean(bytes[idx + 1] & DIR_BITS.s),
        w: Boolean(bytes[idx + 1] & DIR_BITS.w),
        e: Boolean(bytes[idx + 1] & DIR_BITS.e),
        nw: Boolean(bytes[idx + 1] & DIR_BITS.nw),
        ne: Boolean(bytes[idx + 1] & DIR_BITS.ne),
        sw: Boolean(bytes[idx + 1] & DIR_BITS.sw),
        se: Boolean(bytes[idx + 1] & DIR_BITS.se)
      }
    };
  }

  function walkableTileCount(mapName) {
    let count = 0;
    for (let x = 1; x <= 31; x++) {
      for (let y = 1; y <= 31; y++) {
        const tile = getTile(mapName, x, y);
        if (tile && tile.walkable) count++;
      }
    }
    return count;
  }

  function findPath(mapName, startX, startY, destX, destY) {
    if (startX === destX && startY === destY) return [];
    const cacheKey = mapName + '|' + startX + ',' + startY + '|' + destX + ',' + destY;
    if (pathCache.has(cacheKey)) return pathCache.get(cacheKey);
    const bytes = decodeWalkgrid(mapName);
    if (!bytes) return null;
    const queue = [[startX, startY]];
    const visited = new Set([startX + ',' + startY]);
    const cameFrom = new Map();
    while (queue.length) {
      const [cx, cy] = queue.shift();
      if (cx === destX && cy === destY) break;
      const idx = (cx * 33 + cy) * 2;
      const dirMask = (bytes[idx] & 1) ? bytes[idx + 1] : 255;
      for (const [dx, dy, name] of DIR_OFFSETS) {
        const nx = cx + dx, ny = cy + dy;
        if (nx < 1 || nx > 31 || ny < 1 || ny > 31) continue;
        if (!(dirMask & DIR_BITS[name])) continue;
        const key = nx + ',' + ny;
        if (visited.has(key)) continue;
        const nextIdx = (nx * 33 + ny) * 2;
        if ((nx === destX && ny === destY) || (bytes[nextIdx] & 1)) {
          visited.add(key);
          cameFrom.set(key, [cx, cy]);
          queue.push([nx, ny]);
        }
      }
    }
    const destKey = destX + ',' + destY;
    if (!visited.has(destKey)) {
      pathCache.set(cacheKey, null);
      return null;
    }
    const path = [];
    let key = destKey;
    while (key !== startX + ',' + startY) {
      const [x, y] = key.split(',').map(Number);
      path.unshift([x, y]);
      const prev = cameFrom.get(key);
      if (!prev) {
        pathCache.set(cacheKey, null);
        return null;
      }
      key = prev[0] + ',' + prev[1];
    }
    pathCache.set(cacheKey, path);
    return path;
  }

  function getUsableRecords() {
    const data = model.transition_registry;
    const records = data.records || data.transitions || data.validation?.records || [];
    return records.filter(record =>
      record.verification_status !== 'INVALID' &&
      record.source_map &&
      record.destination_map &&
      record.source_coord &&
      record.destination_coord
    );
  }

  function relevantCoords(mapName) {
    if (relevantCoordCache.has(mapName)) return relevantCoordCache.get(mapName);
    const set = new Set();
    for (const coord of model.sector_waypoints[mapName] || []) set.add(coord[0] + ',' + coord[1]);
    for (const record of getUsableRecords()) {
      if (record.source_map === mapName && record.source_coord) {
        set.add(record.source_coord[0] + ',' + record.source_coord[1]);
      }
      if (record.destination_map === mapName && record.destination_coord) {
        set.add(record.destination_coord[0] + ',' + record.destination_coord[1]);
      }
    }
    const coords = Array.from(set).map(key => key.split(',').map(Number));
    relevantCoordCache.set(mapName, coords);
    return coords;
  }

  function remainingMacroCost(mapName, coord, targetMapName, sector) {
    if (mapName === targetMapName) {
      const target = model.sector_waypoints[targetMapName][sector];
      const path = findPath(mapName, coord[0], coord[1], target[0], target[1]);
      if (coord[0] === target[0] && coord[1] === target[1]) return 0;
      if (path) return 1;
    }
    const reverse = buildMacroReverse(targetMapName, sector);
    let best = INFINITE;
    for (const record of getUsableRecords()) {
      if (record.source_map !== mapName || !record.source_coord || !record.destination_coord) continue;
      const localPath = findPath(mapName, coord[0], coord[1], record.source_coord[0], record.source_coord[1]);
      if (!localPath) continue;
      const after = reverse.get(macroNodeIndex(record.destination_map, record.destination_coord));
      if (after !== undefined) best = Math.min(best, 1 + after);
    }
    return best;
  }

  function macroNodeIndex(mapName, coord) {
    const mapIndex = model.map_names.indexOf(mapName);
    if (mapIndex < 0) return -1;
    return mapIndex * 1089 + coord[0] * 33 + coord[1];
  }

  function macroIncomingEdges() {
    if (macroIncomingCache) return macroIncomingCache;
    const incoming = new Map();
    for (const edge of model.macro_edges) {
      if (!Array.isArray(edge) || edge.length !== 2) throw new Error('Invalid planner graph edge');
      const source = Number(edge[0]), destination = Number(edge[1]);
      if (!Number.isInteger(source) || !Number.isInteger(destination)) {
        throw new Error('Planner graph contains an invalid node index');
      }
      if (!incoming.has(destination)) incoming.set(destination, []);
      incoming.get(destination).push(source);
    }
    macroIncomingCache = incoming;
    return incoming;
  }

  function buildMacroReverse(targetMapName, sector) {
    const cacheKey = targetMapName + '|' + sector;
    if (macroReverseCache.has(cacheKey)) return macroReverseCache.get(cacheKey);
    const reverse = new Map();
    const targetCoord = model.sector_waypoints[targetMapName][sector];
    const incoming = macroIncomingEdges();
    const zeroSeeds = [];
    const oneSeeds = [];
    function seed(index, cost) {
      const old = reverse.get(index);
      if (old === undefined || cost < old) {
        reverse.set(index, cost);
        (cost === 0 ? zeroSeeds : oneSeeds).push(index);
      }
    }
    for (const coord of relevantCoords(targetMapName)) {
      const index = macroNodeIndex(targetMapName, coord);
      if (coord[0] === targetCoord[0] && coord[1] === targetCoord[1]) seed(index, 0);
      else if (findPath(targetMapName, coord[0], coord[1], targetCoord[0], targetCoord[1])) seed(index, 1);
    }
    const queue = zeroSeeds.concat(oneSeeds);
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const destination = queue[cursor];
      const nextCost = reverse.get(destination) + 1;
      for (const source of incoming.get(destination) || []) {
        if (reverse.has(source)) continue;
        reverse.set(source, nextCost);
        queue.push(source);
      }
    }
    macroReverseCache.set(cacheKey, reverse);
    return reverse;
  }

  function mapHops(fromMap, toMap) {
    if (fromMap === toMap) return 0;
    const queue = [fromMap], seen = new Set([fromMap]), distances = { [fromMap]: 0 };
    while (queue.length) {
      const mapName = queue.shift();
      for (const record of getUsableRecords()) {
        if (record.source_map !== mapName || !record.destination_map) continue;
        if (!seen.has(record.destination_map)) {
          seen.add(record.destination_map);
          distances[record.destination_map] = distances[mapName] + 1;
          queue.push(record.destination_map);
        }
      }
    }
    return distances[toMap] ?? INFINITE;
  }

  function linear(input, weight, bias) {
    const out = new Array(weight.length);
    for (let r = 0; r < weight.length; r++) {
      let sum = bias[r];
      const row = weight[r];
      for (let c = 0; c < row.length; c++) sum += input[c] * row[c];
      out[r] = sum;
    }
    return out;
  }

  function relu(input) { return input.map(v => v > 0 ? v : 0); }

  function forwardPass(input) {
    const p = model.parameters;
    let x = relu(linear(input, p['feature_net.0.weight'], p['feature_net.0.bias']));
    x = relu(linear(x, p['feature_net.2.weight'], p['feature_net.2.bias']));
    let value = relu(linear(x, p['value_stream.0.weight'], p['value_stream.0.bias']));
    value = linear(value, p['value_stream.2.weight'], p['value_stream.2.bias'])[0];
    let adv = relu(linear(x, p['advantage_stream.0.weight'], p['advantage_stream.0.bias']));
    adv = linear(adv, p['advantage_stream.2.weight'], p['advantage_stream.2.bias']);
    const mean = adv.reduce((sum, v) => sum + v, 0) / adv.length;
    return adv.map(v => value + (v - mean));
  }

  function buildActionMask(mapName, coord) {
    const mask = new Array(11).fill(false);
    if (!targetMap) return mask;
    const currentCost = remainingMacroCost(mapName, [coord.x, coord.y], targetMap, targetSector);
    for (let action = 0; action < 5; action++) {
      const waypoint = model.sector_waypoints[mapName][action];
      if (waypoint[0] === coord.x && waypoint[1] === coord.y) continue;
      if (!findPath(mapName, coord.x, coord.y, waypoint[0], waypoint[1])) continue;
      const after = remainingMacroCost(mapName, waypoint, targetMap, targetSector);
      if (after < currentCost) mask[action] = true;
    }
    for (let action = 5; action <= 10; action++) {
      for (const record of transitionCandidates(mapName, action)) {
        const path = findPath(mapName, coord.x, coord.y, record.source_coord[0], record.source_coord[1]);
        if (!path) continue;
        const after = remainingMacroCost(
          record.destination_map,
          record.destination_coord,
          targetMap,
          targetSector
        );
        if (after < INFINITE) {
          mask[action] = true;
          break;
        }
      }
    }
    return mask;
  }

  function buildExecutionMask(mapName, coord, modelMask) {
    const executable = new Array(11).fill(false);
    for (let action = 0; action < 5; action++) executable[action] = Boolean(modelMask[action]);
    for (let action = 5; action <= 8; action++) {
      if (!modelMask[action]) continue;
      executable[action] = transitionCandidates(mapName, action).some(record => {
        if (record.verification_status !== 'VERIFIED') return false;
        const path = findPath(mapName, coord.x, coord.y, record.source_coord[0], record.source_coord[1]);
        if (!path) return false;
        return remainingMacroCost(
          record.destination_map,
          record.destination_coord,
          targetMap,
          targetSector
        ) < INFINITE;
      });
    }
    return executable;
  }

  function buildWarpCosts(mapName, coord) {
    const costs = new Array(4).fill(1);
    for (let action = 5; action <= 8; action++) {
      let bestLocalCost = INFINITE;
      for (const record of transitionCandidates(mapName, action)) {
        const path = findPath(mapName, coord.x, coord.y, record.source_coord[0], record.source_coord[1]);
        if (!path) continue;
        const after = remainingMacroCost(
          record.destination_map,
          record.destination_coord,
          targetMap,
          targetSector
        );
        if (after < INFINITE) bestLocalCost = Math.min(bestLocalCost, path.length);
      }
      if (bestLocalCost < INFINITE) costs[action - 5] = Math.min(bestLocalCost / 32, 1);
    }
    return costs;
  }

  function transitionCandidates(mapName, action) {
    const records = getUsableRecords().filter(record => record.source_map === mapName);
    if (action >= 5 && action <= 8) {
      const direction = { 5: 'north', 6: 'south', 7: 'west', 8: 'east' }[action];
      return records.filter(record =>
        record.transition_class === 'overworld_seam' &&
        record.trigger === 'move:' + direction
      );
    }
    if (action === 9) {
      const ascents = records.filter(record =>
        record.transition_class === 'dungeon_floor' &&
        record.transition_type === 'ascend'
      );
      return ascents.length ? ascents : records.filter(record =>
        record.transition_class === 'overworld_to_dungeon' &&
        record.transition_type === 'entrance'
      );
    }
    if (action === 10) {
      const descents = records.filter(record =>
        record.transition_class === 'dungeon_floor' &&
        record.transition_type === 'descend'
      );
      return descents.length ? descents : records.filter(record =>
        record.transition_class === 'overworld_to_dungeon' &&
        record.transition_type === 'exit'
      );
    }
    return [];
  }

  function recordAction(record) {
    if (record.transition_class === 'overworld_seam') {
      return { north: 5, south: 6, west: 7, east: 8 }[record.trigger?.replace('move:', '')];
    }
    return undefined;
  }

  function buildObservation(mapName, coord) {
    if (!targetMap) throw new Error('Target map is not configured');
    const names = model.map_names;
    const obs = [];
    const currentVec = new Array(49).fill(0);
    currentVec[names.indexOf(mapName)] = 1;
    obs.push(...currentVec);
    const targetVec = new Array(49).fill(0);
    targetVec[names.indexOf(targetMap)] = 1;
    obs.push(...targetVec);
    obs.push(coord.x / 32, coord.y / 32);
    const targetCoord = model.sector_waypoints[targetMap][targetSector];
    obs.push(targetCoord[0] / 32, targetCoord[1] / 32);
    obs.push(mapName === targetMap ? 1 : 0);
    const remaining = remainingMacroCost(mapName, [coord.x, coord.y], targetMap, targetSector);
    obs.push(remaining < INFINITE ? Math.min(remaining, 30) / 30 : 1);
    const hops = mapHops(mapName, targetMap);
    obs.push(hops < INFINITE ? Math.min(hops, 10) / 10 : 1);
    let localDistance = 0;
    if (mapName === targetMap) {
      const path = findPath(mapName, coord.x, coord.y, targetCoord[0], targetCoord[1]);
      localDistance = path ? Math.min(path.length / 64, 1) : 1;
    }
    obs.push(localDistance);
    const visitedVec = new Array(49).fill(0);
    visitedMaps.forEach(name => { visitedVec[names.indexOf(name)] = 1; });
    obs.push(...visitedVec);
    obs.push(Math.min((mapVisitCounts[mapName] || 1) / 5, 1));
    const history = recentMaps.slice(-5);
    while (history.length < 5) history.unshift(-1);
    obs.push(...history.map(index => index >= 0 ? index / 49 : -1));
    const actions = recentActions.slice(-4);
    while (actions.length < 4) actions.unshift(-1);
    obs.push(...actions.map(action => action >= 0 ? action / 10 : -1));
    const mask = buildActionMask(mapName, coord);
    obs.push(...mask.map(value => value ? 1 : 0));
    const warpCosts = buildWarpCosts(mapName, coord);
    obs.push(...warpCosts);
    const tile = getTile(mapName, coord.x, coord.y);
    for (const direction of ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se']) {
      obs.push(tile && tile.allowed[direction] ? 1 : 0);
    }
    const transitionSource = getUsableRecords().some(record =>
      record.source_map === mapName &&
      record.source_coord &&
      record.source_coord[0] === coord.x &&
      record.source_coord[1] === coord.y
    ) ? 1 : 0;
    obs.push(transitionSource);
    obs.push(localVisitedTiles.size / Math.max(1, walkableTileCount(mapName)));
    if (obs.length !== 190) throw new Error('Observation length is ' + obs.length + ', expected 190');
    if (obs.some(value => !Number.isFinite(value))) throw new Error('Observation contains non-finite values');
    return { observation: obs, mask };
  }

  function isGameBusy() {
    const encounterVisible = isEncounterVisible();
    if (typeof window.busy !== 'undefined' && window.busy === 1 && !encounterVisible) return true;
    const searching = document.getElementById('searching');
    if (searching && searching.offsetParent !== null && !encounterVisible) return true;
    return false;
  }

  function getChallengeReason() {
    const title = document.title || '';
    if (/just a moment|attention required|security check/i.test(title)) {
      return 'Security challenge detected. Navigation stopped.';
    }
    const challenge = document.querySelector(
      '.cf-challenge, #challenge-form, #cf-challenge-running, .cf-turnstile iframe'
    );
    if (challenge && challenge.offsetParent !== null) {
      return 'CAPTCHA/Cloudflare challenge detected. Navigation stopped.';
    }
    return null;
  }

  function isEncounterVisible() {
    const encounter = document.querySelector('#encounter, .wild-pokemon, #wild-pokemon, #pokemonimg');
    return Boolean(encounter && encounter.offsetParent !== null);
  }

  function observeEncounter() {
    const visible = isEncounterVisible();
    if (visible && !encounterWasVisible) encounterCount++;
    encounterWasVisible = visible;
  }

  function stopWithError(message) {
    isRunning = false;
    isPaused = false;
    if (timer) clearTimeout(timer);
    if (pendingMoveTimeout) clearTimeout(pendingMoveTimeout);
    timer = null;
    pendingMove = null;
    updateLog(message);
    setStatus('STOPPED');
  }

  function triggerMoveDirection(direction) {
    const move = document.getElementById('move_' + direction) ||
      document.querySelector('#directions a[data-dir="' + direction + '"]');
    const disabled = document.getElementById('dr-' + direction);
    if (disabled && (disabled.className || '').includes('disable')) return false;
    if (!move) return false;
    try {
      move.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      return true;
    } catch (error) {
      return false;
    }
  }

  function executeLocalAction(action, mapName, coord) {
    const target = model.sector_waypoints[mapName][action];
    if (target[0] === coord.x && target[1] === coord.y) return false;
    currentPath = findPath(mapName, coord.x, coord.y, target[0], target[1]);
    pathIndex = 0;
    if (!currentPath || !currentPath.length) return false;
    return executeNextLocalStep(mapName, coord);
  }

  function executeNextLocalStep(mapName, coord) {
    if (!currentPath || pathIndex >= currentPath.length) return false;
    const next = currentPath[pathIndex];
    const dx = next[0] - coord.x, dy = next[1] - coord.y;
    let direction = null;
    for (const [ox, oy, name] of DIR_OFFSETS) {
      if (ox === dx && oy === dy) { direction = name; break; }
    }
    if (!direction) return false;
    pendingMove = { from: [coord.x, coord.y], to: next, direction, mapName };
    if (!triggerMoveDirection(direction)) {
      stopWithError('Movement command could not be issued for ' + direction);
      return false;
    }
    updateLog('Moving ' + direction + ' to (' + next[0] + ', ' + next[1] + ')');
    pendingMoveTimeout = setTimeout(function () {
      stopWithError('Movement confirmation timed out. Execution stopped.');
    }, 3500);
    return true;
  }

  function executeWarpAction(action, mapName, coord) {
    const direction = { 5: 'north', 6: 'south', 7: 'west', 8: 'east' }[action];
    const record = transitionCandidates(mapName, action)
      .filter(candidate => candidate.verification_status === 'VERIFIED')
      .map(candidate => ({
        record: candidate,
        path: findPath(mapName, coord.x, coord.y, candidate.source_coord[0], candidate.source_coord[1])
      }))
      .filter(candidate => candidate.path &&
        remainingMacroCost(
          candidate.record.destination_map,
          candidate.record.destination_coord,
          targetMap,
          targetSector
        ) < INFINITE)
      .sort((a, b) => a.path.length - b.path.length)[0]?.record;
    if (!record) {
      stopWithError('No reachable, verified ' + direction + ' transition is available. No transition was attempted.');
      return false;
    }
    if (!record.source_coord) {
      stopWithError('Selected transition has no source coordinate');
      return false;
    }
    if (coord.x !== record.source_coord[0] || coord.y !== record.source_coord[1]) {
      const path = findPath(mapName, coord.x, coord.y, record.source_coord[0], record.source_coord[1]);
      if (!path) {
        stopWithError('Cannot route to verified transition source');
        return false;
      }
      currentPath = path;
      pathIndex = 0;
      return executeNextLocalStep(mapName, coord);
    }
    const browserDirection = direction === 'north' ? 'n' : direction === 'south' ? 's' : direction === 'west' ? 'w' : 'e';
    pendingMove = { transition: record, to: record.destination_coord, mapName };
    if (!triggerMoveDirection(browserDirection)) {
      stopWithError('Verified transition command could not be issued');
      return false;
    }
    updateLog('Executing verified transition ' + record.portal_id);
    pendingMoveTimeout = setTimeout(function () {
      stopWithError('Transition confirmation timed out');
    }, 5000);
    return true;
  }

  function confirmPendingMove() {
    if (!pendingMove) return;
    const mapName = detectMap();
    const pos = getPlayerPos();
    if (!pos) return;
    if (pendingMove.transition) {
      if (mapName === pendingMove.transition.destination_map &&
          pos.x === pendingMove.transition.destination_coord[0] &&
          pos.y === pendingMove.transition.destination_coord[1]) {
        clearTimeout(pendingMoveTimeout);
        pendingMove = null;
        updateLog('Transition confirmed');
        scheduleNext(500);
      }
    } else if (mapName === pendingMove.mapName &&
               pos.x === pendingMove.to[0] &&
               pos.y === pendingMove.to[1]) {
      clearTimeout(pendingMoveTimeout);
      pathIndex++;
      pendingMove = null;
      updateLog('Movement confirmed');
      scheduleNext(500);
    }
  }

  function safetyCheck() {
    const mapName = detectMap();
    if (!mapName) return 'Current map could not be identified';
    const pos = getPlayerPos();
    if (!pos) return 'Player sprite or coordinates could not be identified';
    const tile = getTile(mapName, pos.x, pos.y);
    if (!tile || !tile.walkable) {
      return 'Detected player tile is not walkable in this map data. Navigation stopped.';
    }
    const challengeReason = getChallengeReason();
    if (challengeReason) return challengeReason;
    return null;
  }

  function scheduleNext(delay) {
    if (!isRunning || isPaused) return;
    if (timer) clearTimeout(timer);
    const configured = Number(document.getElementById('ai-v3-delay')?.value || 1100);
    timer = setTimeout(runStep, Math.max(300, isFinite(configured) ? configured : delay));
  }

  function runStep() {
    if (!isRunning || isPaused) return;
    observeEncounter();
    confirmPendingMove();
    if (pendingMove) return;
    const stopReason = safetyCheck();
    if (stopReason) { stopWithError(stopReason); return; }
    if (isGameBusy()) {
      updateLog('Waiting for the game to finish its current move...');
      setStatus('WAIT');
      scheduleNext(400);
      return;
    }
    setStatus('RUNNING');
    const mapName = detectMap();
    const pos = getPlayerPos();
    visitedMaps.add(mapName);
    mapVisitCounts[mapName] = (mapVisitCounts[mapName] || 0) + 1;
    recentMaps.push(model.map_names.indexOf(mapName));
    if (recentMaps.length > 8) recentMaps.shift();
    localVisitedTiles.add(pos.x + ',' + pos.y);

    let built;
    try {
      built = buildObservation(mapName, pos);
    } catch (error) {
      stopWithError(error.message);
      return;
    }
    const legal = built.mask.map(value => value ? 1 : 0);
    if (!legal.includes(1)) { stopWithError('Action mask is empty'); return; }
    const executionMask = buildExecutionMask(mapName, pos, built.mask);
    if (!executionMask.includes(true)) {
      stopWithError(
        'No safe executable action: this route needs an unverified transition or unsupported dungeon action. No movement issued.'
      );
      return;
    }
    const started = performance.now();
    const qvalues = forwardPass(built.observation);
    let action = -1;
    for (let i = 0; i < qvalues.length; i++) {
      if (executionMask[i] && (action < 0 || qvalues[i] > qvalues[action])) action = i;
    }
    if (action < 0 || !executionMask[action]) { stopWithError('Inference selected an unavailable action'); return; }
    const duration = performance.now() - started;
    recentActions.push(action);
    if (recentActions.length > 8) recentActions.shift();
    lastAction = action;
    macroStep++;
    updateInference(qvalues, built.mask, executionMask, action, duration);

    let startedExecution = false;
    if (action < 5) startedExecution = executeLocalAction(action, mapName, pos);
    else if (action <= 8) startedExecution = executeWarpAction(action, mapName, pos);
    else stopWithError(ACTION_NAMES[action] + ' is unsupported: dungeon automation is safely paused');
    if (!startedExecution && isRunning) {
      stopWithError('Selected action did not produce a movement path. Execution stopped without retrying.');
    }
  }

  function setStatus(status) {
    const badge = document.getElementById('ai-v3-status');
    if (badge) badge.textContent = status;
  }

  function updateLog(message) {
    const log = document.getElementById('ai-v3-log');
    if (log) log.textContent = message;
  }

  function updateInference(qvalues, modelMask, executionMask, action, duration) {
    const selected = document.getElementById('ai-v3-selected');
    if (selected) selected.textContent = ACTION_NAMES[action];
    const rows = document.getElementById('ai-v3-qvalues');
    if (rows) {
      rows.innerHTML = qvalues.map((q, i) =>
        '<div><span>' + ACTION_NAMES[i] + '</span><b>' + q.toFixed(4) +
        '</b><span style="color:' + (executionMask[i] ? '#4ade80' : modelMask[i] ? '#fbbf24' : '#64748b') + '">' +
        (executionMask[i] ? 'READY' : modelMask[i] ? 'UNVERIFIED' : 'blocked') + '</span></div>'
      ).join('');
    }
    const durationElement = document.getElementById('ai-v3-duration');
    if (durationElement) durationElement.textContent = duration.toFixed(3) + ' ms';
  }

  function updateHud() {
    const mapName = detectMap() || '--';
    const pos = getPlayerPos();
    document.getElementById('ai-v3-map').textContent = mapName;
    document.getElementById('ai-v3-pos').textContent = pos ? pos.x + ', ' + pos.y : 'UNKNOWN';
    document.getElementById('ai-v3-target').textContent = targetMap ? targetMap + ' / sector ' + targetSector : '--';
    document.getElementById('ai-v3-visits').textContent = visitedMaps.size;
    document.getElementById('ai-v3-step').textContent = macroStep;
    document.getElementById('ai-v3-encounters').textContent = encounterCount;
  }

  function makeHud() {
    if (document.getElementById('deluge-global-ai-v3')) return;
    const hud = document.createElement('div');
    hud.id = 'deluge-global-ai-v3';
    hud.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;width:min(300px,calc(100vw - 20px));max-height:65vh;overflow:auto;background:rgba(24,30,38,.94);color:#e8edf2;border:1px solid rgba(167,190,210,.48);border-radius:8px;padding:8px;font:12px/1.35 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.32);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)';
    hud.innerHTML = `
      <style>
        #deluge-global-ai-v3 * { box-sizing:border-box; }
        #deluge-global-ai-v3 .ai-v3-header { display:flex;align-items:center;gap:6px;cursor:move;font-weight:650;color:#d9e8f3;border-bottom:1px solid rgba(255,255,255,.13);padding:1px 0 7px;margin-bottom:7px; }
        #deluge-global-ai-v3 .ai-v3-title { flex:1;white-space:nowrap; }
        #deluge-global-ai-v3 #ai-v3-status { color:#b6c5d2;font-size:10px; }
        #deluge-global-ai-v3 button { display:block!important;visibility:visible!important;opacity:1!important;min-width:0!important;margin:0!important;padding:6px 4px!important;border:1px solid rgba(255,255,255,.16)!important;border-radius:5px!important;background:#3a4652!important;color:#f4f7fa!important;font:600 11px/1.15 system-ui,sans-serif!important;white-space:normal!important;cursor:pointer!important; }
        #deluge-global-ai-v3 button:hover { filter:brightness(1.16); }
        #deluge-global-ai-v3 #ai-v3-start { background:#326d52!important; }
        #deluge-global-ai-v3 #ai-v3-stop { background:#843f42!important; }
        #deluge-global-ai-v3 select,#deluge-global-ai-v3 input { min-width:0!important;max-width:100%!important;padding:4px 5px!important;border:1px solid #788692!important;border-radius:4px!important;background:#202932!important;color:#f4f7fa!important;font:11px system-ui,sans-serif!important; }
        #deluge-global-ai-v3 .ai-v3-targets { display:grid;grid-template-columns:minmax(0,1fr) 64px;gap:6px;align-items:center;margin:7px 0; }
        #deluge-global-ai-v3 .ai-v3-targets label { display:grid;gap:2px;color:#c3ced7;font-size:10px; }
        #deluge-global-ai-v3 .ai-v3-controls { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;margin:7px 0; }
        #deluge-global-ai-v3 .ai-v3-statusline { color:#c3ced7;font-size:11px;margin:3px 0; }
        #deluge-global-ai-v3 .ai-v3-debug-details { margin-top:5px; }
        #deluge-global-ai-v3 .ai-v3-debug-details summary { cursor:pointer;color:#cbd5df;font-size:10px; }
        #deluge-global-ai-v3 #ai-v3-qvalues { max-height:120px;overflow:auto;margin-top:5px;font:10px/1.4 ui-monospace,Consolas,monospace; }
        #deluge-global-ai-v3 #ai-v3-qvalues > div { display:grid;grid-template-columns:1fr 54px 38px;gap:3px; }
        #deluge-global-ai-v3 #ai-v3-log { max-height:48px;overflow:auto;margin-top:6px;padding:5px;background:rgba(0,0,0,.25);border-left:2px solid #8da6ba;color:#dce5eb;font-size:10px; }
        #deluge-global-ai-v3 .ai-v3-collapse { width:27px!important;padding:4px!important;font-size:12px!important; }
        @media(max-width:600px) { #deluge-global-ai-v3 { top:auto!important;bottom:8px!important;right:8px!important;width:min(290px,calc(100vw - 16px))!important;max-height:52vh!important; } }
      </style>
      <div id="ai-v3-drag" class="ai-v3-header">
        <span class="ai-v3-title">Global DQN V3 · ep 4400</span>
        <span id="ai-v3-status">IDLE</span>
        <button type="button" class="ai-v3-collapse" id="ai-v3-collapse" title="Collapse HUD">−</button>
      </div>
      <div id="ai-v3-body">
        <div class="ai-v3-statusline">Model: <b id="ai-v3-model">Not loaded</b> · DB: <b id="ai-v3-db">Unknown</b></div>
        <div class="ai-v3-statusline">Map: <span id="ai-v3-map">--</span> · Pos: <span id="ai-v3-pos">--</span></div>
        <div class="ai-v3-targets">
          <label>Target map<select id="ai-v3-target-map"></select></label>
          <label>Sector<select id="ai-v3-target-sector"><option>0</option><option>1</option><option selected>2</option><option>3</option><option>4</option></select></label>
        </div>
        <div class="ai-v3-statusline">Goal: <span id="ai-v3-target">--</span></div>
        <div class="ai-v3-statusline">Maps: <span id="ai-v3-visits">0</span> · Step: <span id="ai-v3-step">0</span> · Pokémon seen: <span id="ai-v3-encounters">0</span></div>
        <div class="ai-v3-statusline">Action: <b id="ai-v3-selected">--</b> · <span id="ai-v3-duration">--</span></div>
        <div class="ai-v3-targets">
          <label style="grid-column:1 / -1">Movement delay (ms)<input id="ai-v3-delay" type="number" min="300" value="1100"></label>
        </div>
        <div class="ai-v3-controls">
          <button id="ai-v3-import" type="button">Import</button><button id="ai-v3-start" type="button">Start</button><button id="ai-v3-one" type="button">One Step</button>
          <button id="ai-v3-pause" type="button">Pause</button><button id="ai-v3-resume" type="button">Resume</button><button id="ai-v3-stop" type="button">Stop</button>
          <button id="ai-v3-reset" type="button">Reset</button><button id="ai-v3-debug" type="button">Debug</button>
        </div>
        <details class="ai-v3-debug-details">
          <summary>Inference diagnostics · Q-values / legal actions</summary>
          <div id="ai-v3-qvalues"></div>
        </details>
        <div id="ai-v3-log">Ready.</div>
      </div>
      <input id="ai-v3-file" type="file" accept=".json" style="display:none">
    `;
    document.body.appendChild(hud);

    let dragging = false, dx = 0, dy = 0;
    document.getElementById('ai-v3-drag').addEventListener('mousedown', function (event) {
      if (event.target.closest('button')) return;
      dragging = true;
      const rect = hud.getBoundingClientRect();
      dx = event.clientX - rect.left; dy = event.clientY - rect.top;
    });
    document.addEventListener('mousemove', function (event) {
      if (!dragging) return;
      hud.style.left = (event.clientX - dx) + 'px';
      hud.style.top = (event.clientY - dy) + 'px';
      hud.style.right = 'auto';
    });
    document.addEventListener('mouseup', function () { dragging = false; });
    document.getElementById('ai-v3-collapse').addEventListener('click', function (event) {
      event.stopPropagation();
      const body = document.getElementById('ai-v3-body');
      const collapsed = body.style.display === 'none';
      body.style.display = collapsed ? 'block' : 'none';
      this.textContent = collapsed ? '−' : '+';
      this.title = collapsed ? 'Collapse HUD' : 'Expand HUD';
    });

    document.getElementById('ai-v3-import').addEventListener('click', () => document.getElementById('ai-v3-file').click());
    document.getElementById('ai-v3-file').addEventListener('change', async function (event) {
      const file = event.target.files[0];
      if (!file) return;
      try {
        const weights = JSON.parse(await file.text());
        const error = validateWeights(weights);
        if (error) throw new Error(error);
        await saveWeights(weights);
        model = weights;
        targetMap = detectMap();
        document.getElementById('ai-v3-model').textContent = 'Loaded episode 4400';
        document.getElementById('ai-v3-db').textContent = 'Saved';
        populateTargets();
        updateHud();
        updateLog('Browser weights imported and verified.');
        setStatus('READY');
      } catch (error) {
        stopWithError('Weight import failed: ' + error.message);
      }
    });
    document.getElementById('ai-v3-start').addEventListener('click', startContinuous);
    document.getElementById('ai-v3-one').addEventListener('click', function () {
      isRunning = true; isPaused = false; runStep();
    });
    document.getElementById('ai-v3-pause').addEventListener('click', function () {
      isPaused = true; if (timer) clearTimeout(timer); setStatus('PAUSED');
    });
    document.getElementById('ai-v3-resume').addEventListener('click', function () {
      if (!model) return;
      isPaused = false; isRunning = true; setStatus('RUNNING'); scheduleNext(300);
    });
    document.getElementById('ai-v3-stop').addEventListener('click', function () {
      stopWithError('Stopped by user');
    });
    document.getElementById('ai-v3-reset').addEventListener('click', resetSession);
    document.getElementById('ai-v3-debug').addEventListener('click', function () {
      debug = !debug;
      updateLog(debug ? 'Debug mode enabled' : 'Debug mode disabled');
    });
  }

  function populateTargets() {
    if (!model) return;
    const select = document.getElementById('ai-v3-target-map');
    select.innerHTML = model.map_names.map(name => '<option value="' + name + '">' + name + '</option>').join('');
    const current = detectMap();
    select.value = current || model.map_names[0];
    targetMap = select.value;
    select.addEventListener('change', function () { targetMap = select.value; resetSession(false); });
    const sector = document.getElementById('ai-v3-target-sector');
    sector.addEventListener('change', function () { targetSector = Number(sector.value); resetSession(false); });
  }

  function startContinuous() {
    if (!model) { stopWithError('Load browser weights before starting'); return; }
    const stopReason = safetyCheck();
    if (stopReason) { stopWithError(stopReason); return; }
    isRunning = true; isPaused = false; setStatus('RUNNING');
    scheduleNext(300);
  }

  function resetSession(clearTarget) {
    if (timer) clearTimeout(timer);
    if (pendingMoveTimeout) clearTimeout(pendingMoveTimeout);
    timer = null; pendingMove = null; currentPath = [];
    isRunning = false; isPaused = false;
    macroStep = 0; encounterCount = 0;
    encounterWasVisible = false;
    visitedMaps = new Set(); mapVisitCounts = {}; recentMaps = []; recentActions = []; localVisitedTiles = new Set();
    if (clearTarget !== false) targetMap = detectMap();
    setStatus('READY'); updateHud(); updateLog('Session reset.');
  }

  async function init() {
    makeHud();
    try {
      model = await loadWeights();
      if (model) {
        const error = validateWeights(model);
        if (error) throw new Error(error);
        document.getElementById('ai-v3-model').textContent = 'Loaded episode 4400';
        document.getElementById('ai-v3-db').textContent = 'Loaded';
        populateTargets();
        setStatus('READY');
        updateLog('V3 weights loaded from IndexedDB.');
      } else {
        document.getElementById('ai-v3-model').textContent = 'Not loaded';
        document.getElementById('ai-v3-db').textContent = 'No V3 entry';
        setStatus('IMPORT');
        updateLog('Import global_49map_v3_browser_weights.json');
      }
    } catch (error) {
      stopWithError('IndexedDB/model validation failed: ' + error.message);
    }
    setInterval(confirmPendingMove, 250);
    setInterval(updateHud, 500);
  }

  window.__DELUGE_GLOBAL_AI_V3_TESTING__ = {
    validateWeights,
    detectMap,
    getPlayerPos,
    findPath,
    buildActionMask,
    buildExecutionMask,
    buildObservation,
    forwardPass,
    recordAction,
    safetyCheck,
    isEncounterVisible,
    isGameBusy,
    buildMacroReverse,
    getModel: function () { return model; },
    setModel: function (weights) { model = weights; },
    setTarget: function (mapName, sector) { targetMap = mapName; targetSector = sector; }
  };

  window.addEventListener('load', () => setTimeout(init, 300));
})();
