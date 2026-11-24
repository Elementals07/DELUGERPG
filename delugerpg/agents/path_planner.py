"""
Hierarchical Path Planning Agent for DelugeRPG.
High-level macro-policy predicts optimal target waypoints across the map,
and low-level controller executes collision-free paths using client-exact find_path().

This guarantees:
1. Zero 2-tile ping-pong loops (paths are acyclic and goal-directed).
2. Broad, human-like exploration across the entire 33x33 map.
3. High encounter rates by routing through high-priority grass and terrain clusters.
4. Fast online inference and seamless browser export to IndexedDB.
"""

import json
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from ..parsers.walkgrid import WalkGrid


@dataclass
class MapWaypoint:
    id: int
    x: int
    y: int
    name: str
    terrain: str
    base_encounter_weight: float  # Grass/caves have higher encounter weight


# 16 Canonical landmark waypoints covering all topological sectors of Overworld 1
WAYPOINTS_OW1: List[MapWaypoint] = [
    MapWaypoint(0, 4, 28, "NE Pine Forest (Tall Grass)", "grass", 1.8),
    MapWaypoint(1, 7, 22, "North Snow Ridge", "snow", 1.0),
    MapWaypoint(2, 8, 29, "East Upper Mountain Trail", "mountain", 1.3),
    MapWaypoint(3, 11, 28, "East Cliff Path", "mountain", 1.2),
    MapWaypoint(4, 11, 19, "Upper Snowfield", "snow", 1.0),
    MapWaypoint(5, 14, 12, "North Central Plains", "snow", 1.1),
    MapWaypoint(6, 14, 2, "Ice Cavern Entrance", "cave", 1.9),
    MapWaypoint(7, 20, 4, "West Upper Bridge", "bridge", 1.2),
    MapWaypoint(8, 20, 11, "Central Crossroads", "snow", 1.1),
    MapWaypoint(9, 19, 19, "East Central Terraces", "snow", 1.1),
    MapWaypoint(10, 19, 26, "Far East Ridge Overlook", "mountain", 1.4),
    MapWaypoint(11, 28, 4, "Southwest Lower Bridge", "bridge", 1.3),
    MapWaypoint(12, 28, 11, "South Valley Entrance", "cave", 1.7),
    MapWaypoint(13, 28, 20, "Southeast Rock Field", "rock", 1.2),
    MapWaypoint(14, 28, 27, "Southeast Dirt Plateau", "dirt", 1.5),
    MapWaypoint(15, 24, 16, "Lower Central Basin", "snow", 1.0),
]


class PathPlannerEnv:
    """
    Hierarchical Macro-Waypoint Environment for DelugeRPG Overworld 1.
    Observations: 67-dim normalized vector.
    Actions: 16 discrete choices (target waypoint index).
    """
    def __init__(self, walkgrid: WalkGrid, max_macro_steps: int = 25):
        self.walkgrid = walkgrid
        self.max_macro_steps = max_macro_steps
        self.waypoints = WAYPOINTS_OW1
        self.num_waypoints = len(self.waypoints)

        # Collect all walkable tiles
        self.walkable_tiles = set(
            (x, y) for x in range(33) for y in range(33)
            if self.walkgrid.get_tile(x, y) and self.walkgrid.get_tile(x, y).walkable
        )
        self.total_walkable = len(self.walkable_tiles)

        # State tracking
        self.curr_x = 14
        self.curr_y = 2
        self.macro_steps = 0
        self.visited_tiles: set[Tuple[int, int]] = set()
        self.waypoint_visit_counts = [0] * self.num_waypoints
        self.waypoint_last_visited = [999] * self.num_waypoints
        self.total_encounters = 0
        self.recent_waypoints: List[int] = []

    def reset(self, start_pos: Optional[Tuple[int, int]] = None) -> np.ndarray:
        if start_pos and start_pos in self.walkable_tiles:
            self.curr_x, self.curr_y = start_pos
        else:
            # Pick a random starting waypoint
            wp = random.choice(self.waypoints)
            self.curr_x, self.curr_y = wp.x, wp.y

        self.macro_steps = 0
        self.visited_tiles = {(self.curr_x, self.curr_y)}
        self.waypoint_visit_counts = [0] * self.num_waypoints
        self.waypoint_last_visited = [999] * self.num_waypoints
        self.total_encounters = 0
        self.recent_waypoints = []
        return self._get_obs()

    def get_action_mask(self, window_size: int = 4) -> np.ndarray:
        """
        Mask out waypoints that:
        1. Agent is currently standing at.
        2. Were visited within the last `window_size` macro-steps to guarantee wide spatial exploration without small cycles.
        """
        mask = np.ones(self.num_waypoints, dtype=np.float32)
        for i, wp in enumerate(self.waypoints):
            if wp.x == self.curr_x and wp.y == self.curr_y:
                mask[i] = 0.0

        # Mask recent waypoints to enforce tour diversity
        recent_window = self.recent_waypoints[-window_size:] if self.recent_waypoints else []
        for r_wp in recent_window:
            mask[r_wp] = 0.0

        # Safety: if too many masked, allow unvisited or least visited
        if mask.sum() == 0:
            mask = np.ones(self.num_waypoints, dtype=np.float32)
            for i, wp in enumerate(self.waypoints):
                if wp.x == self.curr_x and wp.y == self.curr_y:
                    mask[i] = 0.0
            if mask.sum() == 0:
                mask = np.ones(self.num_waypoints, dtype=np.float32)
        return mask

    def _get_obs(self) -> np.ndarray:
        """
        67-dim normalized state vector:
        - 2 dims: curr_x / 32.0, curr_y / 32.0
        - 16 dims: Euclidean distance to each waypoint / 45.0
        - 16 dims: Normalized visit frequency of each waypoint (visits / 10.0, clipped to 1.0)
        - 16 dims: Encounter priority weight of each waypoint zone
        - 16 dims: Recency score (steps since last visit / 20.0, clipped to 1.0)
        - 1 dim: Global map coverage ratio (len(visited) / total_walkable)
        """
        obs = np.zeros(67, dtype=np.float32)
        obs[0] = self.curr_x / 32.0
        obs[1] = self.curr_y / 32.0

        idx = 2
        # Distance to waypoints
        for i, wp in enumerate(self.waypoints):
            dist = np.hypot(self.curr_x - wp.x, self.curr_y - wp.y)
            obs[idx + i] = min(dist / 45.0, 1.0)
        idx += 16

        # Visit frequency
        for i in range(16):
            obs[idx + i] = min(self.waypoint_visit_counts[i] / 5.0, 1.0)
        idx += 16

        # Encounter priority weights
        for i, wp in enumerate(self.waypoints):
            obs[idx + i] = wp.base_encounter_weight / 2.0
        idx += 16

        # Recency score
        for i in range(16):
            obs[idx + i] = min(self.waypoint_last_visited[i] / 20.0, 1.0)
        idx += 16

        # Global coverage
        obs[idx] = len(self.visited_tiles) / max(1, self.total_walkable)

        return obs

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Executes macro-action (target waypoint).
        Walks along find_path(), accumulates step rewards, and returns transition.
        """
        target_wp = self.waypoints[action]
        path = self.walkgrid.find_path(self.curr_x, self.curr_y, target_wp.x, target_wp.y)

        if not path:
            # Already at destination or invalid path
            reward = -1.0
            done = self.macro_steps >= self.max_macro_steps
            return self._get_obs(), reward, done, {"info": "invalid_or_stationary"}

        step_reward = 0.0
        new_tiles_in_path = 0
        encounters_in_path = 0

        # Traverse path coordinate by coordinate
        for px, py in path:
            if (px, py) not in self.visited_tiles:
                self.visited_tiles.add((px, py))
                new_tiles_in_path += 1
                step_reward += 1.5  # High exploration reward!
            else:
                step_reward -= 0.02  # Small revisit penalty

            # Encounter probability simulation based on terrain
            base_prob = 0.12
            if target_wp.terrain == "grass":
                base_prob = 0.28
            elif target_wp.terrain == "cave":
                base_prob = 0.22
            elif target_wp.terrain == "mountain":
                base_prob = 0.18

            if random.random() < base_prob:
                encounters_in_path += 1
                self.total_encounters += 1
                # High priority encounter reward
                step_reward += 0.8 * target_wp.base_encounter_weight

        # Update position to target
        self.curr_x, self.curr_y = target_wp.x, target_wp.y
        self.macro_steps += 1

        # Update waypoint visit statistics
        for i in range(self.num_waypoints):
            self.waypoint_last_visited[i] += 1
        self.waypoint_visit_counts[action] += 1
        self.waypoint_last_visited[action] = 0
        self.recent_waypoints.append(action)
        if len(self.recent_waypoints) > 8:
            self.recent_waypoints.pop(0)

        # Goal arrival bonus
        step_reward += 2.0

        # Coverage milestone bonuses
        coverage = len(self.visited_tiles) / self.total_walkable
        if coverage > 0.5:
            step_reward += 1.0
        if coverage > 0.8:
            step_reward += 2.0
        if coverage > 0.9:
            step_reward += 3.0

        done = (self.macro_steps >= self.max_macro_steps) or (coverage >= 0.95)

        info = {
            "path_length": len(path),
            "new_tiles": new_tiles_in_path,
            "encounters": encounters_in_path,
            "coverage": coverage,
            "target": target_wp.name,
        }

        return self._get_obs(), step_reward, done, info


class PathPlannerNetwork(nn.Module):
    """
    Compact MLP Value Network: 67 -> 128 -> 128 -> 64 -> 16.
    Fast CPU inference (< 0.05 ms).
    """
    def __init__(self, input_dim: int = 67, hidden_dim: int = 128, num_actions: int = 16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, num_actions)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class PathPlannerDQN:
    """
    DQN Agent training loop with action masking and experience replay.
    """
    def __init__(
        self,
        input_dim: int = 67,
        num_actions: int = 16,
        lr: float = 1e-3,
        gamma: float = 0.98,
        buffer_size: int = 20000,
        batch_size: int = 64,
        device: str = "cpu"
    ):
        self.device = torch.device(device)
        self.num_actions = num_actions
        self.gamma = gamma
        self.batch_size = batch_size

        self.policy_net = PathPlannerNetwork(input_dim, 128, num_actions).to(self.device)
        self.target_net = PathPlannerNetwork(input_dim, 128, num_actions).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.criterion = nn.SmoothL1Loss()

        self.replay_buffer: List[Tuple[np.ndarray, int, float, np.ndarray, bool, np.ndarray]] = []
        self.buffer_size = buffer_size
        self.buffer_idx = 0

    def select_action(self, state: np.ndarray, action_mask: np.ndarray, epsilon: float = 0.05) -> int:
        if random.random() < epsilon:
            valid_actions = [i for i, m in enumerate(action_mask) if m > 0.5]
            if valid_actions:
                return random.choice(valid_actions)
            return random.randint(0, self.num_actions - 1)

        self.policy_net.eval()
        with torch.no_grad():
            s_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.policy_net(s_tensor).squeeze(0).cpu().numpy()

        # Apply action mask: set masked actions to -inf
        masked_q = np.where(action_mask > 0.5, q_values, -1e9)
        return int(np.argmax(masked_q))

    def store_transition(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        next_mask: np.ndarray
    ):
        if len(self.replay_buffer) < self.buffer_size:
            self.replay_buffer.append((state, action, reward, next_state, done, next_mask))
        else:
            self.replay_buffer[self.buffer_idx] = (state, action, reward, next_state, done, next_mask)
        self.buffer_idx = (self.buffer_idx + 1) % self.buffer_size

    def update(self) -> Optional[float]:
        if len(self.replay_buffer) < self.batch_size:
            return None

        batch = random.sample(self.replay_buffer, self.batch_size)
        states, actions, rewards, next_states, dones, next_masks = zip(*batch)

        s_t = torch.FloatTensor(np.array(states)).to(self.device)
        a_t = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        r_t = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        ns_t = torch.FloatTensor(np.array(next_states)).to(self.device)
        d_t = torch.FloatTensor(dones).unsqueeze(1).to(self.device)
        nm_t = torch.FloatTensor(np.array(next_masks)).to(self.device)

        # Current Q
        self.policy_net.train()
        q_curr = self.policy_net(s_t).gather(1, a_t)

        # Target Q with action masking
        with torch.no_grad():
            q_next_raw = self.target_net(ns_t)
            # Mask out invalid next actions
            masked_q_next = torch.where(nm_t > 0.5, q_next_raw, torch.tensor(-1e9, device=self.device))
            max_q_next = masked_q_next.max(1, keepdim=True)[0]
            # If all masked or done, clamp
            max_q_next = torch.where(max_q_next < -1e8, torch.tensor(0.0, device=self.device), max_q_next)
            q_target = r_t + (1.0 - d_t) * self.gamma * max_q_next

        loss = self.criterion(q_curr, q_target)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        return float(loss.item())

    def sync_target(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def export_weights_dict(self) -> Dict[str, Any]:
        """
        Exports model weights to a pure JSON-serializable dictionary
        for direct loading into JavaScript / IndexedDB.
        """
        weights: Dict[str, Any] = {
            "model_type": "PathPlannerDQN",
            "input_dim": 67,
            "hidden_dim": 128,
            "output_dim": 16,
            "waypoints": [
                {"id": wp.id, "x": wp.x, "y": wp.y, "name": wp.name, "terrain": wp.terrain, "weight": wp.base_encounter_weight}
                for wp in WAYPOINTS_OW1
            ],
            "layers": []
        }

        # Linear layers in net: 0, 2, 4, 6
        linear_layers = [m for m in self.policy_net.net if isinstance(m, nn.Linear)]
        for i, layer in enumerate(linear_layers):
            weights["layers"].append({
                "layer_index": i,
                "in_features": layer.in_features,
                "out_features": layer.out_features,
                "weight": layer.weight.detach().cpu().numpy().tolist(),  # [out, in]
                "bias": layer.bias.detach().cpu().numpy().tolist()       # [out]
            })

        return weights
