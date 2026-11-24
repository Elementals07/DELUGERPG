"""
Walkgrid Decoder and Pathfinding for DelugeRPG maps.
Corresponds to map.js mechanics (gridTile, setWalkgrid, findPath, PEEP_DIRBITS).
"""

import base64
from typing import Dict, List, Optional, Tuple, Set
from collections import deque
from ..core.types import WalkTile

# Direction bitmasks from map.js PEEP_DIRBITS
DIR_BITS = {
    "n": 1,
    "s": 2,
    "w": 4,
    "e": 8,
    "nw": 16,
    "ne": 32,
    "sw": 64,
    "se": 128
}

# Offsets corresponding to map.js PEEP_DIRS:
# [[-1,0,"n"],[1,0,"s"],[0,-1,"w"],[0,1,"e"],[-1,-1,"nw"],[-1,1,"ne"],[1,-1,"sw"],[1,1,"se"]]
DIR_OFFSETS = [
    (-1, 0, "n"),
    (1, 0, "s"),
    (0, -1, "w"),
    (0, 1, "e"),
    (-1, -1, "nw"),
    (-1, 1, "ne"),
    (1, -1, "sw"),
    (1, 1, "se")
]


class WalkGrid:
    """
    Represents a 33x33 tile grid for a DelugeRPG map.
    """
    WIDTH = 33
    HEIGHT = 33
    EXPECTED_BYTES = 33 * 33 * 2  # 2178 bytes

    def __init__(self, raw_bytes: bytes, map_name: str = "unknown"):
        if len(raw_bytes) != self.EXPECTED_BYTES:
            raise ValueError(f"Invalid walkgrid byte length: expected {self.EXPECTED_BYTES}, got {len(raw_bytes)}")
        self.raw_bytes = raw_bytes
        self.map_name = map_name
        self.tiles: List[List[WalkTile]] = []
        self._decode()

    @classmethod
    def from_base64(cls, b64_str: str, map_name: str = "unknown") -> "WalkGrid":
        raw = base64.b64decode(b64_str.strip())
        return cls(raw, map_name=map_name)

    def _decode(self):
        self.tiles = []
        for x in range(self.HEIGHT):
            row: List[WalkTile] = []
            for y in range(self.WIDTH):
                idx = (x * self.WIDTH + y) * 2
                b0 = self.raw_bytes[idx]
                b1 = self.raw_bytes[idx + 1]

                walkable = bool(b0 & 1)
                is_water = bool(b0 & 2)

                allowed = {}
                for d_name, d_bit in DIR_BITS.items():
                    allowed[d_name] = bool(b1 & d_bit)

                row.append(WalkTile(
                    x=x,
                    y=y,
                    walkable=walkable,
                    is_water=is_water,
                    raw_byte0=b0,
                    raw_dirmask=b1,
                    allowed_directions=allowed
                ))
            self.tiles.append(row)

    def get_tile(self, x: int, y: int) -> Optional[WalkTile]:
        if 0 <= x < self.HEIGHT and 0 <= y < self.WIDTH:
            return self.tiles[x][y]
        return None

    def find_path(self, start_x: int, start_y: int, dest_x: int, dest_y: int) -> Optional[List[Tuple[int, int]]]:
        """
        Replicates client-side findPath(b, c, d, a) from map.js exactly.
        Returns a list of (x, y) coordinates from the first step to the destination,
        or empty list if start == dest, or None if no path found.
        Note: map.js restricts exploration to bounds 1 <= x <= 31 and 1 <= y <= 31.
        """
        if start_x == dest_x and start_y == dest_y:
            return []

        visited: Set[Tuple[int, int]] = set()
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        queue: deque = deque([(start_x, start_y)])
        visited.add((start_x, start_y))

        found = False

        while queue:
            curr_x, curr_y = queue.popleft()
            if curr_x == dest_x and curr_y == dest_y:
                found = True
                break

            curr_tile = self.get_tile(curr_x, curr_y)
            # map.js: h = h ? (h[0] & 1 ? h[1] : 255) : 255
            if curr_tile:
                dir_mask = curr_tile.raw_dirmask if (curr_tile.raw_byte0 & 1) else 255
            else:
                dir_mask = 255

            for dx, dy, d_name in DIR_OFFSETS:
                nx, ny = curr_x + dx, curr_y + dy
                # map.js bound restriction: if (!(p < 1 || p > 31 || m < 1 || m > 31))
                if nx < 1 or nx > 31 or ny < 1 or ny > 31:
                    continue

                if (nx, ny) in visited:
                    continue

                # Check if direction bit is set
                if not (dir_mask & DIR_BITS[d_name]):
                    continue

                next_tile = self.get_tile(nx, ny)
                # map.js: p == d && m == a || ((n ? n[0] : 1) & 1)
                is_dest = (nx == dest_x and ny == dest_y)
                is_walkable = (next_tile.raw_byte0 & 1) if next_tile else 1

                if is_dest or is_walkable:
                    visited.add((nx, ny))
                    came_from[(nx, ny)] = (curr_x, curr_y)
                    queue.append((nx, ny))

        if not found and (dest_x, dest_y) not in visited:
            return None

        # Reconstruct path
        path: List[Tuple[int, int]] = []
        curr = (dest_x, dest_y)
        while curr != (start_x, start_y):
            path.append(curr)
            curr = came_from[curr]
        path.reverse()
        return path

    def to_ascii_map(self) -> str:
        """
        Renders an ASCII visualization of the 33x33 map:
        '.' = walkable land
        '~' = water
        '#' = blocked obstacle
        """
        lines = []
        for row in self.tiles:
            line_chars = []
            for t in row:
                if not t.walkable and not t.is_water:
                    line_chars.append('#')
                elif t.is_water:
                    line_chars.append('~')
                else:
                    line_chars.append('.')
            lines.append("".join(line_chars))
        return "\n".join(lines)
