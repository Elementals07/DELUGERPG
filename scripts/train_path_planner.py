"""
Training script for Hierarchical Path Planner DQN on Overworld 1.
Trains for 1,500 episodes, saves models, generates training logs,
and exports browser-ready weights for IndexedDB persistence.
"""

import sys
import os
import time
import csv
import json
import sqlite3
import numpy as np
import torch

sys.path.insert(0, os.path.abspath("."))
from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.agents.path_planner import PathPlannerEnv, PathPlannerDQN, WAYPOINTS_OW1


def train_path_planner(num_episodes: int = 1500, log_interval: int = 50):
    print("=" * 70)
    print("DELUGERPG HIERARCHICAL PATH PLANNER: OVERWORLD 1 TRAINING")
    print(f"Target: {num_episodes} Episodes | Device: CPU | Action Space: 16 Waypoints")
    print("=" * 70)

    # 1. Load walkgrid from KB
    db_path = os.path.join("data", "processed", "delugerpg_kb.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    row = cur.execute("SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?", ("overworld1",)).fetchone()
    conn.close()

    if not row:
        raise RuntimeError("overworld1 not found in map_walkgrids table!")

    walkgrid = WalkGrid.from_base64(row[0], "overworld1")
    print(f"Loaded WalkGrid for overworld1: {len(walkgrid.tiles)}x{len(walkgrid.tiles[0])}")

    # 2. Setup Environment and Agent
    env = PathPlannerEnv(walkgrid, max_macro_steps=25)
    agent = PathPlannerDQN(input_dim=67, num_actions=16, lr=1e-3, gamma=0.98, buffer_size=30000, batch_size=64)

    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.join("data", "processed"), exist_ok=True)

    csv_path = os.path.join("logs", "path_planner_training_log.csv")
    csv_file = open(csv_path, mode="w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["episode", "epsilon", "reward", "coverage_pct", "encounters", "macro_steps", "loss"])

    epsilon_start = 1.0
    epsilon_min = 0.05
    epsilon_decay_episodes = 1000

    best_coverage = 0.0
    best_reward = -9999.0

    recent_rewards = []
    recent_coverages = []
    recent_encounters = []

    start_time = time.time()

    for episode in range(1, num_episodes + 1):
        # Epsilon linear decay
        if episode <= epsilon_decay_episodes:
            epsilon = epsilon_start - (epsilon_start - epsilon_min) * (episode / epsilon_decay_episodes)
        else:
            epsilon = epsilon_min

        # Half the episodes start randomly, half start at user's recent spot (8, 29) to master the east ridge
        start_pos = (8, 29) if (episode % 3 == 0) else None
        state = env.reset(start_pos=start_pos)
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

        # Target network sync
        if episode % 10 == 0:
            agent.sync_target()

        coverage_pct = (len(env.visited_tiles) / env.total_walkable) * 100.0
        avg_loss = (ep_loss / loss_updates) if loss_updates > 0 else 0.0

        recent_rewards.append(ep_reward)
        recent_coverages.append(coverage_pct)
        recent_encounters.append(env.total_encounters)

        csv_writer.writerow([episode, f"{epsilon:.4f}", f"{ep_reward:.2f}", f"{coverage_pct:.1f}", env.total_encounters, env.macro_steps, f"{avg_loss:.4f}"])

        # Track best model
        if coverage_pct > best_coverage or (coverage_pct == best_coverage and ep_reward > best_reward):
            best_coverage = coverage_pct
            best_reward = ep_reward
            torch.save(agent.policy_net.state_dict(), os.path.join("models", "path_planner_best.pt"))

        if episode % log_interval == 0 or episode == num_episodes:
            mean_r = np.mean(recent_rewards[-log_interval:])
            mean_cov = np.mean(recent_coverages[-log_interval:])
            mean_enc = np.mean(recent_encounters[-log_interval:])
            elapsed = time.time() - start_time
            csv_file.flush()
            print(f"Ep {episode:4d}/{num_episodes} | Eps: {epsilon:.3f} | R: {mean_r:6.1f} | Cov: {mean_cov:5.1f}% | Enc: {mean_enc:4.1f} | BestCov: {best_coverage:5.1f}% | Time: {elapsed:.1f}s", flush=True)

    csv_file.close()

    # Save final model
    torch.save(agent.policy_net.state_dict(), os.path.join("models", "path_planner_final.pt"))

    # Load best model for export
    agent.policy_net.load_state_dict(torch.load(os.path.join("models", "path_planner_best.pt")))
    weights_dict = agent.export_weights_dict()
    weights_dict["training_metadata"] = {
        "episodes": num_episodes,
        "best_coverage_pct": round(best_coverage, 2),
        "best_reward": round(best_reward, 2),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "map_name": "overworld1"
    }

    # Save JSON weights to both locations
    out_paths = [
        os.path.join("data", "processed", "map_path_weights.json"),
        os.path.join("models", "map_path_weights.json")
    ]
    for p in out_paths:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(weights_dict, f)
        print(f"Exported weights JSON to: {p} ({os.path.getsize(p)} bytes)")

    # Automatically recompile deluge_ai_roam.user.js
    try:
        from scripts.build_roam_userscript import generate_userscript
        generate_userscript()
        print("Successfully recompiled deluge_ai_roam.user.js with latest weights.")
    except Exception as e:
        print(f"Userscript rebuild notice: {e}")

    print("=" * 70)
    print("TRAINING COMPLETE! Running Validation Trajectory from (8, 29)...")
    print("=" * 70)

    # Test rollout from user's starting point (8, 29)
    state = env.reset(start_pos=(8, 29))
    mask = env.get_action_mask()
    print(f"Initial Position: ({env.curr_x}, {env.curr_y})")

    steps_taken = 0
    route_log = []
    for step_num in range(1, 16):
        action = agent.select_action(state, mask, epsilon=0.0)  # purely greedy
        wp = WAYPOINTS_OW1[action]
        next_state, reward, done, info = env.step(action)
        mask = env.get_action_mask()
        state = next_state
        steps_taken += info["path_length"]
        route_log.append(f"Step {step_num}: -> [{action}] {wp.name} ({wp.x}, {wp.y}) | Path: {info['path_length']} tiles | Cov: {info['coverage']*100:.1f}%")
        if done:
            break

    for line in route_log:
        print("  " + line)
    print(f"Final Validation: Total micro-steps = {steps_taken}, Final Coverage = {len(env.visited_tiles)/env.total_walkable*100:.1f}%, Encounters = {env.total_encounters}")


if __name__ == "__main__":
    train_path_planner(num_episodes=1500, log_interval=100)
