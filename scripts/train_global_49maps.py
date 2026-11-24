"""
Global 49-Map Hierarchical Exploration and Navigation DQN Training Pipeline.
Trains an autonomous agent across all 49 DelugeRPG maps for 8,000 episodes.
Includes overworld 5x5 grid seams, dungeon ascents/descents, and overworld-dungeon portals.
"""

import os
import sys
import time
import csv
import json
import random
import argparse
from collections import Counter, deque
from typing import Dict, List, Tuple, Optional, Any, Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import networkx as nx

sys.path.insert(0, os.path.abspath("."))
from delugerpg.agents.multi_map_planner import GlobalNavigator, LocalNavigator
from delugerpg.parsers.walkgrid import DIR_BITS, WalkGrid
from delugerpg.models.world_graph import WorldGraph
from delugerpg.models.transition_registry import (
    AmbiguousTransitionError,
    InvalidTransitionError,
    STATUS_INVALID,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    TransitionRegistry,
    UnverifiedTransitionError,
    resolve_transition,
)


DEFAULT_REGISTRY_PATH = "data/processed/transition_registry_v1.json"


# ---------------------------------------------------------
# 1. World Graph with complete 49-map connectivity
# ---------------------------------------------------------
# Legacy Phase 0 audit seed. GlobalWorldGraph no longer uses this list; the
# canonical registry is the source of truth. The constant remains so the
# read-only Phase 0 audit script keeps working unchanged.
DUNGEON_ENTRANCES = [
    ("overworld1", "snowcave1", (14, 2), (16, 16), "Seafoam / Snow Cave"),
    ("overworld3", "pkmntower1", (16, 16), (16, 16), "Pokemon Tower"),
    ("overworld9", "rockcave1", (16, 16), (16, 16), "Rock Cave"),
    ("overworld10", "powerplant1", (16, 16), (16, 16), "Power Plant"),
    ("overworld15", "unownruins1", (16, 16), (16, 16), "Unown Ruins"),
    ("overworld21", "pkmnmansion1", (10, 10), (16, 16), "Pokemon Mansion"),
    ("overworld21", "volcano1", (22, 22), (16, 16), "Volcano"),
]


class GlobalWorldGraph(WorldGraph):
    def __init__(
        self,
        walkgrids_path: str = "data/raw/delugerpg_all_walkgrids.json",
        registry_path: str = DEFAULT_REGISTRY_PATH,
    ):
        super().__init__(walkgrids_path=walkgrids_path)
        self.registry_path = registry_path
        self.registry = TransitionRegistry.load(registry_path)
        self.graph = self.registry.to_networkx()
        self._apply_legacy_direction_labels()

    def _apply_legacy_direction_labels(self) -> None:
        by_id = self.registry.by_id()
        for _source, _destination, data in self.graph.edges(data=True):
            records = [
                by_id[portal_id]
                for portal_id in data.get("portal_ids", [])
                if portal_id in by_id
            ]
            transition_types = {record.transition_type for record in records}
            if "seam" in transition_types:
                seam = next(record for record in records if record.transition_type == "seam")
                data["direction"] = seam.trigger.replace("move:", "")
            elif "entrance" in transition_types:
                data["direction"] = "dungeon_enter"
            elif "exit" in transition_types:
                data["direction"] = "dungeon_exit"
            elif "ascend" in transition_types:
                data["direction"] = "climb_up/advance"
            elif "descend" in transition_types:
                data["direction"] = "climb_down/return"
            else:
                data["direction"] = "unknown"


# ---------------------------------------------------------
# 2. Multi-Map Environment
# ---------------------------------------------------------
ACTION_NAMES = [
    "Local_NW", "Local_NE", "Local_Center", "Local_SW", "Local_SE",
    "Warp_North", "Warp_South", "Warp_West", "Warp_East",
    "Dungeon_Enter_Ascend", "Dungeon_Exit_Descend"
]

SECTOR_TARGETS = {
    0: (8, 8),    # NW
    1: (24, 8),   # NE
    2: (16, 16),  # Center
    3: (8, 24),   # SW
    4: (24, 24),  # SE
}


class Global49MapEnv:
    def __init__(self, world_graph: GlobalWorldGraph, max_macro_steps: int = 25):
        self.wg = world_graph
        self.registry = world_graph.registry
        self.max_macro_steps = max_macro_steps
        self.map_names = sorted(list(self.wg.grids.keys()))
        self.map_to_idx = {name: i for i, name in enumerate(self.map_names)}
        self.num_maps = len(self.map_names)

        # Precompute walkable tiles and sector waypoints for each map
        self.walkable_tiles: Dict[str, List[Tuple[int, int]]] = {}
        self.sector_waypoints: Dict[str, Dict[int, Tuple[int, int]]] = {}

        for name, grid in self.wg.grids.items():
            walkable = [(x, y) for y in range(33) for x in range(33) if grid.get_tile(x, y) and grid.get_tile(x, y).walkable]
            self.walkable_tiles[name] = walkable
            self.sector_waypoints[name] = {}
            for s_idx, (cx, cy) in SECTOR_TARGETS.items():
                best = min(walkable, key=lambda t: (t[0] - cx)**2 + (t[1] - cy)**2)
                self.sector_waypoints[name][s_idx] = best

        # State tracking
        self.current_map = "overworld1"
        self.curr_x = 16
        self.curr_y = 16
        self.target_map = "volcano4"
        self.macro_steps = 0
        self.visited_maps: set[str] = set()
        self.map_visit_counts = np.zeros(self.num_maps, dtype=np.float32)
        self.steps_since_map_visit = np.zeros(self.num_maps, dtype=np.float32)
        self.local_visited_tiles: set[Tuple[int, int]] = set()
        self.recent_map_history: deque = deque(maxlen=5)
        self.total_encounters = 0

    def reset(self, start_map: Optional[str] = None, target_map: Optional[str] = None) -> np.ndarray:
        if start_map and start_map in self.map_names:
            self.current_map = start_map
        else:
            self.current_map = random.choice(self.map_names)

        if target_map and target_map in self.map_names and target_map != self.current_map:
            self.target_map = target_map
        else:
            candidates = [m for m in self.map_names if m != self.current_map]
            self.target_map = random.choice(candidates)

        start_tile = random.choice(self.walkable_tiles[self.current_map])
        self.curr_x, self.curr_y = start_tile

        self.macro_steps = 0
        self.visited_maps = {self.current_map}
        self.map_visit_counts = np.zeros(self.num_maps, dtype=np.float32)
        self.map_visit_counts[self.map_to_idx[self.current_map]] = 1.0
        self.steps_since_map_visit = np.full(self.num_maps, 999.0, dtype=np.float32)
        self.steps_since_map_visit[self.map_to_idx[self.current_map]] = 0.0
        self.local_visited_tiles = {(self.curr_x, self.curr_y)}
        self.recent_map_history = deque([self.map_to_idx[self.current_map]], maxlen=5)
        self.total_encounters = 0

        return self._get_obs()

    def set_scenario(
        self,
        start_map: str,
        start_coord: Tuple[int, int],
        target_map: str,
    ) -> np.ndarray:
        """Set a deterministic baseline scenario without changing v1 dynamics."""
        self.current_map = start_map
        self.curr_x, self.curr_y = start_coord
        self.target_map = target_map
        self.macro_steps = 0
        self.visited_maps = {start_map}
        self.map_visit_counts = np.zeros(self.num_maps, dtype=np.float32)
        self.map_visit_counts[self.map_to_idx[start_map]] = 1.0
        self.steps_since_map_visit = np.full(self.num_maps, 999.0, dtype=np.float32)
        self.steps_since_map_visit[self.map_to_idx[start_map]] = 0.0
        self.local_visited_tiles = {(self.curr_x, self.curr_y)}
        self.recent_map_history = deque([self.map_to_idx[start_map]], maxlen=5)
        self.total_encounters = 0
        return self._get_obs()

    def _get_obs(self) -> np.ndarray:
        obs = []
        # 1. Current map one-hot (49)
        c_map_vec = np.zeros(self.num_maps, dtype=np.float32)
        c_map_vec[self.map_to_idx[self.current_map]] = 1.0
        obs.extend(c_map_vec)

        # 2. Target map one-hot (49)
        t_map_vec = np.zeros(self.num_maps, dtype=np.float32)
        t_map_vec[self.map_to_idx[self.target_map]] = 1.0
        obs.extend(t_map_vec)

        # 3. Position on current map (2)
        obs.extend([self.curr_x / 32.0, self.curr_y / 32.0])

        # 4. Local coverage on current map (1)
        cov = len(self.local_visited_tiles) / max(1, len(self.walkable_tiles[self.current_map]))
        obs.append(cov)

        # 5. Global map visit counts normalized (49)
        obs.extend(np.clip(self.map_visit_counts / 5.0, 0.0, 1.0))

        # 6. Steps since last visit (49)
        obs.extend(np.clip(self.steps_since_map_visit / 50.0, 0.0, 1.0))

        # 7. Recent map history (5)
        hist = list(self.recent_map_history)
        while len(hist) < 5:
            hist.insert(0, -1)
        obs.extend([(idx / float(self.num_maps)) if idx >= 0 else -1.0 for idx in hist])

        return np.array(obs, dtype=np.float32)

    def get_action_mask(self) -> np.ndarray:
        mask = np.ones(11, dtype=bool)
        out_edges = self.wg.graph.out_edges(self.current_map, data=True)

        has_north = any(data.get("direction") == "north" for _, _, data in out_edges)
        has_south = any(data.get("direction") == "south" for _, _, data in out_edges)
        has_west = any(data.get("direction") == "west" for _, _, data in out_edges)
        has_east = any(data.get("direction") == "east" for _, _, data in out_edges)
        has_enter = any(data.get("direction") in ("climb_up/advance", "dungeon_enter") for _, _, data in out_edges)
        has_exit = any(data.get("direction") in ("climb_down/return", "dungeon_exit") for _, _, data in out_edges)

        mask[5] = has_north
        mask[6] = has_south
        mask[7] = has_west
        mask[8] = has_east
        mask[9] = has_enter
        mask[10] = has_exit

        return mask

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        self.macro_steps += 1
        self.steps_since_map_visit += 1.0

        reward = -0.1  # small step penalty to promote direct routing
        done = False
        info = {"transition": None, "path_len": 0, "encounters": 0}

        grid = self.wg.grids[self.current_map]

        if action < 5:
            # Local exploration step to sector waypoint
            target_tile = self.sector_waypoints[self.current_map][action]
            path = grid.find_path(self.curr_x, self.curr_y, target_tile[0], target_tile[1])
            if path:
                info["path_len"] = len(path)
                for x, y in path:
                    if (x, y) not in self.local_visited_tiles:
                        self.local_visited_tiles.add((x, y))
                        reward += 0.25  # exploration reward
                    tile = grid.get_tile(x, y)
                    if tile and tile.is_water:
                        info["encounters"] += 1
                        reward += 0.8
                self.curr_x, self.curr_y = target_tile
                self.total_encounters += info["encounters"]
            else:
                reward -= 1.0  # blocked local path
        else:
            # Cross-map transition action (5..10)
            kind = "seam" if action <= 8 else ("enter" if action == 9 else "exit")
            direction = {5: "north", 6: "south", 7: "west", 8: "east"}.get(action)
            try:
                record, resolution = resolve_transition(
                    self.registry,
                    self.current_map,
                    (self.curr_x, self.curr_y),
                    kind=kind,
                    direction=direction,
                    allow_unverified=True,
                )
            except (InvalidTransitionError, UnverifiedTransitionError, AmbiguousTransitionError) as exc:
                reward -= 1.0
                info["transition_error"] = str(exc)
            else:
                next_map = record.destination_map
                dest_coord = record.destination_coord
                next_grid = self.wg.grids[next_map]
                dest_tile = next_grid.get_tile(dest_coord[0], dest_coord[1]) if dest_coord else None
                if dest_tile is None or not dest_tile.walkable:
                    reward -= 1.0
                    info["transition_error"] = (
                        f"portal {record.portal_id!r} destination {dest_coord!r} "
                        f"is not walkable on {next_map!r}"
                    )
                else:
                    # Loop prevention penalty
                    next_idx = self.map_to_idx[next_map]
                    if next_idx in self.recent_map_history:
                        # Penalize bouncing back to a recently visited map
                        reward -= 12.0
                    else:
                        reward += 8.0  # rewarding progression to fresh maps

                    if next_map not in self.visited_maps:
                        self.visited_maps.add(next_map)
                        reward += 20.0  # big discovery reward for new continent/dungeon

                    # Check if moving closer to the target map via shortest path
                    curr_dist = nx.shortest_path_length(self.wg.graph, self.current_map, self.target_map)
                    new_dist = nx.shortest_path_length(self.wg.graph, next_map, self.target_map)
                    if new_dist < curr_dist:
                        reward += 15.0  # directed navigation progress reward
                    else:
                        reward -= 5.0

                    # Execute transition
                    self.current_map = next_map
                    self.curr_x, self.curr_y = dest_coord
                    self.local_visited_tiles = {(self.curr_x, self.curr_y)}
                    self.map_visit_counts[next_idx] += 1.0
                    self.steps_since_map_visit[next_idx] = 0.0
                    self.recent_map_history.append(next_idx)

                    info["transition"] = next_map
                    info["portal_id"] = record.portal_id
                    info["transition_status"] = record.verification_status
                    info["transition_selection"] = resolution["selection"]

                    # Reached global expedition target map!
                    if self.current_map == self.target_map:
                        reward += 80.0
                        done = True

        if self.macro_steps >= self.max_macro_steps:
            done = True

        return self._get_obs(), reward, done, info


# ---------------------------------------------------------
# 3. Dueling Deep Q-Network Agent
# ---------------------------------------------------------
class DuelingDQN(nn.Module):
    def __init__(self, input_dim: int, num_actions: int):
        super().__init__()
        self.feature_net = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU()
        )
        self.value_stream = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1)
        )
        self.advantage_stream = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, num_actions)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.feature_net(x)
        val = self.value_stream(feat)
        adv = self.advantage_stream(feat)
        return val + (adv - adv.mean(dim=-1, keepdim=True))


class Global49MapDQN:
    def __init__(
        self,
        input_dim: int = 204,
        num_actions: int = 11,
        lr: float = 1e-3,
        gamma: float = 0.98,
        buffer_size: int = 40000,
        batch_size: int = 64
    ):
        self.input_dim = input_dim
        self.num_actions = num_actions
        self.gamma = gamma
        self.batch_size = batch_size

        self.policy_net = DuelingDQN(input_dim, num_actions)
        self.target_net = DuelingDQN(input_dim, num_actions)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.criterion = nn.SmoothL1Loss()  # Huber loss
        self.buffer: deque = deque(maxlen=buffer_size)

    def select_action(self, state: np.ndarray, mask: np.ndarray, epsilon: float = 0.05) -> int:
        valid_indices = np.where(mask)[0]
        if len(valid_indices) == 0:
            return 2  # Center fallback

        if random.random() < epsilon:
            return int(random.choice(valid_indices))

        with torch.no_grad():
            s_t = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.policy_net(s_t).squeeze(0).numpy()
            q_values[~mask] = -1e9
            return int(np.argmax(q_values))

    def store_transition(self, state, action, reward, next_state, done, next_mask):
        self.buffer.append((state, action, reward, next_state, done, next_mask))

    def update(self) -> Optional[float]:
        if len(self.buffer) < self.batch_size:
            return None

        batch = random.sample(self.buffer, self.batch_size)
        states, actions, rewards, next_states, dones, next_masks = zip(*batch)

        s_t = torch.FloatTensor(np.array(states))
        a_t = torch.LongTensor(actions).unsqueeze(1)
        r_t = torch.FloatTensor(rewards).unsqueeze(1)
        ns_t = torch.FloatTensor(np.array(next_states))
        d_t = torch.FloatTensor(dones).unsqueeze(1)

        # Current Q
        current_q = self.policy_net(s_t).gather(1, a_t)

        with torch.no_grad():
            next_q = self.target_net(ns_t)
            for i, mask in enumerate(next_masks):
                invalid = ~torch.tensor(mask, dtype=torch.bool)
                next_q[i][invalid] = -1e9
            max_next_q = next_q.max(dim=1, keepdim=True)[0]
            target_q = r_t + (1.0 - d_t) * self.gamma * max_next_q

        loss = self.criterion(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        return float(loss.item())

    def sync_target(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def export_weights_dict(self) -> Dict[str, Any]:
        weights = {}
        for k, v in self.policy_net.state_dict().items():
            weights[k] = v.cpu().numpy().tolist()
        return weights


# ---------------------------------------------------------
# 4. Main Training Loop for 8,000 Episodes
# ---------------------------------------------------------
def train_global_agent(num_episodes: int = 8000, log_interval: int = 500):
    print("=" * 80)
    print("DELUGERPG SEVERE GLOBAL MULTI-MAP TRAINING: 49 MAPS (8,000 EPISODES)")
    print(f"Maps: 49 (25 Overworld + 24 Dungeons) | Directed Transitions: 126 | Actions: 11")
    print("=" * 80, flush=True)

    wg = GlobalWorldGraph()
    env = Global49MapEnv(wg, max_macro_steps=20)
    obs_dim = len(env.reset())
    print(f"Observation space dimension: {obs_dim} features | Action space: 11 actions")

    agent = Global49MapDQN(input_dim=obs_dim, num_actions=11, lr=7e-4, gamma=0.98, buffer_size=40000, batch_size=64)

    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.join("data", "processed"), exist_ok=True)

    csv_path = os.path.join("logs", "global_49map_training_log.csv")
    csv_file = open(csv_path, mode="w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["episode", "epsilon", "reward", "maps_visited", "target_reached", "encounters", "loss", "steps"])

    epsilon_start = 1.0
    epsilon_min = 0.05
    epsilon_decay_episodes = 5000

    best_reward = -9999.0
    best_maps_visited = 0
    target_successes = 0

    recent_rewards = []
    recent_maps_counts = []
    recent_successes = []

    start_time = time.time()

    for episode in range(1, num_episodes + 1):
        if episode <= epsilon_decay_episodes:
            epsilon = epsilon_start - (epsilon_start - epsilon_min) * (episode / epsilon_decay_episodes)
        else:
            epsilon = epsilon_min

        # Every 4th episode, start on user's overworld 1, otherwise uniform random over 49 maps
        start_map = "overworld1" if (episode % 4 == 0) else None
        state = env.reset(start_map=start_map)
        mask = env.get_action_mask()

        ep_reward = 0.0
        ep_loss = 0.0
        loss_updates = 0
        done = False

        while not done:
            action = agent.select_action(state, mask, epsilon=epsilon)
            next_state, reward, done, info = env.step(action)
            next_mask = env.get_action_mask()

            agent.store_transition(state, action, reward, next_state, done, next_mask)
            loss = agent.update()
            if loss is not None:
                ep_loss += loss
                loss_updates += 1

            state = next_state
            mask = next_mask
            ep_reward += reward

        if episode % 25 == 0:
            agent.sync_target()

        reached_target = 1 if (env.current_map == env.target_map) else 0
        target_successes += reached_target
        avg_loss = (ep_loss / loss_updates) if loss_updates > 0 else 0.0
        num_maps_visited = len(env.visited_maps)

        recent_rewards.append(ep_reward)
        recent_maps_counts.append(num_maps_visited)
        recent_successes.append(reached_target)

        csv_writer.writerow([episode, f"{epsilon:.4f}", f"{ep_reward:.2f}", num_maps_visited, reached_target, env.total_encounters, f"{avg_loss:.4f}", env.macro_steps])

        if ep_reward > best_reward or num_maps_visited > best_maps_visited:
            if ep_reward > best_reward:
                best_reward = ep_reward
            if num_maps_visited > best_maps_visited:
                best_maps_visited = num_maps_visited
            torch.save(agent.policy_net.state_dict(), os.path.join("models", "global_49map_dqn_best.pt"))

        if episode % log_interval == 0 or episode == num_episodes:
            mean_r = np.mean(recent_rewards[-log_interval:])
            mean_maps = np.mean(recent_maps_counts[-log_interval:])
            success_rate = np.mean(recent_successes[-log_interval:]) * 100.0
            elapsed = time.time() - start_time
            csv_file.flush()
            print(f"Ep {episode:5d}/{num_episodes} | Eps: {epsilon:.3f} | R: {mean_r:6.1f} | Maps/Ep: {mean_maps:4.1f} | Success: {success_rate:5.1f}% | Time: {elapsed:.1f}s", flush=True)

    csv_file.close()

    # Save final model
    torch.save(agent.policy_net.state_dict(), os.path.join("models", "global_49map_dqn_final.pt"))

    # Export weights for browser & application consumption
    agent.policy_net.load_state_dict(torch.load(os.path.join("models", "global_49map_dqn_best.pt")))
    weights_dict = agent.export_weights_dict()
    weights_dict["metadata"] = {
        "episodes": num_episodes,
        "maps_count": 49,
        "best_reward": round(best_reward, 2),
        "best_maps_visited": best_maps_visited,
        "training_time_seconds": round(time.time() - start_time, 2),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    out_json = os.path.join("data", "processed", "global_49map_weights.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(weights_dict, f)
    print(f"Exported global weights to {out_json} ({os.path.getsize(out_json)} bytes)")

    print("=" * 80)
    print("GLOBAL 49-MAP TRAINING COMPLETED SUCCESSFULLY!")
    print("=" * 80, flush=True)


# ---------------------------------------------------------
# 5. Phase 3 improved navigation environment
# ---------------------------------------------------------

IMPROVED_STEP_PENALTY = 0.05
IMPROVED_SUCCESS_BONUS = 50.0
IMPROVED_TIMEOUT_PENALTY = 20.0
IMPROVED_NO_ACTIONS_PENALTY = 10.0
IMPROVED_INVALID_ACTION_PENALTY = 1.0
IMPROVED_REPEAT_ACTION_PENALTY = 0.5
IMPROVED_REVISIT_PENALTY = 0.2
IMPROVED_MAP_DISCOVERY_BONUS = 0.2
IMPROVED_TILE_DISCOVERY_BONUS = 0.01
IMPROVED_EFFICIENCY_BONUS_MAX = 5.0
IMPROVED_POTENTIAL_SCALE = 0.1
IMPROVED_GAMMA = 0.99
INFINITE_COST = 10**6


class RemainingCostOracle:
    """Fast target-aware cost estimate for reward shaping and action masks."""

    def __init__(self, world_graph: GlobalWorldGraph, sector_waypoints: Dict[str, Dict[int, Tuple[int, int]]]):
        self.wg = world_graph
        self.grids = world_graph.grids
        self.sector_waypoints = sector_waypoints
        self.map_names = sorted(self.grids.keys())
        self.nav = GlobalNavigator(world_graph.registry, self.grids, allow_unverified=True)
        self.local = self.nav.local
        self.usable_transitions = self.nav.usable_transitions
        self.map_graph = nx.DiGraph()
        for map_name in self.map_names:
            self.map_graph.add_node(map_name)
        for record in self.usable_transitions:
            self.map_graph.add_edge(record.source_map, record.destination_map, weight=1.0)
        self.map_dist = {
            source: dict(distances)
            for source, distances in nx.all_pairs_shortest_path_length(self.map_graph)
        }
        self.portals_by_map: Dict[str, List[Any]] = {}
        for record in self.usable_transitions:
            self.portals_by_map.setdefault(record.source_map, []).append(record)
        self.candidates_by_map_action: Dict[str, Dict[int, List[Any]]] = {}
        for map_name in self.map_names:
            self.candidates_by_map_action[map_name] = {
                action: self._candidates_for_action(map_name, action)
                for action in range(5, 11)
            }
        self._local_route_cache: Dict[Tuple[str, Tuple[int, int], Tuple[int, int]], Optional[int]] = {}
        self._local_distance_cache: Dict[Tuple[str, Tuple[int, int]], Dict[Tuple[int, int], int]] = {}
        self._remaining_cache: Dict[Tuple[str, Tuple[int, int], str, int], int] = {}
        self.target_entry_cost: Dict[Tuple[str, int], int] = {}
        self._build_target_entry_costs()

    def _candidates_for_action(self, map_name: str, action: int) -> List[Any]:
        records = [record for record in self.usable_transitions if record.source_map == map_name]
        if action in (5, 6, 7, 8):
            direction = {5: "north", 6: "south", 7: "west", 8: "east"}[action]
            return [
                record
                for record in records
                if record.transition_class == "overworld_seam"
                and record.trigger == f"move:{direction}"
            ]
        if action == 9:
            ascents = [
                record
                for record in records
                if record.transition_class == "dungeon_floor"
                and record.transition_type == "ascend"
            ]
            if ascents:
                return ascents
            return [
                record
                for record in records
                if record.transition_class == "overworld_to_dungeon"
                and record.transition_type == "entrance"
            ]
        descents = [
            record
            for record in records
            if record.transition_class == "dungeon_floor"
            and record.transition_type == "descend"
        ]
        if descents:
            return descents
        return [
            record
            for record in records
            if record.transition_class == "overworld_to_dungeon"
            and record.transition_type == "exit"
        ]

    def _build_target_entry_costs(self) -> None:
        incoming_by_map: Dict[str, List[Any]] = {}
        for record in self.usable_transitions:
            if record.destination_coord is not None:
                incoming_by_map.setdefault(record.destination_map, []).append(record)
        for target_map in self.map_names:
            for sector, target_coord in self.sector_waypoints[target_map].items():
                best = INFINITE_COST
                for record in incoming_by_map.get(target_map, []):
                    cost = self.local_route(target_map, record.destination_coord, target_coord)
                    if cost is not None and cost < best:
                        best = cost
                self.target_entry_cost[(target_map, sector)] = 0 if best == INFINITE_COST else best

    def local_route(
        self,
        map_name: str,
        start: Sequence[int],
        goal: Sequence[int],
    ) -> Optional[int]:
        key = (map_name, (int(start[0]), int(start[1])), (int(goal[0]), int(goal[1])))
        if key in self._local_route_cache:
            return self._local_route_cache[key]
        start_coord, goal_coord = key[1], key[2]
        if start_coord == goal_coord:
            cost = 0 if self.local.validate_coord(map_name, start_coord)[0] else None
            self._local_route_cache[key] = cost
            return cost
        distance_key = (map_name, start_coord)
        distances = self._local_distance_cache.get(distance_key)
        if distances is None:
            if not self.local.validate_coord(map_name, start_coord)[0]:
                self._local_route_cache[key] = None
                return None
            distances, _ = self.local.bfs_tree(map_name, start_coord)
            self._local_distance_cache[distance_key] = distances
        cost = distances.get(goal_coord)
        self._local_route_cache[key] = cost
        return cost

    def map_hops(self, from_map: str, to_map: str) -> int:
        if from_map == to_map:
            return 0
        return self.map_dist.get(from_map, {}).get(to_map, INFINITE_COST)

    def remaining_cost(
        self,
        map_name: str,
        coord: Sequence[int],
        target_map: str,
        target_sector: int,
    ) -> int:
        key = (map_name, (int(coord[0]), int(coord[1])), target_map, int(target_sector))
        if key in self._remaining_cache:
            return self._remaining_cache[key]

        target_coord = self.sector_waypoints[target_map][target_sector]
        if map_name == target_map:
            local_cost = self.local_route(map_name, key[1], target_coord)
            if local_cost is not None:
                self._remaining_cache[key] = local_cost
                return local_cost
            route = self.nav.plan(map_name, key[1], target_map, target_coord)
            cost = route.total_cost if route.success and route.total_cost is not None else INFINITE_COST
            self._remaining_cache[key] = cost
            return cost

        if target_map not in self.map_dist.get(map_name, {}):
            self._remaining_cache[key] = INFINITE_COST
            return INFINITE_COST

        target_entry = self.target_entry_cost.get((target_map, target_sector), 0)
        best = INFINITE_COST
        for record in self.portals_by_map.get(map_name, []):
            if record.source_coord is None or record.destination_coord is None:
                continue
            if target_map not in self.map_dist.get(record.destination_map, {}):
                continue
            local_cost = self.local_route(map_name, key[1], record.source_coord)
            if local_cost is None:
                continue
            cost = local_cost + 1 + self.map_dist[record.destination_map][target_map] + target_entry
            if cost < best:
                best = cost
        self._remaining_cache[key] = best
        return best

    def potential(
        self,
        map_name: str,
        coord: Sequence[int],
        target_map: str,
        target_sector: int,
    ) -> float:
        cost = self.remaining_cost(map_name, coord, target_map, target_sector)
        if cost >= INFINITE_COST:
            return -5.0
        return -min(cost, 100) * IMPROVED_POTENTIAL_SCALE

    def best_transition(
        self,
        map_name: str,
        coord: Sequence[int],
        action: int,
        target_map: str,
        target_sector: int,
    ) -> Optional[Tuple[Any, int]]:
        best: Optional[Tuple[Any, int]] = None
        best_score = INFINITE_COST
        for record in self.candidates_by_map_action.get(map_name, {}).get(action, []):
            if record.source_coord is None or record.destination_coord is None:
                continue
            local_cost = self.local_route(map_name, coord, record.source_coord)
            if local_cost is None:
                continue
            after = self.remaining_cost(
                record.destination_map,
                record.destination_coord,
                target_map,
                target_sector,
            )
            score = local_cost + 1 + after
            if score < best_score or (
                score == best_score
                and best is not None
                and record.portal_id < best[0].portal_id
            ):
                best = (record, local_cost)
                best_score = score
        return best


class ImprovedGlobal49MapEnv:
    """Target-location-aware macro navigation environment for Phase 3."""

    def __init__(
        self,
        world_graph: GlobalWorldGraph,
        max_macro_steps: int = 30,
        seed: int = 42,
        oracle: Optional[RemainingCostOracle] = None,
    ):
        self.wg = world_graph
        self.registry = world_graph.registry
        self.max_macro_steps = max_macro_steps
        self.map_names = sorted(world_graph.grids.keys())
        self.map_to_idx = {name: i for i, name in enumerate(self.map_names)}
        self.num_maps = len(self.map_names)
        self.walkable_tiles: Dict[str, List[Tuple[int, int]]] = {}
        self.sector_waypoints: Dict[str, Dict[int, Tuple[int, int]]] = {}
        for name, grid in self.wg.grids.items():
            walkable = [
                (x, y)
                for y in range(33)
                for x in range(33)
                if grid.get_tile(x, y) and grid.get_tile(x, y).walkable
            ]
            self.walkable_tiles[name] = walkable
            self.sector_waypoints[name] = {
                sector: min(walkable, key=lambda tile: (tile[0] - cx) ** 2 + (tile[1] - cy) ** 2)
                for sector, (cx, cy) in SECTOR_TARGETS.items()
            }
        self.oracle = oracle or RemainingCostOracle(world_graph, self.sector_waypoints)
        self.nav = self.oracle.nav
        self.local = self.oracle.local
        self.rng = random.Random(seed)
        self.reachable_maps = sorted(
            set(self.oracle.map_dist.get("overworld1", {})) | {"overworld1"}
        )
        self.transition_source_coords = {
            (record.source_map, record.source_coord)
            for record in self.nav.usable_transitions
            if record.source_coord is not None
        }
        self.action_names = ACTION_NAMES
        self.current_map = "overworld1"
        self.curr_x, self.curr_y = self.sector_waypoints["overworld1"][2]
        self.target_map = "overworld2"
        self.target_sector = 2
        self.target_coord = self.sector_waypoints[self.target_map][self.target_sector]
        self.macro_steps = 0
        self.visited_maps: set[str] = set()
        self.map_visit_counts = np.zeros(self.num_maps, dtype=np.float32)
        self.local_visited_tiles: set[Tuple[int, int]] = set()
        self.recent_maps: deque = deque(maxlen=8)
        self.recent_actions: deque = deque(maxlen=8)
        self.recent_state_actions: deque = deque(maxlen=16)
        self.total_invalid_actions = 0
        self.total_repeated_actions = 0
        self.total_repeated_visits = 0
        self.total_transitions = 0
        self.total_local_steps = 0
        self.termination_reason: Optional[str] = None
        self._action_cache: Dict[Tuple[Any, ...], Tuple[np.ndarray, np.ndarray]] = {}

    def _sample_scenario(self) -> Dict[str, Any]:
        for _ in range(200):
            target_map = self.rng.choice(self.reachable_maps)
            target_sector = self.rng.randrange(5)
            target_coord = self.sector_waypoints[target_map][target_sector]
            start_map = self.rng.choice(self.reachable_maps)
            start_coord = self.rng.choice(self.walkable_tiles[start_map])
            if start_map == target_map and start_coord == target_coord:
                continue
            if self.oracle.remaining_cost(start_map, start_coord, target_map, target_sector) >= INFINITE_COST:
                continue
            return {
                "start_map": start_map,
                "start_coord": start_coord,
                "target_map": target_map,
                "target_sector": target_sector,
                "category": "random",
            }
        return {
            "start_map": "overworld1",
            "start_coord": self.sector_waypoints["overworld1"][2],
            "target_map": "overworld6",
            "target_sector": 2,
            "category": "fallback",
        }

    def reset(
        self,
        scenario: Optional[Dict[str, Any]] = None,
        start_map: Optional[str] = None,
        target_map: Optional[str] = None,
        target_sector: Optional[int] = None,
    ) -> np.ndarray:
        if scenario is None:
            if start_map is not None and target_map is not None:
                scenario = {
                    "start_map": start_map,
                    "start_coord": self.rng.choice(self.walkable_tiles[start_map]),
                    "target_map": target_map,
                    "target_sector": self.rng.randrange(5) if target_sector is None else target_sector,
                    "category": "explicit",
                }
            else:
                scenario = self._sample_scenario()

        self.current_map = scenario["start_map"]
        self.curr_x, self.curr_y = tuple(int(v) for v in scenario["start_coord"])
        self.target_map = scenario["target_map"]
        self.target_sector = int(scenario["target_sector"])
        self.target_coord = self.sector_waypoints[self.target_map][self.target_sector]
        if self.current_map == self.target_map and (self.curr_x, self.curr_y) == self.target_coord:
            self.target_sector = (self.target_sector + 1) % 5
            self.target_coord = self.sector_waypoints[self.target_map][self.target_sector]

        self.macro_steps = 0
        self.visited_maps = {self.current_map}
        self.map_visit_counts = np.zeros(self.num_maps, dtype=np.float32)
        self.map_visit_counts[self.map_to_idx[self.current_map]] = 1.0
        self.local_visited_tiles = {(self.curr_x, self.curr_y)}
        self.recent_maps = deque([self.map_to_idx[self.current_map]], maxlen=8)
        self.recent_actions = deque(maxlen=8)
        self.recent_state_actions = deque(maxlen=16)
        self.total_invalid_actions = 0
        self.total_repeated_actions = 0
        self.total_repeated_visits = 0
        self.total_transitions = 0
        self.total_local_steps = 0
        self.termination_reason = None
        self._action_cache.clear()
        self.scenario = dict(scenario)
        return self._get_obs()

    def _cache_key(self) -> Tuple[Any, ...]:
        return (
            self.current_map,
            self.curr_x,
            self.curr_y,
            self.target_map,
            self.target_sector,
        )

    def _compute_action_mask_and_warp_costs(self) -> Tuple[np.ndarray, np.ndarray]:
        key = self._cache_key()
        cached = self._action_cache.get(key)
        if cached is not None:
            return cached
        mask = np.zeros(11, dtype=bool)
        warp_costs = np.ones(4, dtype=np.float32)
        for action in range(5):
            waypoint = self.sector_waypoints[self.current_map][action]
            if waypoint == (self.curr_x, self.curr_y):
                continue
            if self.oracle.local_route(self.current_map, (self.curr_x, self.curr_y), waypoint) is not None:
                mask[action] = True
        for action in range(5, 11):
            best = self.oracle.best_transition(
                self.current_map,
                (self.curr_x, self.curr_y),
                action,
                self.target_map,
                self.target_sector,
            )
            if best is not None:
                mask[action] = True
                if action <= 8:
                    warp_costs[action - 5] = min(best[1] / 32.0, 1.0)
        result = (mask, warp_costs)
        self._action_cache[key] = result
        return result

    def get_action_mask(self) -> np.ndarray:
        mask, _ = self._compute_action_mask_and_warp_costs()
        return mask.copy()

    def _get_obs(self) -> np.ndarray:
        mask, warp_costs = self._compute_action_mask_and_warp_costs()
        obs: List[float] = []

        current_vec = np.zeros(self.num_maps, dtype=np.float32)
        current_vec[self.map_to_idx[self.current_map]] = 1.0
        obs.extend(current_vec.tolist())

        target_vec = np.zeros(self.num_maps, dtype=np.float32)
        target_vec[self.map_to_idx[self.target_map]] = 1.0
        obs.extend(target_vec.tolist())

        obs.extend([self.curr_x / 32.0, self.curr_y / 32.0])
        obs.extend([self.target_coord[0] / 32.0, self.target_coord[1] / 32.0])
        same_map = 1.0 if self.current_map == self.target_map else 0.0
        obs.append(same_map)

        remaining = self.oracle.remaining_cost(
            self.current_map,
            (self.curr_x, self.curr_y),
            self.target_map,
            self.target_sector,
        )
        obs.append(min(remaining, 50) / 50.0 if remaining < INFINITE_COST else 1.0)
        hops = self.oracle.map_hops(self.current_map, self.target_map)
        obs.append(min(hops, 10) / 10.0 if hops < INFINITE_COST else 1.0)

        local_target_distance = 0.0
        if same_map:
            cost = self.oracle.local_route(
                self.current_map,
                (self.curr_x, self.curr_y),
                self.target_coord,
            )
            local_target_distance = 1.0 if cost is None else min(cost / 64.0, 1.0)
        obs.append(local_target_distance)

        visited_vec = np.zeros(self.num_maps, dtype=np.float32)
        for map_name in self.visited_maps:
            visited_vec[self.map_to_idx[map_name]] = 1.0
        obs.extend(visited_vec.tolist())

        obs.append(min(self.map_visit_counts[self.map_to_idx[self.current_map]] / 5.0, 1.0))

        recent_maps = list(self.recent_maps)
        while len(recent_maps) < 5:
            recent_maps.insert(0, -1)
        obs.extend([
            (idx / float(self.num_maps)) if idx >= 0 else -1.0
            for idx in recent_maps[-5:]
        ])

        recent_actions = list(self.recent_actions)
        while len(recent_actions) < 4:
            recent_actions.insert(0, -1)
        obs.extend([
            (action / 10.0) if action >= 0 else -1.0
            for action in recent_actions[-4:]
        ])

        obs.extend([1.0 if value else 0.0 for value in mask])
        obs.extend(warp_costs.tolist())

        tile = self.wg.grids[self.current_map].get_tile(self.curr_x, self.curr_y)
        for direction in ("n", "s", "w", "e", "nw", "ne", "sw", "se"):
            obs.append(1.0 if tile is not None and tile.allowed_directions.get(direction) else 0.0)

        obs.append(
            1.0
            if (self.current_map, (self.curr_x, self.curr_y)) in self.transition_source_coords
            else 0.0
        )
        coverage = len(self.local_visited_tiles) / max(1, len(self.walkable_tiles[self.current_map]))
        obs.append(coverage)

        return np.array(obs, dtype=np.float32)

    def _action_for_record(self, record: Any) -> Optional[int]:
        if record.transition_class == "overworld_seam":
            direction = record.trigger.replace("move:", "")
            return {"north": 5, "south": 6, "west": 7, "east": 8}.get(direction)
        if record.transition_class == "overworld_to_dungeon":
            if record.transition_type == "entrance":
                return 9
            if record.transition_type == "exit":
                return 10
        if record.transition_class == "dungeon_floor":
            if record.transition_type == "ascend":
                return 9
            if record.transition_type == "descend":
                return 10
        return None

    def teacher_action(self) -> Optional[int]:
        if self.current_map == self.target_map:
            if (self.curr_x, self.curr_y) == self.target_coord:
                return None
            if self.oracle.local_route(
                self.current_map,
                (self.curr_x, self.curr_y),
                self.target_coord,
            ) is not None:
                return self.target_sector
            return None

        best_action: Optional[int] = None
        best_score = INFINITE_COST
        for action in range(5, 11):
            best = self.oracle.best_transition(
                self.current_map,
                (self.curr_x, self.curr_y),
                action,
                self.target_map,
                self.target_sector,
            )
            if best is None:
                continue
            record, local_cost = best
            score = local_cost + 1 + self.oracle.remaining_cost(
                record.destination_map,
                record.destination_coord,
                self.target_map,
                self.target_sector,
            )
            if score < best_score:
                best_score = score
                best_action = action
        return best_action

    def _record_new_tiles(self, path: Sequence[Tuple[int, int]]) -> int:
        new_tiles = 0
        for coord in path:
            if coord not in self.local_visited_tiles:
                self.local_visited_tiles.add(coord)
                new_tiles += 1
        return new_tiles

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        action = int(action)
        old_potential = self.oracle.potential(
            self.current_map,
            (self.curr_x, self.curr_y),
            self.target_map,
            self.target_sector,
        )
        previous_state = (self.current_map, self.curr_x, self.curr_y)
        self.macro_steps += 1
        reward = 0.0
        done = False
        info: Dict[str, Any] = {
            "action": action,
            "action_name": self.action_names[action] if 0 <= action < 11 else "Invalid",
            "transition": None,
            "portal_id": None,
            "transition_status": None,
            "path_len": 0,
            "invalid": False,
            "repeated_action": False,
            "revisited_map": False,
        }

        mask = self.get_action_mask()
        if action < 0 or action >= 11 or not mask[action]:
            reward -= IMPROVED_INVALID_ACTION_PENALTY
            self.total_invalid_actions += 1
            info["invalid"] = True
            info["error"] = "invalid_or_masked_action"
        elif action < 5:
            waypoint = self.sector_waypoints[self.current_map][action]
            local_route = self.local.local_route(
                self.current_map,
                (self.curr_x, self.curr_y),
                waypoint,
            )
            if not local_route.reachable:
                reward -= IMPROVED_INVALID_ACTION_PENALTY
                self.total_invalid_actions += 1
                info["invalid"] = True
                info["error"] = local_route.reason
            else:
                new_tiles = self._record_new_tiles(local_route.path)
                self.curr_x, self.curr_y = waypoint
                self.total_local_steps += local_route.cost
                reward = -IMPROVED_STEP_PENALTY + IMPROVED_TILE_DISCOVERY_BONUS * min(new_tiles, 10)
                info["path_len"] = local_route.cost
        else:
            best = self.oracle.best_transition(
                self.current_map,
                (self.curr_x, self.curr_y),
                action,
                self.target_map,
                self.target_sector,
            )
            if best is None:
                reward -= IMPROVED_INVALID_ACTION_PENALTY
                self.total_invalid_actions += 1
                info["invalid"] = True
                info["error"] = "no_reachable_transition"
            else:
                record, local_cost = best
                local_route = self.local.local_route(
                    self.current_map,
                    (self.curr_x, self.curr_y),
                    record.source_coord,
                )
                new_tiles = self._record_new_tiles(local_route.path)
                self.total_local_steps += local_route.cost
                previous_map = self.current_map
                self.current_map = record.destination_map
                self.curr_x, self.curr_y = record.destination_coord
                self.total_transitions += 1
                map_idx = self.map_to_idx[self.current_map]
                self.map_visit_counts[map_idx] += 1.0
                self.recent_maps.append(map_idx)
                if self.current_map not in self.visited_maps:
                    self.visited_maps.add(self.current_map)
                    reward += IMPROVED_MAP_DISCOVERY_BONUS
                if self.current_map in list(self.recent_maps)[:-1] and self.current_map != self.target_map:
                    reward -= IMPROVED_REVISIT_PENALTY
                    self.total_repeated_visits += 1
                    info["revisited_map"] = True
                reward += -IMPROVED_STEP_PENALTY + IMPROVED_TILE_DISCOVERY_BONUS * min(new_tiles, 10)
                info["transition"] = self.current_map
                info["portal_id"] = record.portal_id
                info["transition_status"] = record.verification_status
                info["path_len"] = local_cost
                info["previous_map"] = previous_map

        state_action = (previous_state[0], previous_state[1], previous_state[2], action)
        if state_action in self.recent_state_actions:
            reward -= IMPROVED_REPEAT_ACTION_PENALTY
            self.total_repeated_actions += 1
            info["repeated_action"] = True
        self.recent_state_actions.append(state_action)
        self.recent_actions.append(action)

        new_potential = self.oracle.potential(
            self.current_map,
            (self.curr_x, self.curr_y),
            self.target_map,
            self.target_sector,
        )
        reward += IMPROVED_GAMMA * new_potential - old_potential
        remaining = self.oracle.remaining_cost(
            self.current_map,
            (self.curr_x, self.curr_y),
            self.target_map,
            self.target_sector,
        )
        info["remaining_cost"] = remaining
        info["potential"] = new_potential

        if self.current_map == self.target_map and (self.curr_x, self.curr_y) == self.target_coord:
            efficiency = max(0.0, 1.0 - self.macro_steps / max(1, self.max_macro_steps))
            reward += IMPROVED_SUCCESS_BONUS + IMPROVED_EFFICIENCY_BONUS_MAX * efficiency
            done = True
            self.termination_reason = "success"
        elif self.macro_steps >= self.max_macro_steps:
            reward += IMPROVED_TIMEOUT_PENALTY
            done = True
            self.termination_reason = "timeout"
        elif not self.get_action_mask().any():
            reward += IMPROVED_NO_ACTIONS_PENALTY
            done = True
            self.termination_reason = "no_legal_actions"

        info["termination_reason"] = self.termination_reason
        info["success"] = self.termination_reason == "success"
        info["steps"] = self.macro_steps
        return self._get_obs(), reward, done, info


# ---------------------------------------------------------
# 6. Phase 3 improved DQN training logic
# ---------------------------------------------------------


class Global49MapDQNv2:
    """Dueling DQN with double-Q targets, step epsilon, and full checkpoints."""

    def __init__(
        self,
        input_dim: int,
        num_actions: int = 11,
        lr: float = 5e-4,
        gamma: float = 0.99,
        buffer_size: int = 100_000,
        batch_size: int = 128,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay_steps: int = 30_000,
        warmup_steps: int = 2_000,
        target_update_freq: int = 1_000,
        grad_clip: float = 5.0,
    ):
        self.input_dim = input_dim
        self.num_actions = num_actions
        self.gamma = gamma
        self.batch_size = batch_size
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay_steps = epsilon_decay_steps
        self.warmup_steps = warmup_steps
        self.target_update_freq = target_update_freq
        self.grad_clip = grad_clip
        self.policy_net = DuelingDQN(input_dim, num_actions)
        self.target_net = DuelingDQN(input_dim, num_actions)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.criterion = nn.SmoothL1Loss()
        self.buffer: deque = deque(maxlen=buffer_size)
        self.total_steps = 0
        self.update_steps = 0
        self.episodes = 0
        self.losses: List[float] = []

    @property
    def epsilon(self) -> float:
        progress = min(self.total_steps / max(1, self.epsilon_decay_steps), 1.0)
        return self.epsilon_start + progress * (self.epsilon_end - self.epsilon_start)

    def select_action(
        self,
        state: np.ndarray,
        mask: np.ndarray,
        epsilon: Optional[float] = None,
        teacher_action: Optional[int] = None,
    ) -> int:
        legal = np.where(mask)[0]
        if len(legal) == 0:
            return 0
        if teacher_action is not None and 0 <= teacher_action < self.num_actions and mask[teacher_action]:
            return int(teacher_action)
        eps = self.epsilon if epsilon is None else epsilon
        if random.random() < eps:
            return int(random.choice(legal))
        with torch.no_grad():
            state_t = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.policy_net(state_t).squeeze(0).numpy()
            q_values[~mask] = -1e9
            return int(np.argmax(q_values))

    def store_transition(self, state, action, reward, next_state, done, next_mask):
        self.buffer.append((
            np.asarray(state, dtype=np.float32),
            int(action),
            float(reward),
            np.asarray(next_state, dtype=np.float32),
            float(done),
            np.asarray(next_mask, dtype=bool),
        ))
        self.total_steps += 1

    def update(self) -> Optional[float]:
        if len(self.buffer) < max(self.batch_size, self.warmup_steps):
            return None
        batch = random.sample(self.buffer, self.batch_size)
        states, actions, rewards, next_states, dones, next_masks = zip(*batch)
        s_t = torch.FloatTensor(np.stack(states))
        a_t = torch.LongTensor(actions).unsqueeze(1)
        r_t = torch.FloatTensor(rewards).unsqueeze(1)
        ns_t = torch.FloatTensor(np.stack(next_states))
        d_t = torch.FloatTensor(dones).unsqueeze(1)
        next_mask_t = torch.BoolTensor(np.stack(next_masks))

        current_q = self.policy_net(s_t).gather(1, a_t)
        with torch.no_grad():
            next_policy_q = self.policy_net(ns_t)
            next_policy_q[~next_mask_t] = -1e9
            next_actions = next_policy_q.argmax(dim=1, keepdim=True)
            next_target_q = self.target_net(ns_t).gather(1, next_actions)
            target_q = r_t + (1.0 - d_t) * self.gamma * next_target_q

        loss = self.criterion(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), self.grad_clip)
        self.optimizer.step()
        self.update_steps += 1
        if self.update_steps % self.target_update_freq == 0:
            self.sync_target()
        loss_value = float(loss.item())
        self.losses.append(loss_value)
        return loss_value

    def sync_target(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def checkpoint_payload(
        self,
        episode: int,
        metrics: Optional[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "format": "delugerpg.global_dqn_v2",
            "policy_net_state": self.policy_net.state_dict(),
            "target_net_state": self.target_net.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "episode": episode,
            "total_steps": self.total_steps,
            "update_steps": self.update_steps,
            "episodes": self.episodes,
            "epsilon": self.epsilon,
            "losses": self.losses,
            "metrics": metrics or {},
            "config": config,
            "obs_dim": self.input_dim,
            "num_actions": self.num_actions,
        }

    def save_checkpoint(
        self,
        path: str,
        episode: int,
        metrics: Optional[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(self.checkpoint_payload(episode, metrics, config), path)

    def load_checkpoint(self, path: str) -> Dict[str, Any]:
        checkpoint = torch.load(path, map_location="cpu")
        if "policy_net_state" not in checkpoint:
            raise ValueError(f"{path} is not a Phase 3 full checkpoint")
        self.policy_net.load_state_dict(checkpoint["policy_net_state"])
        self.target_net.load_state_dict(checkpoint.get("target_net_state", checkpoint["policy_net_state"]))
        if "optimizer_state" in checkpoint:
            self.optimizer.load_state_dict(checkpoint["optimizer_state"])
        self.total_steps = int(checkpoint.get("total_steps", 0))
        self.update_steps = int(checkpoint.get("update_steps", 0))
        self.episodes = int(checkpoint.get("episodes", checkpoint.get("episode", 0)))
        self.losses = list(checkpoint.get("losses", []))
        return checkpoint

    def export_weights_dict(self) -> Dict[str, Any]:
        return {
            key: value.cpu().numpy().tolist()
            for key, value in self.policy_net.state_dict().items()
        }


# ---------------------------------------------------------
# 7. Scenario generation, evaluation, and checkpoints
# ---------------------------------------------------------


class ImprovedScenarioGenerator:
    def __init__(self, env: ImprovedGlobal49MapEnv, seed: int = 42):
        self.env = env
        self.oracle = env.oracle
        self.rng = random.Random(seed)
        self.reachable_maps = list(env.reachable_maps)
        self.walkable_tiles = env.walkable_tiles
        self.sector_waypoints = env.sector_waypoints
        self.pairs_by_hops: Dict[int, List[Tuple[str, str]]] = {}
        for start_map in self.reachable_maps:
            for target_map in self.reachable_maps:
                if start_map == target_map:
                    continue
                hops = self.oracle.map_hops(start_map, target_map)
                if hops < INFINITE_COST:
                    self.pairs_by_hops.setdefault(hops, []).append((start_map, target_map))

    def _make(
        self,
        start_map: str,
        target_map: str,
        target_sector: int,
        category: str,
    ) -> Optional[Dict[str, Any]]:
        target_coord = self.sector_waypoints[target_map][target_sector]
        for _ in range(40):
            start_coord = self.rng.choice(self.walkable_tiles[start_map])
            if start_map == target_map and start_coord == target_coord:
                continue
            if self.oracle.remaining_cost(start_map, start_coord, target_map, target_sector) >= INFINITE_COST:
                continue
            return {
                "start_map": start_map,
                "start_coord": start_coord,
                "target_map": target_map,
                "target_sector": target_sector,
                "category": category,
            }
        return None

    def generate(self, episode: int, total_episodes: int) -> Dict[str, Any]:
        progress = episode / max(1, total_episodes)
        if progress < 0.10:
            stage_max_hops = 1
        elif progress < 0.30:
            stage_max_hops = 2
        elif progress < 0.55:
            stage_max_hops = 4
        elif progress < 0.80:
            stage_max_hops = 8
        else:
            stage_max_hops = 12

        easy = self.rng.random() < 0.25
        if easy:
            stage_max_hops = min(stage_max_hops, 1)

        for _ in range(120):
            target_map = self.rng.choice(self.reachable_maps)
            target_sector = self.rng.randrange(5)
            if self.rng.random() < 0.18:
                start_map = target_map
                category = "same_map"
            else:
                candidate_hops = [
                    hops for hops in self.pairs_by_hops
                    if hops <= stage_max_hops
                ]
                if not candidate_hops:
                    candidate_hops = list(self.pairs_by_hops)
                hops = self.rng.choice(candidate_hops)
                pairs = [
                    pair for pair in self.pairs_by_hops.get(hops, [])
                    if pair[1] == target_map
                ]
                if not pairs:
                    pairs = self.pairs_by_hops.get(hops, [])
                if not pairs:
                    continue
                start_map = self.rng.choice(pairs)[0]
                category = f"hops_{hops}"
            scenario = self._make(start_map, target_map, target_sector, category)
            if scenario is not None:
                return scenario
        return self.env._sample_scenario()


def build_eval_scenarios(
    env: ImprovedGlobal49MapEnv,
    seed: int = 12345,
    counts: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    counts = counts or {
        "same_map": 30,
        "short_1hop": 30,
        "medium_2_3": 40,
        "long_4plus": 40,
        "dungeon": 30,
        "disconnected_backtrack": 20,
        "random": 10,
    }
    rng = random.Random(seed)
    oracle = env.oracle
    reachable = list(env.reachable_maps)
    dungeon_maps = [name for name in reachable if not name.startswith("overworld")]
    scenarios: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    def add(scenario: Optional[Dict[str, Any]]) -> None:
        if scenario is None:
            return
        key = (
            scenario["start_map"],
            tuple(scenario["start_coord"]),
            scenario["target_map"],
            scenario["target_sector"],
        )
        if key in seen:
            return
        seen.add(key)
        scenarios.append(scenario)

    def make(start_map: str, target_map: str, category: str) -> Optional[Dict[str, Any]]:
        target_sector = rng.randrange(5)
        target_coord = env.sector_waypoints[target_map][target_sector]
        for _ in range(60):
            start_coord = rng.choice(env.walkable_tiles[start_map])
            if start_map == target_map and start_coord == target_coord:
                continue
            if oracle.remaining_cost(start_map, start_coord, target_map, target_sector) >= INFINITE_COST:
                continue
            return {
                "start_map": start_map,
                "start_coord": start_coord,
                "target_map": target_map,
                "target_sector": target_sector,
                "category": category,
            }
        return None

    for _ in range(counts["same_map"]):
        target_map = rng.choice(reachable)
        add(make(target_map, target_map, "same_map"))

    for _ in range(counts["short_1hop"]):
        target_map = rng.choice(reachable)
        candidates = [
            start for start in reachable
            if oracle.map_hops(start, target_map) == 1
        ]
        if candidates:
            add(make(rng.choice(candidates), target_map, "short_1hop"))

    for _ in range(counts["medium_2_3"]):
        target_map = rng.choice(reachable)
        candidates = [
            start for start in reachable
            if 2 <= oracle.map_hops(start, target_map) <= 3
        ]
        if candidates:
            add(make(rng.choice(candidates), target_map, "medium_2_3"))

    for _ in range(counts["long_4plus"]):
        target_map = rng.choice(reachable)
        candidates = [
            start for start in reachable
            if oracle.map_hops(start, target_map) >= 4
        ]
        if candidates:
            add(make(rng.choice(candidates), target_map, "long_4plus"))

    for _ in range(counts["dungeon"]):
        if dungeon_maps:
            target_map = rng.choice(dungeon_maps)
            candidates = [
                start for start in reachable
                if oracle.map_hops(start, target_map) < INFINITE_COST
            ]
            if candidates:
                add(make(rng.choice(candidates), target_map, "dungeon"))

    disconnected_found = 0
    for map_name in reachable:
        if disconnected_found >= counts["disconnected_backtrack"]:
            break
        for target_sector in range(5):
            target_coord = env.sector_waypoints[map_name][target_sector]
            for _ in range(30):
                start_coord = rng.choice(env.walkable_tiles[map_name])
                if start_coord == target_coord:
                    continue
                local_cost = oracle.local_route(map_name, start_coord, target_coord)
                if local_cost is not None:
                    continue
                if oracle.remaining_cost(map_name, start_coord, map_name, target_sector) >= INFINITE_COST:
                    continue
                add({
                    "start_map": map_name,
                    "start_coord": start_coord,
                    "target_map": map_name,
                    "target_sector": target_sector,
                    "category": "disconnected_backtrack",
                })
                disconnected_found += 1
                break
            if disconnected_found >= counts["disconnected_backtrack"]:
                break

    attempts = 0
    while len(scenarios) < sum(counts.values()) and attempts < 5000:
        attempts += 1
        target_map = rng.choice(reachable)
        start_map = rng.choice(reachable)
        add(make(start_map, target_map, "random"))

    return scenarios


def save_eval_scenarios(path: str, scenarios: Sequence[Dict[str, Any]], seed: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "version": 1,
        "seed": seed,
        "count": len(scenarios),
        "scenarios": list(scenarios),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_eval_scenarios(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    scenarios = list(payload.get("scenarios", []))
    for scenario in scenarios:
        scenario["start_coord"] = tuple(scenario["start_coord"])
    return scenarios


def evaluate_improved_agent(
    env: ImprovedGlobal49MapEnv,
    agent: Global49MapDQNv2,
    scenarios: Sequence[Dict[str, Any]],
    epsilon: float = 0.0,
    seed: int = 0,
) -> Dict[str, Any]:
    random_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.get_rng_state()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    rows: List[Dict[str, Any]] = []
    try:
        for scenario in scenarios:
            state = env.reset(scenario=scenario)
            done = False
            episode_reward = 0.0
            steps = 0
            invalid_actions = 0
            repeated_actions = 0
            termination = None
            while not done:
                mask = env.get_action_mask()
                action = agent.select_action(state, mask, epsilon=epsilon)
                state, reward, done, info = env.step(action)
                episode_reward += reward
                steps += 1
                if info.get("invalid"):
                    invalid_actions += 1
                if info.get("repeated_action"):
                    repeated_actions += 1
                termination = info.get("termination_reason")
            success = termination == "success"
            repeated_visits = int(sum(max(0.0, value - 1.0) for value in env.map_visit_counts))
            rows.append({
                "scenario": scenario,
                "success": success,
                "reward": episode_reward,
                "steps": steps,
                "termination_reason": termination,
                "maps_visited": len(env.visited_maps),
                "map_coverage": len(env.visited_maps) / max(1, len(env.reachable_maps)),
                "repeated_visits": repeated_visits,
                "repeated_actions": repeated_actions,
                "invalid_actions": invalid_actions,
                "final_map": env.current_map,
                "final_coord": [env.curr_x, env.curr_y],
                "target_map": env.target_map,
                "target_coord": [env.target_coord[0], env.target_coord[1]],
            })
    finally:
        random.setstate(random_state)
        np.random.set_state(numpy_state)
        torch.set_rng_state(torch_state)

    total = len(rows)
    successes = [row for row in rows if row["success"]]
    failures = [row for row in rows if not row["success"]]
    termination_counts = Counter(row["termination_reason"] for row in rows)
    total_steps = sum(row["steps"] for row in rows)
    return {
        "scenarios": total,
        "successes": len(successes),
        "success_rate": len(successes) / total if total else 0.0,
        "avg_reward": float(np.mean([row["reward"] for row in rows])) if rows else 0.0,
        "avg_steps": float(np.mean([row["steps"] for row in rows])) if rows else 0.0,
        "avg_steps_success": float(np.mean([row["steps"] for row in successes])) if successes else None,
        "avg_steps_failure": float(np.mean([row["steps"] for row in failures])) if failures else None,
        "avg_map_coverage": float(np.mean([row["map_coverage"] for row in rows])) if rows else 0.0,
        "avg_repeated_visits": float(np.mean([row["repeated_visits"] for row in rows])) if rows else 0.0,
        "avg_repeated_actions": float(np.mean([row["repeated_actions"] for row in rows])) if rows else 0.0,
        "timeout_rate": termination_counts.get("timeout", 0) / total if total else 0.0,
        "invalid_action_rate": (
            sum(row["invalid_actions"] for row in rows) / total_steps if total_steps else 0.0
        ),
        "termination_reasons": dict(termination_counts),
        "rows": rows,
    }


def evaluate_baseline_agent(
    env: Global49MapEnv,
    agent: Global49MapDQN,
    scenarios: Sequence[Dict[str, Any]],
    epsilon: float = 0.0,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for scenario in scenarios:
        state = env.set_scenario(
            scenario["start_map"],
            tuple(scenario["start_coord"]),
            scenario["target_map"],
        )
        target_coord = env.sector_waypoints[scenario["target_map"]][scenario["target_sector"]]
        done = False
        episode_reward = 0.0
        steps = 0
        while not done:
            mask = env.get_action_mask()
            action = agent.select_action(state, mask, epsilon=epsilon)
            state, reward, done, info = env.step(action)
            episode_reward += reward
            steps += 1
        map_success = env.current_map == scenario["target_map"]
        strict_success = map_success and (env.curr_x, env.curr_y) == target_coord
        rows.append({
            "scenario": scenario,
            "success": strict_success,
            "map_success": map_success,
            "reward": episode_reward,
            "steps": steps,
            "maps_visited": len(env.visited_maps),
            "map_coverage": len(env.visited_maps) / max(1, len(env.map_names)),
            "final_map": env.current_map,
            "final_coord": [env.curr_x, env.curr_y],
            "target_map": scenario["target_map"],
            "target_coord": [target_coord[0], target_coord[1]],
        })
    total = len(rows)
    successes = [row for row in rows if row["success"]]
    failures = [row for row in rows if not row["success"]]
    return {
        "scenarios": total,
        "successes": len(successes),
        "success_rate": len(successes) / total if total else 0.0,
        "map_success_rate": sum(1 for row in rows if row["map_success"]) / total if total else 0.0,
        "avg_reward": float(np.mean([row["reward"] for row in rows])) if rows else 0.0,
        "avg_steps": float(np.mean([row["steps"] for row in rows])) if rows else 0.0,
        "avg_steps_success": float(np.mean([row["steps"] for row in successes])) if successes else None,
        "avg_steps_failure": float(np.mean([row["steps"] for row in failures])) if failures else None,
        "avg_map_coverage": float(np.mean([row["map_coverage"] for row in rows])) if rows else 0.0,
        "rows": rows,
    }


def save_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def train_improved_global_agent(
    num_episodes: int = 8_000,
    seed: int = 42,
    max_macro_steps: int = 30,
    eval_interval: int = 400,
    eval_scenarios_path: str = "data/processed/global_eval_scenarios_v1.json",
    checkpoint_prefix: str = "models/global_49map_dqn_v2",
    log_path: str = "logs/global_49map_training_v2_log.csv",
    eval_log_path: str = "logs/global_49map_eval_v2.csv",
    resume: Optional[str] = None,
    use_teacher: bool = True,
    teacher_decay_episodes: int = 3_000,
) -> Dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    print("=" * 80)
    print("DELUGERPG PHASE 3: TARGET-AWARE DUELING DQN NAVIGATION")
    print(f"Episodes: {num_episodes} | Seed: {seed} | Max macro steps: {max_macro_steps}")
    print("=" * 80, flush=True)

    wg = GlobalWorldGraph()
    env = ImprovedGlobal49MapEnv(wg, max_macro_steps=max_macro_steps, seed=seed)
    generator = ImprovedScenarioGenerator(env, seed=seed + 1)

    if os.path.exists(eval_scenarios_path):
        eval_scenarios = load_eval_scenarios(eval_scenarios_path)
    else:
        eval_scenarios = build_eval_scenarios(env, seed=12345)
        save_eval_scenarios(eval_scenarios_path, eval_scenarios, 12345)

    initial_scenario = generator.generate(1, num_episodes)
    obs_dim = len(env.reset(scenario=initial_scenario))
    print(f"Observation dimension: {obs_dim} | Actions: 11 | Eval scenarios: {len(eval_scenarios)}")

    config = {
        "obs_dim": obs_dim,
        "num_actions": 11,
        "lr": 5e-4,
        "gamma": 0.99,
        "batch_size": 128,
        "buffer_size": 100_000,
        "epsilon_start": 1.0,
        "epsilon_end": 0.05,
        "epsilon_decay_steps": 30_000,
        "warmup_steps": 2_000,
        "target_update_freq": 1_000,
        "grad_clip": 5.0,
        "max_macro_steps": max_macro_steps,
        "seed": seed,
        "teacher_decay_episodes": teacher_decay_episodes if use_teacher else 0,
    }
    agent = Global49MapDQNv2(
        input_dim=obs_dim,
        num_actions=11,
        lr=config["lr"],
        gamma=config["gamma"],
        buffer_size=config["buffer_size"],
        batch_size=config["batch_size"],
        epsilon_start=config["epsilon_start"],
        epsilon_end=config["epsilon_end"],
        epsilon_decay_steps=config["epsilon_decay_steps"],
        warmup_steps=config["warmup_steps"],
        target_update_freq=config["target_update_freq"],
        grad_clip=config["grad_clip"],
    )

    start_episode = 1
    best_success = -1.0
    best_metrics: Optional[Dict[str, Any]] = None
    if resume:
        checkpoint = agent.load_checkpoint(resume)
        start_episode = int(checkpoint.get("episode", 0)) + 1
        best_success = float(checkpoint.get("metrics", {}).get("success_rate", -1.0))
        print(f"Resumed from {resume} at episode {start_episode - 1}")

    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    with open(log_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow([
            "episode", "epsilon", "reward", "success", "steps", "maps_visited",
            "invalid_actions", "repeated_actions", "loss", "teacher",
            "start_map", "target_map", "target_sector", "termination_reason",
        ])
        eval_file = open(eval_log_path, "w", newline="", encoding="utf-8")
        eval_writer = csv.writer(eval_file)
        eval_writer.writerow([
            "episode", "success_rate", "avg_reward", "avg_steps_success",
            "timeout_rate", "invalid_action_rate", "best_success",
        ])
        try:
            for episode in range(start_episode, num_episodes + 1):
                scenario = generator.generate(episode, num_episodes)
                state = env.reset(scenario=scenario)
                mask = env.get_action_mask()
                done = False
                episode_reward = 0.0
                episode_loss = 0.0
                loss_updates = 0
                teacher_used = False
                info: Dict[str, Any] = {}

                while not done:
                    teacher_action = None
                    if use_teacher and episode <= teacher_decay_episodes:
                        teacher_probability = 0.5 * (1.0 - episode / max(1, teacher_decay_episodes))
                        if random.random() < teacher_probability:
                            teacher_action = env.teacher_action()
                    action = agent.select_action(
                        state,
                        mask,
                        epsilon=agent.epsilon,
                        teacher_action=teacher_action,
                    )
                    if teacher_action is not None and action == teacher_action:
                        teacher_used = True
                    next_state, reward, done, info = env.step(action)
                    next_mask = env.get_action_mask()
                    agent.store_transition(state, action, reward, next_state, done, next_mask)
                    loss = agent.update()
                    if loss is not None:
                        episode_loss += loss
                        loss_updates += 1
                    state = next_state
                    mask = next_mask
                    episode_reward += reward

                agent.episodes = episode
                success = 1 if info.get("termination_reason") == "success" else 0
                avg_loss = episode_loss / loss_updates if loss_updates else 0.0
                writer.writerow([
                    episode,
                    f"{agent.epsilon:.4f}",
                    f"{episode_reward:.2f}",
                    success,
                    env.macro_steps,
                    len(env.visited_maps),
                    env.total_invalid_actions,
                    env.total_repeated_actions,
                    f"{avg_loss:.4f}",
                    int(teacher_used),
                    scenario["start_map"],
                    scenario["target_map"],
                    scenario["target_sector"],
                    info.get("termination_reason"),
                ])

                if episode % 50 == 0 or episode == num_episodes:
                    csv_file.flush()

                if episode % eval_interval == 0 or episode == num_episodes:
                    metrics = evaluate_improved_agent(
                        env,
                        agent,
                        eval_scenarios,
                        epsilon=0.0,
                        seed=seed,
                    )
                    eval_writer.writerow([
                        episode,
                        f"{metrics['success_rate']:.4f}",
                        f"{metrics['avg_reward']:.2f}",
                        f"{metrics['avg_steps_success'] or 0:.2f}",
                        f"{metrics['timeout_rate']:.4f}",
                        f"{metrics['invalid_action_rate']:.4f}",
                        f"{best_success:.4f}",
                    ])
                    eval_file.flush()
                    if metrics["success_rate"] > best_success:
                        best_success = metrics["success_rate"]
                        best_metrics = metrics
                        agent.save_checkpoint(
                            f"{checkpoint_prefix}_best.pt",
                            episode,
                            metrics,
                            config,
                        )
                    agent.save_checkpoint(
                        f"{checkpoint_prefix}_latest.pt",
                        episode,
                        metrics,
                        config,
                    )
                    print(
                        f"Ep {episode:5d}/{num_episodes} | eps {agent.epsilon:.3f} | "
                        f"train R {episode_reward:7.2f} | eval success {metrics['success_rate']*100:5.1f}% | "
                        f"steps {metrics['avg_steps_success'] or 0:4.1f} | best {best_success*100:5.1f}%",
                        flush=True,
                    )
                elif episode % 100 == 0:
                    print(
                        f"Ep {episode:5d}/{num_episodes} | eps {agent.epsilon:.3f} | "
                        f"R {episode_reward:7.2f} | steps {env.macro_steps} | "
                        f"target {scenario['target_map']} | {info.get('termination_reason')}",
                        flush=True,
                    )
        finally:
            eval_file.close()

    agent.save_checkpoint(f"{checkpoint_prefix}_final.pt", num_episodes, best_metrics, config)
    if best_metrics is not None:
        agent.load_checkpoint(f"{checkpoint_prefix}_best.pt")
    weights = agent.export_weights_dict()
    weights["metadata"] = {
        "phase": 3,
        "episodes": num_episodes,
        "obs_dim": obs_dim,
        "best_success_rate": best_success,
        "config": config,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    weights_path = "data/processed/global_49map_weights_v2.json"
    with open(weights_path, "w", encoding="utf-8") as handle:
        json.dump(weights, handle)
    summary = {
        "config": config,
        "best_success_rate": best_success,
        "best_metrics": best_metrics,
        "weights_path": weights_path,
    }
    save_json("logs/global_49map_training_v2_summary.json", summary)
    print("=" * 80)
    print(f"Training complete. Best eval success: {best_success*100:.1f}%")
    print(f"Best checkpoint: {checkpoint_prefix}_best.pt")
    print("=" * 80, flush=True)
    return summary


def run_phase3_demo(
    checkpoint: str,
    scenario: Optional[Dict[str, Any]] = None,
    seed: int = 42,
) -> None:
    wg = GlobalWorldGraph()
    env = ImprovedGlobal49MapEnv(wg, max_macro_steps=30, seed=seed)
    if scenario is None:
        scenario = {
            "start_map": "overworld1",
            "start_coord": env.sector_waypoints["overworld1"][2],
            "target_map": "overworld6",
            "target_sector": 1,
            "category": "demo",
        }
    state = env.reset(scenario=scenario)
    obs_dim = len(state)
    agent = Global49MapDQNv2(input_dim=obs_dim, num_actions=11)
    checkpoint_data = agent.load_checkpoint(checkpoint)
    print("=" * 72)
    print("DELUGERPG Phase 3 Navigation Demo")
    print("=" * 72)
    print(f"Start: {scenario['start_map']} {tuple(scenario['start_coord'])}")
    print(f"Target: {scenario['target_map']} sector {scenario['target_sector']} {env.target_coord}")
    print(f"Checkpoint: {checkpoint} (episode {checkpoint_data.get('episode')})")
    print("-" * 72)
    done = False
    step = 0
    total_reward = 0.0
    while not done:
        step += 1
        mask = env.get_action_mask()
        action = agent.select_action(state, mask, epsilon=0.0)
        state, reward, done, info = env.step(action)
        total_reward += reward
        transition = info.get("transition")
        suffix = f" -> {transition} via {info.get('portal_id')}" if transition else ""
        print(
            f"{step:02d}. {info['action_name']:<22} "
            f"{env.current_map} ({env.curr_x:02d},{env.curr_y:02d}) "
            f"r={reward:+7.2f} remaining={info.get('remaining_cost')}{suffix}"
        )
    print("-" * 72)
    print(f"Final: {env.current_map} ({env.curr_x},{env.curr_y})")
    print(f"Success: {env.termination_reason == 'success'}")
    print(f"Steps: {env.macro_steps} | Total reward: {total_reward:.2f}")
    print(f"Maps visited: {sorted(env.visited_maps)}")
    print("=" * 72)


def run_baseline_evaluation(
    eval_scenarios_path: str = "data/processed/global_eval_scenarios_v1.json",
    checkpoint: str = "models/global_49map_dqn_best.pt",
    output_path: str = "logs/baseline_evaluation.json",
) -> Dict[str, Any]:
    wg = GlobalWorldGraph()
    env = Global49MapEnv(wg, max_macro_steps=30)
    agent = Global49MapDQN(input_dim=204, num_actions=11)
    state_dict = torch.load(checkpoint, map_location="cpu")
    if "policy_net_state" in state_dict:
        agent.policy_net.load_state_dict(state_dict["policy_net_state"])
    else:
        agent.policy_net.load_state_dict(state_dict)
    agent.target_net.load_state_dict(agent.policy_net.state_dict())
    if os.path.exists(eval_scenarios_path):
        scenarios = load_eval_scenarios(eval_scenarios_path)
    else:
        improved_env = ImprovedGlobal49MapEnv(wg, max_macro_steps=30, seed=42)
        scenarios = build_eval_scenarios(improved_env, seed=12345)
        save_eval_scenarios(eval_scenarios_path, scenarios, 12345)
    results = evaluate_baseline_agent(env, agent, scenarios, epsilon=0.0)
    results["checkpoint"] = checkpoint
    results["eval_scenarios_path"] = eval_scenarios_path
    save_json(output_path, results)
    print(
        f"Baseline strict success: {results['success_rate']*100:.1f}% | "
        f"map-only success: {results['map_success_rate']*100:.1f}% | "
        f"avg reward: {results['avg_reward']:.2f}"
    )
    return results


def run_improved_evaluation(
    checkpoint: str = "models/global_49map_dqn_v2_best.pt",
    eval_scenarios_path: str = "data/processed/global_eval_scenarios_v1.json",
    output_path: str = "logs/improved_evaluation.json",
    seeds: Sequence[int] = (0, 1, 2),
) -> Dict[str, Any]:
    wg = GlobalWorldGraph()
    env = ImprovedGlobal49MapEnv(wg, max_macro_steps=30, seed=42)
    if os.path.exists(eval_scenarios_path):
        scenarios = load_eval_scenarios(eval_scenarios_path)
    else:
        scenarios = build_eval_scenarios(env, seed=12345)
        save_eval_scenarios(eval_scenarios_path, scenarios, 12345)
    probe_state = env.reset(scenario=scenarios[0])
    agent = Global49MapDQNv2(input_dim=len(probe_state), num_actions=11)
    checkpoint_data = agent.load_checkpoint(checkpoint)
    runs = []
    for seed in seeds:
        results = evaluate_improved_agent(env, agent, scenarios, epsilon=0.0, seed=seed)
        results["seed"] = seed
        runs.append(results)
    summary = {
        "checkpoint": checkpoint,
        "checkpoint_episode": checkpoint_data.get("episode"),
        "checkpoint_metrics": checkpoint_data.get("metrics", {}),
        "eval_scenarios_path": eval_scenarios_path,
        "seeds": list(seeds),
        "runs": runs,
        "success_rate_mean": float(np.mean([run["success_rate"] for run in runs])),
        "success_rate_std": float(np.std([run["success_rate"] for run in runs])),
        "avg_reward_mean": float(np.mean([run["avg_reward"] for run in runs])),
        "avg_steps_success_mean": float(np.mean([
            run["avg_steps_success"] for run in runs if run["avg_steps_success"] is not None
        ])) if any(run["avg_steps_success"] is not None for run in runs) else None,
        "timeout_rate_mean": float(np.mean([run["timeout_rate"] for run in runs])),
        "invalid_action_rate_mean": float(np.mean([run["invalid_action_rate"] for run in runs])),
    }
    save_json(output_path, summary)
    print(
        f"Improved success: {summary['success_rate_mean']*100:.1f}% "
        f"(+/- {summary['success_rate_std']*100:.1f}%) | "
        f"reward {summary['avg_reward_mean']:.2f} | "
        f"steps {summary['avg_steps_success_mean'] or 0:.1f}"
    )
    return summary


def build_eval_command(output_path: str = "data/processed/global_eval_scenarios_v1.json") -> None:
    wg = GlobalWorldGraph()
    env = ImprovedGlobal49MapEnv(wg, max_macro_steps=30, seed=42)
    scenarios = build_eval_scenarios(env, seed=12345)
    save_eval_scenarios(output_path, scenarios, 12345)
    print(f"Wrote {len(scenarios)} fixed eval scenarios to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 target-aware Dueling DQN navigation")
    parser.add_argument(
        "--mode",
        choices=("train", "build-eval", "baseline-eval", "evaluate", "demo"),
        default="train",
    )
    parser.add_argument("--episodes", type=int, default=8_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-macro-steps", type=int, default=30)
    parser.add_argument("--eval-interval", type=int, default=400)
    parser.add_argument("--eval-scenarios", default="data/processed/global_eval_scenarios_v1.json")
    parser.add_argument("--checkpoint", default="models/global_49map_dqn_v2_best.pt")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--no-teacher", action="store_true")
    args = parser.parse_args()

    if args.mode == "build-eval":
        build_eval_command(args.eval_scenarios)
    elif args.mode == "baseline-eval":
        run_baseline_evaluation(args.eval_scenarios)
    elif args.mode == "evaluate":
        run_improved_evaluation(args.checkpoint, args.eval_scenarios)
    elif args.mode == "demo":
        run_phase3_demo(args.checkpoint)
    else:
        train_improved_global_agent(
            num_episodes=args.episodes,
            seed=args.seed,
            max_macro_steps=args.max_macro_steps,
            eval_interval=args.eval_interval,
            eval_scenarios_path=args.eval_scenarios,
            resume=args.resume,
            use_teacher=not args.no_teacher,
        )


if __name__ == "__main__":
    main()
