"""
Evaluation Benchmark: DQN Agents vs. Non-Learning Baselines.

Compares:
1. Map DQN (Trained) vs. BFSMapAgent on Overworld map exploration (100 episodes).
   - Metrics: Coverage %, Mean Reward, Steps taken, Collisions.
2. Battle DQN (Trained) vs. GreedyBattleAgent on randomized 6v6 battles (200 episodes).
   - Metrics: Win Rate %, Mean Reward, Turn Duration, Survival Rate.

Outputs:
    logs/evaluation_results.json
"""

import os
import sys
import json
import random
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.simulator.map_env import MapEnv
from delugerpg.agents.dqn import DQNAgent
from delugerpg.agents.baseline import BFSMapAgent, GreedyBattleAgent
from delugerpg.simulator.battle_env import BattleEnv, BattlePokemon
from delugerpg.parsers.typechart import TypeChart
from delugerpg.db.database import DatabaseManager
from delugerpg.core.types import Attack


def evaluate_map_agents(map_name: str = "overworld1", n_episodes: int = 100, max_steps: int = 200) -> dict:
    print(f"\n--- [1/2] Evaluating Map Agents on '{map_name}' ({n_episodes} episodes) ---")
    with open("data/raw/delugerpg_all_walkgrids.json") as f:
        maps = json.load(f)
    grid = WalkGrid.from_base64(maps[map_name], map_name=map_name)

    env = MapEnv(grid, max_steps=max_steps, encounter_prob=0.15)

    # 1. Evaluate BFS Agent
    bfs_agent = BFSMapAgent(grid)
    bfs_coverages, bfs_rewards, bfs_collisions = [], [], []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=ep + 1000)
        total_r = 0.0
        coll = 0
        for _ in range(max_steps):
            mask = env.get_action_mask()
            action = bfs_agent.choose_action(env.current_pos, env.visited, mask)
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            if info.get("collided"):
                coll += 1
            if term or trunc:
                break
        bfs_coverages.append(info.get("coverage", 0.0))
        bfs_rewards.append(total_r)
        bfs_collisions.append(coll)

    # 2. Evaluate Trained Map DQN (Pure greedy policy, epsilon=0)
    dqn_model_path = "models/map_dqn_best.pt" if os.path.exists("models/map_dqn_best.pt") else "models/map_dqn.pt"
    dqn_agent = DQNAgent(obs_dim=env.obs_dim, n_actions=8, epsilon_start=0.0, epsilon_end=0.0)
    dqn_agent.load(dqn_model_path)
    dqn_agent.epsilon_start = 0.0
    dqn_agent.epsilon_end = 0.0

    dqn_coverages, dqn_rewards, dqn_collisions = [], [], []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=ep + 1000)
        total_r = 0.0
        coll = 0
        for _ in range(max_steps):
            mask = env.get_action_mask()
            action = dqn_agent.choose_action(obs, action_mask=mask)
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            if info.get("collided"):
                coll += 1
            if term or trunc:
                break
        dqn_coverages.append(info.get("coverage", 0.0))
        dqn_rewards.append(total_r)
        dqn_collisions.append(coll)

    results = {
        "map_name": map_name,
        "n_episodes": n_episodes,
        "bfs_baseline": {
            "mean_coverage": float(np.mean(bfs_coverages)),
            "std_coverage": float(np.std(bfs_coverages)),
            "mean_reward": float(np.mean(bfs_rewards)),
            "mean_collisions": float(np.mean(bfs_collisions)),
        },
        "map_dqn": {
            "mean_coverage": float(np.mean(dqn_coverages)),
            "std_coverage": float(np.std(dqn_coverages)),
            "mean_reward": float(np.mean(dqn_rewards)),
            "mean_collisions": float(np.mean(dqn_collisions)),
            "model_path": dqn_model_path,
        }
    }
    print(f"  BFS Baseline: Coverage={results['bfs_baseline']['mean_coverage']:.1%} "
          f"± {results['bfs_baseline']['std_coverage']:.1%} | Reward={results['bfs_baseline']['mean_reward']:.2f}")
    print(f"  Map DQN:      Coverage={results['map_dqn']['mean_coverage']:.1%} "
          f"± {results['map_dqn']['std_coverage']:.1%} | Reward={results['map_dqn']['mean_reward']:.2f}")
    return results


SAMPLE_MOVES = [
    Attack(name="Tackle",       type="normal",   power=50,  accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Flamethrower", type="fire",     power=90,  accuracy=100, effect="burn",  effect_accuracy=10),
    Attack(name="Surf",         type="water",    power=90,  accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Thunderbolt",  type="electric", power=90,  accuracy=100, effect="paralysis", effect_accuracy=10),
    Attack(name="Ice Beam",     type="ice",      power=90,  accuracy=100, effect="freeze", effect_accuracy=10),
    Attack(name="Earthquake",   type="ground",   power=100, accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Psychic",      type="psychic",  power=90,  accuracy=100, effect="confuse", effect_accuracy=10),
    Attack(name="Shadow Ball",  type="ghost",    power=80,  accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Dark Pulse",   type="dark",     power=80,  accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Dragon Claw",  type="dragon",   power=80,  accuracy=100, effect=None, effect_accuracy=0),
]


def build_team_from_species(species_rows, size=6, level=50, class_name="Normal"):
    team = []
    for r in species_rows[:size]:
        moves = random.sample(SAMPLE_MOVES, 4)
        team.append(BattlePokemon(
            name=r["name"], level=level, class_name=class_name,
            type1=r["type1"], type2=r["type2"], attacks=moves
        ))
    return team


def evaluate_battle_agents(n_battles: int = 200, max_turns: int = 100) -> dict:
    print(f"\n--- [2/2] Evaluating Battle Agents ({n_battles} randomized 6v6 battles) ---")
    db = DatabaseManager()
    cursor = db.conn.cursor()
    cursor.execute("SELECT name, type1, type2 FROM pokemon_species WHERE is_mega=0 AND is_gmax=0")
    all_species = [dict(r) for r in cursor.fetchall()]

    TC_HTML = "DELUGERPG_Consolidated_Reference/pages/23_pages_type_chart.html"
    with open(TC_HTML, "r", encoding="utf-8", errors="ignore") as f:
        type_chart = TypeChart.from_html(f.read())
    env = BattleEnv(type_chart, max_turns=max_turns)

    # 1. Greedy Baseline
    greedy_agent = GreedyBattleAgent(type_chart)
    greedy_wins = 0
    greedy_rewards = []
    greedy_turns = []

    # Pre-generate match matchups for reproducible fair comparison
    random.seed(42)
    matchups = []
    for _ in range(n_battles):
        p_spec = random.sample(all_species, 6)
        o_spec = random.sample(all_species, 6)
        matchups.append((p_spec, o_spec))

    # Evaluate Greedy
    for p_spec, o_spec in matchups:
        player_team = build_team_from_species(p_spec)
        opp_team = build_team_from_species(o_spec)
        obs, info = env.reset(player_team, opp_team)
        total_r = 0.0
        turns = 0
        for t in range(max_turns):
            mask = env.get_action_mask()
            action = greedy_agent.choose_action(obs, mask, env.active_player_pokemon, env.active_opponent_pokemon)
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            turns = t + 1
            if term or trunc:
                if info.get("result") == "win":
                    greedy_wins += 1
                break
        greedy_rewards.append(total_r)
        greedy_turns.append(turns)

    # 2. Evaluate Trained Battle DQN (epsilon=0)
    dqn_model_path = "models/battle_dqn_best.pt" if os.path.exists("models/battle_dqn_best.pt") else "models/battle_dqn.pt"
    dqn_agent = DQNAgent(obs_dim=BattleEnv.OBS_DIM, n_actions=BattleEnv.NUM_ACTIONS, epsilon_start=0.0, epsilon_end=0.0)
    dqn_agent.load(dqn_model_path)
    dqn_agent.epsilon_start = 0.0
    dqn_agent.epsilon_end = 0.0

    dqn_wins = 0
    dqn_rewards = []
    dqn_turns = []

    for p_spec, o_spec in matchups:
        player_team = build_team_from_species(p_spec)
        opp_team = build_team_from_species(o_spec)
        obs, info = env.reset(player_team, opp_team)
        total_r = 0.0
        turns = 0
        for t in range(max_turns):
            mask = env.get_action_mask()
            action = dqn_agent.choose_action(obs, action_mask=mask)
            obs, r, term, trunc, info = env.step(action)
            total_r += r
            turns = t + 1
            if term or trunc:
                if info.get("result") == "win":
                    dqn_wins += 1
                break
        dqn_rewards.append(total_r)
        dqn_turns.append(turns)

    db.close()

    results = {
        "n_battles": n_battles,
        "greedy_baseline": {
            "win_rate": greedy_wins / n_battles,
            "wins": greedy_wins,
            "mean_reward": float(np.mean(greedy_rewards)),
            "mean_turns": float(np.mean(greedy_turns)),
        },
        "battle_dqn": {
            "win_rate": dqn_wins / n_battles,
            "wins": dqn_wins,
            "mean_reward": float(np.mean(dqn_rewards)),
            "mean_turns": float(np.mean(dqn_turns)),
            "model_path": dqn_model_path,
        }
    }
    print(f"  Greedy Baseline: Win Rate={results['greedy_baseline']['win_rate']:.1%} "
          f"({greedy_wins}/{n_battles}) | Avg Turns={results['greedy_baseline']['mean_turns']:.1f}")
    print(f"  Battle DQN:      Win Rate={results['battle_dqn']['win_rate']:.1%} "
          f"({dqn_wins}/{n_battles}) | Avg Turns={results['battle_dqn']['mean_turns']:.1f}")
    return results


def main():
    map_res = evaluate_map_agents(n_episodes=100)
    battle_res = evaluate_battle_agents(n_battles=200)

    summary = {
        "map_evaluation": map_res,
        "battle_evaluation": battle_res,
    }

    os.makedirs("logs", exist_ok=True)
    out_path = "logs/evaluation_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[OK] Evaluation completed and saved to {out_path}")


if __name__ == "__main__":
    main()
