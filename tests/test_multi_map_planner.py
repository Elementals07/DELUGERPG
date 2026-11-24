"""Phase 2 tests for deterministic local and global navigation."""

import json
from collections import Counter

import pytest

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
from delugerpg.parsers.walkgrid import WalkGrid

REGISTRY_PATH = "data/processed/transition_registry_v1.json"
WALKGRID_PATH = "data/raw/delugerpg_all_walkgrids.json"


@pytest.fixture(scope="session")
def registry():
    return TransitionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="session")
def grids():
    with open(WALKGRID_PATH, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        map_name: WalkGrid.from_base64(b64, map_name=map_name)
        for map_name, b64 in raw.items()
    }


@pytest.fixture(scope="session")
def local(grids):
    return LocalNavigator(grids)


@pytest.fixture(scope="session")
def navigator(registry, grids):
    return GlobalNavigator(registry, grids, allow_unverified=True)


@pytest.fixture(scope="session")
def strict_navigator(registry, grids):
    return GlobalNavigator(registry, grids, allow_unverified=False)


def walkable_coords(grid):
    return [
        (tile.x, tile.y)
        for row in grid.tiles
        for tile in row
        if tile.walkable and 1 <= tile.x <= 31 and 1 <= tile.y <= 31
    ]


def first_non_walkable_coord(grid):
    for row in grid.tiles:
        for tile in row:
            if 1 <= tile.x <= 31 and 1 <= tile.y <= 31 and not tile.walkable:
                return tile.x, tile.y
    raise AssertionError("No non-walkable playable coordinate found")


def simulated_ow21_registry(registry):
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
            "SIMULATED Phase 2 test landing: observed dungeon entry spawn, "
            "not a physically observed portal landing."
        )
    return TransitionRegistry.from_dict(data)


def test_transition_statuses_are_distinguished(navigator, registry):
    usable = navigator.usable_transitions
    excluded = navigator.excluded_transitions
    assert len(usable) == 2020
    assert len(excluded) == 38

    usable_counts = Counter((record.transition_class, record.verification_status) for record in usable)
    assert usable_counts[("overworld_seam", STATUS_UNVERIFIED)] == 2010
    assert usable_counts[("overworld_to_dungeon", STATUS_UNVERIFIED)] == 10
    assert not any(record.verification_status == STATUS_VERIFIED for record in registry.records)
    assert not any(record.verification_status == STATUS_INVALID for record in usable)

    excluded_counts = Counter(item.reason for item in excluded)
    assert excluded_counts["invalid_status"] == 4
    assert excluded_counts["missing_source_coord"] == 34
    assert all(item.reason != "invalid_status" or item.verification_status == STATUS_INVALID for item in excluded)


def test_local_routes_across_all_49_maps(local, grids):
    routed_maps = 0
    for map_name, grid in grids.items():
        walkable = walkable_coords(grid)
        start = walkable[0]
        distances, _ = local.bfs_tree(map_name, start)
        goal = next(coord for coord in walkable if coord in distances and coord != start)
        route = local.local_route(map_name, start, goal)
        assert route.reachable, f"{map_name}: {route.reason}"
        assert route.path[0] == start
        assert route.path[-1] == goal
        assert route.cost == len(route.path) - 1
        assert local.validate_path(map_name, start, goal, route.path) == []

        reference = grid.find_path(start[0], start[1], goal[0], goal[1])
        assert reference is not None
        assert len(reference) == route.cost
        routed_maps += 1
    assert routed_maps == 49


def test_directional_movement_restrictions(local, grids):
    tile = grids["overworld15"].get_tile(21, 15)
    assert tile.allowed_directions["w"] is True
    assert tile.allowed_directions["e"] is True
    assert tile.allowed_directions["n"] is False
    assert tile.allowed_directions["s"] is False

    ok, reason = local.validate_step("overworld15", (21, 15), (21, 16))
    assert ok, reason
    ok, reason = local.validate_step("overworld15", (21, 15), (21, 14))
    assert ok, reason
    ok, reason = local.validate_step("overworld15", (21, 15), (20, 15))
    assert not ok
    assert reason in {"direction_bit_missing:n", "next_coord_not_walkable"}
    ok, reason = local.validate_step("overworld15", (21, 15), (22, 15))
    assert not ok
    assert reason in {"direction_bit_missing:s", "next_coord_not_walkable"}


def test_obstacle_avoidance(local, grids):
    found_detour = False
    for map_name, grid in grids.items():
        walkable = walkable_coords(grid)
        start = walkable[0]
        for goal in walkable[1:30]:
            route = local.local_route(map_name, start, goal)
            if not route.reachable:
                continue
            manhattan = abs(goal[0] - start[0]) + abs(goal[1] - start[1])
            if route.cost > manhattan:
                found_detour = True
                for coord in route.path:
                    tile = grid.get_tile(*coord)
                    assert tile is not None and tile.walkable
                assert local.validate_path(map_name, start, goal, route.path) == []
                break
        if found_detour:
            break
    assert found_detour, "Expected at least one route with an obstacle detour"

    grid = grids["overworld1"]
    blocked = first_non_walkable_coord(grid)
    route = local.local_route("overworld1", (20, 13), blocked)
    assert not route.reachable
    assert route.reason == "invalid_goal:coord_not_walkable"


def test_unreachable_walkable_coordinates(local, grids):
    grid = grids["overworld2"]
    walkable = walkable_coords(grid)
    start = walkable[0]
    distances, _ = local.bfs_tree("overworld2", start)
    unreachable = next(coord for coord in walkable if coord not in distances)
    route = local.local_route("overworld2", start, unreachable)
    assert not route.reachable
    assert route.reason == "local_unreachable"


def test_same_map_route(navigator):
    route = navigator.plan("overworld1", (20, 13), "overworld1", (24, 16))
    assert route.success, route.reason
    assert route.total_cost == 4
    assert route.map_sequence == ["overworld1"]
    assert route.transition_ids == []
    assert route.uses_unverified is False
    assert len(route.legs) == 1
    assert route.legs[0].kind == "local"
    assert navigator.validate_route(route) == []


def test_overworld_seam_route(navigator):
    route = navigator.plan("overworld1", (20, 13), "overworld6", (10, 10))
    assert route.success, route.reason
    assert route.uses_unverified is True
    assert route.map_sequence == ["overworld1", "overworld6"]
    assert len(route.transition_ids) == 1
    assert route.transition_ids[0].startswith("seam:overworld1:")
    assert route.warnings
    assert navigator.validate_route(route) == []

    transition_leg = next(leg for leg in route.legs if leg.kind == "transition")
    assert transition_leg.verification_status == STATUS_UNVERIFIED
    assert transition_leg.start == navigator._records_by_id[transition_leg.portal_id].source_coord
    assert transition_leg.end == navigator._records_by_id[transition_leg.portal_id].destination_coord

    local_legs = [leg for leg in route.legs if leg.kind == "local"]
    assert local_legs[0].end == transition_leg.start
    assert local_legs[-1].start == transition_leg.end


def test_route_requires_unverified_transition_and_strict_mode(navigator, strict_navigator):
    route = navigator.plan("overworld1", (20, 13), "overworld6", (10, 10))
    assert route.success
    assert route.uses_unverified

    strict = strict_navigator.plan("overworld1", (20, 13), "overworld6", (10, 10))
    assert not strict.success
    assert strict.reason == "unverified_not_allowed"
    assert strict.diagnostics["reason"] == "unverified_not_allowed"
    assert strict.diagnostics["excluded_by_reason"]["unverified_not_allowed"] > 0


def test_invalid_transition_excluded(navigator):
    for goal_map, goal_coord in (("pkmnmansion1", (20, 21)), ("volcano1", (20, 15))):
        route = navigator.plan("overworld21", (10, 10) if goal_map == "pkmnmansion1" else (22, 22), goal_map, goal_coord)
        assert not route.success
        assert route.reason == "blocked_by_invalid_transitions"
        assert route.uses_invalid is False
        assert route.legs == []
        assert route.diagnostics["blocking_portal_ids"]
        assert all(
            "overworld21" in portal_id and goal_map in portal_id
            for portal_id in route.diagnostics["blocking_portal_ids"]
        )

    invalid_ids = {
        "entrance:overworld21->pkmnmansion1",
        "exit:pkmnmansion1->overworld21",
        "entrance:overworld21->volcano1",
        "exit:volcano1->overworld21",
    }
    assert invalid_ids.isdisjoint({record.portal_id for record in navigator.usable_transitions})
    for portal_id in invalid_ids:
        record = navigator._records_by_id[portal_id]
        check = navigator.check_transition_landing(record, record.destination_map, record.destination_coord)
        assert check.matches_expected
        assert check.physically_verified is False
        assert check.reason == "invalid_transition"


def test_ow21_parallel_entrance_selection_simulated(registry, grids):
    simulated = simulated_ow21_registry(registry)
    navigator = GlobalNavigator(simulated, grids, allow_unverified=True)

    mansion = navigator.plan("overworld21", (10, 10), "pkmnmansion1", (20, 21))
    assert mansion.success, mansion.reason
    assert mansion.transition_ids == ["entrance:overworld21->pkmnmansion1"]

    volcano = navigator.plan("overworld21", (22, 22), "volcano1", (20, 15))
    assert volcano.success, volcano.reason
    assert volcano.transition_ids == ["entrance:overworld21->volcano1"]

    from_mansion_side = navigator.rank_portals_from("overworld21", (10, 10))
    from_volcano_side = navigator.rank_portals_from("overworld21", (22, 22))
    assert from_mansion_side[0]["portal_id"] == "entrance:overworld21->pkmnmansion1"
    assert from_volcano_side[0]["portal_id"] == "entrance:overworld21->volcano1"
    assert from_mansion_side[0]["local_cost"] == 0
    assert from_volcano_side[0]["local_cost"] == 0


def test_missing_floor_coordinates_blocked(navigator):
    route = navigator.plan("snowcave1", (11, 11), "snowcave2", (19, 20))
    assert not route.success
    assert route.reason == "blocked_by_missing_coordinates"
    assert "floor:snowcave1->snowcave2" in route.diagnostics["blocking_portal_ids"]
    assert route.legs == []
    assert route.total_cost is None


def test_start_and_goal_validation(navigator, grids):
    route = navigator.plan("overworld1", (0, 0), "overworld1", (20, 13))
    assert not route.success
    assert route.reason.startswith("invalid_start:coord_out_of_playable_bounds")

    route = navigator.plan("overworld1", (20, 13), "overworld1", (0, 0))
    assert not route.success
    assert route.reason.startswith("invalid_goal:coord_out_of_playable_bounds")

    route = navigator.plan("not_a_map", (1, 1), "overworld1", (20, 13))
    assert not route.success
    assert route.reason.startswith("invalid_start:unknown_map")

    route = navigator.plan("overworld1", (20, 13), "not_a_map", (1, 1))
    assert not route.success
    assert route.reason.startswith("invalid_goal:unknown_map")

    blocked = first_non_walkable_coord(grids["overworld1"])
    route = navigator.plan("overworld1", (20, 13), "overworld1", blocked)
    assert not route.success
    assert route.reason.startswith("invalid_goal:coord_not_walkable")
    assert route.legs == []


def test_route_replay_uses_unverified_transitions(navigator):
    route = navigator.plan("overworld1", (20, 13), "overworld11", (20, 15))
    assert route.success, route.reason
    assert len(route.transition_ids) == 2
    assert route.uses_unverified is True
    assert navigator.validate_route(route) == []

    current_map = route.start_map
    current_coord = route.start_coord
    for leg in route.legs:
        assert leg.source_map == current_map
        assert leg.start == current_coord
        if leg.kind == "local":
            assert leg.path[0] == current_coord
            for first, second in zip(leg.path, leg.path[1:]):
                ok, reason = navigator.local.validate_step(current_map, first, second)
                assert ok, reason
            current_coord = leg.end
        else:
            record = navigator._records_by_id[leg.portal_id]
            check = navigator.check_transition_landing(record, leg.destination_map, leg.end)
            assert check.matches_expected
            assert check.physically_verified is False
            assert check.registry_status == STATUS_UNVERIFIED
            current_map = leg.destination_map
            current_coord = leg.end

    assert current_map == route.goal_map
    assert current_coord == route.goal_coord
    assert route.total_cost == sum(leg.cost for leg in route.legs)


def test_route_diagnostics_are_meaningful(navigator):
    local_unreachable = navigator.plan("overworld2", (1, 1), "overworld2", (1, 22))
    assert not local_unreachable.success
    assert local_unreachable.reason == "local_unreachable"
    assert local_unreachable.diagnostics["start_component_size"] != local_unreachable.diagnostics["goal_component_size"]

    unknown = navigator.plan("not_a_map", (1, 1), "overworld1", (20, 13))
    assert unknown.diagnostics["reason"] == "unknown_start_map"

    floor = navigator.plan("snowcave1", (11, 11), "snowcave2", (19, 20))
    assert floor.reason == "blocked_by_missing_coordinates"
    assert floor.diagnostics["blocking_edges"]
