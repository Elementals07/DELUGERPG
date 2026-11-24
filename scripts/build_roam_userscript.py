"""
Generates the diagnostic userscript with verbose console and HUD output,
multi-method movement triggering, and exact position calculation.
"""

import os
import sqlite3

def generate_diagnostic_userscript():
    db_path = os.path.join("data", "processed", "delugerpg_kb.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    row = cur.execute("SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?", ("overworld1",)).fetchone()
    conn.close()
    walkgrid_b64 = row[0]

    script_content = f"""// ==UserScript==
// @name         DelugeRPG AI Hierarchical Path Planner (Overworld 1)
// @namespace    DelugeRPG.AI.Project
// @version      2.2.0
// @description  Hierarchical Waypoint Planning DQN with deep diagnostics, multi-method DOM click dispatch, and continuous exploration.
// @match        https://www.delugerpg.com/map/*
// @match        https://m.delugerpg.com/map/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function () {{
  'use strict';

  console.log('[DelugeAI] Script loaded into page.');

  // --- CONFIGURATION & CONSTANTS ---
  const CONFIG = {{
    stepIntervalMs: 1100,    // DelugeRPG server requires >800ms cooldown (1100ms is safe & reliable)
    recencyWindow: 4,
    dbName: 'DelugeAI_DB',
    dbVersion: 1,
    storeName: 'weights',
    weightsKey: 'map_path_planner'
  }};

  const EMBEDDED_WALKGRID_B64 = "{walkgrid_b64}";

  const WAYPOINTS = [
    {{ id: 0, x: 4, y: 28, name: "NE Pine Forest (Tall Grass)", terrain: "grass", weight: 1.8 }},
    {{ id: 1, x: 7, y: 22, name: "North Snow Ridge", terrain: "snow", weight: 1.0 }},
    {{ id: 2, x: 8, y: 29, name: "East Upper Mountain Trail", terrain: "mountain", weight: 1.3 }},
    {{ id: 3, x: 11, y: 28, name: "East Cliff Path", terrain: "mountain", weight: 1.2 }},
    {{ id: 4, x: 11, y: 19, name: "Upper Snowfield", terrain: "snow", weight: 1.0 }},
    {{ id: 5, x: 14, y: 12, name: "North Central Plains", terrain: "snow", weight: 1.1 }},
    {{ id: 6, x: 14, y: 2, name: "Ice Cavern Entrance", terrain: "cave", weight: 1.9 }},
    {{ id: 7, x: 20, y: 4, name: "West Upper Bridge", terrain: "bridge", weight: 1.2 }},
    {{ id: 8, x: 20, y: 11, name: "Central Crossroads", terrain: "snow", weight: 1.1 }},
    {{ id: 9, x: 19, y: 19, name: "East Central Terraces", terrain: "snow", weight: 1.1 }},
    {{ id: 10, x: 19, y: 26, name: "Far East Ridge Overlook", terrain: "mountain", weight: 1.4 }},
    {{ id: 11, x: 28, y: 4, name: "Southwest Lower Bridge", terrain: "bridge", weight: 1.3 }},
    {{ id: 12, x: 28, y: 11, name: "South Valley Entrance", terrain: "cave", weight: 1.7 }},
    {{ id: 13, x: 28, y: 20, name: "Southeast Rock Field", terrain: "rock", weight: 1.2 }},
    {{ id: 14, x: 28, y: 27, name: "Southeast Dirt Plateau", terrain: "dirt", weight: 1.5 }},
    {{ id: 15, x: 24, y: 16, name: "Lower Central Basin", terrain: "snow", weight: 1.0 }}
  ];

  const DIR_BITS = {{ n: 1, s: 2, w: 4, e: 8, nw: 16, ne: 32, sw: 64, se: 128 }};
  const DIR_OFFSETS = [
    [-1, 0, "n"], [1, 0, "s"], [0, -1, "w"], [0, 1, "e"],
    [-1, -1, "nw"], [-1, 1, "ne"], [1, -1, "sw"], [1, 1, "se"]
  ];

  // --- STATE ---
  let activeWeights = null;
  let isRoaming = false;
  let roamTimer = null;
  let currentPath = [];
  let pathStepIdx = 0;
  let currentWaypoint = null;
  let recentWaypoints = [];
  let waypointVisitCounts = new Array(16).fill(0);
  let waypointRecency = new Array(16).fill(999);
  let visitedTiles = new Set();
  let totalEncounters = 0;
  let totalStepsTaken = 0;
  let rawWalkgridBytes = null;
  let lastMoveAttemptTime = 0;

  // --- 1. INDEXED-DB PERSISTENCE ---
  function openDatabase() {{
    return new Promise((resolve, reject) => {{
      const req = indexedDB.open(CONFIG.dbName, CONFIG.dbVersion);
      req.onupgradeneeded = (e) => {{
        const db = e.target.result;
        if (!db.objectStoreNames.contains(CONFIG.storeName)) {{
          db.createObjectStore(CONFIG.storeName);
        }}
      }};
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }});
  }}

  async function saveWeightsToDB(weightsObj) {{
    try {{
      const db = await openDatabase();
      return new Promise((resolve, reject) => {{
        const tx = db.transaction(CONFIG.storeName, 'readwrite');
        const store = tx.objectStore(CONFIG.storeName);
        const req = store.put(weightsObj, CONFIG.weightsKey);
        req.onsuccess = () => resolve(true);
        req.onerror = () => reject(req.error);
      }});
    }} catch (err) {{
      console.error('[DelugeAI] DB Save Error:', err);
      return false;
    }}
  }}

  async function loadWeightsFromDB() {{
    try {{
      const db = await openDatabase();
      return new Promise((resolve, reject) => {{
        const tx = db.transaction(CONFIG.storeName, 'readonly');
        const store = tx.objectStore(CONFIG.storeName);
        const req = store.get(CONFIG.weightsKey);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error);
      }});
    }} catch (err) {{
      console.error('[DelugeAI] DB Load Error:', err);
      return null;
    }}
  }}

  // --- 2. WALKGRID & BFS ---
  function initWalkgrid() {{
    try {{
      const binary = atob(EMBEDDED_WALKGRID_B64.trim());
      rawWalkgridBytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {{
        rawWalkgridBytes[i] = binary.charCodeAt(i);
      }}
      console.log('[DelugeAI] Decoded WalkGrid: ' + rawWalkgridBytes.length + ' bytes.');
    }} catch (err) {{
      console.error('[DelugeAI] Walkgrid decode error:', err);
    }}
  }}

  function findPath(startX, startY, destX, destY) {{
    if (!rawWalkgridBytes) return null;
    if (startX === destX && startY === destY) return [];

    const queue = [[startX, startY]];
    const visited = new Set([startX + ',' + startY]);
    const cameFrom = new Map();
    let found = false;

    while (queue.length > 0) {{
      const [cx, cy] = queue.shift();
      if (cx === destX && cy === destY) {{
        found = true;
        break;
      }}

      const idx = (cx * 33 + cy) * 2;
      const b0 = rawWalkgridBytes[idx];
      const b1 = rawWalkgridBytes[idx + 1];
      const dirMask = (b0 & 1) ? b1 : 255;

      for (let i = 0; i < DIR_OFFSETS.length; i++) {{
        const [dx, dy, dName] = DIR_OFFSETS[i];
        const nx = cx + dx;
        const ny = cy + dy;

        if (nx < 1 || nx > 31 || ny < 1 || ny > 31) continue;
        const key = nx + ',' + ny;
        if (visited.has(key)) continue;

        if (!(dirMask & DIR_BITS[dName])) continue;

        const nextIdx = (nx * 33 + ny) * 2;
        const isDest = (nx === destX && ny === destY);
        const isWalkable = Boolean(rawWalkgridBytes[nextIdx] & 1);

        if (isDest || isWalkable) {{
          visited.add(key);
          cameFrom.set(key, [cx, cy]);
          queue.push([nx, ny]);
        }}
      }}
    }}

    if (!found) return null;

    const path = [];
    let currKey = destX + ',' + destY;
    while (currKey !== (startX + ',' + startY)) {{
      const [px, py] = currKey.split(',').map(Number);
      path.unshift([px, py]);
      const prev = cameFrom.get(currKey);
      if (!prev) break;
      currKey = prev[0] + ',' + prev[1];
    }}
    return path;
  }}

  // --- 3. PLAYER POSITION (EXACT GAME SPRITE FORMULA) ---
  const PEEP_OX = 17;
  const PEEP_OY = 9;

  function getPlayerPos() {{
    const sprite = document.getElementById('usersprite');
    if (!sprite) {{
      console.warn('[DelugeAI] #usersprite element not found on page.');
      return {{ cx: 8, cy: 29, source: 'default_fallback' }};
    }}
    const parent = sprite.parentElement;
    if (!parent) {{
      console.warn('[DelugeAI] #usersprite parent element not found.');
      return {{ cx: 8, cy: 29, source: 'default_fallback' }};
    }}

    const top = parseInt(parent.style.top || '0', 10);
    const left = parseInt(parent.style.left || '0', 10);

    // Exact game formula from DelugeRPG map.js:
    // top = (x - 1) * 16 - PEEP_OX  ==>  x = round((top + PEEP_OX)/16) + 1
    // left = (y - 1) * 16 - PEEP_OY + 2 ==> y = round((left + PEEP_OY - 2)/16) + 1
    const cx = Math.max(1, Math.min(31, Math.round((top + PEEP_OX) / 16) + 1));
    const cy = Math.max(1, Math.min(31, Math.round((left + PEEP_OY - 2) / 16) + 1));

    return {{ cx, cy, top, left, source: 'sprite' }};
  }}

  function isGameBusy() {{
    if (typeof window.busy !== 'undefined' && window.busy === 1) return true;
    const searching = document.getElementById('searching');
    if (searching && searching.offsetParent !== null) return true;
    return false;
  }}

  // --- 4. MULTI-METHOD MOVEMENT TRIGGER ---
  function triggerMoveDir(dir) {{
    console.log('[DelugeAI] Attempting move direction: ' + dir);

    // Check if direction button has class m-disable
    const drDiv = document.getElementById('dr-' + dir);
    if (drDiv) {{
      const className = drDiv.className || '';
      if (className.indexOf('disable') !== -1) {{
        console.warn('[DelugeAI] Direction ' + dir + ' is blocked (class: ' + className + ')');
        updateHUDLog('⚠️ Direction ' + dir.toUpperCase() + ' is blocked by terrain.');
        return false;
      }}
    }}

    let executed = false;

    // Method 1: DelugeRPG's native Move(dir) function if accessible
    if (typeof window.Move === 'function') {{
      try {{
        console.log('[DelugeAI] Calling window.Move("' + dir + '") directly');
        const res = window.Move(dir);
        console.log('[DelugeAI] window.Move returned:', res);
        executed = true;
      }} catch (err) {{
        console.warn('[DelugeAI] window.Move direct call error:', err);
      }}
    }}

    // Method 2: Click the <a> element (which DelugeRPG binds with $("#directions a").click(...))
    const moveA = document.getElementById('move_' + dir) || document.querySelector('#directions a[data-dir="' + dir + '"]');
    if (moveA) {{
      console.log('[DelugeAI] Found movement <a> element:', moveA.id || moveA.getAttribute('data-dir'));
      // Dispatch real MouseEvent
      try {{
        moveA.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
        moveA.click();
        executed = true;
      }} catch (err) {{
        console.warn('[DelugeAI] <a> click dispatch error:', err);
      }}
    }} else {{
      console.warn('[DelugeAI] No <a> tag found for #move_' + dir);
    }}

    // Method 3: Fallback click the inner <div> #dr-[dir]
    if (drDiv) {{
      try {{
        drDiv.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
        drDiv.click();
        executed = true;
      }} catch (err) {{
        console.warn('[DelugeAI] #dr- click dispatch error:', err);
      }}
    }}

    if (!executed) {{
      updateHUDLog('❌ Error: Could not find move button for ' + dir);
    }}
    return executed;
  }}

  // --- 5. NEURAL INFERENCE & SELECTION ---
  function buildObservation(curX, curY) {{
    const obs = new Float32Array(67);
    obs[0] = curX / 32.0;
    obs[1] = curY / 32.0;
    let idx = 2;
    for (let i = 0; i < 16; i++) {{
      const wp = WAYPOINTS[i];
      obs[idx + i] = Math.min(Math.hypot(curX - wp.x, curY - wp.y) / 45.0, 1.0);
    }}
    idx += 16;
    for (let i = 0; i < 16; i++) obs[idx + i] = Math.min((waypointVisitCounts[i] || 0) / 5.0, 1.0);
    idx += 16;
    for (let i = 0; i < 16; i++) obs[idx + i] = WAYPOINTS[i].weight / 2.0;
    idx += 16;
    for (let i = 0; i < 16; i++) obs[idx + i] = Math.min((waypointRecency[i] || 999) / 20.0, 1.0);
    idx += 16;
    obs[idx] = visitedTiles.size / 532.0;
    return obs;
  }}

  function forwardPass(weights, inputVec) {{
    let cur = inputVec;
    const layers = weights.layers;
    for (let l = 0; l < layers.length; l++) {{
      const layer = layers[l];
      const W = layer.weight;
      const b = layer.bias;
      const next = new Float32Array(layer.out_features);
      const isLast = (l === layers.length - 1);
      for (let i = 0; i < layer.out_features; i++) {{
        let sum = b[i];
        const row = W[i];
        for (let j = 0; j < layer.in_features; j++) sum += row[j] * cur[j];
        next[i] = isLast ? sum : Math.max(0, sum);
      }}
      cur = next;
    }}
    return cur;
  }}

  function selectNextWaypoint(curX, curY) {{
    if (!activeWeights) return selectHeuristicWaypoint(curX, curY);

    const obs = buildObservation(curX, curY);
    const qValues = forwardPass(activeWeights, obs);
    const recentMask = new Set(recentWaypoints.slice(-CONFIG.recencyWindow));
    let bestAction = -1;
    let bestQ = -1e9;

    for (let i = 0; i < 16; i++) {{
      const wp = WAYPOINTS[i];
      if (wp.x === curX && wp.y === curY) continue;
      if (recentMask.has(i)) continue;
      if (qValues[i] > bestQ) {{
        bestQ = qValues[i];
        bestAction = i;
      }}
    }}

    if (bestAction === -1) {{
      for (let i = 0; i < 16; i++) {{
        const wp = WAYPOINTS[i];
        if (wp.x !== curX || wp.y !== curY) {{
          if (qValues[i] > bestQ) {{
            bestQ = qValues[i];
            bestAction = i;
          }}
        }}
      }}
    }}
    return bestAction !== -1 ? bestAction : 0;
  }}

  function selectHeuristicWaypoint(curX, curY) {{
    const recentMask = new Set(recentWaypoints.slice(-CONFIG.recencyWindow));
    let bestAction = 0;
    let maxDist = -1;
    for (let i = 0; i < 16; i++) {{
      if (recentMask.has(i)) continue;
      const wp = WAYPOINTS[i];
      const d = Math.hypot(curX - wp.x, curY - wp.y);
      if (d > maxDist) {{
        maxDist = d;
        bestAction = i;
      }}
    }}
    return bestAction;
  }}

  // --- 6. ROAMING STEP CONTROLLER ---
  function checkWildEncounter() {{
    const encDiv = document.querySelector('#encounter, .wild-pokemon, #wild-pokemon, #show-poke img#pokemonimg');
    return Boolean(encDiv && encDiv.offsetParent !== null);
  }}

  function stepRoam() {{
    if (!isRoaming) return;

    const now = Date.now();
    if (now - lastMoveAttemptTime < 900) {{
      roamTimer = setTimeout(stepRoam, 200);
      return;
    }}

    if (isGameBusy()) {{
      console.log('[DelugeAI] Game is currently busy / loading. Waiting 300ms...');
      updateHUDLog('⏳ Waiting for map action to complete...');
      roamTimer = setTimeout(stepRoam, 300);
      return;
    }}

    // Check encounter: Log & count, DO NOT STOP!
    if (checkWildEncounter()) {{
      totalEncounters++;
      console.log('[DelugeAI] Encounter spotted! Total: ' + totalEncounters);
      updateHUDLog('[!] Wild Encounter Spotted! (Total: ' + totalEncounters + ')');
    }}

    const pos = getPlayerPos();
    const cx = pos.cx;
    const cy = pos.cy;
    visitedTiles.add(cx + ',' + cy);

    console.log(`[DelugeAI] Tick: Pos=(${cx},${cy}) (top:${pos.top}, left:${pos.left}) | PathIdx=${pathStepIdx}/${currentPath ? currentPath.length : 0}`);

    // If path is complete or not yet planned, generate next macro path
    if (!currentPath || pathStepIdx >= currentPath.length) {{
      const nextWpId = selectNextWaypoint(cx, cy);
      currentWaypoint = WAYPOINTS[nextWpId];
      currentPath = findPath(cx, cy, currentWaypoint.x, currentWaypoint.y);
      pathStepIdx = 0;

      for (let i = 0; i < 16; i++) waypointRecency[i]++;
      waypointVisitCounts[nextWpId]++;
      waypointRecency[nextWpId] = 0;
      recentWaypoints.push(nextWpId);
      if (recentWaypoints.length > 8) recentWaypoints.shift();

      if (!currentPath || currentPath.length === 0) {{
        console.warn('[DelugeAI] Could not find path to ' + currentWaypoint.name);
        updateHUDLog('⚠️ No path found to ' + currentWaypoint.name);
        roamTimer = setTimeout(stepRoam, 800);
        return;
      }}
      console.log(`[DelugeAI] New Macro Destination -> [${nextWpId}] ${currentWaypoint.name} (${currentPath.length} steps)`);
      updateHUDLog(`🎯 Heading to: ${currentWaypoint.name}`);
      updateHUD();
    }}

    // Take next step along the BFS path
    if (currentPath && pathStepIdx < currentPath.length) {{
      const [nx, ny] = currentPath[pathStepIdx];
      const dx = nx - cx;
      const dy = ny - cy;

      console.log(`[DelugeAI] Next target tile: (${nx}, ${ny}), offset: dx=${dx}, dy=${dy}`);

      let dir = null;
      if (dx === -1 && dy === 0) dir = 'n';
      else if (dx === 1 && dy === 0) dir = 's';
      else if (dx === 0 && dy === -1) dir = 'w';
      else if (dx === 0 && dy === 1) dir = 'e';
      else if (dx === -1 && dy === -1) dir = 'nw';
      else if (dx === -1 && dy === 1) dir = 'ne';
      else if (dx === 1 && dy === -1) dir = 'sw';
      else if (dx === 1 && dy === 1) dir = 'se';

      if (dir) {{
        lastMoveAttemptTime = Date.now();
        const success = triggerMoveDir(dir);
        if (success) {{
          pathStepIdx++;
          totalStepsTaken++;
          updateHUDLog(`👟 Moving ${dir.toUpperCase()} -> (${nx}, ${ny})`);
        }} else {{
          updateHUDLog(`⚠️ Failed to execute move ${dir.toUpperCase()}`);
        }}
      }} else {{
        // Character is already standing on this tile
        console.log('[DelugeAI] Character already at next tile, advancing step.');
        pathStepIdx++;
      }}
      updateHUD();
    }}

    roamTimer = setTimeout(stepRoam, CONFIG.stepIntervalMs);
  }}

  function startRoaming() {{
    if (isRoaming) return;
    isRoaming = true;
    currentPath = [];
    pathStepIdx = 0;
    lastMoveAttemptTime = 0;
    updateHUD();
    console.log('[DelugeAI] === Autonomous Roaming Started ===');
    updateHUDLog('▶ Roaming started.');
    stepRoam();
  }}

  function stopRoaming() {{
    if (!isRoaming) return;
    isRoaming = false;
    if (roamTimer) {{
      clearTimeout(roamTimer);
      roamTimer = null;
    }}
    updateHUD();
    console.log('[DelugeAI] === Autonomous Roaming Paused ===');
    updateHUDLog('⏸ Roaming paused.');
  }}

  // --- 7. HUD ---
  function createHUD() {{
    if (document.getElementById('deluge-ai-hud')) return;

    const hud = document.createElement('div');
    hud.id = 'deluge-ai-hud';
    hud.style.cssText = `
      position: fixed;
      top: 15px;
      right: 15px;
      z-index: 999999;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(8px);
      border: 1px solid #38bdf8;
      border-radius: 10px;
      padding: 12px 16px;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
      min-width: 260px;
      max-width: 330px;
    `;

    hud.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #334155; padding-bottom:6px;">
        <span style="font-weight:700; color:#38bdf8; font-size:13px;">🤖 DelugeRPG Path Planner</span>
        <span id="ai-status-badge" style="background:#22c55e; color:#052e16; padding:2px 6px; border-radius:4px; font-weight:600; font-size:10px;">READY</span>
      </div>

      <div style="margin-bottom:8px; line-height:1.6;">
        <div><b>Target:</b> <span id="ai-target" style="color:#fbbf24;">Waiting...</span></div>
        <div><b>Path Progress:</b> <span id="ai-progress">0 / 0</span></div>
        <div><b>Player Pos:</b> <span id="ai-pos" style="color:#38bdf8;">--</span></div>
        <div><b>Map Coverage:</b> <span id="ai-coverage" style="color:#4ade80;">0.0%</span> (0/532)</div>
        <div><b>Encounters:</b> <span id="ai-encounters" style="color:#f43f5e; font-weight:700;">0</span></div>
        <div><b>Model Source:</b> <span id="ai-model-source" style="color:#94a3b8;">Checking DB...</span></div>
      </div>

      <div style="display:flex; gap:6px; margin-top:8px;">
        <button id="btn-toggle-roam" style="flex:1; background:#0284c7; color:#fff; border:none; padding:7px 10px; border-radius:6px; font-weight:600; cursor:pointer;">▶ Start Roam</button>
        <button id="btn-update-weights" style="background:#334155; color:#cbd5e1; border:1px solid #475569; padding:7px 10px; border-radius:6px; font-weight:600; cursor:pointer;">📂 Update Weights</button>
      </div>

      <input type="file" id="ai-file-input" accept=".json" style="display:none;" />
      <div id="ai-log" style="margin-top:8px; font-size:11px; color:#cbd5e1; background:rgba(0,0,0,0.3); padding:4px 6px; border-radius:4px; max-height:48px; overflow-y:auto; border-left:2px solid #38bdf8;">Ready to explore Overworld 1.</div>
    `;

    document.body.appendChild(hud);

    const toggleBtn = document.getElementById('btn-toggle-roam');
    toggleBtn.addEventListener('click', () => {{
      if (isRoaming) {{
        stopRoaming();
        toggleBtn.textContent = '▶ Start Roam';
        toggleBtn.style.background = '#0284c7';
      }} else {{
        startRoaming();
        toggleBtn.textContent = '⏸ Pause Roam';
        toggleBtn.style.background = '#dc2626';
      }}
    }});

    const updateBtn = document.getElementById('btn-update-weights');
    const fileInput = document.getElementById('ai-file-input');
    updateBtn.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', async (e) => {{
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (evt) => {{
        try {{
          const parsed = JSON.parse(evt.target.result);
          if (parsed.layers && parsed.layers.length === 4) {{
            await saveWeightsToDB(parsed);
            activeWeights = parsed;
            updateHUDLog('✅ Weights loaded & saved into IndexedDB permanently!');
            updateHUD();
          }} else {{
            alert('Invalid weights JSON: Missing expected layer matrices.');
          }}
        }} catch (err) {{
          alert('Failed to parse weights JSON: ' + err.message);
        }}
      }};
      reader.readAsText(file);
    }});
  }}

  function updateHUD() {{
    const targetElem = document.getElementById('ai-target');
    const progElem = document.getElementById('ai-progress');
    const posElem = document.getElementById('ai-pos');
    const covElem = document.getElementById('ai-coverage');
    const encElem = document.getElementById('ai-encounters');
    const srcElem = document.getElementById('ai-model-source');
    const statusBadge = document.getElementById('ai-status-badge');

    if (targetElem && currentWaypoint) targetElem.textContent = currentWaypoint.name;
    if (progElem && currentPath) progElem.textContent = pathStepIdx + ' / ' + currentPath.length + ' steps';
    if (posElem) {{
      const p = getPlayerPos();
      posElem.textContent = `(${p.cx}, ${p.cy})`;
    }}
    if (covElem) {{
      const pct = (visitedTiles.size / 532.0 * 100.0).toFixed(1);
      covElem.textContent = pct + '% (' + visitedTiles.size + '/532)';
    }}
    if (encElem) encElem.textContent = totalEncounters;
    if (srcElem) srcElem.textContent = activeWeights ? 'IndexedDB (Active)' : 'Default Heuristic';
    if (statusBadge) {{
      statusBadge.textContent = isRoaming ? 'ROAMING' : 'READY';
      statusBadge.style.background = isRoaming ? '#3b82f6' : '#22c55e';
    }}
  }}

  function updateHUDLog(msg) {{
    const logElem = document.getElementById('ai-log');
    if (logElem) logElem.textContent = msg;
  }}

  // --- INIT ---
  async function init() {{
    console.log('[DelugeAI] Initializing DelugeRPG Path Planner...');
    initWalkgrid();
    createHUD();

    const saved = await loadWeightsFromDB();
    if (saved && saved.layers) {{
      activeWeights = saved;
      updateHUDLog('✅ Loaded weights from browser IndexedDB.');
      console.log('[DelugeAI] Loaded model weights from IndexedDB:', saved.model_type || 'Custom');
    }} else {{
      updateHUDLog('ℹ️ No weights in IndexedDB yet. Ready.');
      console.log('[DelugeAI] No weights in IndexedDB yet. Ready for heuristic or upload.');
    }}
    updateHUD();
  }}

  window.addEventListener('load', () => setTimeout(init, 500));
}})();
"""

    out_path = "deluge_ai_roam.user.js"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    print(f"Generated diagnostic {out_path} ({os.path.getsize(out_path)} bytes)")

if __name__ == "__main__":
    generate_diagnostic_userscript()
