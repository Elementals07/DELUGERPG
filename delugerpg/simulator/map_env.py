"""
Map Exploration and Navigation Environment for DelugeRPG.
Simulates moving on the 33x33 tile grid based on decoded walkgrid byte masks.
Adheres strictly to the standard Reinforcement Learning Env interface (reset, step, action_space, observation_space).
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from ..parsers.walkgrid import WalkGrid, DIR_OFFSETS, DIR_BITS


class DiscreteSpace:
    def __init__(self, n: int):
        self.n = n

    def sample(self) -> int:
        return int(np.random.randint(0, self.n))

    def contains(self, x: Any) -> bool:
        return isinstance(x, (int, np.integer)) and 0 <= x < self.n


class BoxSpace:
    def __init__(self, low: float, high: float, shape: Tuple[int, ...], dtype=np.float32):
        self.low = low
        self.high = high
        self.shape = shape
        self.dtype = dtype

    def sample(self) -> np.ndarray:
        return np.random.uniform(self.low, self.high, size=self.shape).astype(self.dtype)


class MapEnv:
    """
    33x33 DelugeRPG Map Exploration Environment.

    Actions:
      0: 'n'  (-1,  0)
      1: 's'  ( 1,  0)
      2: 'w'  ( 0, -1)
      3: 'e'  ( 0,  1)
      4: 'nw' (-1, -1)
      5: 'ne' (-1,  1)
      6: 'sw' ( 1, -1)
      7: 'se' ( 1,  1)

    Observation:
      Flattened vector or multichannel tensor:
      Default vector representation (length = 49 + 4 = 53):
      - 7x7 local surrounding window (walkable mask, water mask, visited mask)
      - Normalized current position [x/32, y/32]
      - Exploration progress (visited_count / total_walkable)
      - Steps remaining ratio
    """

    ACTIONS = DIR_OFFSETS  # [(-1, 0, 'n'), (1, 0, 's'), ...]

    def __init__(
        self,
        walkgrid: WalkGrid,
        max_steps: int = 200,
        encounter_prob: float = 0.15,
        window_size: int = 7
    ):
        self.walkgrid = walkgrid
        self.max_steps = max_steps
        self.encounter_prob = encounter_prob
        self.window_size = window_size
        self.half_win = window_size // 2

        self.action_space = DiscreteSpace(len(self.ACTIONS))

        # Local window: window_size * window_size * 2 (walkable, visited) + 4 scalar features
        self.obs_dim = (self.window_size * self.window_size * 2) + 4
        self.observation_space = BoxSpace(low=0.0, high=1.0, shape=(self.obs_dim,), dtype=np.float32)

        # Precompute walkable tiles
        self.walkable_tiles = []
        for x in range(33):
            for y in range(33):
                if self.walkgrid.tiles[x][y].walkable:
                    self.walkable_tiles.append((x, y))

        if not self.walkable_tiles:
            raise ValueError(f"Walkgrid {walkgrid.map_name} has no walkable tiles!")

        self.total_walkable = len(self.walkable_tiles)
        self.current_pos = (0, 0)
        self.visited: Set[Tuple[int, int]] = set()
        self.step_count = 0
        self.total_encounters = 0

    def reset(self, seed: Optional[int] = None, start_pos: Optional[Tuple[int, int]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        if seed is not None:
            np.random.seed(seed)

        self.step_count = 0
        self.total_encounters = 0
        self.visited = set()

        if start_pos and start_pos in self.walkable_tiles:
            self.current_pos = start_pos
        else:
            idx = np.random.randint(0, len(self.walkable_tiles))
            self.current_pos = self.walkable_tiles[idx]

        self.visited.add(self.current_pos)
        obs = self._get_observation()
        info = {
            "pos": self.current_pos,
            "visited_count": len(self.visited),
            "total_walkable": self.total_walkable,
            "encounter": False
        }
        return obs, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        if not self.action_space.contains(action):
            raise ValueError(f"Invalid action {action}")

        self.step_count += 1
        dx, dy, dir_name = self.ACTIONS[action]
        cx, cy = self.current_pos
        nx, ny = cx + dx, cy + dy

        reward = -0.01  # Small step penalty to promote efficient exploration
        collided = False
        encounter_occurred = False

        # Validate movement according to DelugeRPG walkgrid rules
        cur_tile = self.walkgrid.tiles[cx][cy]
        if not cur_tile.allowed_directions.get(dir_name, False):
            # Direction blocked by byte 1 bitmask
            collided = True
        elif not (0 <= nx < 33 and 0 <= ny < 33):
            # Out of bounds
            collided = True
        elif not self.walkgrid.tiles[nx][ny].walkable:
            # Target tile not walkable
            collided = True
        else:
            # Valid movement!
            self.current_pos = (nx, ny)
            if self.current_pos not in self.visited:
                self.visited.add(self.current_pos)
                reward += 1.0  # Dominant exploration reward for new unvisited tile
            else:
                reward -= 0.08  # Revisit penalty: discourages looping and backtracking

            # Check encounter spawn (stat tracking only, zero exploit reward)
            if np.random.random() < self.encounter_prob:
                encounter_occurred = True
                self.total_encounters += 1

        if collided:
            reward -= 0.2  # Collision penalty

        terminated = len(self.visited) >= self.total_walkable
        truncated = self.step_count >= self.max_steps

        obs = self._get_observation()
        info = {
            "pos": self.current_pos,
            "visited_count": len(self.visited),
            "coverage": len(self.visited) / self.total_walkable,
            "collided": collided,
            "encounter": encounter_occurred,
            "total_encounters": self.total_encounters
        }
        return obs, reward, terminated, truncated, info

    def get_action_mask(self) -> np.ndarray:
        """
        Returns a binary vector of shape (8,) where 1 indicates a valid legal move.
        Crucial for masked DQN/PPO agents.
        """
        mask = np.zeros(len(self.ACTIONS), dtype=np.float32)
        cx, cy = self.current_pos
        cur_tile = self.walkgrid.tiles[cx][cy]

        for i, (dx, dy, dir_name) in enumerate(self.ACTIONS):
            if cur_tile.allowed_directions.get(dir_name, False):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < 33 and 0 <= ny < 33 and self.walkgrid.tiles[nx][ny].walkable:
                    mask[i] = 1.0
        return mask

    def _get_observation(self) -> np.ndarray:
        cx, cy = self.current_pos
        grid_features = np.zeros((self.window_size, self.window_size, 2), dtype=np.float32)

        for i, dx in enumerate(range(-self.half_win, self.half_win + 1)):
            for j, dy in enumerate(range(-self.half_win, self.half_win + 1)):
                wx = cx + dx
                wy = cy + dy
                if 0 <= wx < 33 and 0 <= wy < 33:
                    tile = self.walkgrid.tiles[wx][wy]
                    grid_features[i, j, 0] = 1.0 if tile.walkable else 0.0
                    grid_features[i, j, 1] = 1.0 if (wx, wy) in self.visited else 0.0
                else:
                    grid_features[i, j, 0] = 0.0
                    grid_features[i, j, 1] = 0.0

        scalars = np.array([
            cx / 32.0,
            cy / 32.0,
            len(self.visited) / self.total_walkable,
            (self.max_steps - self.step_count) / self.max_steps
        ], dtype=np.float32)

        return np.concatenate([grid_features.flatten(), scalars])
