import pytest
from delugerpg.models.world_graph import WorldGraph

def test_world_graph_initialization():
    wg = WorldGraph()
    assert wg.graph.number_of_nodes() == 49
    assert wg.graph.number_of_edges() >= 100
    assert "overworld1" in wg.graph
    assert "overworld25" in wg.graph

def test_world_graph_routing():
    wg = WorldGraph()
    # Route across diagonal of 5x5 grid
    route = wg.find_map_route("overworld1", "overworld25")
    assert route is not None
    assert route[0] == "overworld1"
    assert route[-1] == "overworld25"
    assert len(route) == 9  # Manhattan distance in 5x5 grid (4 steps east, 4 steps south)

def test_dungeon_transitions():
    wg = WorldGraph()
    mansion_route = wg.find_map_route("pkmnmansion1", "pkmnmansion4")
    assert mansion_route == ["pkmnmansion1", "pkmnmansion2", "pkmnmansion3", "pkmnmansion4"]

def test_invalid_routing():
    wg = WorldGraph()
    # Unconnected dungeon floor to unrelated dungeon floor
    route = wg.find_map_route("pkmnmansion1", "volcano4")
    assert route is None
