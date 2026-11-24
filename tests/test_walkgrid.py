import re
import pytest
from delugerpg.parsers.walkgrid import WalkGrid

SAMPLE_WALKGRID_FILE = "DELUGERPG_Consolidated_Reference/source/javascript/inline/inline/script_003__084447d5c3.js"

def get_sample_b64():
    with open(SAMPLE_WALKGRID_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    match = re.search(r'"([A-Za-z0-9+/=]{100,})"', text)
    assert match is not None
    return match.group(1)

def test_walkgrid_decode():
    b64_str = get_sample_b64()
    grid = WalkGrid.from_base64(b64_str, map_name="overworld12")
    assert grid.HEIGHT == 33
    assert grid.WIDTH == 33
    assert len(grid.tiles) == 33
    assert len(grid.tiles[0]) == 33

    # Check that some tiles are walkable and some are water/blocked
    walkable_tiles = [t for row in grid.tiles for t in row if t.walkable]
    assert len(walkable_tiles) > 0

    water_tiles = [t for row in grid.tiles for t in row if t.is_water]
    assert len(water_tiles) > 0

def test_walkgrid_pathfinding():
    b64_str = get_sample_b64()
    grid = WalkGrid.from_base64(b64_str, map_name="overworld12")

    # Find two walkable points
    walkable = [(t.x, t.y) for row in grid.tiles for t in row if t.walkable and 1 <= t.x <= 31 and 1 <= t.y <= 31]
    assert len(walkable) >= 2

    start = walkable[0]
    dest = walkable[min(10, len(walkable) - 1)]

    path = grid.find_path(start[0], start[1], dest[0], dest[1])
    # Path should either be a list of steps or None if disconnected
    if path is not None:
        assert isinstance(path, list)
        if start != dest:
            assert len(path) > 0
            assert path[-1] == dest

def test_walkgrid_same_start_and_dest():
    b64_str = get_sample_b64()
    grid = WalkGrid.from_base64(b64_str, map_name="overworld12")
    path = grid.find_path(5, 5, 5, 5)
    assert path == []

def test_walkgrid_invalid_length():
    with pytest.raises(ValueError):
        WalkGrid(b"short bytes")

def test_all_49_maps_ingested_and_decodable():
    import json
    with open("data/raw/delugerpg_all_walkgrids.json", "r") as f:
        maps = json.load(f)
    assert len(maps) == 49
    for map_name, b64 in maps.items():
        grid = WalkGrid.from_base64(b64, map_name=map_name)
        assert grid.HEIGHT == 33
        assert grid.WIDTH == 33
        assert len(grid.tiles) == 33
        assert len(grid.tiles[0]) == 33
        # Every map must have at least some walkable tiles
        walkable = [t for row in grid.tiles for t in row if t.walkable]
        assert len(walkable) > 100

def test_directional_bridge_restriction():
    # overworld15 has known horizontal bridges at (21, 14..18)
    import json
    with open("data/raw/delugerpg_all_walkgrids.json", "r") as f:
        maps = json.load(f)
    grid = WalkGrid.from_base64(maps["overworld15"], map_name="overworld15")
    bridge_tile = grid.get_tile(21, 15)
    assert bridge_tile is not None
    assert bridge_tile.raw_dirmask == 12  # West (4) + East (8) = 12
    assert bridge_tile.allowed_directions["w"] is True
    assert bridge_tile.allowed_directions["e"] is True
    assert bridge_tile.allowed_directions["n"] is False
    assert bridge_tile.allowed_directions["s"] is False

