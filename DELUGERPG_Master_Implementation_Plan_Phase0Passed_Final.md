# DelugeRPG Roaming AI — Master Phased Implementation Plan (Authoritative Updated Version — Phase 0 Passed)

**Purpose:** Turn the current DelugeRPG project into a reliable 49-map roaming simulator, then train an agent that explores naturally and eventually behaves more like a human. Work offline in the simulator. This plan is deliberately split into small, gated phases so Antigravity does not attempt a risky full rewrite in one task.

**Authority:** This file is the updated authoritative copy after the Phase 0 audit. It supersedes the earlier `DELUGERPG_Antigravity_Phased_Implementation_Plan.md`; use this filename when opening the plan in Antigravity/OpenCode.


## Start a new Antigravity or OpenCode chat — Phase 0 is complete; start Phase 1 only

Make this plan available in the project workspace. Phase 0 has been reported PASS. Confirm its three audit artifacts exist, inspect the current working tree, and use the measured results recorded below. Do not repeat Phase 0 unless the artifacts are missing, stale, or contradicted by current source.

```text
You are continuing an existing DelugeRPG AI roaming project. Read the complete `DELUGERPG_Master_Implementation_Plan_Phase0Passed.md`, especially the Phase 0 completion record and Phase 1 instructions.

Phase 0 has been reported PASS. First verify that these artifacts exist and are readable:
- scripts/audit_navigation_baseline.py
- docs/ROAMING_BASELINE_AUDIT.md
- logs/phase0_audit.json

Do not redo Phase 0 or start any later phase. Execute PHASE 1 ONLY.

Current audit findings that Phase 1 must address:
1. 78 overworld seam edges were flagged axis-mismatched under the documented x=row/y=column convention. Confirm the actual game coordinate convention from captured DelugeRPG source before changing any coordinates.
2. The graph reports differ: WorldGraph has 49 nodes/112 edges/8 SCCs; GlobalWorldGraph has 49 nodes/126 edges/one SCC. Preserve both facts and determine why their transition sets differ. Neither proves physical coordinate-level reachability.
3. There are 1,646 portal records. Audit every record and preserve portal identity.
4. 34 dungeon-floor edges lack portal coordinates.
5. Five default dungeon-floor landing coordinates at (16,16) are invalid, and four dungeon entrance edges have invalid coordinates. Do not invent stair/landing positions.
6. Pokémon Mansion and Volcano entrances from Overworld 21 collide on action 9. They must become distinct physical transition IDs.
7. Remove any silent fallback to the first walkable tile.

Phase 1 goal: create one canonical transition registry, confirm coordinate semantics from game-source evidence, fix only evidenced geometry, uniquely represent every portal, and validate all known transitions. Mark missing evidence as UNVERIFIED. Do not modify rewards, RL model architecture, training configuration, or start training.

Before editing:
- Inspect git status/working-tree changes and preserve user changes.
- Read the Phase 0 audit report and machine-readable JSON.
- Identify the captured game source used to establish coordinate/portal trigger semantics.
- Make a backup/versioned output before changing generated transition data.

At completion:
- Run the transition validator and focused tests plus the full existing test suite.
- Report counts of VERIFIED, INVALID, and UNVERIFIED transitions, broken down by overworld seams, dungeon entrances and dungeon-floor transitions.
- Show exactly which coordinates changed and the evidence supporting each change.
- Confirm the two Overworld 21 entrances are independently selectable.
- Confirm no invalid landing silently falls back to an arbitrary tile.
- List changed files and exact test outputs.
- Mark every Phase 1 acceptance criterion PASS/FAIL/BLOCKED.
- Stop. Do not begin Phase 2 without my explicit approval.

If source evidence cannot establish a coordinate or transition trigger, do not guess. Leave it UNVERIFIED and stop at the Phase 1 gate with the missing evidence clearly described.
```




## Phase 0 completion record — accepted baseline (2026-11-24)

**Status: PASS with explicitly unavailable historical/physical metrics.** This record is based on the Phase 0 report supplied by Antigravity. Before Phase 1 edits, confirm the three audit artifacts exist in the current workspace and that the repository has not changed since the audit:
- `scripts/audit_navigation_baseline.py`
- `docs/ROAMING_BASELINE_AUDIT.md`
- `logs/phase0_audit.json`

### Measured results

| Area | Phase 0 result |
|---|---|
| Maps | 49 grids decoded: 25 overworld + 24 dungeon; each 33×33 / 2,178 bytes |
| Walkable tiles | 34,117 |
| Water tiles | 9,604 |
| `WorldGraph` | 49 nodes, 112 edges, 8 strongly connected components |
| `GlobalWorldGraph` | 49 nodes, 126 edges, one strongly connected component; topological only |
| Global graph diameter / mean hops | 14 / 5.82; topological only |
| Legacy 20-macro-step feasibility | 0% of map-hop targets reported infeasible under the macro semantics; this says nothing about future tile-level route cost |
| Portal audit | 1,646 portal records |
| Overworld seams | 78; 0 match the documented `x=row, y=column` boundary convention; all 78 flagged axis-mismatched pending confirmation against actual captured game source |
| Dungeon-floor edges | 34 lack portal coordinates |
| Default dungeon landings | 5 invalid `(16,16)` defaults reported: `pkmnmansion2→pkmnmansion1`, `powerplant2→powerplant3`, `volcano2→volcano1`, `volcano2→volcano3`, `volcano4→volcano3` |
| Dungeon entrances | 4 edges have invalid coordinates; `pkmnmansion1` and `volcano1` both have non-walkable `(16,16)` landing defaults |
| Overworld 21 ambiguity | Mansion and Volcano both use action 9; handler always selects Pokémon Mansion |
| Environment schemas | `MapEnv`: 8 actions / actual 102 features; `PathPlannerEnv`: 16 actions / 67 features; `Global49MapEnv`: 11 actions / 204 features |
| Global macro semantics | Actions 0–4 execute a complete BFS route to a sector waypoint in one macro-step; actions 5–10 are transition macros |
| Recorder | 8,733 events; 53 map-change events; 0 with coordinates; 0 walkgrid `g` events; parser fabricated `(0,0)` for 50 exits |
| Model/log provenance | Current metadata claims 8,000 episodes; log has 8,000 rows; max reward 583.8; max maps visited 15; checkpoint schema 204→11 |
| Historical screenshot linkage | NOT AVAILABLE: included files cannot prove the checkpoint/log is the exact 6,500-episode screenshot run |
| Tests | `python -m pytest -q`: 41 passed, 1 warning |
| Reward accounting fidelity | Reconciled against real environment for 120 steps; max absolute error `3.55e-15`; 0 mismatches |

### Measured reward-hacking evidence

The source-verified reward components are:
- Step: `−0.1`
- Newly visited tile: `+0.25`
- Water tile: `+0.8` on every traversal, including revisits
- Blocked local path: `−1.0`
- Recent map: `−12`
- Fresh map: `+8`
- First map visit: `+20`
- Map-graph distance progress: `+15`; regression: `−5`
- Target-map arrival: `+80`
- No tall-grass reward was found in the 49-map trainer source inspected by Phase 0; it must not be claimed unless another current code path proves it.

Controlled fixed-seed comparison:
| Target distance bucket (map hops) | Deterministic route policy success | Available greedy checkpoint success |
|---|---:|---:|
| Near (1–3) | 95.0% | 22.5% |
| Medium (4–7) | 97.5% | 2.5% |
| Far (8–14) | 80.0% | 0.0% |

A repeatable water-farming policy on `rockcave4` earned `+277.75` reward and counted 340 water-tile “encounters” with **0 target successes**. The word “encounters” is a legacy counter label, not proof of actual Pokémon encounters.

Historical 8,000-row trend:
- Success declined from 10.5% in the first half to 5.7% in the second half.
- Mean reward rose approximately 190→311.
- Water-tile “encounters” rose 32→239.
- Mean maps visited fell 6.3→3.9.
- All 7,353 failures were 20-step timeouts; 647 successes terminated in 1–20 steps.

### Limitations that remain open

- **Physical route cost: NOT AVAILABLE.** Do not substitute map hops for tile/portal route cost. Phase 2 must build it.
- **Historical success by distance bucket: NOT AVAILABLE.** The historical CSV lacks start/target map columns. Only the controlled experiment can currently be bucketed.
- The axis convention used for the audit is documented in Python, but must still be confirmed against captured DelugeRPG source before changing seam coordinates.
- The 34 dungeon-floor edges have no recorded portal coordinates. Stair/landing positions need source evidence or must remain unverified.
- The current report is supplied as a Phase 0 result; do not independently claim its artifacts were inspected unless they are present in the current workspace.

### Phase 0 decision

Phase 0 is accepted. Its unavailable metrics are documented limitations, not reasons to rerun Phase 0. They become explicit constraints for Phases 1 and 2. **The next authorized task, when the user approves, is Phase 1 only.**

---

---

## A. Project facts Antigravity must respect

These points were verified from the uploaded project snapshot. Re-check the current workspace before changing anything; the user may have made newer edits.

1. The project has 49 walkgrids: 25 overworld maps and 24 dungeon maps. Each grid is 33×33 and `WalkGrid` decodes 2,178 bytes into tiles with walkability, water and directional bitmasks.
2. `delugerpg/parsers/walkgrid.py` defines the movement axes as `n=(-1,0)`, `s=(1,0)`, `w=(0,-1)`, `e=(0,1)`. `WalkTile.x` is documented as row and `WalkTile.y` as column.
3. Phase 0 measured two different graph views: `WorldGraph` has 49 nodes, 112 directed edges and 8 strongly connected components; `GlobalWorldGraph` has 49 nodes, 126 directed edges and one strongly connected component. Phase 1 must explain why their edge sets differ. The larger graph's topological connectivity is not proof that coordinate-level routes are physically traversable.
4. Phase 0 audited 78 overworld seam edges; 0 matched the documented `x=row, y=column` boundary convention, and all 78 were flagged as axis-mismatched. This is a measured inconsistency under the documented convention, not proof that swapping axes is correct. Phase 1 must confirm the actual game convention from captured DelugeRPG source before changing coordinates.
5. The global navigation data includes seven hardcoded overworld-to-dungeon entrances. The two entrances from `overworld21` (Pokémon Mansion and Volcano) both use action 9 (`dungeon_enter`); the handler always selects Pokémon Mansion, so Volcano cannot be deliberately selected. Phase 0 confirmed this collision.
6. Phase 0 found four dungeon-entrance edges with invalid coordinates, including non-walkable `(16,16)` landings for `pkmnmansion1` and `volcano1`. It also found five invalid `(16,16)` default dungeon-floor landings. `Global49MapEnv.step()` silently substitutes the first walkable tile. Phase 1 must remove this fallback and mark any unverified landing explicitly.
7. `Global49MapEnv` has a 204-feature observation and 11 actions. Five actions select sector waypoints; each call runs BFS over the entire route and immediately moves the simulated player to the waypoint. The remaining six are map-transition macros. This is not tile-by-tile movement.
8. `Global49MapEnv` resets local tile visitation to the single landing tile after every map transition. It does not retain complete per-map tile exploration memory.
9. The global action mask marks all five local sector actions valid, even when a sector waypoint is unreachable. Map-transition masks test whether a direction exists in the graph, not whether the corresponding portal is reachable from the player's current coordinate.
10. The global reward mixes novelty, map discovery, graph-distance progress and target arrival. It also increments `encounters` for every water tile on an abstract BFS route; that is not evidence of a real encounter.
11. `MapEnv` is a better low-level starting point: eight directional tile actions and a 7×7 local window, but its 53-feature observation includes only walkability/visited channels plus four scalar values. Directional affordances and water/portal information are not in its observation. Its visited set resets each episode.
12. `PathPlannerEnv` is a separate Overworld-1-only waypoint environment (16 macro-actions, 67 features). It is not a 49-map roaming solution.
13. `scripts/build_roam_userscript.py` embeds the Overworld 1 grid and fixed waypoints. Its movement trigger can call the native move function and multiple click paths for one intended action; it advances the path index when a command is issued rather than after movement is verified. Its position detector has a hardcoded fallback coordinate. Treat this as legacy diagnostic code, not a valid global integration.
14. Phase 0 counted 8,733 recorder events, including 53 map-change events, none with coordinates and no walkgrid `g` events. `RecorderParser` assigns `(0,0)` to 50 array-form map-change exits. The included session is not a valid tile-by-tile human trajectory dataset. Missing coordinates must remain missing, never be fabricated as zero.
15. Phase 0 reports that current model metadata claims 8,000 episodes, the available training log has 8,000 rows, and the checkpoint schema is 204→11. However, the artifacts cannot be cryptographically or otherwise conclusively linked to the 6,500-episode CMD screenshot. Do not claim that they are the same run without evidence. Re-check current workspace provenance before relying on these figures.
16. In `scripts/train_global_49maps.py`, the actual training entry point constructs `Global49MapEnv(..., max_macro_steps=20)`, even though the class constructor default is 25. The episode ends when this macro-action count is reached or the target map is entered. The CSV does not separately identify timeouts.
17. The legacy target success condition is only `current_map == target_map`. It does not require reaching a target coordinate, exploring a region, or behaving like a human. The start map is random except every fourth episode starts at `overworld1`; the target is a random different map.
18. A legacy local sector action runs a complete `grid.find_path()` route in one macro-action, adds `+0.25` for each newly visited tile on that route, and adds `+0.8` for every water tile traversed, including revisits. Phase 0's source audit found no tall-grass reward in the 49-map trainer. It also measured water farming on `rockcave4`: `+277.75` reward and 340 water-tile counter increments with zero target success.
19. Phase 0 verified the legacy reward components: step `−0.1`; novelty `+0.25` per newly visited tile; water `+0.8` on every water tile traversal including revisits; blocked local path `−1.0`; recent map `−12`; fresh map `+8`; first map visit `+20`; map-graph distance progress `+15` or regression `−5`; target-map arrival `+80`. Graph distance is not verified coordinate/portal route cost.
20. `local_visited_tiles` resets to the landing tile after each map transition. Repeated water traversal can still earn `+0.8`; the `encounters` counter is incremented by water traversal and is not a validated in-game encounter event.
21. Phase 0 now provides controlled evidence for reward hacking: route policy success was 95.0%/97.5%/80.0% across near/medium/far map-hop buckets, while the available greedy checkpoint achieved 22.5%/2.5%/0.0%; repeatable water farming earned `+277.75` with zero target success. These experiments strongly support reward misalignment, but do not prove the policy's internal motive. The historical CSV still lacks start/target maps, so historical success cannot be grouped by distance.
22. Antigravity's reported graph diameter/average map distance must be recomputed against current data. Map-hop distance is topological only; Phase 2's physically verified portal-aware route cost is authoritative. Do not assume increasing the old macro-step limit from 20 to 35 fixes the issue, particularly after moving to tile-level actions.

---

## B. Global rules for every phase

These rules are mandatory. They override any shortcut that would make a metric look better while making the simulator less accurate.

1. **One phase at a time.** Execute only the phase explicitly requested. Do not start, partially implement, or pre-empt the next phase.
2. **Stop at the gate.** After implementation and tests, report PASS or BLOCKED against every acceptance criterion and stop. Wait for the user to authorize the next phase.
3. **Inspect before editing.** Check the current branch, working-tree changes, relevant files, and existing tests. Do not overwrite user changes.
4. **Keep changes scoped.** Do not rewrite unrelated Pokédex, battle, database, embeddings or advisor components.
5. **Preserve old artifacts.** Never overwrite old model weights, logs, maps, session archives or generated scripts. Use versioned filenames for new models and exports.
6. **No fake success.** Do not teleport, silently relocate to the first walkable tile, ignore directional masks, treat a failed move as success, or award success without meeting the real task condition.
7. **No invented map facts.** If an entrance, landing coordinate or movement rule cannot be verified from the captured game source, valid walkgrid data or recorded evidence, mark it `unverified` and report the missing evidence. Do not guess.
8. **Separate topology from physical reachability.** A connected map graph does not prove a player can reach the correct portal or traverse the local route.
9. **Keep offline-first behaviour.** Training and simulation must remain offline. Recorder changes must be passive. Do not send movement commands to the live DelugeRPG website, add automatic live gameplay, or run the legacy movement userscript as a bot.
10. **Validate actions against the true state.** Every legal movement must use the same row/column convention and directional bitmask rules as the actual game implementation.
11. **Reproducible tests.** Use fixed seeds for tests and evaluation scenarios. Do not use long training runs as a substitute for unit tests.
12. **No premature training.** Do not launch 8,000-episode training in early phases. Use small smoke tests only when needed. Full training begins only after the simulator and evaluation gates pass.
13. **Do not tune hyperparameters to hide environment bugs.** Fix transitions, observations, terminal conditions and reward definitions before changing network sizes or epsilon schedules.
14. **Keep schemas explicit.** Version observation/action/model schemas. A model trained for 204 features/11 macro-actions must never be loaded into a model expecting a different input/action layout.
15. **Document the reason for each change.** Add concise comments and update docs when behaviour or schemas change.
16. **Separate objectives and rewards.** Map-to-map navigation, coordinate navigation, exploration, roaming and encounter simulation are different tasks. Do not let tile novelty or water/grass bonuses substitute for target completion in a navigation task.
17. **No magic reward constants or guaranteed performance claims.** Do not blindly apply `+250` target reward, `+25` distance reward, a 35-step horizon or a claimed 90% success target. Derive settings from measured reward ranges, verified route costs, controlled ablations and held-out evaluation.
18. **Use verified route cost for goal progress.** Once Phase 2 exists, do not use map-graph hop distance as the sole progress signal. Use the shortest legal coordinate/portal route from the deterministic planner, with one consistent cost unit.
19. **Prove that reward cannot be farmed.** Every reward change must include component-level logging and regression tests for repeated water traversal, local sector loops, backtracking and ignoring a reachable target.
20. **Treat the legacy 8,000-episode run as a diagnostic baseline, not a training target.** Do not resume or extend it until the replacement environment, reward and evaluation gates pass.

### Required completion report after every phase

Antigravity must output:

- **Phase status:** PASS or BLOCKED.
- **Files changed:** exact paths.
- **What changed:** concise before/after summary.
- **Tests run:** exact commands and actual results.
- **Acceptance criteria:** each criterion PASS/FAIL with evidence.
- **Known limitations:** anything still unverified.
- **Artifacts:** report paths, logs, model files or visual/demo outputs created.
- **Next phase:** name only; do not begin it.

If any acceptance criterion fails, fix it within the current phase if possible. If it cannot be fixed without missing evidence or a design decision, stop and ask the user with a concise blocker report.

---

# C. Phases and individual Antigravity prompts

Run these prompts separately and in order. Attach/open this plan once, then paste only the prompt for the current phase. This keeps each Antigravity task small.

## Phase 0 — Audit, protect current work and create a reproducible baseline (COMPLETED)

**Status:** PASS with documented unavailable metrics. The actual results are recorded in the Phase 0 completion record above and in the project artifacts `docs/ROAMING_BASELINE_AUDIT.md`, `logs/phase0_audit.json`, and `scripts/audit_navigation_baseline.py`. Do not rerun this phase unless those artifacts are missing, stale or contradicted by current code.

**Visible result achieved:** read-only audit, 49-grid inventory, 1,646-record portal audit, environment/reward audit, controlled reward-farming experiments, and 41 passing tests. No existing artifact was modified.

**Why first:** We need an exact baseline and must prevent Antigravity from rewriting working map/battle/knowledge-base features or confusing the 5-episode included checkpoint with the screenshot's 6,500-episode run.

**Inspect:**
- `scripts/train_global_49maps.py`
- `scripts/build_global_navigation.py`
- `delugerpg/models/world_graph.py`
- `delugerpg/parsers/walkgrid.py`
- `delugerpg/simulator/map_env.py`
- `delugerpg/agents/path_planner.py`
- `delugerpg/parsers/recorder.py`
- `scripts/build_roam_userscript.py`
- `tests/` and `docs/`
- map grid JSON, graph JSON, model metadata and available logs.

**Implement:**
1. Add a read-only audit script that checks all 49 map names, base64 decode, byte length, walkable count, coordinates and directional masks.
2. Report graph nodes/edges, strongly connected components and unreachable map pairs, but label graph-only reachability as *topological*, not physically verified.
3. Audit every graph portal's source and destination coordinate, walkability, direction legality and coordinate-axis consistency.
4. Explicitly report the `overworld21` `dungeon_enter` action collision and invalid `(16,16)` dungeon landing coordinates if still present.
5. Report current observation/action dimensions and action semantics for `MapEnv`, `PathPlannerEnv` and `Global49MapEnv`.
6. Report global training settings, success condition, max macro-steps, epsilon schedule, reward components and checkpoint-selection rule.
7. Report recorder event formats and count movement records with valid positions. Missing coordinates must be `null`/unknown, not `(0,0)`.
8. Compare model metadata and available logs. Do not claim the included `episodes: 5` weights represent the screenshot's 6,500-episode run.
9. Run the existing test suite and record existing failures without broadly fixing unrelated components.
10. Audit the exact reward code and produce a reward-component table for every action type: step cost, newly visited tile, water-tile traversal, map novelty, recent-map penalty, map-distance progress/regression and target-map arrival. Verify whether tall grass is actually rewarded; do not copy that claim without source evidence.
11. Add a diagnostic mode/script for fixed start/target episodes that reports each reward component separately. Compare (a) a route-following baseline, (b) repeated local-sector actions, (c) repeat traversal of a water tile where reachable, and (d) the available greedy checkpoint if its matching weights exist.
12. Report map-graph hop distance separately from coordinate/portal route cost. If the physical planner does not exist yet, mark route cost `not available` rather than substituting graph hops.
13. Report the distribution of random reachable start/target route lengths and the proportion that cannot fit within the legacy 20-macro-action limit. Label this as a legacy-environment diagnostic; do not extrapolate it to the future tile-level simulator.
14. Confirm the screenshot's success definition against code and report success by target-distance bucket, not only as one aggregate percentage.

**Acceptance gate:**
- Audit runs from the repository root with one documented command.
- All 49 grids are checked, not just sample maps.
- It emits a concrete portal/transition audit, not only a graph node count.
- It distinguishes verified, invalid and unverified transitions.
- It records the current pytest baseline and model/log provenance.
- No existing model/data/log is overwritten.
- Reward components are reported separately and match the inspected source.
- Controlled tests establish whether local-sector/water reward competes with target completion; unsupported expected-return estimates are marked unverified.
- Graph-hop distance, physical route cost and legacy 20-macro-step feasibility are reported separately.
- Success is grouped by target-distance bucket, and timeout is distinguishable from other failure causes.

**Historical Antigravity prompt — Phase 0 (completed; do not execute again by default):**

> This phase has already been completed. Re-run only if the audit artifacts are missing, stale, or contradicted by the current workspace. Execute Phase 0 only from `DELUGERPG_Master_Implementation_Plan_Phase0Passed.md`. First inspect the workspace/working tree. Add a read-only navigation audit and `docs/ROAMING_BASELINE_AUDIT.md` covering all 49 grids, graph topology, coordinate-level portals, row/column convention, Overworld 21 entrance collision, invalid dungeon landing points, environment observation/action definitions, recorder quality and model/log provenance. Inspect `Global49MapEnv.step()` and quantify each reward component. Run fixed-start/target comparisons between route-following and local-sector/water-tile farming; do not invent expected returns. Verify whether tall grass has a reward in the current code. Compute success by map-hop-distance bucket and report legacy 20-macro-step feasibility separately from physical route cost. Confirm what counts as success and distinguish target failure, timeout, invalid action and no-route. Run existing tests and record exact results. Do not change navigation algorithms/rewards or start training. Preserve current files. Stop at the Phase 0 gate.

---

## Phase 1 — Make map geometry and every transition trustworthy

**Status:** Next phase, pending explicit user approval.

**Visible result:** one canonical, auditable transition registry plus a validation report that distinguishes physically verified transitions from graph-only or unknown connections. No RL changes.

**Main files to inspect (modify only when needed):**
- `delugerpg/models/world_graph.py`
- `delugerpg/parsers/walkgrid.py` only if the audit proves a decoder issue
- `delugerpg/core/types.py` for a transition type if useful
- `scripts/build_global_navigation.py`
- `scripts/train_global_49maps.py` only to remove duplicated transition definitions after a shared registry exists
- `data/processed/` for a new/versioned transition manifest
- focused tests under `tests/`

### Phase 0 findings Phase 1 must resolve

- `WorldGraph`: 49 nodes, 112 edges, 8 strongly connected components.
- `GlobalWorldGraph`: 49 nodes, 126 edges, one strongly connected component.
- 78 overworld seam edges were flagged as axis-mismatched under the documented `x=row, y=column` convention. Zero matched the expected boundary under that convention. Do not assume simply swapping axes is correct.
- The audit covered 1,646 portal records.
- 34 dungeon-floor edges have no portal coordinates.
- Five invalid `(16,16)` default dungeon-floor landings were reported:
  `pkmnmansion2→pkmnmansion1`, `powerplant2→powerplant3`,
  `volcano2→volcano1`, `volcano2→volcano3`, `volcano4→volcano3`.
- Four dungeon-entrance edges have invalid coordinates; `pkmnmansion1` and `volcano1` have non-walkable `(16,16)` landing defaults.
- Pokémon Mansion and Volcano entrances from Overworld 21 both use action 9; the handler selects Pokémon Mansion.

### Implementation steps

1. **Verify Phase 0 artifacts and repository state.** Read `docs/ROAMING_BASELINE_AUDIT.md` and `logs/phase0_audit.json`. Confirm they match the current workspace. Check git status and preserve all user changes. Record audit artifact hashes/timestamps in the Phase 1 report.

2. **Explain the two graph versions.** Produce an edge-by-edge diff of `WorldGraph` (112 edges / 8 SCCs) and `GlobalWorldGraph` (126 edges / 1 SCC). Identify the exact 14-edge difference and explain the source and purpose of each edge. Determine whether edges are missing, derived, duplicated or invalid. Do not silently merge the graphs or treat either graph as proof of physical connectivity.

3. **Prove the actual coordinate convention.** Inspect captured DelugeRPG browser/game JavaScript and trace the code that reads player coordinates, indexes map-grid cells and handles north/south/east/west movement or map-boundary transitions. Confirm whether the game's `x/y` correspond to row/column or column/row. Cite exact source files/functions and create a small test/example mapping a known browser coordinate to a walkgrid cell. Python comments and assumptions are not sufficient evidence.

4. **Audit and correct all 78 overworld seams.** For every seam, check source and destination map, boundary side, exact source/destination coordinate, walkability, directional bit, crossing trigger and reverse crossing separately. Record whether the connection is one-way or bidirectional. Create a corrected candidate manifest with new/versioned output first. Only change coordinates that are supported by game-source evidence and tests. Unresolved seams remain `UNVERIFIED`.

5. **Create one canonical transition registry.** Each physical transition must have a stable unique ID and fields for `source_map`, `source_coord`, `trigger/direction`, `destination_map`, `destination_coord`, `transition_type`, `evidence/source`, and `verification_status`. Keep multiple distinct portals between the same pair of maps as separate records. A map-level graph may be generated from this registry, but it must not replace it.

6. **Resolve graph/action identity problems.** Replace duplicated transition definitions with the canonical registry. The Overworld 21 Pokémon Mansion and Volcano entrances must have separate portal IDs and be independently selectable by physical location. Do not use one generic `dungeon_enter` action that always selects the first matching edge.

7. **Audit all overworld-to-dungeon entrances.** Check all seven hardcoded entrance pairs. Phase 0 found four invalid entrance edges, including non-walkable `(16,16)` landings for `pkmnmansion1` and `volcano1`. Find the real source trigger and destination landing from captured game source or valid observed evidence. Do not use a first-walkable fallback. If evidence is missing, mark the pair `UNVERIFIED`.

8. **Audit dungeon-floor transitions.** Account for all 34 floor edges with missing portal coordinates and the five invalid `(16,16)` defaults reported in Phase 0. Locate actual stairs/ladders/transition tiles from captured source or valid observations. Do not infer a stair position from map center or first walkable tile. Unverified coordinates must remain unknown, not fabricated.

9. **Remove silent relocation.** Remove or replace the affected `(16,16)`/first-walkable fallback so invalid or unverified transitions fail explicitly with a useful diagnostic. Do not silently move the simulated player to another coordinate.

10. **Build exhaustive validation.** Validate all 1,646 Phase 0 portal records and all graph transitions for map existence, coordinate bounds, source/destination walkability, direction/trigger semantics, boundary geometry, duplicate IDs, landing validity and reverse-edge expectations. Generate a report with `VERIFIED`, `INVALID` and `UNVERIFIED` counts separately for overworld seams, overworld-to-dungeon entrances and dungeon-floor transitions. Include record IDs, maps, coordinates, evidence source and failure reason.

11. **Add focused tests.** Cover coordinate-axis interpretation, all four seam directions, directional bitmasks, destination walkability, one-way transitions, parallel portals, duplicate IDs, invalid defaults, missing coordinates, first-walkable fallback removal and independent Overworld 21 entrance selection.

12. **Preserve legacy compatibility.** Do not modify reward logic, DQN architecture, observation/action schema, training settings or model weights in this phase. Keep old transition data available as a versioned baseline until the new registry passes validation.

### Acceptance gate

- The 112-edge/8-SCC versus 126-edge/1-SCC discrepancy is explained by an edge-by-edge diff.
- The actual game coordinate convention is supported by captured-source evidence and a reproducible coordinate mapping test.
- All 78 seam records are either corrected with evidence or explicitly `UNVERIFIED`; none is accepted with a direction/axis mismatch.
- All 1,646 portal records are accounted for and categorized.
- Every `VERIFIED` transition has a legal, walkable source and destination and correct game trigger semantics.
- Both Overworld 21 entrances are uniquely represented and independently selectable.
- All 34 missing-coordinate dungeon-floor edges and five invalid default landings are accounted for; unknown positions remain `UNVERIFIED`.
- No affected transition silently falls back to an arbitrary walkable tile.
- The report does not claim all maps are physically connected unless evidence demonstrates it.
- Focused tests and the full existing test suite pass, or every failure is clearly reported and explained.
- The final report lists changed files, test commands/results, changed coordinates with evidence, and remaining blockers.

**Antigravity prompt — Phase 1:**

> Execute Phase 1 only. First verify the Phase 0 audit artifacts are present and current. Resolve the difference between `WorldGraph` (112 edges / 8 SCCs) and `GlobalWorldGraph` (126 edges / 1 SCC) with an edge-by-edge diff. Use captured DelugeRPG source to prove the coordinate convention before changing any of the 78 seam records flagged axis-mismatched. Build one canonical versioned transition registry with stable unique IDs for every physical portal. Audit all 1,646 portal records, all seven overworld-to-dungeon entrance pairs, the 34 dungeon-floor edges with missing coordinates, and the five invalid default `(16,16)` floor landings. Fix the Overworld 21 Mansion/Volcano ambiguity so both entrances are independently selectable. Remove silent fallback to the first walkable tile. Add exhaustive validation and tests; report VERIFIED/INVALID/UNVERIFIED counts by transition class and cite evidence for every changed coordinate. Do not modify rewards, RL models or training settings. Unknown coordinates stay UNVERIFIED. Stop at the Phase 1 gate.


## Phase 2 — Build deterministic navigation across the full world

**Visible result:** a non-AI planner can route from a valid start coordinate to a valid target coordinate through verified portals, with a readable route trace.

**Main files:**
- New `delugerpg/agents/multi_map_planner.py` (or equivalent)
- `delugerpg/models/world_graph.py`
- `delugerpg/parsers/walkgrid.py`
- new `scripts/test_global_routes.py` / `scripts/benchmark_global_routes.py`
- new tests under `tests/`

**Implement:**
1. Keep `WalkGrid.find_path()` faithful to actual game path rules. Add a separate planner-level endpoint validator so an invalid/non-walkable target cannot be accepted accidentally.
2. Build local pathfinding that returns the exact tile sequence and validates directional masks on every step. Confirm boundary rules match the captured game source.
3. Route globally using exact portal endpoints, not only `nx.shortest_path()` between map names.
4. Among multiple portals for the same map connection, choose one reachable from the current position with the lowest valid path cost.
5. Account for disconnected walkable components within a map. A map can be in the topological graph but a particular portal may be inaccessible from the current tile.
6. Use a portal-state graph or equivalent Dijkstra/A* model: local path segments connect reachable portal endpoints within a map; transition edges connect verified portal pairs across maps. Cache local path/distance calculations when safe.
7. Return a structured route: map sequence, portal IDs, local path per map, expected landing coordinates and total tile/transition cost.
8. Support same-map start-to-target routing and cross-map routing.
9. If no verified route exists, return a meaningful `NoRoute`/unverified reason. Do not teleport or guess another portal.
10. Add a CLI diagnostic that prints a route step-by-step and optionally draws/prints ASCII map segments.

**Acceptance gate:**
- Same-map routes match local BFS legality.
- Routes crossing overworld seams use the correct source edge and destination edge.
- Routes entering/exiting dungeons use the correct distinct portal IDs.
- Each returned local step is legal according to the directional bitmask.
- Route replay reaches the exact requested target coordinate.
- Invalid or unknown portals produce explicit failure, not a fabricated route.
- Benchmark includes fixed start/target pairs across overworld, dungeons and multi-transition journeys.

**Antigravity prompt — Phase 2:**

> Execute Phase 2 only, using the verified transition registry from Phase 1. Implement an offline deterministic coordinate-to-coordinate planner across all verified maps. Use local directional-mask-aware paths and a global portal-state route search; do not rely on map-only shortest paths or choose the first portal arbitrarily. Return structured route legs and exact landing positions. Add route replay tests and a CLI showing map/portal/tile steps. Test same-map, overworld seam, dungeon entrance/exit and multi-map journeys. Unknown transitions must fail explicitly. Do not add RL or change rewards. Stop at the Phase 2 gate.

---

## Phase 3 — Replace the macro simulator with a physically accurate multi-map simulator

**Visible result:** a player advances one legal tile per environment step and crosses maps only through verified transition mechanics. Per-map exploration memory survives map changes.

**Main files:**
- New `delugerpg/simulator/multi_map_env.py`
- `delugerpg/simulator/map_env.py` as reusable reference or refactor target
- `delugerpg/models/world_graph.py`
- `delugerpg/core/types.py`
- tests under `tests/`
- keep `scripts/train_global_49maps.py` as legacy until replacement is validated

**Implement:**
1. Build a new `MultiMapNavigationEnv`; do not silently change old checkpoints' environment schema.
2. Define one low-level movement step per action. Use the eight directions already defined in `WalkGrid`. A single action must not execute a full BFS path.
3. Model overworld seam crossing, dungeon entry and stairs/ladders according to verified game mechanics from Phase 1. If the transition is triggered by stepping off a seam, simulate that exact step; if it requires an interaction, model a valid interaction action. Do not decide by assumption.
4. Every environment step must update exactly one movement or one verified transition. Blocked moves leave the player in place and are counted as collisions.
5. Add a fixed action mask based on current tile directional permissions, bounds, destination walkability and verified transition availability.
6. Maintain persistent `visited_tiles_by_map` for all 49 maps. Do not reset a map's visit history when leaving/re-entering it. Reset all memory only when a new episode begins, unless an explicit continuing-world mode is selected.
7. Track map visit counts, last-visit age, recent positions, recent transitions and failed actions without losing per-map coverage.
8. Build a documented observation schema. At minimum include a local spatial window with walkability, water/terrain, visited state and directional affordances; current map/coordinates; goal/target information; and relevant global exploration memory. Ensure the observation contains information needed to distinguish states requiring different actions.
9. Keep observation values normalized and schema-versioned. Add shape/range validation.
10. Support deterministic seeding and explicit start map/position and target map/position. Reject invalid start/target coordinates.
11. Keep navigation-to-goal and world-exploration as separate environment modes or clearly separate task definitions.
12. Add a transition trace to `info`: before/after map and position, action, legality, collision and transition ID.

**Acceptance gate:**
- One movement action changes position by at most one tile unless a verified map-crossing event occurs.
- The simulator never teleports to an arbitrary tile.
- Every movement is validated against the same directional rules as `WalkGrid`.
- Visited tiles persist independently for all maps during an episode.
- Re-entering a map retains its old exploration memory.
- Observations/action masks match declared shapes and actual legal actions.
- Seeded runs are reproducible.
- A human-readable replay demonstrates a multi-map route.

**Antigravity prompt — Phase 3:**

> Execute Phase 3 only. Create a new versioned tile-level multi-map simulator based on the verified registry and deterministic planner. Do not keep the 11 macro-actions that instantly traverse BFS paths. Use one legal directional tile action per step and transition only with verified game mechanics. Add a correct action mask, versioned observation including local directional affordances and persistent per-map visited memory, seeded reset, explicit start/target validation and detailed transition traces. Keep legacy environments/checkpoints intact. Add tests for movement, collisions, map crossing, map re-entry memory and deterministic replay. Do not train the agent. Stop at the Phase 3 gate.

---

## Phase 4 — Separate navigation from exploration, fix reward hacking and build evaluation

**Visible result:** a benchmark that exposes target progress and reward farming separately, plus reward definitions that cannot profitably replace the assigned task with repetitive local activity.

**Why this phase is expanded:** Antigravity's explanation is consistent with the legacy code: local sector actions can collect per-tile novelty and repeatable water-tile rewards while target completion is delayed or missed. The exact claimed expected returns (such as 340 points from farming) are not proven until Phase 0 runs component-level controlled tests. Use measurements, not assumptions.

**Main files:**
- New `delugerpg/evaluation/` module or equivalent
- `scripts/evaluate_global_roamer.py`
- fixed scenario fixtures under `tests/fixtures/` or `data/processed/`
- `docs/ROAMING_METRICS.md`
- reward/task code in the new Phase 3 environment; keep legacy reward implementation available for comparison

**Implement:**
1. Define separate tasks and success conditions:
   - **Map-to-map navigation:** enter the specified target map using physically valid portals. This matches the legacy trainer's success definition.
   - **Coordinate-to-coordinate navigation:** reach the exact target tile.
   - **Exploration:** discover a defined proportion/set of reachable walkable tiles or maps.
   - **Roaming:** explore reachable frontiers while controlling loops and revisits.
   - **Encounter simulation:** only if separately implemented with an explicit encounter event/probability; tile traversal alone is not an encounter.
2. Never mix rewards across tasks accidentally. In map/coordinate navigation mode, disable positive tile-novelty, water and grass rewards. Navigation is rewarded for reaching the assigned target efficiently and penalized for time, collisions and invalid actions. Exploration rewards belong only to exploration/roaming modes.
3. In exploration mode, award novelty only for genuinely new tiles/frontiers, at most once per tile per episode or via a documented diminishing-return scheme. Repeated crossing of a previously visited water tile must not produce repeatable positive reward. Keep encounter reward separate and emit it only from a modeled encounter event.
4. Instrument every reward component in `info` and episode CSV/JSON: base step cost, collision/invalid-action cost, novelty/frontier reward, water/encounter reward (if applicable), distance shaping, map transition reward and terminal success/failure reward. Log totals and counts per episode, not only summed reward.
5. For navigation progress, use the Phase 2 verified planner's minimum remaining route cost from current map/coordinate to assigned target. It must include legal local tile movement and exact portal transitions. Do not use `nx.shortest_path_length()` over map names as authoritative progress.
6. If using potential-based reward shaping (PBRS), implement the mathematically correct form:
   - `Phi(s, goal) = -alpha * D(s, goal)`, where `D` is verified remaining route cost in the same primitive-action units used by the environment.
   - `F(s, s', goal) = gamma * Phi(s', goal) - Phi(s, goal)`, using the same `gamma` as the learner.
   - Define terminal potential consistently and make termination/truncation handling agree with the learner's bootstrap logic.
   - If actions are variable-duration options, use duration-aware discounting (`gamma ** duration`) and aggregate intermediate rewards correctly. Do not apply the one-step formula to multi-step macros without accounting for duration.
   - Do not call `alpha * (D_current - D_next)` PBRS unless equivalence for the chosen discount and terminal semantics has been demonstrated. If correct PBRS is not implemented, use a transparent alternative and prove it with ablations.
7. Do not blindly set target reward to `+250`, distance reward to `+25`, or any magic number. First remove local farming bonuses from navigation mode; then tune `alpha`, step cost and terminal reward using reward-component ranges, controlled ablations and fixed validation scenarios. Scales must make task completion preferable to looping/timing out without producing unstable Q-value magnitudes.
8. Use a small per-primitive-step time cost where appropriate so unnecessarily long routes and loops are costly. Test its scale; do not add a large arbitrary repeated-position penalty that also discourages valid backtracking and recovery.
9. Add fixed anti-farming tests: (a) shortest verified route to target, (b) repeated water/grass traversal, (c) repeated local-sector selection, (d) bouncing between two maps, (e) wandering without target progress and (f) a valid detour followed by recovery. Report reward components and task outcome. A local farming policy must not outperform successful task completion in navigation mode.
10. Build held-out scenarios across near/medium/far difficulty, multiple portal choices, dungeon routes, narrow corridors, disconnected local components and different starting maps. Exclude truly unreachable goals or label them `no_route` rather than counting them as normal failures.
11. Compute start/goal difficulty using verified route cost. Keep map-hop distance as a separate topological diagnostic. Report success by route-cost bucket and map class.
12. Evaluate random legal actions and the Phase 2 deterministic planner before RL. Record task success, target error, route length/optimal length, collisions, invalid actions, transitions, coverage, revisit/loop rate, timeout/no-route counts and recovery success independently of reward.
13. Use repeated seeds and save raw per-episode CSV/JSON. Report sample size and variation; do not promise 90%+ success before measurement.
14. Select checkpoints using validation task success and path/loop/collision quality, not maximum training reward alone.

**Acceptance gate:**
- Map-to-map navigation, coordinate navigation, exploration and roaming have separate task definitions and metrics.
- Navigation mode has no positive tile-novelty/water/grass farming reward.
- Repeated water/grass traversal and local-sector loops cannot accumulate repeatable positive reward in navigation mode.
- Reward-component totals reconcile with total episode reward.
- If PBRS is used, tests verify formula, gamma, route-cost units and terminal/truncation handling; otherwise the alternative is documented and tested.
- Random and deterministic baselines are saved on fixed held-out scenarios.
- Success/failure are reported by verified route-distance bucket; timeout and no-route are distinguishable.
- No claim of 90%+ is made unless held-out measurements support it.

**Antigravity prompt — Phase 4:**

> Execute Phase 4 only. Use Phase 0's measured reward breakdown and the Phase 2 planner's verified route costs. Separate map-to-map navigation, coordinate navigation, exploration and roaming. In navigation mode, remove positive tile-novelty/water/grass rewards so local farming cannot replace target completion. Keep encounter simulation separate from tile traversal. Instrument every reward component. If using PBRS, implement `Phi=-alpha*verified_route_cost` and `F=gamma*Phi(next)-Phi(current)` with correct terminal/truncation and action-duration handling; otherwise use a simpler transparent reward with explicit loop/farming ablations. Do not blindly use +250, +25 or a 35-step cap. Build held-out near/medium/far scenarios using verified route cost, evaluate random and deterministic baselines, and log success/timeout/no-route/loops/collisions separately from reward. Add regression tests proving water/grass repeats, sector loops and map bouncing do not beat task completion. Do not start full RL training. Stop at the Phase 4 gate.

---

## Phase 5 — Train a goal-conditioned navigation/exploration agent using route-cost curriculum

**Visible result:** versioned checkpoints plus validation curves showing the policy learns to complete increasingly difficult goals instead of maximizing local reward.

**Main files:**
- New `scripts/train_roamer.py`
- Existing DQN code may be reused/refactored only after checking compatibility
- New model config/schema manifest
- `logs/` and `models/` with versioned names

**Design rule:** Keep the deterministic planner responsible for safe physical route execution. RL should learn which reachable frontier/destination to choose, or learn goal-conditioned local decisions only if the Phase 3 simulator and tests justify that design. RL must not bypass verified planner/portal rules.

**Implement:**
1. Keep navigation and exploration training separate. A navigation episode has an explicit target and no exploration/encounter farming bonus. An exploration episode has explicit coverage/frontier objectives and does not pretend that visiting a random map is point-to-point success.
2. Use Phase 2 exact route cost to create target difficulty buckets. Do not use raw map-hop count as the only curriculum measure. Suggested progression: (a) same-map/short local routes, (b) one verified map transition, (c) short regional routes across a few transitions, (d) medium multi-map journeys, (e) long routes across all verified maps. Include dungeons and all map classes progressively.
3. Promote to the next curriculum bucket only after repeated fixed validation runs meet a configured success/quality threshold. Record threshold and sample size. Do not advance merely because an episode counter reaches 2,000 or 5,000. If performance regresses, retain the prior curriculum mix and diagnose it.
4. Sample start/goal pairs from all reachable maps and route-cost buckets. Balance start maps, target maps, dungeon/overworld mix, portal choices and route direction. Avoid overrepresenting easy maps or a single start location.
5. Set the episode horizon from verified optimal route length and measured detour allowance, for example `H = ceil(route_cost * horizon_factor + horizon_slack)`. Calibrate the factor/slack against deterministic and learned-policy rollouts. Ensure the deterministic baseline can complete each benchmark route within the assigned horizon. If the remaining budget affects decisions, expose it in the observation or use a fixed horizon per curriculum bucket. Do not blindly raise legacy 20 macro-steps to 35: old steps were macro-actions; the replacement simulator uses primitive movement steps. If using variable-duration options, account for their duration in horizon and discounting.
6. Reuse DQN/PPO only if action masking, termination/truncation, target conditioning, reward shaping and model I/O match the new schema. The old 204-feature/11-macro-action checkpoint is not compatible by assumption.
7. Apply action masks in random exploration, greedy selection and target-Q calculation. Handle all-invalid terminal states safely; do not use an arbitrary center-action fallback as a legal action.
8. Use fixed held-out validation and separate final test sets. Evaluate greedily with epsilon=0. Training-time exploratory success is not evaluation success.
9. Log per episode: task mode, start/goal, verified optimal route cost, horizon, success, timeout, no-route, reward components, total reward, collision/invalid actions, route efficiency, loop/revisit rate, coverage, action distribution, loss, epsilon and duration.
10. Schedule epsilon/exploration based on training progress and validation evidence, not an arbitrary episode count alone. Keep training exploration distinct from greedy evaluation. Do not assume slower epsilon decay alone fixes reward hacking.
11. Select checkpoints primarily by validation task success, then route efficiency, collision rate and loop rate. Never select solely by shaped reward or map count. Keep best and latest checkpoints separately.
12. Save versioned metadata: environment version, map/portal registry version, observation/action schema, task mode, reward config, gamma, epsilon schedule, curriculum stage, seeds, evaluation results and code revision.
13. Start with a small smoke run and bounded experiment. Run ablations: no shaping vs PBRS, no exploration bonus vs separate exploration mode, and multiple reward scales/horizon settings. Full long training is allowed only after reward-hacking regression tests and stable validation curves pass.
14. Compare the trained policy against random legal actions and deterministic planning on identical held-out scenarios. RL is better only if it measurably improves its intended objective, not merely because reward is higher.

**Acceptance gate:**
- Navigation and exploration use separate training objectives.
- Curriculum stages use verified route-cost buckets and are promoted by measured validation, not fixed episode counts alone.
- Horizons are feasible for the deterministic baseline and based on primitive route cost, not copied macro-step counts.
- Local farming/loop regression tests pass.
- Greedy held-out target success improves over random baseline and is compared fairly with deterministic planning.
- Timeout, no-route, loop, collision and target-distance results are visible in logs.
- Checkpoint selection is validation-first; old checkpoints remain untouched.
- 90%+ is not claimed until a sufficiently large held-out evaluation demonstrates it.

**Antigravity prompt — Phase 5:**

> Execute Phase 5 only. Build a versioned training pipeline on the Phase 3/4 environment. Keep navigation and exploration objectives separate. Use exact Phase 2 route cost to sample near/medium/far goals and promote curriculum stages only after repeated fixed validation runs pass a configured threshold. Set horizons from primitive optimal route length plus measured slack; do not blindly change 20 macro-steps to 35. Keep planner-enforced movement/portal safety. Apply correct masks and termination/truncation handling. Log reward components, route-cost bucket, success, timeout, no-route, loops, collisions and efficiency. Evaluate greedily with epsilon=0 and compare random and deterministic baselines. Run small smoke tests and reward/horizon ablations before long training. Save versioned checkpoints selected by validation success/quality, not shaped reward. Do not begin Phase 6. Stop at the Phase 5 gate.

---

## Phase 6 — Collect valid human movement demonstrations (passive only)

**Visible result:** a versioned trajectory dataset whose movement records have trustworthy before/after positions and timings.

**Main files:**
- `delugerpg/parsers/recorder.py`
- a passive recorder userscript if the real recorder source is absent from the repository
- new `delugerpg/parsers/trajectory.py` or equivalent
- tests under `tests/`
- `data/raw/` or a documented dataset directory, with private/session values removed

**Implement:**
1. Correct `RecorderParser`: array-form map-change events with no coordinates must store `x/y=None` or an explicit `coordinates_missing` flag, never `(0,0)`.
2. Keep map-change events distinct from tile-movement events. A map page change alone is not evidence of a tile movement.
3. If current recorder code cannot capture tile movements, create/modify a **passive-only** recorder that observes human-initiated movement events and player sprite/map state changes. It must not issue clicks, key presses, AJAX requests or movement commands.
4. Capture timestamp, map ID, position before/after, user-initiated direction/input where observable, movement success/failure, collision, transition ID and relevant map changes.
5. Capture the player coordinate from a validated game DOM/source formula and verify it against observed state. If position cannot be read, mark it missing rather than guessing.
6. Record timing between movements; use monotonic elapsed time and preserve original event timestamps.
7. Exclude cookies, auth tokens, session IDs, passwords and unnecessary account data from exported datasets.
8. Add a trajectory validator: valid map names, valid coordinates, adjacent legal movement within a map, valid portal crossing between maps, monotonic timestamps, and no fabricated coordinates.
9. Build a small dataset summary: sessions, valid movement steps, missing positions, transition samples, map coverage and rejected records.
10. Inspect current `data/raw/deluge_session_20261124-113227.zip`; do not treat its array-form `m` events as tile-level demonstrations because they do not contain x/y positions.

**Acceptance gate:**
- Missing map-event coordinates remain missing, not `(0,0)`.
- The recorder is strictly passive.
- Trajectory records have valid map/position/timing or are explicitly rejected/marked incomplete.
- Parser tests cover array and dictionary schemas.
- Dataset validation reports usable versus unusable samples.
- No human-like model is trained until enough valid samples exist.

**Antigravity prompt — Phase 6:**

> Execute Phase 6 only. Fix recorder schema handling so map events without coordinates remain unknown, not `(0,0)`. Separate map changes from actual tile moves. Add or update a passive-only human movement recorder that observes but never triggers actions. Capture timestamp, map, before/after coordinates, observed direction, movement result and transition. Validate coordinate formulas and reject incomplete/invalid trajectories. Remove sensitive session/auth data from exports. Inspect the included session and correctly label it unsuitable for tile-level imitation if positions are absent. Add parser and trajectory tests plus a dataset-quality report. Do not train imitation learning yet. Stop at the Phase 6 gate.

---

## Phase 7 — Add human-like behaviour on top of safe navigation

**Visible result:** an agent that reaches valid destinations safely while choosing movement patterns closer to recorded human play.

**Main files:**
- New behavior-cloning model or policy module under `delugerpg/agents/`
- new training/evaluation scripts
- trajectory dataset from Phase 6
- replay/visualization output

**Implement:**
1. Do not replace the reliable map/portal planner. Keep it as the safety and reachability layer.
2. Train behavior cloning from valid human trajectories only. Use session-separated train/validation/test splits to prevent leakage from adjacent frames of the same session.
3. Predict only among currently legal actions; apply the simulator action mask after model inference.
4. Model optional human tendencies: route preference, turn frequency, pacing/pauses and exploration choices. Do not fake human timing if the dataset does not support it.
5. Combine the behavior model with the planner: planner defines safe/reachable alternatives; behavior policy ranks those alternatives. It must never choose a wall, illegal direction or unverified transition.
6. Evaluate navigation success and human similarity separately. Similarity metrics may include action distribution, turn/change frequency, path stretch over shortest path, pause distribution and trajectory similarity, but report limitations.
7. Compare three agents: deterministic planner, RL roaming policy, hybrid human-like policy.
8. Test on unseen maps/sessions and unseen start-target combinations where supported.
9. If trajectory volume or quality is insufficient, deliver the recorder/data-quality pipeline and report the blocker; do not claim human-like learning from a tiny dataset.

**Acceptance gate:**
- Hybrid policy never violates movement legality or portal constraints.
- Navigation success does not materially regress versus the safe planner without an explicitly approved trade-off.
- Human similarity is measured against held-out human trajectories, not visual intuition.
- No training/test leakage.
- If data is insufficient, the phase is honestly marked BLOCKED for imitation training.

**Antigravity prompt — Phase 7:**

> Execute Phase 7 only using the validated Phase 6 trajectory dataset. Keep the deterministic planner as the safety/reachability layer. Train a behavior-cloning model to rank only legal reachable movement choices, with session-separated train/validation/test splits. Combine it with planner candidates so the behavior model cannot choose illegal movement or an unverified transition. Compare deterministic, RL and hybrid policies on both navigation success and held-out human-similarity metrics. If trajectory data is insufficient, do not fabricate training; report the exact data gap and stop. Do not add live-game automation. Stop at the Phase 7 gate.

---

## Phase 8 — Final offline product, replay and reliability validation

**Visible result:** one command to run a simulator demonstration and one report showing what the agent can and cannot do.

**Main files:**
- `scripts/run_roamer_demo.py`
- `scripts/evaluate_roamer.py`
- `docs/ROAMER_USER_GUIDE.md`
- `docs/ROAMER_MODEL_CARD.md`
- versioned model/config/transition manifests

**Implement:**
1. Provide a CLI that runs a selected scenario with a selected agent and seed.
2. Print or render a replay showing map, coordinates, direction, portal ID, target, visited coverage and collisions over time.
3. Make the output distinguish planned action, executed simulator action and observed resulting state.
4. Provide commands for deterministic planner, RL policy and human-like hybrid policy.
5. Export a model manifest containing model version, observation schema version, action schema version, map/transition data version, training seed/config, training data version and evaluation results.
6. Fail safely if model/data/schema versions do not match.
7. Run all tests and the complete fixed benchmark. Publish a capabilities/limitations report.
8. Keep the real-game recorder passive. Do not turn the demo into an automatic live-game bot.

**Acceptance gate:**
- One documented command runs a reproducible offline demonstration.
- A replay trace can be inspected and independently checked.
- Model/schema mismatches fail clearly rather than silently loading.
- All tests and benchmark results are recorded.
- Claims about human-like behaviour are supported by held-out trajectory metrics.

**Antigravity prompt — Phase 8:**

> Execute Phase 8 only. Build the final offline simulator demo, replay/trace output, versioned model/config manifest and user guide. Support deterministic, RL and hybrid agents where those phases passed. Validate schema/version compatibility and fail safely on mismatch. Run the full test suite and fixed benchmark, then write a model card that states measured capabilities and limitations. Keep the browser recorder passive; do not add live movement automation. Stop after the final report.

---

## D. Recommended execution sequence

Do not ask Antigravity to implement all phases in one run. Use this exact sequence:

1. Send the **Master Rules + Phase 0 prompt**. Wait for its completion report.
2. Review the report and code diff. If Phase 0 passes, send Phase 1 prompt.
3. Continue in order only after the previous phase passes its gate.
4. If a phase is BLOCKED, resolve its listed blocker before continuing.
5. Never run full training before Phase 5.
6. Never train human imitation before Phase 6 has enough valid trajectory data.

### Short master instruction to paste before each phase

> Follow the global rules in `DELUGERPG_Master_Implementation_Plan_Phase0Passed.md`. Execute only the phase prompt I provide in this message. Keep the task scoped to that phase, inspect before editing, preserve old data/models, make visible tested changes, and stop at its acceptance gate. Do not continue to the next phase. If a required map fact is not evidenced, mark it unverified instead of guessing.



## E. Review of Antigravity's low-success-rate explanation (added in v2)

### Supported by the inspected source

- **Reward hacking is plausible and strongly supported as a hypothesis.** `Global49MapEnv.step()` grants reward for local sector paths without requiring map-target progress. Re-traversing water tiles can grant `+0.8` repeatedly because the water check is outside the `newly visited tile` condition.
- The legacy trainer uses **20 macro-actions per episode**, decays epsilon linearly from `1.0` to `0.05` over 5,000 episodes, and records success only when `current_map == target_map`.
- One local sector action executes an entire BFS path inside one macro-action. Thus a single action can collect rewards for many tile visits, while target-arrival reward is paid only when the target map is entered.
- Map-distance shaping occurs only on map transitions, uses the unweighted map graph, and does not reward local movement toward a correct portal.
- The training CSV records total reward, not reward-component totals. The screenshot alone cannot prove exactly how much return came from farming.

### Plausible but still requires measurement

- The stated 14-hop diameter and 8–10 average random target distance.
- The estimated 340-point return from local farming.
- A 10–12% random-walk target success rate.
- That the learned policy's exact motive was water/grass farming. The code permits that behaviour, but controlled rollouts and reward attribution are required to establish it.
- Whether tall grass receives `+0.8`; the inspected `train_global_49maps.py` checks `tile.is_water`. Verify other current-workspace code before claiming a tall-grass bonus.

### Which proposed fixes to adopt

- **Target-distance curriculum:** adopt it, but use verified portal-aware route cost, not map hops alone. Promote stages based on held-out validation, not fixed episode numbers.
- **Progress reward shaping:** adopt only with correct mathematics and tests. `25 * (D_current - D_next)` is a raw distance-difference bonus; by itself it is not the standard discounted potential-based formula when `gamma != 1`. If using PBRS, use `F = gamma * Phi(next) - Phi(current)` with `Phi = -alpha * D`, consistent termination/truncation semantics and correct action-duration handling.
- **Episode horizon:** make it route-aware, based on primitive route cost and measured detour allowance. Do not assume 35 is sufficient or appropriate after replacing macro-actions with tile actions.
- **Terminal reward:** strengthen task alignment only after removing local farming reward from navigation mode and measuring reward ranges. Do not copy `+250` blindly. The cleanest first navigation experiment removes tile novelty and water/grass bonuses entirely; keep novelty in a separate exploration task.
- **Reward decomposition and anti-farming tests:** add these before any new long training run.

### Required outcome

Every episode must show whether reward came from target progress, novelty, water/encounter events, map discovery, step cost or completion. Evaluation must show success by verified route-distance bucket, not only one average. Higher average reward without better held-out target success is a failed navigation-training result.
