"""Benchmark deterministic local/global routes and write Phase 2 reports."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.abspath("."))

from delugerpg.agents.multi_map_planner import (
    GlobalNavigator,
    LocalNavigator,
    load_navigation_data,
)
from delugerpg.models.transition_registry import (
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    TransitionRegistry,
)

REGISTRY_PATH = "data/processed/transition_registry_v1.json"
WALKGRID_PATH = "data/raw/delugerpg_all_walkgrids.json"
REPORT_JSON = "data/processed/route_feasibility_report.json"
DEPENDENCIES_JSON = "data/processed/unresolved_transition_dependencies.json"
REPORT_MD = "docs/ROUTE_FEASIBILITY_REPORT.md"
DEPENDENCIES_MD = "docs/UNRESOLVED_TRANSITION_DEPENDENCIES.md"


def simulated_ow21_registry(registry: TransitionRegistry) -> TransitionRegistry:
    data = registry.to_dict()
    simulated_destinations = {
        "entrance:overworld21->pkmnmansion1": [20, 21],
        "entrance:overworld21->volcano1": [20, 15],
    }
    for record in data["records"]:
        if record["portal_id"] not in simulated_destinations:
            continue
        record["verification_status"] = STATUS_UNVERIFIED
        record["destination_coord"] = simulated_destinations[record["portal_id"]]
        checks = dict(record.get("checks", {}))
        checks["destination_walkable"] = True
        checks["reasons"] = []
        record["checks"] = checks
        record["notes"] = (
            "SIMULATED Phase 2 benchmark landing: observed dungeon entry spawn, "
            "not a physically observed portal landing."
        )
    return TransitionRegistry.from_dict(data)


def transition_statuses(route) -> List[str]:
    return [
        leg.verification_status
        for leg in route.legs
        if leg.kind == "transition" and leg.verification_status is not None
    ]


def compact_route(route) -> Dict[str, Any]:
    return {
        "success": route.success,
        "reason": route.reason,
        "total_cost": route.total_cost,
        "map_sequence": list(route.map_sequence),
        "transition_ids": list(route.transition_ids),
        "transition_statuses": transition_statuses(route),
        "uses_unverified": route.uses_unverified,
        "uses_invalid": route.uses_invalid,
        "warnings": list(route.warnings),
        "legs": [
            {
                "kind": leg.kind,
                "source_map": leg.source_map,
                "destination_map": leg.destination_map,
                "start": list(leg.start),
                "end": list(leg.end),
                "cost": leg.cost,
                "portal_id": leg.portal_id,
                "verification_status": leg.verification_status,
            }
            for leg in route.legs
        ],
        "diagnostics": route.diagnostics,
    }


def run_scenario(
    name: str,
    navigator: GlobalNavigator,
    start_map: str,
    start: Sequence[int],
    goal_map: str,
    goal: Sequence[int],
    simulated: bool = False,
) -> Dict[str, Any]:
    route = navigator.plan(start_map, start, goal_map, goal)
    return {
        "name": name,
        "simulated": simulated,
        "start_map": start_map,
        "start": list(start),
        "goal_map": goal_map,
        "goal": list(goal),
        "result": compact_route(route),
    }


def local_coverage(grids) -> Tuple[int, int]:
    local = LocalNavigator(grids)
    valid_maps = 0
    disconnected_maps = 0
    for map_name, grid in grids.items():
        walkable = [
            (tile.x, tile.y)
            for row in grid.tiles
            for tile in row
            if tile.walkable and 1 <= tile.x <= 31 and 1 <= tile.y <= 31
        ]
        start = walkable[0]
        distances, _ = local.bfs_tree(map_name, start)
        goal = next((coord for coord in walkable if coord in distances and coord != start), None)
        if goal is not None and local.local_route(map_name, start, goal).reachable:
            valid_maps += 1
        if any(coord not in distances for coord in walkable):
            disconnected_maps += 1
    return valid_maps, disconnected_maps


def build_dependencies(registry: TransitionRegistry) -> Dict[str, Any]:
    invalid = [record for record in registry.records if record.verification_status == STATUS_INVALID]
    missing = [
        record
        for record in registry.records
        if record.source_coord is None or record.destination_coord is None
    ]
    unverified_seams = [
        record
        for record in registry.records
        if record.transition_class == "overworld_seam"
        and record.verification_status == STATUS_UNVERIFIED
    ]
    unverified_entrances = [
        record
        for record in registry.records
        if record.transition_class == "overworld_to_dungeon"
        and record.verification_status == STATUS_UNVERIFIED
    ]
    verified = [
        record for record in registry.records if record.verification_status == STATUS_VERIFIED
    ]
    seam_directions = Counter(record.trigger.replace("move:", "") for record in unverified_seams)
    return {
        "registry_version": registry.version,
        "total_transitions": len(registry.records),
        "verified_transitions": [
            {
                "portal_id": record.portal_id,
                "source_map": record.source_map,
                "destination_map": record.destination_map,
            }
            for record in verified
        ],
        "invalid_transitions": [
            {
                "portal_id": record.portal_id,
                "transition_class": record.transition_class,
                "source_map": record.source_map,
                "source_coord": list(record.source_coord) if record.source_coord is not None else None,
                "destination_map": record.destination_map,
                "destination_coord": (
                    list(record.destination_coord) if record.destination_coord is not None else None
                ),
                "reasons": list(record.checks.get("reasons", [])) if record.checks else [],
            }
            for record in invalid
        ],
        "missing_coordinate_transitions": [
            {
                "portal_id": record.portal_id,
                "transition_class": record.transition_class,
                "source_map": record.source_map,
                "destination_map": record.destination_map,
                "transition_type": record.transition_type,
            }
            for record in missing
        ],
        "unverified_seams": {
            "count": len(unverified_seams),
            "by_direction": dict(sorted(seam_directions.items())),
            "portal_ids": [record.portal_id for record in unverified_seams],
        },
        "unverified_entrances": [
            {
                "portal_id": record.portal_id,
                "source_map": record.source_map,
                "source_coord": list(record.source_coord) if record.source_coord is not None else None,
                "destination_map": record.destination_map,
                "destination_coord": (
                    list(record.destination_coord) if record.destination_coord is not None else None
                ),
            }
            for record in unverified_entrances
        ],
    }


def build_coverage(registry: TransitionRegistry, navigator: GlobalNavigator) -> Dict[str, Any]:
    classes = ("overworld_seam", "overworld_to_dungeon", "dungeon_floor")
    by_class: Dict[str, Dict[str, int]] = {}
    for transition_class in classes:
        records = [record for record in registry.records if record.transition_class == transition_class]
        by_class[transition_class] = {
            "total": len(records),
            "known_coordinates": sum(
                1 for record in records if record.source_coord is not None and record.destination_coord is not None
            ),
            "missing_coordinates": sum(
                1 for record in records if record.source_coord is None or record.destination_coord is None
            ),
            "invalid": sum(1 for record in records if record.verification_status == STATUS_INVALID),
            "verified": sum(1 for record in records if record.verification_status == STATUS_VERIFIED),
            "unverified": sum(1 for record in records if record.verification_status == STATUS_UNVERIFIED),
            "usable_by_planner": sum(
                1 for record in navigator.usable_transitions if record.transition_class == transition_class
            ),
        }
    total = len(registry.records)
    known = sum(item["known_coordinates"] for item in by_class.values())
    usable = len(navigator.usable_transitions)
    return {
        "total_transitions": total,
        "known_coordinate_transitions": known,
        "known_coordinate_fraction": known / total if total else 0.0,
        "planner_usable_transitions": usable,
        "planner_usable_fraction": usable / total if total else 0.0,
        "verified_transitions": sum(item["verified"] for item in by_class.values()),
        "usable_by_planner": usable,
        "excluded_by_planner": len(navigator.excluded_transitions),
        "by_class": by_class,
    }


def scenario_table(scenarios: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "| Scenario | Simulated | Start | Goal | Result | Cost | Transitions | Status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scenario in scenarios:
        result = scenario["result"]
        outcome = "OK" if result["success"] else f"NO ROUTE ({result['reason']})"
        statuses = ", ".join(result["transition_statuses"]) if result["transition_statuses"] else "-"
        lines.append(
            f"| {scenario['name']} | {'yes' if scenario['simulated'] else 'no'} | "
            f"{scenario['start_map']} {tuple(scenario['start'])} | "
            f"{scenario['goal_map']} {tuple(scenario['goal'])} | "
            f"{outcome} | {result['total_cost'] if result['total_cost'] is not None else '-'} | "
            f"{len(result['transition_ids'])} | {statuses} |"
        )
    return "\n".join(lines)


def write_report(
    registry: TransitionRegistry,
    navigator: GlobalNavigator,
    strict_navigator: GlobalNavigator,
    scenarios: Sequence[Dict[str, Any]],
    local_valid_maps: int,
    disconnected_maps: int,
    coverage: Dict[str, Any],
    dependencies: Dict[str, Any],
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    successful = [scenario for scenario in scenarios if scenario["result"]["success"]]
    failed = [scenario for scenario in scenarios if not scenario["result"]["success"]]
    global_success = [scenario for scenario in successful if scenario["result"]["transition_ids"]]
    verified_global = [
        scenario
        for scenario in global_success
        if scenario["result"]["transition_statuses"]
        and all(status == STATUS_VERIFIED for status in scenario["result"]["transition_statuses"])
    ]
    unverified_global = [
        scenario for scenario in global_success if STATUS_UNVERIFIED in scenario["result"]["transition_statuses"]
    ]
    simulated_global = [scenario for scenario in global_success if scenario["simulated"]]
    same_map = [scenario for scenario in successful if not scenario["result"]["transition_ids"]]

    report = {
        "generated_at": generated_at,
        "registry_version": registry.version,
        "policy": {
            "local_bounds": "1..31 inclusive, matching map.js findPath",
            "coordinate_order": "row,column",
            "invalid_transitions": "excluded from every route",
            "unverified_transitions": "allowed only when allow_unverified=True and labeled in warnings",
            "verified_only_mode": "available with allow_unverified=False",
            "missing_coordinates": "never guessed and never replaced with a first-walkable fallback",
            "transition_cost": navigator.transition_cost,
        },
        "local_navigation": {
            "maps_total": len(navigator.grids),
            "maps_with_valid_local_navigation": local_valid_maps,
            "maps_with_disconnected_walkable_components": disconnected_maps,
        },
        "route_coverage": {
            "successful_scenarios": len(successful),
            "failed_scenarios": len(failed),
            "same_map_routes": len(same_map),
            "global_routes": len(global_success),
            "verified_global_routes": len(verified_global),
            "unverified_global_routes": len(unverified_global),
            "simulated_global_routes": len(simulated_global),
            "unreachable_routes": len(failed),
        },
        "physical_route_cost_coverage": coverage,
        "scenarios": list(scenarios),
    }

    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    dependency_payload = dict(dependencies)
    dependency_payload["generated_at"] = generated_at
    with open(DEPENDENCIES_JSON, "w", encoding="utf-8") as handle:
        json.dump(dependency_payload, handle, indent=2, sort_keys=True)

    coverage_rows = []
    for transition_class, item in coverage["by_class"].items():
        coverage_rows.append(
            f"| {transition_class} | {item['total']} | {item['known_coordinates']} | "
            f"{item['missing_coordinates']} | {item['invalid']} | {item['usable_by_planner']} |"
        )

    invalid_rows = [
        f"| {item['portal_id']} | {item['source_map']} {tuple(item['source_coord'])} | "
        f"{item['destination_map']} {tuple(item['destination_coord'])} | "
        f"{', '.join(item['reasons']) or 'no reason recorded'} |"
        for item in dependencies["invalid_transitions"]
    ]
    floor_rows = [
        f"| {item['portal_id']} | {item['source_map']} | {item['destination_map']} |"
        for item in dependencies["missing_coordinate_transitions"]
    ]

    md = f"""# Phase 2 Route Feasibility Report

Generated: {generated_at}

Registry: `{REGISTRY_PATH}` version `{registry.version}` with `{len(registry.records)}` records.

## Policy

- Coordinates are `row,column`; local movement uses the captured 33x33 walkgrids.
- Local pathfinding is restricted to playable bounds `1..31`, matching captured `map.js` `findPath`.
- The planner validates start and goal endpoints before pathfinding. A non-walkable endpoint is never accepted.
- Global planning uses exact portal source and destination coordinates. INVALID transitions are excluded.
- UNVERIFIED transitions are allowed only in `allow_unverified=True` mode and are labeled in route warnings.
- Missing destination coordinates are never guessed and never replaced with a first-walkable fallback.
- `allow_unverified=False` provides a strict verified-only mode. With the current registry it finds no cross-map route.

## Local navigation

- Maps with at least one valid local route: **{local_valid_maps}/{len(navigator.grids)}**.
- Maps with disconnected walkable components: **{disconnected_maps}/{len(navigator.grids)}**.
- Local disconnected components are handled explicitly; a map-level transition does not imply that its portal is reachable.

## Scenario results

{scenario_table(scenarios)}

## Route coverage

| Metric | Count |
| --- | --- |
| Successful scenarios | {len(successful)} |
| Failed scenarios | {len(failed)} |
| Same-map routes | {len(same_map)} |
| Global routes | {len(global_success)} |
| Verified global routes | {len(verified_global)} |
| Unverified global routes | {len(unverified_global)} |
| Simulated global routes | {len(simulated_global)} |
| Unreachable routes | {len(failed)} |

No transition in the registry is currently `VERIFIED`. All cross-map routes are therefore either
UNVERIFIED or SIMULATED. This report does not claim physical navigation through unverified portals.

## Physical route-cost coverage

| Transition class | Records | Known coordinates | Missing coordinates | INVALID | Usable by planner |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(coverage_rows)}

Known source/destination coordinate records, including 4 INVALID entrances:
**{coverage['known_coordinate_transitions']}/{coverage['total_transitions']}**
({coverage['known_coordinate_fraction']:.2%}). Planner-usable transitions with known coordinates:
**{coverage['planner_usable_transitions']}/{coverage['total_transitions']}**
({coverage['planner_usable_fraction']:.2%}). Excluded transitions:
**{coverage['excluded_by_planner']}**.

## Unresolved dependencies

- **4 INVALID overworld-to-dungeon transitions** block the Mansion and Volcano entrances from `overworld21`.
- **34 dungeon-floor transitions** have no source or destination coordinates and cannot be planned.
- **2,010 overworld seams** have verified boundary geometry but unobserved physical landings.
- **10 overworld-to-dungeon entrances** have known coordinates but unobserved physical landings.
- **0 transitions are VERIFIED**, so no cross-map route can be reported as physically verified.

Detailed machine-readable dependencies: `{DEPENDENCIES_JSON}`.

## Verification commands

```powershell
python -m pytest tests\\test_multi_map_planner.py -q
python -m pytest -q
python scripts\\test_global_routes.py --start-map overworld1 --start 20,13 --goal-map overworld6 --goal 10,10
python scripts\\test_global_routes.py --start-map overworld1 --start 20,13 --goal-map overworld6 --goal 10,10 --require-verified
```
"""
    with open(REPORT_MD, "w", encoding="utf-8") as handle:
        handle.write(md)

    dependencies_md = f"""# Unresolved Transition Dependencies

Generated: {generated_at}

Registry: `{REGISTRY_PATH}` version `{registry.version}` with `{len(registry.records)}` records.

## Hard blockers

### INVALID transitions ({len(dependencies['invalid_transitions'])})

| Portal | Source | Destination | Reasons |
| --- | --- | --- | --- |
{chr(10).join(invalid_rows)}

These transitions are excluded from every route. In particular, both `overworld21` dungeon
entrances are blocked by non-walkable `(16,16)` destination tiles. The observed dungeon entry
spawns are not portal landings and are not used as substitutes.

### Missing coordinates ({len(dependencies['missing_coordinate_transitions'])})

| Portal | Source map | Destination map |
| --- | --- | --- |
{chr(10).join(floor_rows)}

All 34 are dungeon-floor transitions. They have no recorded stair/ladder source or landing
coordinates, so no route through them can be planned.

## Physical verification gaps

- `VERIFIED` transitions: **{len(dependencies['verified_transitions'])}**
- `UNVERIFIED` overworld seams: **{dependencies['unverified_seams']['count']}**
  (directions: {json.dumps(dependencies['unverified_seams']['by_direction'], sort_keys=True)})
- `UNVERIFIED` overworld-to-dungeon entrances: **{len(dependencies['unverified_entrances'])}**

The seam records have verified boundary geometry, source direction bits, walkable endpoints,
and reverse records. Their server-side landing coordinates were not observed, so they remain
UNVERIFIED. The entrance records have known coordinates but their physical landings were not
observed either.

## OW21 parallel entrances

`overworld21` has two physically distinct entrance source coordinates:

- Mansion: source `(10,10)` to `pkmnmansion1`, currently INVALID because `(16,16)` is not walkable.
- Volcano: source `(22,22)` to `volcano1`, currently INVALID because `(16,16)` is not walkable.

The planner treats these as independent transitions. It never substitutes the observed dungeon
entry spawn for the missing portal landing. The Phase 2 tests use a clearly labeled simulated
registry to exercise independent Mansion/Volcano selection.

## Full data

- `{DEPENDENCIES_JSON}` contains the full invalid list, missing-coordinate list, unverified
  entrance list, and all 2,010 unverified seam portal IDs.
- `{REPORT_JSON}` contains the scenario results and coverage metrics.
"""
    with open(DEPENDENCIES_MD, "w", encoding="utf-8") as handle:
        handle.write(dependencies_md)


def main() -> int:
    registry, grids = load_navigation_data(REGISTRY_PATH, WALKGRID_PATH)
    navigator = GlobalNavigator(registry, grids, allow_unverified=True)
    strict_navigator = GlobalNavigator(registry, grids, allow_unverified=False)
    simulated_navigator = GlobalNavigator(simulated_ow21_registry(registry), grids, allow_unverified=True)

    local_valid_maps, disconnected_maps = local_coverage(grids)
    coverage = build_coverage(registry, navigator)
    dependencies = build_dependencies(registry)

    scenarios = [
        run_scenario("same_map_local", navigator, "overworld1", (20, 13), "overworld1", (24, 16)),
        run_scenario("overworld_seam_unverified", navigator, "overworld1", (20, 13), "overworld6", (10, 10)),
        run_scenario("multi_seam_unverified", navigator, "overworld1", (20, 13), "overworld11", (20, 15)),
        run_scenario("dungeon_entrance_unverified", navigator, "overworld1", (20, 13), "snowcave1", (11, 11)),
        run_scenario("strict_seam_rejected", strict_navigator, "overworld1", (20, 13), "overworld6", (10, 10)),
        run_scenario("invalid_mansion_entrance", navigator, "overworld21", (10, 10), "pkmnmansion1", (20, 21)),
        run_scenario("invalid_volcano_entrance", navigator, "overworld21", (22, 22), "volcano1", (20, 15)),
        run_scenario("missing_floor_coordinates", navigator, "snowcave1", (11, 11), "snowcave2", (19, 20)),
        run_scenario("local_unreachable", navigator, "overworld2", (1, 1), "overworld2", (1, 22)),
        run_scenario("invalid_start", navigator, "overworld1", (0, 0), "overworld1", (20, 13)),
        run_scenario(
            "simulated_ow21_mansion",
            simulated_navigator,
            "overworld21",
            (10, 10),
            "pkmnmansion1",
            (20, 21),
            simulated=True,
        ),
        run_scenario(
            "simulated_ow21_volcano",
            simulated_navigator,
            "overworld21",
            (22, 22),
            "volcano1",
            (20, 15),
            simulated=True,
        ),
    ]

    write_report(
        registry,
        navigator,
        strict_navigator,
        scenarios,
        local_valid_maps,
        disconnected_maps,
        coverage,
        dependencies,
    )
    print(f"Wrote {REPORT_MD}")
    print(f"Wrote {DEPENDENCIES_MD}")
    print(f"Wrote {REPORT_JSON}")
    print(f"Wrote {DEPENDENCIES_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
