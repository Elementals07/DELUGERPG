/**
 * DelugeRPG Complete Walkgrid Scraper (Browser Console Script)
 * Run this in your browser DevTools Console (F12) while logged into DelugeRPG.
 * 
 * It queries all 49 DelugeRPG maps, extracts window.mapWalkgrid from each,
 * and downloads a single 'delugerpg_all_walkgrids.json' file containing every map's grid!
 */
(async function() {
  const MAPS = [
    // 25 Overworld maps
    ...Array.from({length: 25}, (_, i) => `overworld${i+1}`),
    // Special cave & dungeon maps
    'pkmnmansion1', 'pkmnmansion2', 'pkmnmansion3', 'pkmnmansion4',
    'pkmntower1', 'pkmntower2', 'pkmntower3',
    'powerplant1', 'powerplant2', 'powerplant3',
    'rockcave1', 'rockcave2', 'rockcave3', 'rockcave4',
    'snowcave1', 'snowcave2', 'snowcave3', 'snowcave4',
    'unownruins1', 'unownruins2',
    'volcano1', 'volcano2', 'volcano3', 'volcano4'
  ];

  console.log(`%c[DelugeRPG] Starting Walkgrid Scraper for ${MAPS.length} maps...`, 'color: #00bcd4; font-weight: bold;');
  const results = {};
  let successCount = 0;

  for (let i = 0; i < MAPS.length; i++) {
    const mapName = MAPS[i];
    console.log(`[${i+1}/${MAPS.length}] Fetching grid for ${mapName}...`);
    try {
      const resp = await fetch(`/map/${mapName}`, { credentials: 'include' });
      if (!resp.ok) {
        console.warn(`Failed to fetch ${mapName}: HTTP ${resp.status}`);
        continue;
      }
      const html = await resp.text();
      const match = html.match(/mapWalkgrid\s*=\s*["']([^"']+)["']/);
      if (match && match[1].length > 100) {
        results[mapName] = match[1];
        successCount++;
        console.log(`%c  ✔ ${mapName}: extracted walkgrid (${match[1].length} chars)`, 'color: #4caf50;');
      } else {
        console.warn(`  ✖ ${mapName}: mapWalkgrid pattern not found in HTML response.`);
      }
    } catch (e) {
      console.error(`  ✖ Error fetching ${mapName}:`, e);
    }
    // Polite 300ms delay between fetches to respect server limits
    await new Promise(r => setTimeout(r, 300));
  }

  console.log(`%c[DelugeRPG] Scrape complete! Captured ${successCount}/${MAPS.length} map walkgrids.`, 'color: #00bcd4; font-weight: bold;');

  // Download results as JSON file
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'delugerpg_all_walkgrids.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  console.log('%c[DelugeRPG] delugerpg_all_walkgrids.json downloaded!', 'color: #4caf50; font-weight: bold;');
})();
