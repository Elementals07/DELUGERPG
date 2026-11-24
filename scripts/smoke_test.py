import sys, json, random
sys.path.insert(0, '.')

print("=== SMOKE TEST: DQN Agent Import ===")
from delugerpg.agents.dqn import DQNAgent, QNetwork, ReplayBuffer
agent = DQNAgent(obs_dim=102, n_actions=8)
print(f"Map DQN created. Params: {agent.q_net.param_count():,}")
agent2 = DQNAgent(obs_dim=64, n_actions=9)
print(f"Battle DQN created. Params: {agent2.q_net.param_count():,}")

print()
print("=== SMOKE TEST: BFS Baseline Import ===")
from delugerpg.agents.baseline import BFSMapAgent, GreedyBattleAgent
from delugerpg.parsers.walkgrid import WalkGrid
with open("data/raw/delugerpg_all_walkgrids.json") as f:
    maps = json.load(f)
grid = WalkGrid.from_base64(maps["overworld1"], map_name="overworld1")
bfs = BFSMapAgent(grid)
print(f"BFSMapAgent created for overworld1")

print()
print("=== SMOKE TEST: 10-step DQN training loop on MapEnv ===")
from delugerpg.simulator.map_env import MapEnv
import numpy as np
env = MapEnv(grid, max_steps=50)
obs, info = env.reset()
pos = info["pos"]
print(f"Env reset. obs shape: {obs.shape}, pos: {pos}")

for step in range(20):
    mask = env.get_action_mask()
    action = agent.choose_action(obs, action_mask=mask)
    next_obs, reward, terminated, truncated, info = env.step(action)
    agent.remember(obs, action, reward, next_obs, terminated or truncated)
    loss = agent.learn()
    obs = next_obs
    if terminated or truncated:
        break

print(f"Ran {step+1} steps. Buffer size: {len(agent.replay)}")
print(f"Coverage: {info['coverage']:.3f}, Epsilon: {agent.epsilon:.4f}")

print()
print("=== SMOKE TEST: BFS agent 5-step test ===")
obs, info = env.reset()
for step in range(5):
    mask = env.get_action_mask()
    action = bfs.choose_action(env.current_pos, env.visited, mask)
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        break
print(f"BFS ran {step+1} steps. Coverage: {info['coverage']:.3f}")

print()
print("=== SMOKE TEST: Battle DQN + GreedyBattleAgent ===")
from delugerpg.db.database import DatabaseManager
from delugerpg.parsers.typechart import TypeChart
from delugerpg.simulator.battle_env import BattleEnv, BattlePokemon
from delugerpg.core.types import Attack

db = DatabaseManager()
# TypeChart loads from the HTML capture
TC_HTML = "DELUGERPG_Consolidated_Reference/pages/23_pages_type_chart.html"
with open(TC_HTML, "r", encoding="utf-8", errors="ignore") as f:
    type_chart = TypeChart.from_html(f.read())
battle_env = BattleEnv(type_chart, max_turns=30)

moves = [
    Attack(name="Tackle", type="normal", power=50, accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Flamethrower", type="fire", power=90, accuracy=100, effect="burn", effect_accuracy=10),
    Attack(name="Surf", type="water", power=90, accuracy=100, effect=None, effect_accuracy=0),
    Attack(name="Thunderbolt", type="electric", power=90, accuracy=100, effect=None, effect_accuracy=0),
]
player_team = [BattlePokemon("Charizard", 50, "Normal", "fire", "flying", moves)]
opp_team = [BattlePokemon("Blastoise", 50, "Normal", "water", None, moves)]

obs, info = battle_env.reset(player_team, opp_team)
print(f"Battle reset. obs shape: {obs.shape}")

greedy = GreedyBattleAgent(type_chart)
for turn in range(10):
    mask = battle_env.get_action_mask()
    action = greedy.choose_action(obs, mask, battle_env.active_player_pokemon, battle_env.active_opponent_pokemon)
    obs, reward, terminated, truncated, info = battle_env.step(action)
    if terminated or truncated:
        print(f"Battle ended after {turn+1} turns. Result: {info.get('result', 'unknown')}")
        break

db.close()
print()
print("ALL SMOKE TESTS PASSED!")
