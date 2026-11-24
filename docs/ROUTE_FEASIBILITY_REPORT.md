# Phase 2 Route Feasibility Report

Generated: 2026-11-24T14:07:39.233990+00:00

Registry: `data/processed/transition_registry_v1.json` version `1.0.0` with `2058` records.

## Policy

- Coordinates are `row,column`; local movement uses the captured 33x33 walkgrids.
- Local pathfinding is restricted to playable bounds `1..31`, matching captured `map.js` `findPath`.
- The planner validates start and goal endpoints before pathfinding. A non-walkable endpoint is never accepted.
- Global planning uses exact portal source and destination coordinates. INVALID transitions are excluded.
- UNVERIFIED transitions are allowed only in `allow_unverified=True` mode and are labeled in route warnings.
- Missing destination coordinates are never guessed and never replaced with a first-walkable fallback.
- `allow_unverified=False` provides a strict verified-only mode. With the current registry it finds no cross-map route.

## Local navigation

- Maps with at least one valid local route: **49/49**.
- Maps with disconnected walkable components: **16/49**.
- Local disconnected components are handled explicitly; a map-level transition does not imply that its portal is reachable.

## Scenario results

| Scenario | Simulated | Start | Goal | Result | Cost | Transitions | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| same_map_local | no | overworld1 (20, 13) | overworld1 (24, 16) | OK | 4 | 0 | - |
| overworld_seam_unverified | no | overworld1 (20, 13) | overworld6 (10, 10) | OK | 21 | 1 | UNVERIFIED |
| multi_seam_unverified | no | overworld1 (20, 13) | overworld11 (20, 15) | OK | 62 | 2 | UNVERIFIED, UNVERIFIED |
| dungeon_entrance_unverified | no | overworld1 (20, 13) | snowcave1 (11, 11) | OK | 17 | 1 | UNVERIFIED |
| strict_seam_rejected | no | overworld1 (20, 13) | overworld6 (10, 10) | NO ROUTE (unverified_not_allowed) | - | 0 | - |
| invalid_mansion_entrance | no | overworld21 (10, 10) | pkmnmansion1 (20, 21) | NO ROUTE (blocked_by_invalid_transitions) | - | 0 | - |
| invalid_volcano_entrance | no | overworld21 (22, 22) | volcano1 (20, 15) | NO ROUTE (blocked_by_invalid_transitions) | - | 0 | - |
| missing_floor_coordinates | no | snowcave1 (11, 11) | snowcave2 (19, 20) | NO ROUTE (blocked_by_missing_coordinates) | - | 0 | - |
| local_unreachable | no | overworld2 (1, 1) | overworld2 (1, 22) | NO ROUTE (local_unreachable) | - | 0 | - |
| invalid_start | no | overworld1 (0, 0) | overworld1 (20, 13) | NO ROUTE (invalid_start:coord_out_of_playable_bounds) | - | 0 | - |
| simulated_ow21_mansion | yes | overworld21 (10, 10) | pkmnmansion1 (20, 21) | OK | 1 | 1 | UNVERIFIED |
| simulated_ow21_volcano | yes | overworld21 (22, 22) | volcano1 (20, 15) | OK | 1 | 1 | UNVERIFIED |

## Route coverage

| Metric | Count |
| --- | --- |
| Successful scenarios | 6 |
| Failed scenarios | 6 |
| Same-map routes | 1 |
| Global routes | 5 |
| Verified global routes | 0 |
| Unverified global routes | 5 |
| Simulated global routes | 2 |
| Unreachable routes | 6 |

No transition in the registry is currently `VERIFIED`. All cross-map routes are therefore either
UNVERIFIED or SIMULATED. This report does not claim physical navigation through unverified portals.

## Physical route-cost coverage

| Transition class | Records | Known coordinates | Missing coordinates | INVALID | Usable by planner |
| --- | --- | --- | --- | --- | --- |
| overworld_seam | 2010 | 2010 | 0 | 0 | 2010 |
| overworld_to_dungeon | 14 | 14 | 0 | 4 | 10 |
| dungeon_floor | 34 | 0 | 34 | 0 | 0 |

Known source/destination coordinate records, including 4 INVALID entrances:
**2024/2058**
(98.35%). Planner-usable transitions with known coordinates:
**2020/2058**
(98.15%). Excluded transitions:
**38**.

## Unresolved dependencies

- **4 INVALID overworld-to-dungeon transitions** block the Mansion and Volcano entrances from `overworld21`.
- **34 dungeon-floor transitions** have no source or destination coordinates and cannot be planned.
- **2,010 overworld seams** have verified boundary geometry but unobserved physical landings.
- **10 overworld-to-dungeon entrances** have known coordinates but unobserved physical landings.
- **0 transitions are VERIFIED**, so no cross-map route can be reported as physically verified.

Detailed machine-readable dependencies: `data/processed/unresolved_transition_dependencies.json`.

## Verification commands

```powershell
python -m pytest tests\test_multi_map_planner.py -q
python -m pytest -q
python scripts\test_global_routes.py --start-map overworld1 --start 20,13 --goal-map overworld6 --goal 10,10
python scripts\test_global_routes.py --start-map overworld1 --start 20,13 --goal-map overworld6 --goal 10,10 --require-verified
```
