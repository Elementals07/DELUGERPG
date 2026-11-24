"""
Map Exploration DQN Training Script.

Trains a small DQN agent to explore DelugeRPG maps efficiently.
Runs entirely on CPU — no GPU needed.

Usage:
    python scripts/train_map_agent.py
    python scripts/train_map_agent.py --map overworld1 --episodes 3000
    python scripts/train_map_agent.py --map all --episodes 1000  # rotates through all 49 maps

Outputs:
    models/map_dqn.pt          — saved model weights
    logs/map_training_log.csv  — per-episode metrics
"""

import argparse
import json
import os
import sys
import csv
import random
import base64

import numpy as np

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.simulator.map_env import MapEnv
from delugerpg.agents.dqn import DQNAgent
from delugerpg.agents.baseline import BFSMapAgent


def load_all_grids(walkgrid_path: str):
    with open(walkgrid_path) as f:
        raw = json.load(f)
    grids = {}
    for name, b64 in raw.items():
        try:
            grids[name] = WalkGrid.from_base64(b64, map_name=name)
        except Exception as e:
            print(f"  Warning: skipping {name}: {e}")
    return grids


def run_bfs_baseline(grid: WalkGrid, n_episodes: int = 100, max_steps: int = 200) -> dict:
    """Evaluate BFS baseline on a grid. Returns average coverage and reward."""
    env = MapEnv(grid, max_steps=max_steps)
    agent = BFSMapAgent(grid)
    coverages, rewards = [], []

    for _ in range(n_episodes):
        obs, info = env.reset()
        total_reward = 0.0
        for _ in range(max_steps):
            mask = env.get_action_mask()
            action = agent.choose_action(env.current_pos, env.visited, mask)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            if terminated or truncated:
                break
        coverages.append(info["coverage"])
        rewards.append(total_reward)

    return {
        "avg_coverage": float(np.mean(coverages)),
        "avg_reward": float(np.mean(rewards)),
        "std_coverage": float(np.std(coverages)),
    }


def train(args):
    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    print("Loading walkgrids...")
    grids = load_all_grids("data/raw/delugerpg_all_walkgrids.json")
    print(f"  Loaded {len(grids)} maps")

    # Pick which maps to train on
    if args.map == "all":
        map_names = list(grids.keys())
    else:
        if args.map not in grids:
            print(f"Error: map '{args.map}' not found. Available: {list(grids.keys())[:5]}...")
            sys.exit(1)
        map_names = [args.map]

    # Build env and agent using the first map (others rotate during training)
    first_grid = grids[map_names[0]]
    env = MapEnv(first_grid, max_steps=args.max_steps, encounter_prob=0.15)

    # obs_dim: 7*7*2 + 4 = 102
    agent = DQNAgent(
        obs_dim=env.obs_dim,
        n_actions=8,
        lr=args.lr,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_end=0.05,
        epsilon_decay=args.epsilon_decay,
        batch_size=64,
        buffer_capacity=10_000,
        target_update_freq=200,
        hidden=128,
    )

    if args.resume and os.path.exists("models/map_dqn.pt"):
        agent.load("models/map_dqn.pt")

    print(f"\nTraining on {map_names if len(map_names) <= 3 else str(len(map_names)) + ' maps'}")
    print(f"Episodes: {args.episodes}  Max steps/ep: {args.max_steps}\n")

    # ── BFS Baseline (run once before training) ──
    print("Running BFS baseline (100 episodes)...")
    baseline_map = grids[map_names[0]]
    bfs_stats = run_bfs_baseline(baseline_map, n_episodes=100)
    print(f"  BFS baseline on {map_names[0]}: coverage={bfs_stats['avg_coverage']:.3f} reward={bfs_stats['avg_reward']:.2f}")

    log_path = "logs/map_training_log.csv"
    with open(log_path, "w", newline="") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["episode", "map", "total_reward", "coverage", "encounters",
                         "steps", "epsilon", "loss_avg", "collisions"])

        best_coverage = 0.0
        recent_rewards = []

        for ep in range(1, args.episodes + 1):
            # Rotate maps if training on all
            map_name = map_names[(ep - 1) % len(map_names)]
            if args.map == "all" and ep % len(map_names) == 1:
                env = MapEnv(grids[map_name], max_steps=args.max_steps, encounter_prob=0.15)

            obs, info = env.reset()
            total_reward = 0.0
            episode_losses = []
            collisions = 0
            encounters = 0

            for step in range(args.max_steps):
                mask = env.get_action_mask()
                action = agent.choose_action(obs, action_mask=mask)
                next_obs, reward, terminated, truncated, info = env.step(action)

                agent.remember(obs, action, reward, next_obs, terminated or truncated)
                loss = agent.learn()
                if loss is not None:
                    episode_losses.append(loss)

                total_reward += reward
                if info.get("collided"):
                    collisions += 1
                if info.get("encounter"):
                    encounters += 1

                obs = next_obs
                if terminated or truncated:
                    break

            coverage = info.get("coverage", 0.0)
            avg_loss = float(np.mean(episode_losses)) if episode_losses else 0.0
            recent_rewards.append(total_reward)
            if len(recent_rewards) > 100:
                recent_rewards.pop(0)

            writer.writerow([ep, map_name, f"{total_reward:.3f}", f"{coverage:.4f}",
                             encounters, step + 1, f"{agent.epsilon:.4f}",
                             f"{avg_loss:.5f}", collisions])

            # Save best model
            if coverage > best_coverage:
                best_coverage = coverage
                agent.save("models/map_dqn_best.pt")

            # Print progress
            if ep % args.log_every == 0:
                avg_r = np.mean(recent_rewards)
                print(f"Ep {ep:5d}/{args.episodes} | map={map_name:12s} | "
                      f"reward={total_reward:7.2f} | avg100={avg_r:7.2f} | "
                      f"cov={coverage:.3f} | eps={agent.epsilon:.3f} | "
                      f"loss={avg_loss:.4f}")

        agent.save("models/map_dqn.pt")
        print(f"\nTraining complete! Best coverage: {best_coverage:.3f}")
        print(f"BFS baseline coverage: {bfs_stats['avg_coverage']:.3f}")
        print(f"Log saved to {log_path}")


def main():
    parser = argparse.ArgumentParser(description="Train DQN Map Exploration Agent")
    parser.add_argument("--map", default="overworld1",
                        help="Map name to train on, or 'all' to rotate through all 49 maps")
    parser.add_argument("--episodes", type=int, default=5000)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--epsilon-decay", type=int, default=2000)
    parser.add_argument("--log-every", type=int, default=100)
    parser.add_argument("--resume", action="store_true", help="Resume from saved checkpoint")
    args = parser.parse_args()

    train(args)


if __name__ == "__main__":
    main()
