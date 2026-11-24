"""
Non-learning baseline agents for comparison with DQN.

BFSMapAgent:
  On each step, finds the nearest unvisited walkable tile using BFS
  and takes the first step of that path. Pure deterministic logic, no neural net.

GreedyBattleAgent:
  On each turn, picks the move with the highest expected damage against the opponent.
  Uses type chart + STAB — no learning, just the obvious greedy rule.

Both are used in the ablation / comparison section of the course report.
"""

import numpy as np
from collections import deque
from typing import List, Optional, Tuple, Set

from ..parsers.walkgrid import WalkGrid, DIR_OFFSETS, DIR_BITS
from ..parsers.typechart import TypeChart


# ─────────────────────────────────────────────
# BFS Baseline — Map Exploration
# ─────────────────────────────────────────────

class BFSMapAgent:
    """
    Greedy map explorer that always goes to the nearest unvisited tile.

    Strategy:
      1. From current position, BFS over walkable tiles respecting direction bitmasks.
      2. Find the closest unvisited walkable tile.
      3. Take the first step of the BFS path toward it.
      4. If no unvisited tile reachable, take a random legal move.

    This is the non-learning baseline. DQN should beat it on average reward per episode.
    """

    def __init__(self, walkgrid: WalkGrid):
        self.walkgrid = walkgrid

    def choose_action(
        self,
        current_pos: Tuple[int, int],
        visited: Set[Tuple[int, int]],
        action_mask: np.ndarray
    ) -> int:
        """
        Returns action index (0-7) corresponding to the first step toward the
        nearest unvisited tile.
        """
        cx, cy = current_pos
        target = self._bfs_nearest_unvisited(cx, cy, visited)

        if target is not None:
            tx, ty = target
            # Find which direction takes us one step toward target
            # Re-run BFS and extract the first step
            first_step = self._bfs_first_step(cx, cy, tx, ty, visited)
            if first_step is not None:
                return first_step

        # Fallback: pick any legal action at random
        legal = [i for i, m in enumerate(action_mask) if m > 0]
        return np.random.choice(legal) if legal else 0

    def _bfs_nearest_unvisited(
        self,
        sx: int, sy: int,
        visited: Set[Tuple[int, int]]
    ) -> Optional[Tuple[int, int]]:
        """BFS to find the nearest unvisited walkable tile."""
        queue = deque([(sx, sy)])
        seen = {(sx, sy)}

        while queue:
            x, y = queue.popleft()
            if (x, y) not in visited and self.walkgrid.tiles[x][y].walkable:
                return (x, y)

            tile = self.walkgrid.tiles[x][y]
            dir_mask = tile.raw_dirmask if (tile.raw_byte0 & 1) else 255

            for dx, dy, d_name in DIR_OFFSETS:
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                if not (1 <= nx <= 31 and 1 <= ny <= 31):
                    continue
                if not (dir_mask & DIR_BITS[d_name]):
                    continue
                if not self.walkgrid.tiles[nx][ny].walkable:
                    continue
                seen.add((nx, ny))
                queue.append((nx, ny))

        return None  # Everything reachable is visited

    def _bfs_first_step(
        self,
        sx: int, sy: int,
        tx: int, ty: int,
        visited: Set[Tuple[int, int]]
    ) -> Optional[int]:
        """
        BFS from (sx,sy) to (tx,ty), returns the action index of the first step.
        """
        if (sx, sy) == (tx, ty):
            return None

        queue = deque([(sx, sy, None)])  # (x, y, first_action_taken)
        seen = {(sx, sy)}

        while queue:
            x, y, first_action = queue.popleft()

            tile = self.walkgrid.tiles[x][y]
            dir_mask = tile.raw_dirmask if (tile.raw_byte0 & 1) else 255

            for action_idx, (dx, dy, d_name) in enumerate(DIR_OFFSETS):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                if not (0 <= nx < 33 and 0 <= ny < 33):
                    continue
                if not (dir_mask & DIR_BITS[d_name]):
                    continue
                if not self.walkgrid.tiles[nx][ny].walkable:
                    continue

                fa = first_action if first_action is not None else action_idx

                if (nx, ny) == (tx, ty):
                    return fa

                seen.add((nx, ny))
                queue.append((nx, ny, fa))

        return None


# ─────────────────────────────────────────────
# Greedy Baseline — Battle
# ─────────────────────────────────────────────

class GreedyBattleAgent:
    """
    Non-learning battle agent that always picks the highest-damage move.

    Strategy:
      - Compute expected damage for each of the 4 moves: power * STAB * type_effectiveness
      - Pick the move with the highest expected damage
      - Switch if current Pokémon has fainted (pick first healthy bench member)

    This is the non-learning battle baseline.
    """

    def __init__(self, type_chart: TypeChart):
        self.type_chart = type_chart

    def choose_action(
        self,
        obs: np.ndarray,
        action_mask: np.ndarray,
        player_active,   # BattlePokemon
        opponent_active  # BattlePokemon
    ) -> int:
        """
        Returns action index 0-8.
        Actions 0-3: use move 0-3
        Actions 4-8: switch to bench slot 0-4
        """
        # If we must switch (active fainted), pick first legal switch
        if player_active.is_fainted:
            for i in range(4, 9):
                if action_mask[i] > 0:
                    return i
            return 0

        # Score each legal move by expected damage
        best_action = -1
        best_score = -1.0

        is_negative = (
            player_active.class_name.lower() == "negative" or
            opponent_active.class_name.lower() == "negative"
        )

        for move_idx in range(4):
            if action_mask[move_idx] == 0:
                continue
            if move_idx >= len(player_active.attacks):
                continue

            attack = player_active.attacks[move_idx]
            if not attack or not attack.name or not attack.power:
                continue

            power = attack.power
            # STAB bonus
            stab = 1.5 if (
                attack.type == player_active.type1 or
                attack.type == player_active.type2
            ) else 1.0
            # Type effectiveness
            eff = self.type_chart.get_defender_multiplier(
                opponent_active.type1,
                opponent_active.type2,
                attack.type,
                inverse=is_negative
            )
            score = power * stab * eff

            if score > best_score:
                best_score = score
                best_action = move_idx

        if best_action >= 0:
            return best_action

        # Fallback: any legal action
        for i, m in enumerate(action_mask):
            if m > 0:
                return i
        return 0
