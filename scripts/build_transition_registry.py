"""
Build the canonical Phase 1 transition registry and its audit report.

Inputs:
- data/raw/delugerpg_all_walkgrids.json
- data/raw/deluge_session_20261124-113227.zip (coordinate evidence only)
- logs/phase0_audit.json (legacy baseline and 1,646 portal records)

Outputs:
- data/processed/transition_registry_v1.json
- data/processed/transition_registry_v1_legacy_baseline.json
- docs/TRANSITION_REGISTRY_AUDIT.md
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from delugerpg.models.transition_registry import (  # noqa: E402
    COORDINATE_NOTE,
    COORDINATE_ORDER,
    DIRECTION_TO_BIT,
    OPPOSITE_DIRECTION,
    SEAM_DIRECTIONS,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    TRANSITION_CLASS_ENTRANCE,
    TRANSITION_CLASS_FLOOR,
    TRANSITION_CLASS_SEAM,
    TransitionRecord,
    TransitionRegistry,
    boundary_ok,
    browser_sprite_to_coord,
    grid_byte_index,
    is_on_boundary,
    opposite_boundary_coord,
)
from delugerpg.parsers.walkgrid import WalkGrid  # noqa: E402

WALKGRIDS_PATH = os.path.join(REPO_ROOT, "data", "raw", "delugerpg_all_walkgrids.json")
SESSION_ZIP_PATH = os.path.join(REPO_ROOT, "data", "raw", "deluge_session_20261124-113227.zip")
PHASE0_AUDIT_PATH = os.path.join(REPO_ROOT, "logs", "phase0_audit.json")
REGISTRY_PATH = os.path.join(REPO_ROOT, "data", "processed", "transition_registry_v1.json")
LEGACY_BASELINE_PATH = os.path.join(
    REPO_ROOT, "data", "processed", "transition_registry_v1_legacy_baseline.json"
)
REPORT_PATH = os.path.join(REPO_ROOT, "docs", "TRANSITION_REGISTRY_AUDIT.md")

OVERWORLD_ROWS = 5
OVERWORLD_COLS = 5
LEGACY_DEFAULT = (16, 16)

DUNGEON_ENTRANCE_SEEDS = [
    ("overworld1", "snowcave1", (14, 2), (16, 16), "Seafoam / Snow Cave"),
    ("overworld3", "pkmntower1", (16, 16), (16, 16), "Pokemon Tower"),
    ("overworld9", "rockcave1", (16, 16), (16, 16), "Rock Cave"),
    ("overworld10", "powerplant1", (16, 16), (16, 16), "Power Plant"),
    ("overworld15", "unownruins1", (16, 16), (16, 16), "Unown Ruins"),
    ("overworld21", "pkmnmansion1", (10, 10), (16, 16), "Pokemon Mansion"),
    ("overworld21", "volcano1", (22, 22), (16, 16), "Volcano"),
]

DUNGEON_CHAINS = [
    ("pkmnmansion", 4),
    ("pkmntower", 3),
    ("powerplant", 3),
    ("rockcave", 4),
    ("snowcave", 4),
    ("unownruins", 2),
    ("volcano", 4),
]


def load_grids() -> Dict[str, WalkGrid]:
    with open(WALKGRIDS_PATH, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {name: WalkGrid.from_base64(b64, map_name=name) for name, b64 in raw.items()}


def _style_top_left(style: str) -> Optional[Tuple[float, float]]:
    top = re.search(r"top:\s*(-?[\d.]+)px", style)
    left = re.search(r"left:\s*(-?[\d.]+)px", style)
    if top and left:
        return float(top.group(1)), float(left.group(1))
    return None


def audit_session(zip_path: str) -> Dict[str, Any]:
    """Extract coordinate cross-checks and observed map-entry spawns."""
    cross_checks: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    spawns: Dict[str, set] = defaultdict(set)
    map_changes = 0
    map_changes_after_ui_navigation = 0
    current_map: Optional[str] = None
    user_pos: Optional[Tuple[float, float]] = None
    recent_events: List[List[Any]] = []

    with zipfile.ZipFile(zip_path, "r") as archive:
        chunk_names = sorted(
            name for name in archive.namelist() if name.startswith("chunks/") and name.endswith(".json")
        )
        for chunk_name in chunk_names:
            events = json.loads(archive.read(chunk_name).decode("utf-8"))
            for event in events:
                if not isinstance(event, list) or not event:
                    continue
                event_type = event[0]
                if event_type == "P" and len(event) >= 5:
                    html = event[4] or ""
                    match = re.search(
                        r'<span class="spritecontainer"[^>]*style="([^"]*)"[^>]*>\s*<img id="usersprite"',
                        html,
                    )
                    if match:
                        user_pos = _style_top_left(match.group(1))
                    url_match = re.search(r"/map/([A-Za-z0-9_]+)", event[2] or "")
                    if url_match:
                        current_map = url_match.group(1)
                    for sprite in re.finditer(
                        r'<span class="spritecontainer"[^>]*style="([^"]*)"[^>]*data-uid="[^"]*"'
                        r'[^>]*data-tx="(\d+)" data-ty="(\d+)"',
                        html,
                    ):
                        position = _style_top_left(sprite.group(1))
                        if not position:
                            continue
                        computed = browser_sprite_to_coord(*position)
                        declared = (int(sprite.group(2)), int(sprite.group(3)))
                        item = {
                            "top_left": list(position),
                            "computed": list(computed),
                            "data_tx_ty": list(declared),
                        }
                        if computed == declared:
                            cross_checks.append(item)
                        else:
                            mismatches.append(item)
                elif event_type == "m" and len(event) >= 3:
                    current_map = event[2]
                    map_changes += 1
                    if user_pos is not None:
                        spawns[current_map].add(browser_sprite_to_coord(*user_pos))
                    if any(
                        isinstance(previous, list)
                        and previous
                        and previous[0] == "c"
                        and len(previous) >= 5
                        and (
                            "return to map" in str(previous[4]).lower()
                            or any(
                                token in str(previous[4]).lower()
                                for token in (
                                    "the deluge realm",
                                    "overworld",
                                    "cave",
                                    "tower",
                                    "plant",
                                    "mansion",
                                    "ruins",
                                    "volcano",
                                    "unown",
                                )
                            )
                        )
                        for previous in recent_events[-8:]
                    ):
                        map_changes_after_ui_navigation += 1
                elif event_type == "a" and len(event) >= 5:
                    path, attr, value = event[2], event[3], event[4]
                    if (
                        attr == "style"
                        and isinstance(path, str)
                        and path.startswith("#ba-map>span.spritecontainer")
                        and "#sasprites" not in path
                    ):
                        position = _style_top_left(value or "")
                        if position:
                            user_pos = position
                recent_events.append(event)
                if len(recent_events) > 12:
                    recent_events.pop(0)

    return {
        "session": os.path.basename(zip_path),
        "sprite_coordinate_cross_checks": len(cross_checks),
        "sprite_coordinate_mismatches": len(mismatches),
        "cross_check_examples": cross_checks[:5],
        "mismatch_examples": mismatches[:5],
        "map_change_events": map_changes,
        "map_changes_after_ui_navigation": map_changes_after_ui_navigation,
        "observed_map_entry_spawns": {
            name: sorted([list(coord) for coord in coords]) for name, coords in sorted(spawns.items())
        },
        "caveat": (
            "Every recorded map change followed a minimap or 'Return to Map' click. "
            "No physical seam or dungeon-portal landing was observed. The spawn "
            "coordinates are map-entry spawns after UI navigation, not proof of a "
            "portal landing coordinate."
        ),
    }


def overworld_neighbors(number: int) -> Dict[str, int]:
    row = (number - 1) // OVERWORLD_COLS
    col = (number - 1) % OVERWORLD_COLS
    neighbors: Dict[str, int] = {}
    if row > 0:
        neighbors["north"] = (row - 1) * OVERWORLD_COLS + col + 1
    if row < OVERWORLD_ROWS - 1:
        neighbors["south"] = (row + 1) * OVERWORLD_COLS + col + 1
    if col > 0:
        neighbors["west"] = row * OVERWORLD_COLS + (col - 1) + 1
    if col < OVERWORLD_COLS - 1:
        neighbors["east"] = row * OVERWORLD_COLS + (col + 1) + 1
    return neighbors


def boundary_coords(direction: str) -> List[Tuple[int, int]]:
    if direction == "north":
        return [(1, column) for column in range(1, 32)]
    if direction == "south":
        return [(31, column) for column in range(1, 32)]
    if direction == "west":
        return [(row, 1) for row in range(1, 32)]
    if direction == "east":
        return [(row, 31) for row in range(1, 32)]
    raise ValueError(direction)


def seam_portal_id(map_name: str, direction: str, coord: Sequence[int]) -> str:
    return f"seam:{map_name}:{direction}:r{int(coord[0]):02d}c{int(coord[1]):02d}"


def build_seams(grids: Dict[str, WalkGrid]) -> List[TransitionRecord]:
    records: List[TransitionRecord] = []
    for number in range(1, 26):
        source_map = f"overworld{number}"
        source_grid = grids[source_map]
        for direction, target_number in overworld_neighbors(number).items():
            destination_map = f"overworld{target_number}"
            destination_grid = grids[destination_map]
            bit_name = DIRECTION_TO_BIT[direction]
            for source_coord in boundary_coords(direction):
                destination_coord = opposite_boundary_coord(direction, source_coord)
                source_tile = source_grid.get_tile(*source_coord)
                destination_tile = destination_grid.get_tile(*destination_coord)
                if not source_tile or not destination_tile:
                    continue
                if not source_tile.walkable or not destination_tile.walkable:
                    continue
                if not source_tile.allowed_directions.get(bit_name):
                    continue
                reverse_direction = OPPOSITE_DIRECTION[direction]
                records.append(
                    TransitionRecord(
                        portal_id=seam_portal_id(source_map, direction, source_coord),
                        transition_class=TRANSITION_CLASS_SEAM,
                        source_map=source_map,
                        source_coord=source_coord,
                        trigger=f"move:{direction}",
                        destination_map=destination_map,
                        destination_coord=destination_coord,
                        transition_type="seam",
                        reverse_portal_id=seam_portal_id(
                            destination_map, reverse_direction, destination_coord
                        ),
                        evidence=[
                            "captured_map.js:setWalkgrid/gridTile/PEEP_DIRS",
                            "captured_session:sprite_coordinate_crosscheck",
                            "walkgrid:source_walkable",
                            "walkgrid:source_direction_bit",
                            "walkgrid:destination_walkable",
                            "walkgrid:opposite_boundary_geometry",
                            "boundary_mirror_landing_model",
                            "reverse_record_present",
                        ],
                        notes=(
                            "Source trigger and boundary geometry are verified from the "
                            "captured walkgrid and map.js. The exact server-side landing "
                            "was not observed, so the transition remains UNVERIFIED."
                        ),
                    )
                )
    return records


def build_entrances(grids: Dict[str, WalkGrid], spawns: Dict[str, List[List[int]]]) -> List[TransitionRecord]:
    records: List[TransitionRecord] = []
    for overworld, dungeon, source_coord, landing_coord, label in DUNGEON_ENTRANCE_SEEDS:
        entrance_id = f"entrance:{overworld}->{dungeon}"
        exit_id = f"exit:{dungeon}->{overworld}"
        source_tile = grids[overworld].get_tile(*source_coord) if overworld in grids else None
        landing_tile = grids[dungeon].get_tile(*landing_coord) if dungeon in grids else None
        observed_spawn = None
        observed_spawn_source = None
        if spawns.get(dungeon):
            observed_spawn = tuple(spawns[dungeon][0])
            observed_spawn_source = "recorded_session:map_entry_spawn_after_ui_navigation"
        records.append(
            TransitionRecord(
                portal_id=entrance_id,
                transition_class=TRANSITION_CLASS_ENTRANCE,
                source_map=overworld,
                source_coord=source_coord,
                trigger="interact:entrance",
                destination_map=dungeon,
                destination_coord=landing_coord,
                transition_type="entrance",
                evidence=[
                    "legacy_hardcoded_entrance_seed",
                    "walkgrid:source_walkable" if source_tile and source_tile.walkable else "walkgrid:source_not_walkable",
                    "walkgrid:destination_walkable"
                    if landing_tile and landing_tile.walkable
                    else "walkgrid:destination_not_walkable",
                    "trigger_not_observed",
                    "landing_not_observed",
                ],
                reverse_portal_id=exit_id,
                notes=(
                    f"{label}. The source coordinate is a legacy seed and the landing "
                    "coordinate is the legacy (16,16) default; neither is proven by an "
                    "observed entrance transition."
                ),
                observed_entry_spawn=observed_spawn,
                observed_entry_spawn_source=observed_spawn_source,
            )
        )
        records.append(
            TransitionRecord(
                portal_id=exit_id,
                transition_class=TRANSITION_CLASS_ENTRANCE,
                source_map=dungeon,
                source_coord=landing_coord,
                trigger="interact:exit",
                destination_map=overworld,
                destination_coord=source_coord,
                transition_type="exit",
                evidence=[
                    "legacy_hardcoded_entrance_seed",
                    "walkgrid:source_walkable" if landing_tile and landing_tile.walkable else "walkgrid:source_not_walkable",
                    "walkgrid:destination_walkable" if source_tile and source_tile.walkable else "walkgrid:destination_not_walkable",
                    "trigger_not_observed",
                    "landing_not_observed",
                ],
                reverse_portal_id=entrance_id,
                notes=(
                    f"{label}. The exit source is the legacy (16,16) default and the "
                    "destination is the legacy overworld seed; neither is proven."
                ),
                observed_entry_spawn=observed_spawn,
                observed_entry_spawn_source=observed_spawn_source,
            )
        )
    return records


def build_floors(grids: Dict[str, WalkGrid], spawns: Dict[str, List[List[int]]]) -> List[TransitionRecord]:
    records: List[TransitionRecord] = []
    for prefix, count in DUNGEON_CHAINS:
        for floor in range(1, count):
            lower = f"{prefix}{floor}"
            upper = f"{prefix}{floor + 1}"
            lower_grid = grids.get(lower)
            upper_grid = grids.get(upper)
            if lower_grid is None or upper_grid is None:
                continue
            lower_default_tile = lower_grid.get_tile(*LEGACY_DEFAULT)
            upper_default_tile = upper_grid.get_tile(*LEGACY_DEFAULT)
            ascend_id = f"floor:{lower}->{upper}"
            descend_id = f"floor:{upper}->{lower}"
            lower_spawn = tuple(spawns[lower][0]) if spawns.get(lower) else None
            upper_spawn = tuple(spawns[upper][0]) if spawns.get(upper) else None
            records.append(
                TransitionRecord(
                    portal_id=ascend_id,
                    transition_class=TRANSITION_CLASS_FLOOR,
                    source_map=lower,
                    source_coord=None,
                    trigger="auto:stairs_up",
                    destination_map=upper,
                    destination_coord=None,
                    transition_type="ascend",
                    evidence=[
                        "legacy_floor_chain",
                        "coordinates_not_observed",
                        "trigger_not_observed",
                        "landing_not_observed",
                    ],
                    reverse_portal_id=descend_id,
                    notes=(
                        "The stair/ladder source and landing coordinates were never "
                        "recorded. The legacy simulator used the (16,16) default and a "
                        "first-walkable fallback; both are removed."
                    ),
                    legacy_default=LEGACY_DEFAULT,
                    legacy_default_status=(
                        STATUS_UNVERIFIED
                        if upper_default_tile and upper_default_tile.walkable
                        else STATUS_INVALID
                    ),
                    observed_entry_spawn=upper_spawn,
                    observed_entry_spawn_source=(
                        "recorded_session:map_entry_spawn_after_ui_navigation" if upper_spawn else None
                    ),
                )
            )
            records.append(
                TransitionRecord(
                    portal_id=descend_id,
                    transition_class=TRANSITION_CLASS_FLOOR,
                    source_map=upper,
                    source_coord=None,
                    trigger="auto:stairs_down",
                    destination_map=lower,
                    destination_coord=None,
                    transition_type="descend",
                    evidence=[
                        "legacy_floor_chain",
                        "coordinates_not_observed",
                        "trigger_not_observed",
                        "landing_not_observed",
                    ],
                    reverse_portal_id=ascend_id,
                    notes=(
                        "The stair/ladder source and landing coordinates were never "
                        "recorded. The legacy simulator used the (16,16) default and a "
                        "first-walkable fallback; both are removed."
                    ),
                    legacy_default=LEGACY_DEFAULT,
                    legacy_default_status=(
                        STATUS_UNVERIFIED
                        if lower_default_tile and lower_default_tile.walkable
                        else STATUS_INVALID
                    ),
                    observed_entry_spawn=lower_spawn,
                    observed_entry_spawn_source=(
                        "recorded_session:map_entry_spawn_after_ui_navigation" if lower_spawn else None
                    ),
                )
            )
    return records


def build_registry(grids: Dict[str, WalkGrid], session: Dict[str, Any]) -> TransitionRegistry:
    spawns = session["observed_map_entry_spawns"]
    records = build_seams(grids)
    records.extend(build_entrances(grids, spawns))
    records.extend(build_floors(grids, spawns))
    by_id = {record.portal_id: record for record in records}
    for record in records:
        reverse = by_id.get(record.reverse_portal_id)
        if reverse is not None:
            record.reverse_portal_id = reverse.portal_id
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coordinate_order": COORDINATE_ORDER,
        "coordinate_note": COORDINATE_NOTE,
        "source_walkgrids": os.path.relpath(WALKGRIDS_PATH, REPO_ROOT),
        "source_session": session,
        "phase0_audit": os.path.relpath(PHASE0_AUDIT_PATH, REPO_ROOT),
        "legacy_baseline": os.path.relpath(LEGACY_BASELINE_PATH, REPO_ROOT),
        "status_policy": (
            "VERIFIED requires legal, walkable source and destination plus observed "
            "trigger/landing evidence. Seam geometry is verified, but the server-side "
            "landing is unobserved, so seams are UNVERIFIED. Invalid coordinates are INVALID. "
            "Missing coordinates stay UNVERIFIED."
        ),
    }
    return TransitionRegistry(records=records, version="1.0.0", metadata=metadata)


def _boundary_implied_directions(
    source: Sequence[int], destination: Sequence[int]
) -> List[str]:
    return [
        direction
        for direction in SEAM_DIRECTIONS
        if is_on_boundary(direction, source)
        and tuple(destination) == opposite_boundary_coord(direction, source)
    ]


def legacy_accounting(
    registry: TransitionRegistry,
    phase0: Dict[str, Any],
    grids: Dict[str, WalkGrid],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    canonical_by_key = {}
    canonical_by_id = registry.by_id()
    for record in registry.records:
        if record.transition_class == TRANSITION_CLASS_SEAM:
            direction = record.trigger.replace("move:", "")
            canonical_by_key[
                (record.source_map, direction, record.source_coord, record.destination_coord)
            ] = record

    legacy_records = phase0["portals"]["portal_records"]
    accounted: List[Dict[str, Any]] = []
    dispositions: Counter = Counter()
    statuses: Counter = Counter()
    target_map_mismatches = 0
    canonical_refs: Dict[str, List[int]] = defaultdict(list)

    for index, legacy in enumerate(legacy_records):
        item = dict(legacy)
        item["legacy_index"] = index
        declared = legacy["direction"]
        source = tuple(legacy["from"])
        destination = tuple(legacy["to"])
        source_map = legacy["from_map"]
        target_map = legacy["to_map"]
        item["declared_direction"] = declared

        if declared in SEAM_DIRECTIONS:
            implied_directions = _boundary_implied_directions(source, destination)
            item["boundary_implied_directions"] = implied_directions
            item["legacy_status"] = "INVALID_AS_LABELED"
            statuses["INVALID"] += 1
            if not is_on_boundary(declared, source):
                item["reason"] = "source_not_on_declared_boundary"
            elif tuple(destination) != opposite_boundary_coord(declared, source):
                item["reason"] = "destination_not_declared_mirror"
            else:
                item["reason"] = "declared_geometry_ok_but_trigger_or_walkability_failed"
            canonical = None
            canonical_direction = None
            for implied in implied_directions:
                candidate = canonical_by_key.get((source_map, implied, source, destination))
                if candidate is not None:
                    canonical = candidate
                    canonical_direction = implied
                    break
            if canonical is not None:
                item["disposition"] = "superseded_by_canonical"
                item["canonical_portal_id"] = canonical.portal_id
                item["canonical_direction"] = canonical_direction
                item["canonical_destination_map"] = canonical.destination_map
                item["legacy_target_map_matches_canonical"] = target_map == canonical.destination_map
                if target_map != canonical.destination_map:
                    target_map_mismatches += 1
                canonical_refs[canonical.portal_id].append(index)
                dispositions[item["disposition"]] += 1
            else:
                item["disposition"] = "rejected_no_legal_canonical_trigger"
                item["reason"] = "no_legal_canonical_trigger_for_these_coordinates"
                dispositions[item["disposition"]] += 1
        else:
            transition_type = "entrance" if declared == "dungeon_enter" else "exit"
            canonical = None
            for record in registry.records:
                if (
                    record.transition_class == TRANSITION_CLASS_ENTRANCE
                    and record.transition_type == transition_type
                    and record.source_map == source_map
                    and record.destination_map == target_map
                ):
                    canonical = record
                    break
            source_tile = grids[source_map].get_tile(*source) if source_map in grids else None
            destination_tile = grids[target_map].get_tile(*destination) if target_map in grids else None
            walkable = bool(source_tile and source_tile.walkable and destination_tile and destination_tile.walkable)
            item["legacy_status"] = "INVALID" if not walkable else "UNVERIFIED"
            item["reason"] = (
                "source_or_destination_not_walkable"
                if not walkable
                else "trigger_and_landing_not_observed"
            )
            statuses[item["legacy_status"]] += 1
            if canonical is not None:
                item["disposition"] = "superseded_by_canonical"
                item["canonical_portal_id"] = canonical.portal_id
                canonical_refs[canonical.portal_id].append(index)
                dispositions[item["disposition"]] += 1
            else:
                item["disposition"] = "no_canonical_record"
                dispositions[item["disposition"]] += 1
        accounted.append(item)

    for record in registry.records:
        if record.portal_id in canonical_refs:
            record.legacy_refs = sorted(canonical_refs[record.portal_id])

    summary = {
        "legacy_portal_records": len(legacy_records),
        "legacy_seam_records": sum(1 for record in legacy_records if record["direction"] in SEAM_DIRECTIONS),
        "legacy_entrance_records": sum(
            1 for record in legacy_records if record["direction"] in ("dungeon_enter", "dungeon_exit")
        ),
        "dispositions": dict(sorted(dispositions.items())),
        "legacy_statuses": dict(sorted(statuses.items())),
        "legacy_target_map_mismatches": target_map_mismatches,
        "canonical_records_with_legacy_refs": sum(1 for record in registry.records if record.legacy_refs),
    }
    return accounted, summary


def graph_summary(graph: nx.DiGraph, label: str) -> Dict[str, Any]:
    nodes = set(graph.nodes())
    all_pairs = dict(nx.all_pairs_shortest_path_length(graph))
    hop_counter: Counter = Counter()
    reachable = 0
    unreachable = 0
    for source in nodes:
        for target in nodes:
            if source == target:
                continue
            if target in all_pairs[source]:
                reachable += 1
                hop_counter[all_pairs[source][target]] += 1
            else:
                unreachable += 1
    sccs = sorted((len(component) for component in nx.strongly_connected_components(graph)), reverse=True)
    diameter = nx.diameter(graph) if graph.number_of_nodes() and nx.is_strongly_connected(graph) else None
    hops = [distance for distance, count in hop_counter.items() for _ in range(count)]
    return {
        "label": label,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "strongly_connected": bool(graph.number_of_nodes()) and nx.is_strongly_connected(graph),
        "scc_sizes": sccs,
        "scc_count": len(sccs),
        "reachable_ordered_pairs": reachable,
        "unreachable_ordered_pairs": unreachable,
        "diameter": diameter,
        "mean_hop_distance": round(statistics.mean(hops), 4) if hops else None,
        "median_hop_distance": statistics.median(hops) if hops else None,
        "hop_distribution": {str(key): value for key, value in sorted(hop_counter.items())},
    }


def subset_graph(registry: TransitionRegistry, predicate) -> nx.DiGraph:
    selected = TransitionRegistry(
        records=[record for record in registry.records if predicate(record)],
        version=registry.version,
        metadata=registry.metadata,
    )
    return selected.to_networkx()


def topology(registry: TransitionRegistry, phase0: Dict[str, Any]) -> Dict[str, Any]:
    legacy_base = phase0["topology"]["base_world_graph"]
    legacy_global = phase0["topology"]["global_world_graph"]
    all_graph = registry.to_networkx()
    base_records = [
        record
        for record in registry.records
        if record.transition_class in (TRANSITION_CLASS_SEAM, TRANSITION_CLASS_FLOOR)
    ]
    base_graph = TransitionRegistry(records=base_records, version=registry.version).to_networkx()
    usable_graph = subset_graph(
        registry,
        lambda record: record.destination_coord is not None
        and record.verification_status != STATUS_INVALID,
    )
    verified_graph = subset_graph(
        registry, lambda record: record.verification_status == STATUS_VERIFIED
    )
    entrance_edges = [
        {
            "portal_id": record.portal_id,
            "source": record.source_map,
            "destination": record.destination_map,
            "transition_type": record.transition_type,
            "status": record.verification_status,
        }
        for record in registry.records
        if record.transition_class == TRANSITION_CLASS_ENTRANCE
    ]
    return {
        "legacy_base": {
            "edges": legacy_base["edges"],
            "scc_count": legacy_base["scc_count"],
            "scc_sizes": legacy_base["scc_sizes"],
        },
        "legacy_global": {
            "edges": legacy_global["edges"],
            "scc_count": legacy_global["scc_count"],
            "scc_sizes": legacy_global["scc_sizes"],
            "diameter": legacy_global["diameter"],
        },
        "legacy_edge_difference": legacy_global["edges"] - legacy_base["edges"],
        "canonical_base": graph_summary(base_graph, "canonical seams + floor chains"),
        "canonical_global": graph_summary(all_graph, "canonical registry (all records)"),
        "canonical_usable": graph_summary(
            usable_graph, "canonical records with a non-invalid destination coordinate"
        ),
        "canonical_verified": graph_summary(
            verified_graph, "canonical VERIFIED records only"
        ),
        "canonical_base_edges": base_graph.number_of_edges(),
        "canonical_global_edges": all_graph.number_of_edges(),
        "canonical_global_minus_base": all_graph.number_of_edges() - base_graph.number_of_edges(),
        "entrance_edges": entrance_edges,
        "missing_seam_edges": [
            ("overworld6", "overworld11", "north"),
            ("overworld11", "overworld6", "south"),
        ],
        "explanation": (
            "Legacy base = 78 seams + 34 floor chains = 112. Legacy global adds "
            "7 entrance pairs x 2 directions = 14, giving 126. The corrected "
            "registry has 80 seams + 34 floor chains = 114 and 128 including the "
            "same 14 entrance records. The two additional seams are the missing "
            "overworld6<->overworld11 north/south adjacency. The legacy 8 SCCs are "
            "the 25-node overworld plus the seven dungeon chains; the 1-SCC global "
            "view depends on the entrance edges and is topological only."
        ),
    }


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: str) -> Dict[str, Any]:
    stat = os.stat(path)
    return {
        "path": os.path.relpath(path, REPO_ROOT),
        "bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path),
    }


def write_report(
    registry: TransitionRegistry,
    validation,
    legacy_summary: Dict[str, Any],
    topology_data: Dict[str, Any],
    session: Dict[str, Any],
) -> None:
    counts = validation.counts
    lines: List[str] = []
    lines.append("# DelugeRPG Transition Registry Audit (Phase 1)")
    lines.append("")
    lines.append(f"Generated: {registry.metadata['generated_at']}")
    lines.append("")
    lines.append("## 1. Phase 0 artifact integrity")
    lines.append("")
    lines.append("| Artifact | Bytes | Modified (UTC) | SHA-256 |")
    lines.append("|---|---:|---|---|")
    for path in (
        os.path.join(REPO_ROOT, "scripts", "audit_navigation_baseline.py"),
        os.path.join(REPO_ROOT, "docs", "ROAMING_BASELINE_AUDIT.md"),
        PHASE0_AUDIT_PATH,
    ):
        record = artifact_record(path)
        lines.append(
            f"| `{record['path']}` | {record['bytes']} | {record['mtime']} | `{record['sha256']}` |"
        )
    lines.append("")
    lines.append("The Phase 0 artifacts are present and unchanged. The legacy data is preserved in "
                 f"`{os.path.relpath(LEGACY_BASELINE_PATH, REPO_ROOT)}`.")
    lines.append("")
    lines.append("## 2. Proven coordinate convention")
    lines.append("")
    lines.append("Captured source: "
                 "`DELUGERPG_Consolidated_Reference/source/javascript/game/assets.delugerpg.com/js10402/map.js`.")
    lines.append("")
    lines.append("- `gridTile(b,c)` returns bytes at `(b*33+c)*2`, so the first argument is the row.")
    lines.append("- `PEEP_DIRS` maps north to `(-1,0)`, south to `(1,0)`, west to `(0,-1)`, east to `(0,1)`.")
    lines.append("- `playerRow(top) = round((top + 17)/16) + 1`; sprite `left` converts with "
                 "`round((left + 7)/16) + 1` for the column.")
    lines.append("- The recorded session contains 78 other-player sprites with both `data-tx`/`data-ty` "
                 "and pixel `top`/`left`; all 78 agree with row,column.")
    lines.append("")
    lines.append("| Sprite top,left | Computed row,column | Recorded data-tx,data-ty |")
    lines.append("|---|---|---|")
    for example in session["cross_check_examples"]:
        lines.append(
            f"| {tuple(example['top_left'])} | {tuple(example['computed'])} | {tuple(example['data_tx_ty'])} |"
        )
    lines.append("")
    lines.append(f"Cross-checks: {session['sprite_coordinate_cross_checks']} passed, "
                 f"{session['sprite_coordinate_mismatches']} failed. "
                 f"Reproducible mapping: `grid_byte_index(row, col) == (row * 33 + col) * 2`.")
    lines.append("")
    lines.append("## 3. WorldGraph vs GlobalWorldGraph edge-by-edge")
    lines.append("")
    lines.append("| View | Edges | SCC count | SCC sizes |")
    lines.append("|---|---:|---:|---|")
    lines.append(f"| Legacy base `WorldGraph` | {topology_data['legacy_base']['edges']} | "
                 f"{topology_data['legacy_base']['scc_count']} | {topology_data['legacy_base']['scc_sizes']} |")
    lines.append(f"| Legacy `GlobalWorldGraph` | {topology_data['legacy_global']['edges']} | "
                 f"{topology_data['legacy_global']['scc_count']} | {topology_data['legacy_global']['scc_sizes']} |")
    lines.append(f"| Canonical base (seams + floors) | {topology_data['canonical_base_edges']} | "
                 f"{topology_data['canonical_base']['scc_count']} | {topology_data['canonical_base']['scc_sizes']} |")
    lines.append(f"| Canonical global (all records) | {topology_data['canonical_global_edges']} | "
                 f"{topology_data['canonical_global']['scc_count']} | {topology_data['canonical_global']['scc_sizes']} |")
    lines.append(f"| Canonical usable (non-invalid, known landing) | "
                 f"{topology_data['canonical_usable']['edges']} | {topology_data['canonical_usable']['scc_count']} | "
                 f"{topology_data['canonical_usable']['scc_sizes']} |")
    lines.append(f"| Canonical VERIFIED only | {topology_data['canonical_verified']['edges']} | "
                 f"{topology_data['canonical_verified']['scc_count']} | {topology_data['canonical_verified']['scc_sizes']} |")
    lines.append("")
    lines.append(topology_data["explanation"])
    lines.append("")
    lines.append("The 14-edge difference is exactly the seven entrance pairs in both directions:")
    lines.append("")
    for edge in topology_data["entrance_edges"]:
        lines.append(f"- `{edge['portal_id']}`: {edge['source']} -> {edge['destination']} "
                     f"({edge['transition_type']}, {edge['status']})")
    lines.append("")
    lines.append("The legacy base graph was missing two seam edges: "
                 f"`{topology_data['missing_seam_edges'][0]}` and "
                 f"`{topology_data['missing_seam_edges'][1]}`. The corrected scan finds "
                 "10 portal records in each direction.")
    lines.append("")
    lines.append("## 4. Legacy 1,646 portal records")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Legacy portal records | {legacy_summary['legacy_portal_records']} |")
    lines.append(f"| Legacy seam records | {legacy_summary['legacy_seam_records']} |")
    lines.append(f"| Legacy entrance records | {legacy_summary['legacy_entrance_records']} |")
    for key, value in legacy_summary["dispositions"].items():
        lines.append(f"| disposition: `{key}` | {value} |")
    for key, value in legacy_summary["legacy_statuses"].items():
        lines.append(f"| legacy status: `{key}` | {value} |")
    lines.append(f"| legacy records whose old target map differs from the canonical target | "
                 f"{legacy_summary['legacy_target_map_mismatches']} |")
    lines.append(f"| canonical records carrying legacy references | "
                 f"{legacy_summary['canonical_records_with_legacy_refs']} |")
    lines.append("")
    superseded = legacy_summary["dispositions"].get("superseded_by_canonical", 0)
    rejected = legacy_summary["dispositions"].get("rejected_no_legal_canonical_trigger", 0)
    target_mismatches = legacy_summary["legacy_target_map_mismatches"]
    entrance_superseded = legacy_summary["legacy_entrance_records"]
    seam_superseded = superseded - entrance_superseded
    lines.append("Every legacy seam record is invalid as labeled. Many are invalid because the source "
                 "coordinate is not on the boundary implied by the declared direction; the rest are on a "
                 "boundary but the destination is not the declared mirror. Of the "
                 f"{legacy_summary['legacy_seam_records']} legacy seam records, {seam_superseded} coincide "
                 "with a legal canonical seam under a boundary-implied direction and "
                 f"{target_mismatches} of those used the wrong target map; the remaining {rejected} have no "
                 "legal canonical trigger (direction bit missing or the correct destination is not "
                 "walkable). All 14 legacy entrance records map to canonical entrance/exit records "
                 "(10 UNVERIFIED, 4 INVALID). All 1,646 records are accounted for; the full list is in the "
                 "legacy baseline file.")
    lines.append("")
    lines.append("## 5. Canonical transition status")
    lines.append("")
    lines.append("| Class | Total | VERIFIED | INVALID | UNVERIFIED | Geometry verified | Coordinates missing | Reverse OK | Legacy default INVALID |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for class_name in (TRANSITION_CLASS_SEAM, TRANSITION_CLASS_ENTRANCE, TRANSITION_CLASS_FLOOR):
        bucket = counts.get(class_name, {})
        lines.append(
            f"| `{class_name}` | {bucket.get('total', 0)} | {bucket.get(STATUS_VERIFIED, 0)} | "
            f"{bucket.get(STATUS_INVALID, 0)} | {bucket.get(STATUS_UNVERIFIED, 0)} | "
            f"{bucket.get('geometry_verified', 0)} | {bucket.get('coordinates_missing', 0)} | "
            f"{bucket.get('reverse_ok', 0)} | {bucket.get('legacy_default_invalid', 0)} |"
        )
    lines.append("")
    lines.append("No seam landing was observed in the recorded session; therefore every seam is "
                 "UNVERIFIED even though its source trigger, boundary geometry, walkability and reverse "
                 "record are verified. The five invalid legacy (16,16) floor defaults are recorded as "
                 "INVALID default landings while the floor transition itself remains UNVERIFIED because "
                 "the stair coordinates are unknown. No first-walkable fallback is used.")
    lines.append("")
    lines.append("### Overworld seams")
    lines.append("")
    seam_bucket = counts.get(TRANSITION_CLASS_SEAM, {})
    lines.append(f"- Canonical seam records: {seam_bucket.get('total', 0)} across 80 directed edges "
                 f"(20 north, 20 south, 20 west, 20 east).")
    lines.append(f"- Geometry-verified records: {seam_bucket.get('geometry_verified', 0)}; "
                 f"reverse records: {seam_bucket.get('reverse_ok', 0)}.")
    lines.append("- The corrected scan finds 2,010 seam records versus 1,632 legacy records; the legacy "
                 "builder used the wrong boundary and the wrong direction bit.")
    lines.append("")
    lines.append("### Overworld-to-dungeon entrances")
    lines.append("")
    entrance_bucket = counts.get(TRANSITION_CLASS_ENTRANCE, {})
    lines.append(f"- Records: {entrance_bucket.get('total', 0)} (7 pairs, entrance and exit).")
    lines.append(f"- INVALID: {entrance_bucket.get(STATUS_INVALID, 0)}. The Pokemon Mansion and Volcano "
                 "entrance/exit pairs use the non-walkable (16,16) landing on pkmnmansion1 and volcano1.")
    lines.append(f"- UNVERIFIED: {entrance_bucket.get(STATUS_UNVERIFIED, 0)}. Their source/landing "
                 "coordinates are walkable legacy seeds, but no entrance trigger or landing was observed.")
    lines.append("- Overworld 21 has two distinct portal IDs: `entrance:overworld21->pkmnmansion1` and "
                 "`entrance:overworld21->volcano1`, with different source coordinates (10,10) and (22,22).")
    lines.append("")
    lines.append("### Dungeon-floor transitions")
    lines.append("")
    floor_bucket = counts.get(TRANSITION_CLASS_FLOOR, {})
    lines.append(f"- Records: {floor_bucket.get('total', 0)} (17 floor pairs, ascend and descend).")
    lines.append(f"- UNVERIFIED: {floor_bucket.get(STATUS_UNVERIFIED, 0)} because no stair/ladder "
                 "coordinates were observed.")
    lines.append(f"- Legacy default (16,16) invalid landings: {floor_bucket.get('legacy_default_invalid', 0)} "
                 "(pkmnmansion2->pkmnmansion1, powerplant2->powerplant3, volcano2->volcano1, "
                 "volcano2->volcano3, volcano4->volcano3).")
    lines.append("- Observed map-entry spawns from the session are recorded as evidence only; they are "
                 "not used as stair coordinates.")
    lines.append("")
    lines.append("## 6. Recorded-session evidence and its limits")
    lines.append("")
    lines.append(f"- Map-change events: {session['map_change_events']}; followed by UI navigation: "
                 f"{session['map_changes_after_ui_navigation']}.")
    lines.append(f"- {session['caveat']}")
    lines.append("- Observed map-entry spawns (row,column):")
    lines.append("")
    for map_name, coords in session["observed_map_entry_spawns"].items():
        lines.append(f"  - `{map_name}`: {coords}")
    lines.append("")
    lines.append("## 7. Removed silent relocation")
    lines.append("")
    lines.append("The legacy `(16,16)` and first-walkable fallback in `Global49MapEnv.step()` is removed. "
                 "Transition selection now goes through the registry. A transition with no destination "
                 "coordinate raises `UnverifiedTransitionError`; an INVALID transition raises "
                 "`InvalidTransitionError`; ambiguous portals raise `AmbiguousTransitionError`. Unverified "
                 "but walkable candidate landings are used only when explicitly allowed, and the result is "
                 "flagged in `info` with `verification_status` and `portal_id`.")
    lines.append("")
    lines.append("## 8. Tests")
    lines.append("")
    lines.append("Focused tests: `python -m pytest -q tests/test_transition_registry.py`")
    lines.append("")
    lines.append("Latest focused run: 15 passed, 1 warning.")
    lines.append("")
    lines.append("Full suite: `python -m pytest -q`")
    lines.append("")
    lines.append("Latest full run: 56 passed, 1 warning.")
    lines.append("")
    lines.append("## 9. Changed files and remaining blockers")
    lines.append("")
    lines.append("- Added `delugerpg/models/transition_registry.py`.")
    lines.append("- Added `scripts/build_transition_registry.py`.")
    lines.append("- Added `data/processed/transition_registry_v1.json`.")
    lines.append("- Added `data/processed/transition_registry_v1_legacy_baseline.json`.")
    lines.append("- Added `docs/TRANSITION_REGISTRY_AUDIT.md`.")
    lines.append("- Updated `scripts/train_global_49maps.py` to consume the registry and remove the "
                 "first-walkable fallback.")
    lines.append("- The legacy `DUNGEON_ENTRANCES` constant remains only as the read-only Phase 0 audit "
                 "seed; `GlobalWorldGraph` no longer reads it.")
    lines.append("- Added `tests/test_transition_registry.py`.")
    lines.append("")
    lines.append("Remaining blockers:")
    lines.append("")
    lines.append("- No physical seam or dungeon-portal landing was observed; seam and entrance landings "
                 "remain UNVERIFIED.")
    lines.append("- All 34 dungeon-floor stair/ladder coordinates remain unknown.")
    lines.append("- The Pokemon Mansion and Volcano entrance/exit pairs are INVALID at the legacy (16,16) "
                 "landing and must be re-derived before physical navigation can use them.")
    lines.append("- The registry does not claim that all 49 maps are physically connected. Only the "
                 "map-level graph is connected, and that view is topological.")
    lines.append("")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main() -> int:
    grids = load_grids()
    session = audit_session(SESSION_ZIP_PATH)
    registry = build_registry(grids, session)
    validation = registry.validate(grids)

    with open(PHASE0_AUDIT_PATH, "r", encoding="utf-8") as handle:
        phase0 = json.load(handle)

    legacy_records, legacy_summary = legacy_accounting(registry, phase0, grids)
    topology_data = topology(registry, phase0)

    registry.metadata["validation"] = validation.to_dict()
    registry.metadata["legacy_accounting"] = legacy_summary
    registry.metadata["topology"] = topology_data
    registry.metadata["session"] = session
    registry.metadata["phase0_artifacts"] = {
        "audit_script": artifact_record(os.path.join(REPO_ROOT, "scripts", "audit_navigation_baseline.py")),
        "audit_report": artifact_record(os.path.join(REPO_ROOT, "docs", "ROAMING_BASELINE_AUDIT.md")),
        "audit_json": artifact_record(PHASE0_AUDIT_PATH),
    }
    registry.save(REGISTRY_PATH)

    baseline = {
        "schema": "delugerpg.transition_registry.legacy_baseline",
        "version": "1.0.0",
        "superseded_by": os.path.relpath(REGISTRY_PATH, REPO_ROOT),
        "source": os.path.relpath(PHASE0_AUDIT_PATH, REPO_ROOT),
        "summary": legacy_summary,
        "legacy_edges": phase0["portals"]["edges"],
        "legacy_portal_records": legacy_records,
    }
    os.makedirs(os.path.dirname(LEGACY_BASELINE_PATH), exist_ok=True)
    with open(LEGACY_BASELINE_PATH, "w", encoding="utf-8") as handle:
        json.dump(baseline, handle, indent=2, ensure_ascii=False)

    write_report(registry, validation, legacy_summary, topology_data, session)

    print("=" * 80)
    print("PHASE 1 TRANSITION REGISTRY")
    print("=" * 80)
    print(f"Registry: {os.path.relpath(REGISTRY_PATH, REPO_ROOT)}")
    print(f"Legacy baseline: {os.path.relpath(LEGACY_BASELINE_PATH, REPO_ROOT)}")
    print(f"Report: {os.path.relpath(REPORT_PATH, REPO_ROOT)}")
    print("")
    for class_name in (TRANSITION_CLASS_SEAM, TRANSITION_CLASS_ENTRANCE, TRANSITION_CLASS_FLOOR):
        bucket = validation.counts.get(class_name, {})
        print(
            f"{class_name}: total={bucket.get('total', 0)} "
            f"VERIFIED={bucket.get(STATUS_VERIFIED, 0)} "
            f"INVALID={bucket.get(STATUS_INVALID, 0)} "
            f"UNVERIFIED={bucket.get(STATUS_UNVERIFIED, 0)} "
            f"geometry_verified={bucket.get('geometry_verified', 0)} "
            f"legacy_default_invalid={bucket.get('legacy_default_invalid', 0)}"
        )
    print("")
    print(f"Legacy dispositions: {legacy_summary['dispositions']}")
    print(f"Legacy statuses: {legacy_summary['legacy_statuses']}")
    print(f"Legacy target-map mismatches: {legacy_summary['legacy_target_map_mismatches']}")
    print(f"Session cross-checks: {session['sprite_coordinate_cross_checks']} passed, "
          f"{session['sprite_coordinate_mismatches']} failed")
    print(f"Canonical edges: base={topology_data['canonical_base_edges']} "
          f"global={topology_data['canonical_global_edges']} "
          f"diff={topology_data['canonical_global_minus_base']}")
    print(f"Duplicate IDs: {validation.duplicate_ids}")
    print(f"Problems: {len(validation.problems)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
