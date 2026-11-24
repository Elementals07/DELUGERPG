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
from typing import Dict, List, Tuple, Optional, Any
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import networkx as nx

sys.path.insert(0, os.path.abspath("."))
from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.models.world_graph import WorldGraph
from delugerpg.models.transition_registry import (
    AmbiguousTransitionError,
    InvalidTransitionError,
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


if __name__ == "__main__":
    train_global_agent(num_episodes=8000, log_interval=500)
