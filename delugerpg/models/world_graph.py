"""
DelugeRPG Cross-Map World Graph.

Models the 49 DelugeRPG maps as a connected topological graph:
- 25 Overworld maps arranged in a 5x5 Cartesian grid with continuous boundary seam warps.
- Special dungeon & interior complexes (Mansion, Tower, Power Plant, Caves, Ruins, Volcano).
- Uses NetworkX for global pathfinding between arbitrary coordinates across different maps.
"""

import json
import os
from typing import Dict, List, Tuple, Optional, Any
import networkx as nx

from delugerpg.parsers.walkgrid import WalkGrid


class WorldGraph:
    """
    Topological multi-map navigation graph for DelugeRPG.
    """

    OVERWORLD_GRID_ROWS = 5
    OVERWORLD_GRID_COLS = 5

    def __init__(self, walkgrids_path: str = "data/raw/delugerpg_all_walkgrids.json"):
        self.walkgrids_path = walkgrids_path
        self.grids: Dict[str, WalkGrid] = {}
        self.graph = nx.DiGraph()
        self._load_grids()
        self._build_overworld_seams()
        self._build_interior_transitions()

    def _load_grids(self):
        with open(self.walkgrids_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for name, b64 in raw.items():
            self.grids[name] = WalkGrid.from_base64(b64, map_name=name)
            # Add node with metadata
            land_c = sum(1 for y in range(33) for x in range(33) if self.grids[name].get_tile(x, y).walkable and not self.grids[name].get_tile(x, y).is_water)
            water_c = sum(1 for y in range(33) for x in range(33) if self.grids[name].get_tile(x, y).is_water)
            self.graph.add_node(
                name,
                map_name=name,
                land_tiles=land_c,
                water_tiles=water_c,
                is_overworld="overworld" in name
            )

    def _build_overworld_seams(self):
        """
        Builds directed warp transitions between adjacent Overworld maps (1..25).
        """
        for num in range(1, 26):
            map_name = f"overworld{num}"
            row = (num - 1) // self.OVERWORLD_GRID_COLS
            col = (num - 1) % self.OVERWORLD_GRID_COLS
            wg = self.grids[map_name]

            # 1. North neighbor (row - 1)
            if row > 0:
                target_num = (row - 1) * self.OVERWORLD_GRID_COLS + col + 1
                target_map = f"overworld{target_num}"
                target_wg = self.grids[target_map]
                seams = []
                for x in range(1, 32):
                    if wg.get_tile(x, 1).walkable and wg.get_tile(x, 1).allowed_directions.get("n"):
                        if target_wg.get_tile(x, 31).walkable:
                            seams.append({"from": (x, 1), "to": (x, 31)})
                if seams:
                    self.graph.add_edge(map_name, target_map, direction="north", portals=seams, weight=1.0)

            # 2. South neighbor (row + 1)
            if row < self.OVERWORLD_GRID_ROWS - 1:
                target_num = (row + 1) * self.OVERWORLD_GRID_COLS + col + 1
                target_map = f"overworld{target_num}"
                target_wg = self.grids[target_map]
                seams = []
                for x in range(1, 32):
                    if wg.get_tile(x, 31).walkable and wg.get_tile(x, 31).allowed_directions.get("s"):
                        if target_wg.get_tile(x, 1).walkable:
                            seams.append({"from": (x, 31), "to": (x, 1)})
                if seams:
                    self.graph.add_edge(map_name, target_map, direction="south", portals=seams, weight=1.0)

            # 3. West neighbor (col - 1)
            if col > 0:
                target_num = row * self.OVERWORLD_GRID_COLS + (col - 1) + 1
                target_map = f"overworld{target_num}"
                target_wg = self.grids[target_map]
                seams = []
                for y in range(1, 32):
                    if wg.get_tile(1, y).walkable and wg.get_tile(1, y).allowed_directions.get("w"):
                        if target_wg.get_tile(31, y).walkable:
                            seams.append({"from": (1, y), "to": (31, y)})
                if seams:
                    self.graph.add_edge(map_name, target_map, direction="west", portals=seams, weight=1.0)

            # 4. East neighbor (col + 1)
            if col < self.OVERWORLD_GRID_COLS - 1:
                target_num = row * self.OVERWORLD_GRID_COLS + (col + 1) + 1
                target_map = f"overworld{target_num}"
                target_wg = self.grids[target_map]
                seams = []
                for y in range(1, 32):
                    if wg.get_tile(31, y).walkable and wg.get_tile(31, y).allowed_directions.get("e"):
                        if target_wg.get_tile(1, y).walkable:
                            seams.append({"from": (31, y), "to": (1, y)})
                if seams:
                    self.graph.add_edge(map_name, target_map, direction="east", portals=seams, weight=1.0)

    def _build_interior_transitions(self):
        """
        Connects sequential dungeon floors (Mansion, Tower, Caves, Volcano, etc.).
        """
        dungeons = [
            ("pkmnmansion", 4),
            ("pkmntower", 3),
            ("powerplant", 3),
            ("rockcave", 4),
            ("snowcave", 4),
            ("unownruins", 2),
            ("volcano", 4),
        ]
        for prefix, count in dungeons:
            for f in range(1, count):
                f1 = f"{prefix}{f}"
                f2 = f"{prefix}{f+1}"
                if f1 in self.grids and f2 in self.grids:
                    self.graph.add_edge(f1, f2, direction="climb_up/advance", portals=[], weight=1.0)
                    self.graph.add_edge(f2, f1, direction="climb_down/return", portals=[], weight=1.0)

    def find_map_route(self, from_map: str, to_map: str) -> Optional[List[str]]:
        """Find the shortest sequence of maps to travel from from_map to to_map."""
        try:
            return nx.shortest_path(self.graph, source=from_map, target=to_map, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def export_graph_summary(self, out_path: str = "data/processed/overworld_graph.json"):
        data = {
            "node_count": self.graph.number_of_nodes(),
            "edge_count": self.graph.number_of_edges(),
            "nodes": {},
            "edges": []
        }
        for n, attrs in self.graph.nodes(data=True):
            data["nodes"][n] = attrs
        for u, v, attrs in self.graph.edges(data=True):
            data["edges"].append({
                "from": u,
                "to": v,
                "direction": attrs.get("direction"),
                "portal_count": len(attrs.get("portals", [])),
                "sample_portals": attrs.get("portals", [])[:3]
            })

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Exported WorldGraph with {data['node_count']} maps and {data['edge_count']} directed transitions to {out_path}")
        return data
