"""
Canonical, versioned map-transition registry for DelugeRPG.

The registry is the single source of truth for physical map transitions. A
map-level graph may be generated from it, but the registry records must remain
the audit trail for every transition.

Coordinate convention (proven from captured ``map.js`` and the recorded
session): the first coordinate is the row (``x``), the second is the column
(``y``). ``gridTile(row, column)`` indexes ``(row * 33 + column) * 2``.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx

from delugerpg.parsers.walkgrid import DIR_BITS, WalkGrid

STATUS_VERIFIED = "VERIFIED"
STATUS_INVALID = "INVALID"
STATUS_UNVERIFIED = "UNVERIFIED"

TRANSITION_CLASS_SEAM = "overworld_seam"
TRANSITION_CLASS_ENTRANCE = "overworld_to_dungeon"
TRANSITION_CLASS_FLOOR = "dungeon_floor"

TRANSITION_CLASSES = (
    TRANSITION_CLASS_SEAM,
    TRANSITION_CLASS_ENTRANCE,
    TRANSITION_CLASS_FLOOR,
)

SEAM_DIRECTIONS = ("north", "south", "west", "east")
DIRECTION_TO_BIT = {
    "north": "n",
    "south": "s",
    "west": "w",
    "east": "e",
}
OPPOSITE_DIRECTION = {
    "north": "south",
    "south": "north",
    "west": "east",
    "east": "west",
}

COORDINATE_ORDER = "row,column"
COORDINATE_NOTE = (
    "First coordinate is the row (x, north-south); second is the column "
    "(y, west-east). Proven by map.js gridTile(b,c) -> (b*33+c)*2, "
    "PEEP_DIRS offsets, and 78/78 recorded sprite cross-checks."
)

PEEP_OX = 17
PEEP_OY = 9
TILE_PX = 16
GRID_SIZE = 33


class TransitionResolutionError(RuntimeError):
    """Base error for a transition that cannot be resolved safely."""


class UnverifiedTransitionError(TransitionResolutionError):
    """A transition has no trustworthy destination coordinate."""


class InvalidTransitionError(TransitionResolutionError):
    """A transition failed a hard validity check."""


class AmbiguousTransitionError(TransitionResolutionError):
    """More than one portal could be selected from the current position."""


def browser_sprite_to_coord(top: float, left: float) -> Tuple[int, int]:
    """Convert a captured browser sprite ``top``/``left`` to (row, column)."""
    row = int(round((float(top) + PEEP_OX) / TILE_PX)) + 1
    col = int(round((float(left) + PEEP_OY - 2) / TILE_PX)) + 1
    return row, col


def coord_to_browser_sprite(row: int, col: int) -> Tuple[float, float]:
    """Convert (row, column) to the captured browser sprite ``top``/``left``."""
    top = (int(row) - 1) * TILE_PX - PEEP_OX
    left = (int(col) - 1) * TILE_PX - PEEP_OY + 2
    return float(top), float(left)


def grid_byte_index(row: int, col: int) -> int:
    """Return the walkgrid byte index used by ``map.js`` ``gridTile``."""
    return (int(row) * GRID_SIZE + int(col)) * 2


def in_bounds(coord: Optional[Sequence[int]]) -> bool:
    if coord is None or len(coord) != 2:
        return False
    row, col = int(coord[0]), int(coord[1])
    return 0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE


def is_on_boundary(direction: str, coord: Sequence[int]) -> bool:
    if not in_bounds(coord):
        return False
    row, col = int(coord[0]), int(coord[1])
    if direction == "north":
        return row == 1
    if direction == "south":
        return row == 31
    if direction == "west":
        return col == 1
    if direction == "east":
        return col == 31
    return False


def opposite_boundary_coord(direction: str, coord: Sequence[int]) -> Tuple[int, int]:
    row, col = int(coord[0]), int(coord[1])
    if direction == "north":
        return 31, col
    if direction == "south":
        return 1, col
    if direction == "west":
        return row, 31
    if direction == "east":
        return row, 1
    raise ValueError(f"Not a seam direction: {direction!r}")


def boundary_ok(direction: str, source: Sequence[int], destination: Sequence[int]) -> bool:
    if direction not in SEAM_DIRECTIONS:
        return False
    return is_on_boundary(direction, source) and tuple(destination) == opposite_boundary_coord(direction, source)


def _tuple_or_none(value: Any) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    raise ValueError(f"Expected a 2-item coordinate, got {value!r}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


@dataclass
class TransitionRecord:
    portal_id: str
    transition_class: str
    source_map: str
    source_coord: Optional[Tuple[int, int]]
    trigger: str
    destination_map: str
    destination_coord: Optional[Tuple[int, int]]
    transition_type: str
    evidence: List[str] = field(default_factory=list)
    verification_status: str = STATUS_UNVERIFIED
    reverse_portal_id: Optional[str] = None
    bidirectional: bool = True
    checks: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    legacy_refs: List[int] = field(default_factory=list)
    legacy_default: Optional[Tuple[int, int]] = None
    legacy_default_status: Optional[str] = None
    observed_entry_spawn: Optional[Tuple[int, int]] = None
    observed_entry_spawn_source: Optional[str] = None

    def __post_init__(self) -> None:
        self.source_coord = _tuple_or_none(self.source_coord)
        self.destination_coord = _tuple_or_none(self.destination_coord)
        self.legacy_default = _tuple_or_none(self.legacy_default)
        self.observed_entry_spawn = _tuple_or_none(self.observed_entry_spawn)
        if self.verification_status not in (STATUS_VERIFIED, STATUS_INVALID, STATUS_UNVERIFIED):
            raise ValueError(f"Invalid verification status: {self.verification_status!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portal_id": self.portal_id,
            "transition_class": self.transition_class,
            "source_map": self.source_map,
            "source_coord": _jsonable(self.source_coord),
            "trigger": self.trigger,
            "destination_map": self.destination_map,
            "destination_coord": _jsonable(self.destination_coord),
            "transition_type": self.transition_type,
            "evidence": list(self.evidence),
            "verification_status": self.verification_status,
            "reverse_portal_id": self.reverse_portal_id,
            "bidirectional": self.bidirectional,
            "checks": _jsonable(self.checks),
            "notes": self.notes,
            "legacy_refs": list(self.legacy_refs),
            "legacy_default": _jsonable(self.legacy_default),
            "legacy_default_status": self.legacy_default_status,
            "observed_entry_spawn": _jsonable(self.observed_entry_spawn),
            "observed_entry_spawn_source": self.observed_entry_spawn_source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransitionRecord":
        return cls(
            portal_id=str(data["portal_id"]),
            transition_class=str(data["transition_class"]),
            source_map=str(data["source_map"]),
            source_coord=_tuple_or_none(data.get("source_coord")),
            trigger=str(data.get("trigger", "")),
            destination_map=str(data["destination_map"]),
            destination_coord=_tuple_or_none(data.get("destination_coord")),
            transition_type=str(data.get("transition_type", "")),
            evidence=list(data.get("evidence", [])),
            verification_status=str(data.get("verification_status", STATUS_UNVERIFIED)),
            reverse_portal_id=data.get("reverse_portal_id"),
            bidirectional=bool(data.get("bidirectional", True)),
            checks=dict(data.get("checks", {})),
            notes=str(data.get("notes", "")),
            legacy_refs=list(data.get("legacy_refs", [])),
            legacy_default=_tuple_or_none(data.get("legacy_default")),
            legacy_default_status=data.get("legacy_default_status"),
            observed_entry_spawn=_tuple_or_none(data.get("observed_entry_spawn")),
            observed_entry_spawn_source=data.get("observed_entry_spawn_source"),
        )


@dataclass
class ValidationResult:
    records: List[Dict[str, Any]]
    counts: Dict[str, Dict[str, int]]
    problems: List[Dict[str, Any]]
    duplicate_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": _jsonable(self.records),
            "counts": _jsonable(self.counts),
            "problems": _jsonable(self.problems),
            "duplicate_ids": list(self.duplicate_ids),
        }


def _empty_class_counts() -> Dict[str, int]:
    return {
        STATUS_VERIFIED: 0,
        STATUS_INVALID: 0,
        STATUS_UNVERIFIED: 0,
        "total": 0,
        "geometry_verified": 0,
        "coordinates_missing": 0,
        "reverse_ok": 0,
        "legacy_default_invalid": 0,
    }


def _grid_tile(grids: Dict[str, WalkGrid], map_name: str, coord: Optional[Sequence[int]]):
    if coord is None or map_name not in grids or not in_bounds(coord):
        return None
    return grids[map_name].get_tile(int(coord[0]), int(coord[1]))


def validate_record(
    record: TransitionRecord,
    grids: Dict[str, WalkGrid],
    by_id: Dict[str, TransitionRecord],
) -> Tuple[str, Dict[str, Any], List[str]]:
    checks: Dict[str, Any] = {}
    reasons: List[str] = []

    checks["source_map_exists"] = record.source_map in grids
    checks["destination_map_exists"] = record.destination_map in grids
    checks["transition_class_known"] = record.transition_class in TRANSITION_CLASSES
    checks["source_coord_present"] = record.source_coord is not None
    checks["destination_coord_present"] = record.destination_coord is not None
    checks["source_coord_in_bounds"] = in_bounds(record.source_coord) if record.source_coord is not None else None
    checks["destination_coord_in_bounds"] = (
        in_bounds(record.destination_coord) if record.destination_coord is not None else None
    )

    if not checks["source_map_exists"]:
        reasons.append("source_map_missing")
    if not checks["destination_map_exists"]:
        reasons.append("destination_map_missing")
    if not checks["transition_class_known"]:
        reasons.append("unknown_transition_class")
    if record.source_coord is not None and not checks["source_coord_in_bounds"]:
        reasons.append("source_coord_out_of_bounds")
    if record.destination_coord is not None and not checks["destination_coord_in_bounds"]:
        reasons.append("destination_coord_out_of_bounds")

    source_tile = _grid_tile(grids, record.source_map, record.source_coord)
    destination_tile = _grid_tile(grids, record.destination_map, record.destination_coord)
    checks["source_walkable"] = bool(source_tile and source_tile.walkable) if source_tile else None
    checks["destination_walkable"] = bool(destination_tile and destination_tile.walkable) if destination_tile else None

    if record.source_coord is not None and source_tile is not None and not source_tile.walkable:
        reasons.append("source_not_walkable")
    if record.destination_coord is not None and destination_tile is not None and not destination_tile.walkable:
        reasons.append("destination_not_walkable")

    reverse = by_id.get(record.reverse_portal_id) if record.reverse_portal_id else None
    checks["reverse_portal_present"] = reverse is not None
    checks["reverse_portal_ok"] = False
    if reverse is not None:
        checks["reverse_portal_ok"] = (
            reverse.source_map == record.destination_map
            and reverse.destination_map == record.source_map
            and reverse.source_coord == record.destination_coord
            and reverse.destination_coord == record.source_coord
        )
        if not checks["reverse_portal_ok"]:
            reasons.append("reverse_portal_coordinate_mismatch")
    elif record.bidirectional:
        reasons.append("reverse_portal_missing")

    if record.transition_class == TRANSITION_CLASS_SEAM:
        direction = record.trigger.replace("move:", "")
        checks["direction"] = direction
        checks["source_on_declared_boundary"] = (
            is_on_boundary(direction, record.source_coord) if record.source_coord is not None else None
        )
        checks["destination_on_opposite_boundary"] = (
            boundary_ok(direction, record.source_coord, record.destination_coord)
            if record.source_coord is not None and record.destination_coord is not None
            else None
        )
        bit_name = DIRECTION_TO_BIT.get(direction)
        checks["direction_bit_name"] = bit_name
        checks["direction_bit_ok"] = (
            bool(source_tile and source_tile.allowed_directions.get(bit_name))
            if source_tile is not None and bit_name
            else None
        )
        checks["landing_observed"] = any("observed_landing" in item for item in record.evidence)
        checks["geometry_verified"] = all(
            checks.get(key) is True
            for key in (
                "source_on_declared_boundary",
                "destination_on_opposite_boundary",
                "source_walkable",
                "destination_walkable",
                "direction_bit_ok",
                "reverse_portal_ok",
            )
        )
        if checks["source_on_declared_boundary"] is False:
            reasons.append("source_not_on_declared_boundary")
        if checks["destination_on_opposite_boundary"] is False:
            reasons.append("destination_not_on_opposite_boundary")
        if checks["direction_bit_ok"] is False:
            reasons.append("source_direction_bit_missing")
    elif record.transition_class == TRANSITION_CLASS_ENTRANCE:
        checks["trigger_observed"] = any("observed_trigger" in item for item in record.evidence)
        checks["landing_observed"] = any("observed_landing" in item for item in record.evidence)
        checks["geometry_verified"] = bool(checks["source_walkable"] and checks["destination_walkable"])
    elif record.transition_class == TRANSITION_CLASS_FLOOR:
        checks["trigger_observed"] = any("observed_trigger" in item for item in record.evidence)
        checks["landing_observed"] = any("observed_landing" in item for item in record.evidence)
        checks["geometry_verified"] = bool(checks["source_walkable"] and checks["destination_walkable"])
        checks["legacy_default_status"] = record.legacy_default_status
    else:
        checks["geometry_verified"] = False

    hard_failure = any(
        reason
        in {
            "source_map_missing",
            "destination_map_missing",
            "unknown_transition_class",
            "source_coord_out_of_bounds",
            "destination_coord_out_of_bounds",
            "source_not_walkable",
            "destination_not_walkable",
            "source_not_on_declared_boundary",
            "destination_not_on_opposite_boundary",
            "source_direction_bit_missing",
            "reverse_portal_missing",
            "reverse_portal_coordinate_mismatch",
        }
        for reason in reasons
    )

    if hard_failure:
        status = STATUS_INVALID
    elif record.source_coord is None or record.destination_coord is None:
        status = STATUS_UNVERIFIED
    elif not checks.get("landing_observed", False):
        status = STATUS_UNVERIFIED
    elif record.transition_class == TRANSITION_CLASS_ENTRANCE and not checks.get("trigger_observed", False):
        status = STATUS_UNVERIFIED
    elif record.transition_class == TRANSITION_CLASS_FLOOR and not checks.get("trigger_observed", False):
        status = STATUS_UNVERIFIED
    else:
        status = STATUS_VERIFIED

    checks["reasons"] = reasons
    return status, checks, reasons


@dataclass
class TransitionRegistry:
    records: List[TransitionRecord]
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def by_id(self) -> Dict[str, TransitionRecord]:
        return {record.portal_id: record for record in self.records}

    def by_class(self, transition_class: str) -> List[TransitionRecord]:
        return [record for record in self.records if record.transition_class == transition_class]

    def for_map(self, map_name: str) -> List[TransitionRecord]:
        return [record for record in self.records if record.source_map == map_name]

    def at(self, map_name: str, coord: Optional[Sequence[int]] = None) -> List[TransitionRecord]:
        records = self.for_map(map_name)
        if coord is None:
            return records
        target = tuple(int(value) for value in coord)
        return [record for record in records if record.source_coord == target]

    def validate(self, grids: Dict[str, WalkGrid]) -> ValidationResult:
        by_id = self.by_id()
        duplicate_ids = sorted(
            {portal_id for portal_id, count in _count_ids(self.records).items() if count > 1}
        )
        record_results: List[Dict[str, Any]] = []
        counts: Dict[str, Dict[str, int]] = {name: _empty_class_counts() for name in TRANSITION_CLASSES}
        problems: List[Dict[str, Any]] = []

        for record in self.records:
            status, checks, reasons = validate_record(record, grids, by_id)
            if record.portal_id in duplicate_ids:
                reasons = list(reasons) + ["duplicate_portal_id"]
                status = STATUS_INVALID
            record.verification_status = status
            record.checks = checks
            bucket = counts.setdefault(record.transition_class, _empty_class_counts())
            bucket["total"] += 1
            bucket[status] += 1
            if checks.get("geometry_verified"):
                bucket["geometry_verified"] += 1
            if record.source_coord is None or record.destination_coord is None:
                bucket["coordinates_missing"] += 1
            if checks.get("reverse_portal_ok"):
                bucket["reverse_ok"] += 1
            if record.legacy_default_status == STATUS_INVALID:
                bucket["legacy_default_invalid"] += 1
            record_results.append(
                {
                    "portal_id": record.portal_id,
                    "transition_class": record.transition_class,
                    "source_map": record.source_map,
                    "source_coord": _jsonable(record.source_coord),
                    "destination_map": record.destination_map,
                    "destination_coord": _jsonable(record.destination_coord),
                    "verification_status": status,
                    "evidence": list(record.evidence),
                    "reasons": reasons,
                    "checks": checks,
                }
            )
            if status == STATUS_INVALID:
                problems.append(
                    {
                        "kind": "invalid_transition",
                        "portal_id": record.portal_id,
                        "transition_class": record.transition_class,
                        "source_map": record.source_map,
                        "destination_map": record.destination_map,
                        "reasons": reasons,
                    }
                )

        return ValidationResult(
            records=record_results,
            counts=counts,
            problems=problems,
            duplicate_ids=duplicate_ids,
        )

    def to_networkx(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        for record in self.records:
            graph.add_node(record.source_map)
            graph.add_node(record.destination_map)

        grouped: Dict[Tuple[str, str], List[TransitionRecord]] = {}
        for record in self.records:
            grouped.setdefault((record.source_map, record.destination_map), []).append(record)

        for (source_map, destination_map), group in grouped.items():
            directions = sorted({record.trigger for record in group})
            statuses = {record.verification_status for record in group}
            if STATUS_INVALID in statuses:
                overall = STATUS_INVALID
            elif STATUS_UNVERIFIED in statuses:
                overall = STATUS_UNVERIFIED
            else:
                overall = STATUS_VERIFIED
            graph.add_edge(
                source_map,
                destination_map,
                direction=directions[0] if len(directions) == 1 else directions,
                portals=[
                    {"from": record.source_coord, "to": record.destination_coord}
                    for record in group
                    if record.source_coord is not None and record.destination_coord is not None
                ],
                portal_ids=[record.portal_id for record in group],
                portal_count=len(group),
                verification_status=overall,
                verified_count=sum(1 for record in group if record.verification_status == STATUS_VERIFIED),
                unverified_count=sum(1 for record in group if record.verification_status == STATUS_UNVERIFIED),
                invalid_count=sum(1 for record in group if record.verification_status == STATUS_INVALID),
                weight=1.0,
            )
        return graph

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "delugerpg.transition_registry",
            "version": self.version,
            "metadata": _jsonable(self.metadata),
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransitionRegistry":
        return cls(
            records=[TransitionRecord.from_dict(item) for item in data.get("records", [])],
            version=str(data.get("version", "1.0.0")),
            metadata=dict(data.get("metadata", {})),
        )

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "TransitionRegistry":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))


def _count_ids(records: Iterable[TransitionRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        counts[record.portal_id] = counts.get(record.portal_id, 0) + 1
    return counts


def _manhattan(a: Sequence[int], b: Sequence[int]) -> int:
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


def resolve_transition(
    registry: TransitionRegistry,
    source_map: str,
    current_coord: Optional[Sequence[int]],
    kind: str,
    direction: Optional[str] = None,
    portal_id: Optional[str] = None,
    allow_unverified: bool = True,
) -> Tuple[TransitionRecord, Dict[str, Any]]:
    """Select the physical transition to use, or raise a clear error.

    ``kind`` is one of ``seam``, ``enter``, ``exit``. ``enter`` prefers a
    dungeon floor ascent and falls back to an overworld entrance; ``exit``
    prefers a dungeon floor descent and falls back to a dungeon exit.
    """
    by_id = registry.by_id()

    if portal_id is not None:
        record = by_id.get(portal_id)
        if record is None:
            raise InvalidTransitionError(f"Unknown portal_id {portal_id!r}")
        if record.source_map != source_map:
            raise InvalidTransitionError(
                f"Portal {portal_id!r} belongs to {record.source_map!r}, not {source_map!r}"
            )
        candidates = [record]
    elif kind == "seam":
        if direction not in SEAM_DIRECTIONS:
            raise InvalidTransitionError(f"Unknown seam direction {direction!r}")
        candidates = [
            record
            for record in registry.records
            if record.transition_class == TRANSITION_CLASS_SEAM
            and record.source_map == source_map
            and record.trigger == f"move:{direction}"
        ]
    elif kind == "enter":
        candidates = [
            record
            for record in registry.records
            if record.source_map == source_map
            and record.transition_class == TRANSITION_CLASS_FLOOR
            and record.transition_type == "ascend"
        ]
        if not candidates:
            candidates = [
                record
                for record in registry.records
                if record.source_map == source_map
                and record.transition_class == TRANSITION_CLASS_ENTRANCE
                and record.transition_type == "entrance"
            ]
    elif kind == "exit":
        candidates = [
            record
            for record in registry.records
            if record.source_map == source_map
            and record.transition_class == TRANSITION_CLASS_FLOOR
            and record.transition_type == "descend"
        ]
        if not candidates:
            candidates = [
                record
                for record in registry.records
                if record.source_map == source_map
                and record.transition_class == TRANSITION_CLASS_ENTRANCE
                and record.transition_type == "exit"
            ]
    else:
        raise InvalidTransitionError(f"Unknown transition kind {kind!r}")

    if not candidates:
        raise InvalidTransitionError(
            f"No {kind!r} transition is defined from {source_map!r}"
        )

    selection = "only_candidate"
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        if current_coord is None:
            raise AmbiguousTransitionError(
                f"{len(candidates)} {kind!r} candidates from {source_map!r} and no current coordinate"
            )
        target = tuple(int(value) for value in current_coord)
        exact = [record for record in candidates if record.source_coord == target]
        if len(exact) == 1:
            chosen = exact[0]
            selection = "exact_source_coord"
        elif len(exact) > 1:
            raise AmbiguousTransitionError(
                f"{len(exact)} {kind!r} portals share source coordinate {target} on {source_map!r}"
            )
        else:
            ranked = sorted(
                candidates,
                key=lambda record: (
                    _manhattan(record.source_coord, target) if record.source_coord is not None else math.inf,
                    record.portal_id,
                ),
            )
            best_distance = _manhattan(ranked[0].source_coord, target) if ranked[0].source_coord is not None else math.inf
            tied = [
                record
                for record in ranked
                if (record.source_coord is not None and _manhattan(record.source_coord, target) == best_distance)
            ]
            if len(tied) > 1:
                raise AmbiguousTransitionError(
                    f"{len(tied)} {kind!r} portals are equally near {target} on {source_map!r}: "
                    + ", ".join(record.portal_id for record in tied)
                )
            chosen = ranked[0]
            selection = "nearest_source_coord"

    if chosen.verification_status == STATUS_INVALID:
        reasons = chosen.checks.get("reasons", []) if chosen.checks else []
        raise InvalidTransitionError(
            f"Portal {chosen.portal_id!r} is INVALID: {', '.join(reasons) or 'no reason recorded'}"
        )
    if chosen.destination_coord is None:
        raise UnverifiedTransitionError(
            f"Portal {chosen.portal_id!r} has no verified destination coordinate; "
            "no first-walkable fallback is permitted"
        )
    if chosen.verification_status != STATUS_VERIFIED and not allow_unverified:
        reasons = chosen.checks.get("reasons", []) if chosen.checks else []
        raise UnverifiedTransitionError(
            f"Portal {chosen.portal_id!r} is {chosen.verification_status}: "
            f"{', '.join(reasons) or 'landing not observed'}"
        )

    info = {
        "portal_id": chosen.portal_id,
        "selection": selection,
        "transition_class": chosen.transition_class,
        "transition_type": chosen.transition_type,
        "verification_status": chosen.verification_status,
        "destination_coord": chosen.destination_coord,
        "reverse_portal_id": chosen.reverse_portal_id,
    }
    return chosen, info
