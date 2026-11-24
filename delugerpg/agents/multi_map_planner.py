"""Deterministic local and global navigation over the transition registry."""

from __future__ import annotations

import heapq
import json
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx

from delugerpg.models.transition_registry import (
    DIRECTION_TO_BIT,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    TransitionRecord,
    TransitionRegistry,
)
from delugerpg.parsers.walkgrid import DIR_BITS, DIR_OFFSETS, WalkGrid

Coord = Tuple[int, int]
Node = Tuple[str, int, int]

PLAYABLE_MIN = 1
PLAYABLE_MAX = 31
DEFAULT_TRANSITION_COST = 1


@dataclass
class LocalRoute:
    map_name: str
    start: Coord
    goal: Coord
    path: List[Coord]
    cost: int
    reachable: bool
    reason: Optional[str] = None


@dataclass
class RouteLeg:
    kind: str
    source_map: str
    destination_map: str
    start: Coord
    end: Coord
    path: List[Coord] = field(default_factory=list)
    cost: int = 0
    portal_id: Optional[str] = None
    transition_class: Optional[str] = None
    transition_type: Optional[str] = None
    verification_status: Optional[str] = None
    reverse_portal_id: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source_map": self.source_map,
            "destination_map": self.destination_map,
            "start": list(self.start),
            "end": list(self.end),
            "path": [list(coord) for coord in self.path],
            "cost": self.cost,
            "portal_id": self.portal_id,
            "transition_class": self.transition_class,
            "transition_type": self.transition_type,
            "verification_status": self.verification_status,
            "reverse_portal_id": self.reverse_portal_id,
            "notes": self.notes,
        }


@dataclass
class RouteResult:
    success: bool
    start_map: str
    start_coord: Coord
    goal_map: str
    goal_coord: Coord
    legs: List[RouteLeg] = field(default_factory=list)
    total_cost: Optional[int] = None
    map_sequence: List[str] = field(default_factory=list)
    transition_ids: List[str] = field(default_factory=list)
    uses_unverified: bool = False
    uses_invalid: bool = False
    warnings: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "start_map": self.start_map,
            "start_coord": list(self.start_coord),
            "goal_map": self.goal_map,
            "goal_coord": list(self.goal_coord),
            "legs": [leg.to_dict() for leg in self.legs],
            "total_cost": self.total_cost,
            "map_sequence": list(self.map_sequence),
            "transition_ids": list(self.transition_ids),
            "uses_unverified": self.uses_unverified,
            "uses_invalid": self.uses_invalid,
            "warnings": list(self.warnings),
            "reason": self.reason,
            "diagnostics": _jsonable(self.diagnostics),
        }


@dataclass
class LandingCheck:
    matches_expected: bool
    expected_map: str
    expected_coord: Optional[Coord]
    actual_map: str
    actual_coord: Coord
    registry_status: str
    physically_verified: bool
    reason: str


@dataclass
class ExcludedTransition:
    portal_id: str
    transition_class: str
    source_map: str
    destination_map: str
    verification_status: str
    reason: str


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _coord(value: Sequence[int]) -> Coord:
    return int(value[0]), int(value[1])


def _node(map_name: str, coord: Coord) -> Node:
    return map_name, int(coord[0]), int(coord[1])


def _node_coord(node: Node) -> Coord:
    return int(node[1]), int(node[2])


class LocalNavigator:
    """Validated local movement on the captured 33x33 walkgrids."""

    def __init__(self, grids: Dict[str, WalkGrid]):
        self.grids = grids

    def validate_coord(self, map_name: str, coord: Optional[Sequence[int]]) -> Tuple[bool, str]:
        if map_name not in self.grids:
            return False, "unknown_map"
        if coord is None or len(coord) != 2:
            return False, "coord_missing"
        try:
            row, col = int(coord[0]), int(coord[1])
        except (TypeError, ValueError):
            return False, "coord_invalid"
        if not (PLAYABLE_MIN <= row <= PLAYABLE_MAX and PLAYABLE_MIN <= col <= PLAYABLE_MAX):
            return False, "coord_out_of_playable_bounds"
        tile = self.grids[map_name].get_tile(row, col)
        if tile is None:
            return False, "coord_out_of_bounds"
        if not tile.walkable:
            return False, "coord_not_walkable"
        return True, "ok"

    def validate_step(
        self,
        map_name: str,
        current: Sequence[int],
        nxt: Sequence[int],
    ) -> Tuple[bool, str]:
        current_coord = _coord(current)
        next_coord = _coord(nxt)
        ok, reason = self.validate_coord(map_name, current_coord)
        if not ok:
            return False, f"current_{reason}"
        ok, reason = self.validate_coord(map_name, next_coord)
        if not ok:
            return False, f"next_{reason}"

        delta = (next_coord[0] - current_coord[0], next_coord[1] - current_coord[1])
        direction = None
        for dx, dy, name in DIR_OFFSETS:
            if (dx, dy) == delta:
                direction = name
                break
        if direction is None:
            return False, "not_adjacent"

        tile = self.grids[map_name].get_tile(*current_coord)
        if tile is None:
            return False, "current_tile_missing"
        if not (tile.raw_dirmask & DIR_BITS[direction]):
            return False, f"direction_bit_missing:{direction}"
        return True, "ok"

    def bfs_tree(
        self,
        map_name: str,
        start: Sequence[int],
    ) -> Tuple[Dict[Coord, int], Dict[Coord, Optional[Coord]]]:
        start_coord = _coord(start)
        ok, reason = self.validate_coord(map_name, start_coord)
        if not ok:
            raise ValueError(f"Invalid local BFS start on {map_name!r}: {reason}")

        grid = self.grids[map_name]
        distances: Dict[Coord, int] = {start_coord: 0}
        parents: Dict[Coord, Optional[Coord]] = {start_coord: None}
        queue: deque[Coord] = deque([start_coord])

        while queue:
            current = queue.popleft()
            tile = grid.get_tile(*current)
            if tile is None:
                continue
            for dx, dy, direction in DIR_OFFSETS:
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in distances:
                    continue
                if not (
                    PLAYABLE_MIN <= nxt[0] <= PLAYABLE_MAX
                    and PLAYABLE_MIN <= nxt[1] <= PLAYABLE_MAX
                ):
                    continue
                if not (tile.raw_dirmask & DIR_BITS[direction]):
                    continue
                next_tile = grid.get_tile(*nxt)
                if next_tile is None or not next_tile.walkable:
                    continue
                distances[nxt] = distances[current] + 1
                parents[nxt] = current
                queue.append(nxt)

        return distances, parents

    def validate_path(
        self,
        map_name: str,
        start: Sequence[int],
        goal: Sequence[int],
        path: Sequence[Sequence[int]],
    ) -> List[str]:
        errors: List[str] = []
        if not path:
            return ["empty_path"]
        start_coord = _coord(start)
        goal_coord = _coord(goal)
        path_coords = [_coord(coord) for coord in path]
        if path_coords[0] != start_coord:
            errors.append("path_does_not_start_at_start")
        if path_coords[-1] != goal_coord:
            errors.append("path_does_not_end_at_goal")
        for index in range(len(path_coords) - 1):
            ok, reason = self.validate_step(map_name, path_coords[index], path_coords[index + 1])
            if not ok:
                errors.append(f"step_{index}_to_{index + 1}:{reason}")
        return errors

    def local_route(
        self,
        map_name: str,
        start: Sequence[int],
        goal: Sequence[int],
    ) -> LocalRoute:
        start_coord = _coord(start)
        goal_coord = _coord(goal)
        ok, reason = self.validate_coord(map_name, start_coord)
        if not ok:
            return LocalRoute(map_name, start_coord, goal_coord, [], 0, False, f"invalid_start:{reason}")
        ok, reason = self.validate_coord(map_name, goal_coord)
        if not ok:
            return LocalRoute(map_name, start_coord, goal_coord, [], 0, False, f"invalid_goal:{reason}")
        if start_coord == goal_coord:
            return LocalRoute(map_name, start_coord, goal_coord, [start_coord], 0, True)

        distances, parents = self.bfs_tree(map_name, start_coord)
        if goal_coord not in distances:
            return LocalRoute(map_name, start_coord, goal_coord, [], 0, False, "local_unreachable")

        path: List[Coord] = []
        current: Optional[Coord] = goal_coord
        while current is not None:
            path.append(current)
            current = parents[current]
        path.reverse()
        errors = self.validate_path(map_name, start_coord, goal_coord, path)
        if errors:
            return LocalRoute(
                map_name,
                start_coord,
                goal_coord,
                path,
                0,
                False,
                "invalid_path:" + ";".join(errors),
            )
        return LocalRoute(map_name, start_coord, goal_coord, path, len(path) - 1, True)

    def component_size(self, map_name: str, coord: Sequence[int]) -> Optional[int]:
        start_coord = _coord(coord)
        ok, _ = self.validate_coord(map_name, start_coord)
        if not ok:
            return None
        distances, _ = self.bfs_tree(map_name, start_coord)
        return len(distances)


class GlobalNavigator:
    """Portal-state Dijkstra/A* planner over validated registry transitions."""

    def __init__(
        self,
        registry: TransitionRegistry,
        grids: Dict[str, WalkGrid],
        allow_unverified: bool = True,
        transition_cost: int = DEFAULT_TRANSITION_COST,
    ):
        self.registry = registry
        self.grids = grids
        self.local = LocalNavigator(grids)
        self.allow_unverified = allow_unverified
        self.transition_cost = int(transition_cost)
        self._records_by_id = registry.by_id()
        self._usable: List[TransitionRecord] = []
        self._excluded: List[ExcludedTransition] = []
        self._filter_transitions()
        self._usable_ids = {record.portal_id for record in self._usable}
        self._excluded_by_id = {item.portal_id: item for item in self._excluded}
        self._transitions_from: Dict[Node, List[TransitionRecord]] = {}
        self._relevant: Dict[str, Set[Coord]] = {name: set() for name in grids}
        self._local_cache: Dict[Tuple[str, Coord], Dict[Coord, int]] = {}
        self._build_transition_index()

    @property
    def usable_transitions(self) -> List[TransitionRecord]:
        return list(self._usable)

    @property
    def excluded_transitions(self) -> List[ExcludedTransition]:
        return list(self._excluded)

    def _filter_transitions(self) -> None:
        for record in self.registry.records:
            if record.verification_status == STATUS_INVALID:
                self._exclude(record, "invalid_status")
                continue
            if not self.allow_unverified and record.verification_status != STATUS_VERIFIED:
                self._exclude(record, "unverified_not_allowed")
                continue
            if record.source_coord is None:
                self._exclude(record, "missing_source_coord")
                continue
            if record.destination_coord is None:
                self._exclude(record, "missing_destination_coord")
                continue
            ok, reason = self.local.validate_coord(record.source_map, record.source_coord)
            if not ok:
                self._exclude(record, f"source_{reason}")
                continue
            ok, reason = self.local.validate_coord(record.destination_map, record.destination_coord)
            if not ok:
                self._exclude(record, f"destination_{reason}")
                continue
            if record.transition_class == "overworld_seam":
                direction = record.trigger.replace("move:", "")
                bit_name = DIRECTION_TO_BIT.get(direction)
                if bit_name is None:
                    self._exclude(record, "unknown_seam_direction")
                    continue
                tile = self.grids[record.source_map].get_tile(*record.source_coord)
                if tile is None or not (tile.raw_dirmask & DIR_BITS[bit_name]):
                    self._exclude(record, "source_direction_bit_missing")
                    continue
            self._usable.append(record)

    def _exclude(self, record: TransitionRecord, reason: str) -> None:
        self._excluded.append(
            ExcludedTransition(
                portal_id=record.portal_id,
                transition_class=record.transition_class,
                source_map=record.source_map,
                destination_map=record.destination_map,
                verification_status=record.verification_status,
                reason=reason,
            )
        )

    def _build_transition_index(self) -> None:
        for record in self._usable:
            if record.source_coord is None or record.destination_coord is None:
                continue
            source_node = _node(record.source_map, record.source_coord)
            self._transitions_from.setdefault(source_node, []).append(record)
            self._relevant[record.source_map].add(record.source_coord)
            self._relevant[record.destination_map].add(record.destination_coord)

    def _add_relevant(self, map_name: str, coord: Coord) -> bool:
        if map_name not in self._relevant:
            return False
        if coord in self._relevant[map_name]:
            return False
        self._relevant[map_name].add(coord)
        self._local_cache.clear()
        return True

    def _local_distances(self, map_name: str, source: Coord) -> Dict[Coord, int]:
        key = (map_name, source)
        cached = self._local_cache.get(key)
        if cached is not None:
            return cached
        ok, _ = self.local.validate_coord(map_name, source)
        if not ok:
            self._local_cache[key] = {}
            return {}
        distances, _ = self.local.bfs_tree(map_name, source)
        targets = self._relevant.get(map_name, set())
        result = {
            coord: distance
            for coord, distance in distances.items()
            if coord != source and coord in targets
        }
        self._local_cache[key] = result
        return result

    def rank_portals_from(
        self,
        map_name: str,
        coord: Sequence[int],
        destination_map: Optional[str] = None,
        include_unverified: bool = True,
    ) -> List[Dict[str, Any]]:
        start = _coord(coord)
        ok, _ = self.local.validate_coord(map_name, start)
        if not ok:
            return []
        ranked: List[Dict[str, Any]] = []
        for record in self._usable:
            if record.source_map != map_name or record.source_coord is None:
                continue
            if destination_map is not None and record.destination_map != destination_map:
                continue
            if not include_unverified and record.verification_status != STATUS_VERIFIED:
                continue
            local_route = self.local.local_route(map_name, start, record.source_coord)
            if not local_route.reachable:
                continue
            ranked.append(
                {
                    "portal_id": record.portal_id,
                    "source_coord": record.source_coord,
                    "destination_map": record.destination_map,
                    "destination_coord": record.destination_coord,
                    "local_cost": local_route.cost,
                    "verification_status": record.verification_status,
                    "transition_class": record.transition_class,
                    "transition_type": record.transition_type,
                }
            )
        ranked.sort(key=lambda item: (item["local_cost"], item["portal_id"]))
        return ranked

    def plan(
        self,
        start_map: str,
        start_coord: Sequence[int],
        goal_map: str,
        goal_coord: Sequence[int],
    ) -> RouteResult:
        start = _coord(start_coord)
        goal = _coord(goal_coord)
        ok, reason = self.local.validate_coord(start_map, start)
        if not ok:
            return self._no_route(start_map, start, goal_map, goal, f"invalid_start:{reason}")
        ok, reason = self.local.validate_coord(goal_map, goal)
        if not ok:
            return self._no_route(start_map, start, goal_map, goal, f"invalid_goal:{reason}")

        self._add_relevant(start_map, start)
        self._add_relevant(goal_map, goal)

        if start_map == goal_map:
            local_route = self.local.local_route(start_map, start, goal)
            if not local_route.reachable:
                return self._no_route(
                    start_map,
                    start,
                    goal_map,
                    goal,
                    local_route.reason or "local_unreachable",
                )
            leg = RouteLeg(
                kind="local",
                source_map=start_map,
                destination_map=start_map,
                start=start,
                end=goal,
                path=local_route.path,
                cost=local_route.cost,
            )
            route = RouteResult(
                success=True,
                start_map=start_map,
                start_coord=start,
                goal_map=goal_map,
                goal_coord=goal,
                legs=[leg],
                total_cost=local_route.cost,
                map_sequence=[start_map],
            )
            return self._finish_route(route)

        start_node = _node(start_map, start)
        goal_node = _node(goal_map, goal)
        distances: Dict[Node, int] = {start_node: 0}
        previous: Dict[Node, Tuple[Node, str, Optional[TransitionRecord]]] = {}
        heap: List[Tuple[int, Node]] = [(0, start_node)]

        while heap:
            cost, node = heapq.heappop(heap)
            if cost != distances.get(node):
                continue
            if node == goal_node:
                break

            map_name = node[0]
            current = _node_coord(node)
            for target, local_cost in self._local_distances(map_name, current).items():
                neighbor = _node(map_name, target)
                new_cost = cost + local_cost
                if new_cost < distances.get(neighbor, 10**18):
                    distances[neighbor] = new_cost
                    previous[neighbor] = (node, "local", None)
                    heapq.heappush(heap, (new_cost, neighbor))

            for record in self._transitions_from.get(node, []):
                if record.destination_coord is None:
                    continue
                neighbor = _node(record.destination_map, record.destination_coord)
                new_cost = cost + self.transition_cost
                if new_cost < distances.get(neighbor, 10**18):
                    distances[neighbor] = new_cost
                    previous[neighbor] = (node, "transition", record)
                    heapq.heappush(heap, (new_cost, neighbor))

        if goal_node not in distances:
            return self._no_route(start_map, start, goal_map, goal, "no_route")

        edges: List[Tuple[Node, Node, str, Optional[TransitionRecord]]] = []
        current_node = goal_node
        while current_node != start_node:
            previous_node, kind, record = previous[current_node]
            edges.append((previous_node, current_node, kind, record))
            current_node = previous_node
        edges.reverse()

        legs = self._edges_to_legs(edges)
        route = RouteResult(
            success=True,
            start_map=start_map,
            start_coord=start,
            goal_map=goal_map,
            goal_coord=goal,
            legs=legs,
            total_cost=sum(leg.cost for leg in legs),
            map_sequence=self._map_sequence(start_map, legs),
            transition_ids=[leg.portal_id for leg in legs if leg.kind == "transition" and leg.portal_id],
            uses_unverified=any(
                leg.kind == "transition" and leg.verification_status == STATUS_UNVERIFIED
                for leg in legs
            ),
            uses_invalid=any(
                leg.kind == "transition" and leg.verification_status == STATUS_INVALID
                for leg in legs
            ),
        )
        return self._finish_route(route)

    def _edges_to_legs(
        self,
        edges: Sequence[Tuple[Node, Node, str, Optional[TransitionRecord]]],
    ) -> List[RouteLeg]:
        legs: List[RouteLeg] = []
        index = 0
        while index < len(edges):
            source_node, destination_node, kind, record = edges[index]
            if kind == "transition":
                if record is None:
                    raise RuntimeError("Transition edge is missing its registry record")
                legs.append(
                    RouteLeg(
                        kind="transition",
                        source_map=source_node[0],
                        destination_map=destination_node[0],
                        start=_node_coord(source_node),
                        end=_node_coord(destination_node),
                        cost=self.transition_cost,
                        portal_id=record.portal_id,
                        transition_class=record.transition_class,
                        transition_type=record.transition_type,
                        verification_status=record.verification_status,
                        reverse_portal_id=record.reverse_portal_id,
                        notes=record.notes,
                    )
                )
                index += 1
                continue

            map_name = source_node[0]
            segment_start = _node_coord(source_node)
            segment_end = _node_coord(destination_node)
            cursor = index
            while (
                cursor + 1 < len(edges)
                and edges[cursor + 1][2] == "local"
                and edges[cursor + 1][0][0] == map_name
            ):
                cursor += 1
                segment_end = _node_coord(edges[cursor][1])

            local_route = self.local.local_route(map_name, segment_start, segment_end)
            if not local_route.reachable:
                raise RuntimeError(
                    f"Local route reconstruction failed on {map_name!r}: {local_route.reason}"
                )
            legs.append(
                RouteLeg(
                    kind="local",
                    source_map=map_name,
                    destination_map=map_name,
                    start=segment_start,
                    end=segment_end,
                    path=local_route.path,
                    cost=local_route.cost,
                )
            )
            index = cursor + 1
        return legs

    @staticmethod
    def _map_sequence(start_map: str, legs: Sequence[RouteLeg]) -> List[str]:
        sequence = [start_map]
        for leg in legs:
            if leg.kind == "transition" and leg.destination_map != sequence[-1]:
                sequence.append(leg.destination_map)
        return sequence

    def _finish_route(self, route: RouteResult) -> RouteResult:
        if route.uses_unverified:
            count = sum(
                1
                for leg in route.legs
                if leg.kind == "transition" and leg.verification_status == STATUS_UNVERIFIED
            )
            route.warnings.append(
                f"Route uses {count} UNVERIFIED transition(s); physical landing coordinates were not observed."
            )
        errors = self.validate_route(route)
        if errors:
            return RouteResult(
                success=False,
                start_map=route.start_map,
                start_coord=route.start_coord,
                goal_map=route.goal_map,
                goal_coord=route.goal_coord,
                reason="route_validation_failed:" + ";".join(errors),
                diagnostics={"validation_errors": errors},
            )
        return route

    def validate_route(self, route: RouteResult) -> List[str]:
        errors: List[str] = []
        if not route.success:
            return ["route_not_successful"]
        if not route.legs:
            if route.start_map != route.goal_map or route.start_coord != route.goal_coord:
                errors.append("empty_route_does_not_reach_goal")
            if route.total_cost != 0:
                errors.append("empty_route_has_nonzero_cost")
            return errors

        expected_map = route.start_map
        expected_coord = route.start_coord
        total_cost = 0
        for index, leg in enumerate(route.legs):
            if leg.source_map != expected_map or leg.start != expected_coord:
                errors.append(f"leg_{index}_does_not_start_at_previous_end")
            if leg.kind == "local":
                if leg.source_map != leg.destination_map:
                    errors.append(f"leg_{index}_local_changes_map")
                if not leg.path:
                    errors.append(f"leg_{index}_local_path_empty")
                else:
                    if leg.path[0] != leg.start:
                        errors.append(f"leg_{index}_local_path_start_mismatch")
                    if leg.path[-1] != leg.end:
                        errors.append(f"leg_{index}_local_path_end_mismatch")
                    errors.extend(
                        f"leg_{index}_{error}"
                        for error in self.local.validate_path(
                            leg.source_map,
                            leg.start,
                            leg.end,
                            leg.path,
                        )
                    )
                if leg.cost != max(0, len(leg.path) - 1):
                    errors.append(f"leg_{index}_local_cost_mismatch")
            elif leg.kind == "transition":
                record = self._records_by_id.get(leg.portal_id or "")
                if record is None:
                    errors.append(f"leg_{index}_unknown_portal")
                else:
                    if record.verification_status == STATUS_INVALID:
                        errors.append(f"leg_{index}_invalid_portal")
                    if leg.portal_id not in self._usable_ids:
                        errors.append(f"leg_{index}_portal_not_usable")
                    if record.source_map != leg.source_map or record.source_coord != leg.start:
                        errors.append(f"leg_{index}_portal_source_mismatch")
                    if record.destination_map != leg.destination_map or record.destination_coord != leg.end:
                        errors.append(f"leg_{index}_portal_destination_mismatch")
                if leg.cost != self.transition_cost:
                    errors.append(f"leg_{index}_transition_cost_mismatch")
            else:
                errors.append(f"leg_{index}_unknown_kind")
            total_cost += leg.cost
            expected_map = leg.destination_map
            expected_coord = leg.end

        if expected_map != route.goal_map or expected_coord != route.goal_coord:
            errors.append("route_does_not_end_at_goal")
        if route.total_cost != total_cost:
            errors.append("route_total_cost_mismatch")
        if route.uses_invalid:
            errors.append("route_uses_invalid_transition")
        if route.map_sequence != self._map_sequence(route.start_map, route.legs):
            errors.append("route_map_sequence_mismatch")
        return errors

    def check_transition_landing(
        self,
        record: TransitionRecord,
        actual_map: str,
        actual_coord: Sequence[int],
    ) -> LandingCheck:
        actual = _coord(actual_coord)
        matches = (
            actual_map == record.destination_map
            and record.destination_coord is not None
            and actual == record.destination_coord
        )
        if record.verification_status == STATUS_INVALID:
            reason = "invalid_transition"
        elif not matches:
            reason = "landing_mismatch"
        elif record.verification_status == STATUS_UNVERIFIED:
            reason = "registry_match_but_physical_landing_unverified"
        else:
            reason = "ok"
        return LandingCheck(
            matches_expected=matches,
            expected_map=record.destination_map,
            expected_coord=record.destination_coord,
            actual_map=actual_map,
            actual_coord=actual,
            registry_status=record.verification_status,
            physically_verified=record.verification_status == STATUS_VERIFIED,
            reason=reason,
        )

    def _no_route(
        self,
        start_map: str,
        start: Coord,
        goal_map: str,
        goal: Coord,
        reason: str,
    ) -> RouteResult:
        diagnostics = self._diagnose(start_map, start, goal_map, goal)
        if reason == "no_route":
            reason = diagnostics.get("reason", "no_route")
        elif not reason.startswith("invalid_"):
            diagnostics["planner_reason"] = reason
        return RouteResult(
            success=False,
            start_map=start_map,
            start_coord=start,
            goal_map=goal_map,
            goal_coord=goal,
            reason=reason,
            diagnostics=diagnostics,
        )

    def _diagnose(
        self,
        start_map: str,
        start: Coord,
        goal_map: str,
        goal: Coord,
    ) -> Dict[str, Any]:
        excluded_counts = Counter(item.reason for item in self._excluded)
        diagnostics: Dict[str, Any] = {
            "allow_unverified": self.allow_unverified,
            "usable_transition_count": len(self._usable),
            "excluded_transition_count": len(self._excluded),
            "excluded_by_reason": dict(excluded_counts),
        }

        if start_map not in self.grids:
            diagnostics["reason"] = "unknown_start_map"
            return diagnostics
        if goal_map not in self.grids:
            diagnostics["reason"] = "unknown_goal_map"
            return diagnostics

        if start_map == goal_map:
            local_route = self.local.local_route(start_map, start, goal)
            diagnostics["reason"] = local_route.reason or "local_unreachable"
            diagnostics["start_component_size"] = self.local.component_size(start_map, start)
            diagnostics["goal_component_size"] = self.local.component_size(start_map, goal)
            return diagnostics

        graph_all = self._map_graph(include_invalid=True)
        graph_non_invalid = self._map_graph(include_invalid=False)

        if not self._has_map_path(graph_all, start_map, goal_map):
            diagnostics["reason"] = "destination_map_not_topologically_reachable"
            return diagnostics

        if not self._has_map_path(graph_non_invalid, start_map, goal_map):
            path = nx.shortest_path(graph_all, start_map, goal_map)
            blocking = self._blocking_transitions(graph_all, path, status=STATUS_INVALID)
            diagnostics["reason"] = "blocked_by_invalid_transitions"
            diagnostics["topological_path"] = path
            diagnostics["blocking_portal_ids"] = [record.portal_id for record in blocking]
            diagnostics["blocking_transitions"] = [self._transition_summary(record) for record in blocking]
            return diagnostics

        path = nx.shortest_path(graph_non_invalid, start_map, goal_map)
        diagnostics["topological_path"] = path
        blocking_edges: List[Dict[str, Any]] = []
        for source, destination in zip(path, path[1:]):
            edge_records = graph_non_invalid[source][destination]["records"]
            if any(record.portal_id in self._usable_ids for record in edge_records):
                continue
            blocking_edges.append(
                {
                    "source_map": source,
                    "destination_map": destination,
                    "transitions": [
                        self._transition_summary(record)
                        for record in edge_records
                    ],
                }
            )

        if blocking_edges:
            blocking_ids = [
                item["portal_id"]
                for edge in blocking_edges
                for item in edge["transitions"]
            ]
            reasons = {
                self._excluded_by_id[item["portal_id"]].reason
                for edge in blocking_edges
                for item in edge["transitions"]
                if item["portal_id"] in self._excluded_by_id
            }
            if reasons and all(reason in {"missing_source_coord", "missing_destination_coord"} for reason in reasons):
                diagnostics["reason"] = "blocked_by_missing_coordinates"
            elif "unverified_not_allowed" in reasons:
                diagnostics["reason"] = "unverified_not_allowed"
            else:
                diagnostics["reason"] = "blocked_by_unusable_transitions"
            diagnostics["blocking_portal_ids"] = blocking_ids
            diagnostics["blocking_edges"] = blocking_edges
            return diagnostics

        diagnostics["reason"] = "no_usable_route_due_to_local_disconnections"
        diagnostics["start_component_size"] = self.local.component_size(start_map, start)
        diagnostics["goal_component_size"] = self.local.component_size(goal_map, goal)
        return diagnostics

    def _map_graph(self, include_invalid: bool) -> nx.DiGraph:
        graph = nx.DiGraph()
        for map_name in self.grids:
            graph.add_node(map_name)
        for record in self.registry.records:
            if not include_invalid and record.verification_status == STATUS_INVALID:
                continue
            if not graph.has_edge(record.source_map, record.destination_map):
                graph.add_edge(record.source_map, record.destination_map, records=[])
            graph[record.source_map][record.destination_map]["records"].append(record)
        return graph

    @staticmethod
    def _has_map_path(graph: nx.DiGraph, start_map: str, goal_map: str) -> bool:
        if start_map not in graph or goal_map not in graph:
            return False
        return nx.has_path(graph, start_map, goal_map)

    def _blocking_transitions(
        self,
        graph: nx.DiGraph,
        path: Sequence[str],
        status: str,
    ) -> List[TransitionRecord]:
        blocking: List[TransitionRecord] = []
        for source, destination in zip(path, path[1:]):
            for record in graph[source][destination]["records"]:
                if record.verification_status == status:
                    blocking.append(record)
        return blocking

    @staticmethod
    def _transition_summary(record: TransitionRecord) -> Dict[str, Any]:
        return {
            "portal_id": record.portal_id,
            "transition_class": record.transition_class,
            "source_map": record.source_map,
            "source_coord": list(record.source_coord) if record.source_coord is not None else None,
            "destination_map": record.destination_map,
            "destination_coord": (
                list(record.destination_coord) if record.destination_coord is not None else None
            ),
            "verification_status": record.verification_status,
            "transition_type": record.transition_type,
        }

    def describe_route(self, route: RouteResult, include_ascii: bool = False) -> str:
        lines = [
            f"Route: {route.start_map} {tuple(route.start_coord)} -> "
            f"{route.goal_map} {tuple(route.goal_coord)}",
        ]
        if not route.success:
            lines.append(f"Result: NO ROUTE ({route.reason})")
            diagnostics = route.diagnostics
            if diagnostics:
                lines.append(f"Diagnostic reason: {diagnostics.get('reason', route.reason)}")
                for key in (
                    "usable_transition_count",
                    "excluded_transition_count",
                    "excluded_by_reason",
                    "topological_path",
                    "start_component_size",
                    "goal_component_size",
                ):
                    if key in diagnostics:
                        lines.append(f"  {key}: {json.dumps(_jsonable(diagnostics[key]), sort_keys=True)}")
                blocking = diagnostics.get("blocking_portal_ids", [])
                if blocking:
                    sample = ", ".join(blocking[:5])
                    suffix = f" ... (+{len(blocking) - 5} more)" if len(blocking) > 5 else ""
                    lines.append(f"  blocking_portal_ids: {len(blocking)} portal(s): {sample}{suffix}")
            return "\n".join(lines)

        local_steps = sum(leg.cost for leg in route.legs if leg.kind == "local")
        transition_count = sum(1 for leg in route.legs if leg.kind == "transition")
        lines.append(
            f"Result: OK; {local_steps} tile move(s), {transition_count} transition(s), "
            f"total cost {route.total_cost}"
        )
        lines.append("Maps: " + " -> ".join(route.map_sequence))
        if route.transition_ids:
            lines.append("Portals: " + ", ".join(route.transition_ids))
        for warning in route.warnings:
            lines.append(f"WARNING: {warning}")
        for index, leg in enumerate(route.legs):
            if leg.kind == "local":
                lines.append(
                    f"  {index + 1}. local {leg.source_map}: {tuple(leg.start)} -> "
                    f"{tuple(leg.end)} ({leg.cost} step(s))"
                )
                if include_ascii:
                    lines.append(self.ascii_segment(leg))
            else:
                lines.append(
                    f"  {index + 1}. transition {leg.portal_id} [{leg.verification_status}]: "
                    f"{leg.source_map} {tuple(leg.start)} -> "
                    f"{leg.destination_map} {tuple(leg.end)}"
                )
        return "\n".join(lines)

    def ascii_segment(self, leg: RouteLeg) -> str:
        grid = self.grids[leg.source_map]
        lines = [list(line) for line in grid.to_ascii_map().splitlines()]
        for row, col in leg.path:
            if 0 <= row < grid.HEIGHT and 0 <= col < grid.WIDTH:
                lines[row][col] = "*"
        start_row, start_col = leg.start
        end_row, end_col = leg.end
        if 0 <= start_row < grid.HEIGHT and 0 <= start_col < grid.WIDTH:
            lines[start_row][start_col] = "S"
        if 0 <= end_row < grid.HEIGHT and 0 <= end_col < grid.WIDTH:
            lines[end_row][end_col] = "G"
        return "\n".join("".join(line) for line in lines)


def load_navigation_data(
    registry_path: str = "data/processed/transition_registry_v1.json",
    walkgrid_path: str = "data/raw/delugerpg_all_walkgrids.json",
) -> Tuple[TransitionRegistry, Dict[str, WalkGrid]]:
    registry = TransitionRegistry.load(registry_path)
    with open(walkgrid_path, "r", encoding="utf-8") as handle:
        raw_grids = json.load(handle)
    grids = {
        map_name: WalkGrid.from_base64(b64, map_name=map_name)
        for map_name, b64 in raw_grids.items()
    }
    return registry, grids
