# Global DQN V3 Browser Demo

This demo runs the trained `global_49map_dqn_v3_best.pt` checkpoint entirely inside OrangeMonkey. It does not use a Python inference server.

## Generate weights

From the repository root:

```powershell
python scripts/export_global_v3_browser_weights.py --checkpoint models/global_49map_dqn_v3_best.pt --output data/processed/global_49map_v3_browser_weights.json
```

The exporter:

- validates the 190-input / 11-output architecture
- exports the Dueling DQN policy tensors
- embeds the 49 map walkgrids and transition registry
- compares deterministic Python and JavaScript test-vector outputs

The expected output is [global_49map_v3_browser_weights.json](/c:/Users/dugge/OneDrive/Documents/Projects/DELUGERPG/data/processed/global_49map_v3_browser_weights.json).

## Install OrangeMonkey

1. Install OrangeMonkey in your browser.
2. Open the OrangeMonkey dashboard.
3. Create a new userscript.
4. Paste [deluge_global_ai_v3.user.js](/c:/Users/dugge/OneDrive/Documents/Projects/DELUGERPG/deluge_global_ai_v3.user.js).
5. Save and enable the userscript.

The script matches all DelugeRPG pages on both supported domains.

## Import and configure

1. Open a DelugeRPG map page.
2. Open the Global DQN V3 HUD.
3. Select **Import Weights**.
4. Choose `global_49map_v3_browser_weights.json`.
5. Wait for the status to show `Loaded episode 4400`.
6. Select a target map and target sector.

Weights are stored under IndexedDB database `DelugeAI_DB`, object store `weights`, key `global_49map_dqn_v3`. They reload automatically.

## Run

The default mode is supervised.

- **One Step** executes one deterministic inference decision.
- **Start** continuously runs inferred decisions at the configured delay.
- **Pause** preserves the current session.
- **Resume** continues the session.
- **Stop** cancels timers and pending movement.
- **Reset Session** clears visited maps and action history.

Begin with same-map navigation. Visible wild Pokémon no longer pause the demo; the HUD counts a newly visible encounter. The trained model mask is retained for observations, but execution additionally excludes unverified transitions and unsupported dungeon actions. If no executable action remains, the script stops without moving.

## Troubleshooting

- **Import failed / wrong checkpoint:** regenerate weights from `models/global_49map_dqn_v3_best.pt`.
- **Planner graph missing / action mask unavailable:** re-import the newly generated `global_49map_v3_browser_weights.json`; the exact action mask requires the exported planner graph.
- **Player position UNKNOWN:** ensure `#usersprite` exists. Missing or unparseable position data always stops execution.
- **Current map UNKNOWN:** open a `/map/<mapname>` page.
- **Game is processing a move:** the script waits and retries after a short delay. A visible CAPTCHA/Cloudflare challenge still stops navigation; do not try to bypass it.
- **Encounter or battle:** leave the page state and then manually resume only after it is safe.
- **No verified transition:** cross-map and dungeon execution is disabled until registry transitions are verified.
- **No safe executable action:** choose a reachable same-map target for the demo. No movement is issued when only unverified transitions remain.
- **Movement confirmation timed out:** stop and inspect the game manually; the script never retries repeatedly by default.
