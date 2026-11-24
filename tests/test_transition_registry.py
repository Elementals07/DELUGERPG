import copy
import json

import networkx as nx
import pytest

from delugerpg.models.transition_registry import (
    DIRECTION_TO_BIT,
    OPPOSITE_DIRECTION,
    SEAM_DIRECTIONS,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    TRANSITION_CLASS_ENTRANCE,
    TRANSITION_CLASS_FLOOR,
    TRANSITION_CLASS_SEAM,
    AmbiguousTransitionError,
    InvalidTransitionError,
    TransitionRecord,
    TransitionRegistry,
    UnverifiedTransitionError,
    browser_sprite_to_coord,
    coord_to_browser_sprite,
    grid_byte_index,
    resolve_transition,
)
from delugerpg.parsers.walkgrid import WalkGrid

REGISTRY_PATH = "data/processed/transition_registry_v1.json"
LEGACY_PATH = "data/processed/transition_registry_v1_legacy_baseline.json"
WALKGRIDS_PATH = "data/raw/delugerpg_all_walkgrids.json"


@pytest.fixture(scope="module")
def registry():
    return TransitionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def grids():
    with open(WALKGRIDS_PATH, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        name: WalkGrid.from_base64(b64, map_name=name)
        for name, b64 in raw.items()
    }


@pytest.fixture(scope="module")
def validated(registry, grids):
    return registry.validate(grids)


def test_coordinate_convention_matches_map_js():
    assert grid_byte_index(0, 0) == 0
    assert grid_byte_index(0, 1) == 2
    assert grid_byte_index(1, 0) == 66
    assert browser_sprite_to_coord(191.0, 105.0) == (14, 8)
    assert coord_to_browser_sprite(14, 8) == (191.0, 105.0)


def test_all_four_seam_directions_have_geometry_and_bits(registry):
    for direction in SEAM_DIRECTIONS:
        records = [
            record
            for record in registry.by_class(TRANSITION_CLASS_SEAM)
            if record.trigger == f"move:{direction}"
        ]
        assert records, f"missing {direction} seam records"
        for record in records[:10]:
            assert record.checks["source_on_declared_boundary"] is True
            assert record.checks["destination_on_opposite_boundary"] is True
            assert record.checks["direction_bit_ok"] is True
            assert record.checks["destination_walkable"] is True
            assert record.checks["reverse_portal_ok"] is True
            assert DIRECTION_TO_BIT[direction] == record.checks["direction_bit_name"]
            assert OPPOSITE_DIRECTION[direction] != direction


def test_validation_counts(validated):
    counts = validated.counts
    assert counts[TRANSITION_CLASS_SEAM]["total"] == 2010
    assert counts[TRANSITION_CLASS_SEAM][STATUS_VERIFIED] == 0
    assert counts[TRANSITION_CLASS_SEAM][STATUS_INVALID] == 0
    assert counts[TRANSITION_CLASS_SEAM][STATUS_UNVERIFIED] == 2010
    assert counts[TRANSITION_CLASS_SEAM]["geometry_verified"] == 2010

    assert counts[TRANSITION_CLASS_ENTRANCE]["total"] == 14
    assert counts[TRANSITION_CLASS_ENTRANCE][STATUS_INVALID] == 4
    assert counts[TRANSITION_CLASS_ENTRANCE][STATUS_UNVERIFIED] == 10
    assert counts[TRANSITION_CLASS_ENTRANCE]["geometry_verified"] == 10

    assert counts[TRANSITION_CLASS_FLOOR]["total"] == 34
    assert counts[TRANSITION_CLASS_FLOOR][STATUS_UNVERIFIED] == 34
    assert counts[TRANSITION_CLASS_FLOOR]["coordinates_missing"] == 34
    assert counts[TRANSITION_CLASS_FLOOR]["legacy_default_invalid"] == 5
    assert validated.duplicate_ids == []


def test_registry_topology(registry):
    graph = registry.to_networkx()
    assert graph.number_of_nodes() == 49
    assert graph.number_of_edges() == 128
    assert nx.number_strongly_connected_components(graph) == 1

    base = nx.DiGraph()
    for record in registry.records:
        if record.transition_class == TRANSITION_CLASS_ENTRANCE:
            continue
        base.add_edge(record.source_map, record.destination_map)
    assert base.number_of_edges() == 114
    assert nx.number_strongly_connected_components(base) == 8


def test_invalid_entrance_defaults_are_explicit(registry):
    by_id = registry.by_id()
    for portal_id in (
        "entrance:overworld21->pkmnmansion1",
        "entrance:overworld21->volcano1",
    ):
        record = by_id[portal_id]
        assert record.verification_status == STATUS_INVALID
        assert "destination_not_walkable" in record.checks["reasons"]

    for portal_id in (
        "exit:pkmnmansion1->overworld21",
        "exit:volcano1->overworld21",
    ):
        record = by_id[portal_id]
        assert record.verification_status == STATUS_INVALID
        assert "source_not_walkable" in record.checks["reasons"]


def test_missing_floor_coordinates_stay_unknown(registry):
    floor = registry.by_id()["floor:pkmnmansion1->pkmnmansion2"]
    assert floor.verification_status == STATUS_UNVERIFIED
    assert floor.source_coord is None
    assert floor.destination_coord is None

    with pytest.raises(UnverifiedTransitionError, match="no first-walkable fallback"):
        resolve_transition(registry, "pkmnmansion1", (16, 16), kind="enter")


def test_invalid_entrance_fails_instead_of_relocating(registry):
    with pytest.raises(InvalidTransitionError, match="entrance:overworld21->pkmnmansion1"):
        resolve_transition(registry, "overworld21", (10, 10), kind="enter")


def test_parallel_entrances_are_independently_selectable(registry):
    entrances = [
        record
        for record in registry.by_class(TRANSITION_CLASS_ENTRANCE)
        if record.source_map == "overworld21" and record.transition_type == "entrance"
    ]
    assert {record.portal_id for record in entrances} == {
        "entrance:overworld21->pkmnmansion1",
        "entrance:overworld21->volcano1",
    }
    assert {record.source_coord for record in entrances} == {(10, 10), (22, 22)}

    selectable = TransitionRegistry.from_dict(registry.to_dict())
    for record in selectable.records:
        if record.source_map == "overworld21" and record.transition_class == TRANSITION_CLASS_ENTRANCE:
            record.verification_status = STATUS_UNVERIFIED

    mansion, mansion_info = resolve_transition(
        selectable, "overworld21", (10, 10), kind="enter", allow_unverified=True
    )
    volcano, volcano_info = resolve_transition(
        selectable, "overworld21", (22, 22), kind="enter", allow_unverified=True
    )
    assert mansion.portal_id == "entrance:overworld21->pkmnmansion1"
    assert volcano.portal_id == "entrance:overworld21->volcano1"
    assert mansion_info["selection"] in ("exact_source_coord", "nearest_source_coord")
    assert volcano_info["selection"] in ("exact_source_coord", "nearest_source_coord")


def test_duplicate_ids_are_invalid_and_counted(registry, grids):
    source = next(
        record
        for record in registry.by_class(TRANSITION_CLASS_SEAM)
        if record.verification_status == STATUS_UNVERIFIED
    )
    duplicate = copy.deepcopy(source)
    duplicate.reverse_portal_id = None
    duplicate.bidirectional = False
    test_registry = TransitionRegistry(records=[source, duplicate])
    result = test_registry.validate(grids)
    assert result.duplicate_ids == [source.portal_id]
    assert result.counts[TRANSITION_CLASS_SEAM]["total"] == 2
    assert result.counts[TRANSITION_CLASS_SEAM][STATUS_INVALID] == 2
    assert all(
        "duplicate_portal_id" in problem["reasons"] for problem in result.problems
    )


def test_one_way_transition_does_not_require_reverse(registry, grids):
    record = copy.deepcopy(registry.by_id()["exit:snowcave1->overworld1"])
    record.reverse_portal_id = None
    record.bidirectional = False
    result = TransitionRegistry(records=[record]).validate(grids)
    assert result.counts[TRANSITION_CLASS_ENTRANCE][STATUS_UNVERIFIED] == 1
    assert result.counts[TRANSITION_CLASS_ENTRANCE][STATUS_INVALID] == 0
    assert "reverse_portal_missing" not in record.checks["reasons"]


def test_destination_walkability_is_a_hard_failure(registry, grids):
    record = copy.deepcopy(registry.by_id()["entrance:overworld21->pkmnmansion1"])
    result = TransitionRegistry(records=[record]).validate(grids)
    assert result.counts[TRANSITION_CLASS_ENTRANCE][STATUS_INVALID] == 1
    assert "destination_not_walkable" in record.checks["reasons"]


def test_legacy_baseline_is_fully_accounted(registry, validated):
    with open(LEGACY_PATH, "r", encoding="utf-8") as handle:
        legacy = json.load(handle)
    summary = legacy["summary"]
    assert summary["legacy_portal_records"] == 1646
    assert summary["legacy_seam_records"] == 1632
    assert summary["legacy_entrance_records"] == 14
    assert sum(summary["dispositions"].values()) == 1646
    assert sum(summary["legacy_statuses"].values()) == 1646
    assert summary["legacy_statuses"]["INVALID"] == 1636
    assert summary["legacy_statuses"]["UNVERIFIED"] == 10
    assert all(
        item["legacy_status"] == "INVALID_AS_LABELED"
        for item in legacy["legacy_portal_records"]
        if item["direction"] in SEAM_DIRECTIONS
    )


def test_legacy_entrance_dispositions_are_complete(validated):
    with open(LEGACY_PATH, "r", encoding="utf-8") as handle:
        legacy = json.load(handle)
    entrances = [
        item
        for item in legacy["legacy_portal_records"]
        if item["direction"] not in SEAM_DIRECTIONS
    ]
    assert len(entrances) == 14
    assert all(item["disposition"] == "superseded_by_canonical" for item in entrances)
    assert {item["legacy_status"] for item in entrances} == {"INVALID", "UNVERIFIED"}


def test_env_does_not_fallback_to_first_walkable():
    from scripts.train_global_49maps import Global49MapEnv, GlobalWorldGraph

    graph = GlobalWorldGraph()
    assert graph.graph.number_of_edges() == 128
    env = Global49MapEnv(graph, max_macro_steps=20)
    env.current_map = "pkmnmansion1"
    env.curr_x, env.curr_y = 16, 16
    _, _, _, info = env.step(9)
    assert info["transition"] is None
    assert "no verified destination coordinate" in info["transition_error"]
    assert env.current_map == "pkmnmansion1"
    assert (env.curr_x, env.curr_y) == (16, 16)

    env.current_map = "overworld21"
    env.curr_x, env.curr_y = 10, 10
    _, _, _, info = env.step(9)
    assert info["transition"] is None
    assert "INVALID" in info["transition_error"]
    assert env.current_map == "overworld21"
    assert (env.curr_x, env.curr_y) == (10, 10)


def test_env_uses_registry_portal_id_for_seam():
    from scripts.train_global_49maps import Global49MapEnv, GlobalWorldGraph

    graph = GlobalWorldGraph()
    env = Global49MapEnv(graph, max_macro_steps=20)
    env.current_map = "overworld1"
    env.curr_x, env.curr_y = 31, 13
    _, _, _, info = env.step(6)
    assert env.current_map == "overworld6"
    assert info["portal_id"] == "seam:overworld1:south:r31c13"
    assert info["transition_status"] == STATUS_UNVERIFIED
    assert (env.curr_x, env.curr_y) == (1, 13)
