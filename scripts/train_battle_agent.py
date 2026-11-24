"""
Battle DQN Training Script.

Trains a small DQN agent to win turn-based battles in DelugeRPG.
Uses BattleEnv with randomly generated teams from the actual Pokédex.

Usage:
    python scripts/train_battle_agent.py
    python scripts/train_battle_agent.py --episodes 10000

Outputs:
    models/battle_dqn.pt        — saved model weights
    logs/battle_training_log.csv — per-episode metrics
"""

import argparse
import os
import sys
import csv
import random

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delugerpg.db.database import DatabaseManager
from delugerpg.parsers.typechart import TypeChart
from delugerpg.core.types import Attack
from delugerpg.simulator.battle_env import BattleEnv, BattlePokemon
from delugerpg.agents.dqn import DQNAgent
from delugerpg.agents.baseline import GreedyBattleAgent


# ─────────────────────────────────────────────
# Team Builder (pulls from real DB)
# ─────────────────────────────────────────────

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


def build_random_team(db: DatabaseManager, size: int = 6, level: int = 50, class_name: str = "Normal") -> list:
    """Build a random team of `size` Pokémon from the DB."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT name, type1, type2 FROM pokemon_species WHERE is_mega=0 AND is_gmax=0 ORDER BY RANDOM() LIMIT ?", (size,))
    rows = cursor.fetchall()

    team = []
    for row in rows:
        name, type1, type2 = row["name"], row["type1"], row["type2"]
        # Give each Pokémon 4 random moves from the sample set
        moves = random.sample(SAMPLE_MOVES, 4)
        team.append(BattlePokemon(
            name=name,
            level=level,
            class_name=class_name,
            type1=type1,
            type2=type2,
            attacks=moves,
        ))
    return team


def run_greedy_baseline(env: BattleEnv, type_chart: TypeChart, db: DatabaseManager, n_episodes: int = 200) -> dict:
    """Evaluate greedy baseline win rate."""
    agent = GreedyBattleAgent(type_chart)
    wins, losses = 0, 0

    for _ in range(n_episodes):
        player_team = build_random_team(db)
        opp_team = build_random_team(db)
        obs, info = env.reset(player_team, opp_team)

        for _ in range(100):
            mask = env.get_action_mask()
            action = agent.choose_action(obs, mask, env.active_player_pokemon, env.active_opponent_pokemon)
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                if info.get("result") == "win":
                    wins += 1
                else:
                    losses += 1
                break

    total = wins + losses
    return {"win_rate": wins / total if total > 0 else 0.0, "wins": wins, "losses": losses}


def train(args):
    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    db = DatabaseManager()
    TC_HTML = "DELUGERPG_Consolidated_Reference/pages/23_pages_type_chart.html"
    with open(TC_HTML, "r", encoding="utf-8", errors="ignore") as f:
        type_chart = TypeChart.from_html(f.read())
    env = BattleEnv(type_chart, max_turns=args.max_turns)

    agent = DQNAgent(
        obs_dim=BattleEnv.OBS_DIM,    # 64
        n_actions=BattleEnv.NUM_ACTIONS,  # 9
        lr=args.lr,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_end=0.05,
        epsilon_decay=args.epsilon_decay,
        batch_size=64,
        buffer_capacity=20_000,
        target_update_freq=500,
        hidden=128,
    )

    if args.resume and os.path.exists("models/battle_dqn.pt"):
        agent.load("models/battle_dqn.pt")

    print("Running Greedy baseline (200 episodes)...")
    baseline = run_greedy_baseline(env, type_chart, db)
    print(f"  Greedy baseline win rate: {baseline['win_rate']:.3f}")

    print(f"\nTraining Battle DQN: {args.episodes} episodes, max {args.max_turns} turns each\n")

    log_path = "logs/battle_training_log.csv"
    with open(log_path, "w", newline="") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["episode", "result", "total_reward", "turns", "epsilon", "loss_avg"])

        recent_wins = []
        best_win_rate = 0.0

        for ep in range(1, args.episodes + 1):
            player_team = build_random_team(db)
            opp_team = build_random_team(db)
            obs, info = env.reset(player_team, opp_team)

            total_reward = 0.0
            episode_losses = []
            result = "unknown"

            for turn in range(args.max_turns):
                mask = env.get_action_mask()
                action = agent.choose_action(obs, action_mask=mask)
                next_obs, reward, terminated, truncated, info = env.step(action)

                agent.remember(obs, action, reward, next_obs, terminated or truncated)
                loss = agent.learn()
                if loss is not None:
                    episode_losses.append(loss)

                total_reward += reward
                obs = next_obs

                if terminated or truncated:
                    result = info.get("result", "unknown")
                    break

            won = 1 if result == "win" else 0
            recent_wins.append(won)
            if len(recent_wins) > 200:
                recent_wins.pop(0)

            avg_loss = float(np.mean(episode_losses)) if episode_losses else 0.0
            writer.writerow([ep, result, f"{total_reward:.3f}", turn + 1,
                             f"{agent.epsilon:.4f}", f"{avg_loss:.5f}"])

            win_rate = float(np.mean(recent_wins))
            if win_rate > best_win_rate and len(recent_wins) >= 100:
                best_win_rate = win_rate
                agent.save("models/battle_dqn_best.pt")

            if ep % args.log_every == 0:
                print(f"Ep {ep:6d}/{args.episodes} | result={result:7s} | "
                      f"reward={total_reward:7.2f} | wr200={win_rate:.3f} | "
                      f"eps={agent.epsilon:.3f} | loss={avg_loss:.4f}")

        agent.save("models/battle_dqn.pt")
        print(f"\nTraining complete! Best win rate (200ep window): {best_win_rate:.3f}")
        print(f"Greedy baseline win rate: {baseline['win_rate']:.3f}")
        print(f"Log saved to {log_path}")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="Train DQN Battle Agent")
    parser.add_argument("--episodes", type=int, default=10_000)
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--epsilon-decay", type=int, default=5000)
    parser.add_argument("--log-every", type=int, default=500)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    train(args)


if __name__ == "__main__":
    main()
