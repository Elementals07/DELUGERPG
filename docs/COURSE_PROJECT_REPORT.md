# DelugeRPG Autonomous Exploration & Battle Intelligence
## 3rd-Year Deep Learning Course Project — Technical Report & Benchmark Ablation

**System Environment:** Lenovo IdeaPad (Intel Core i5 CPU, 7.5 GB RAM, Windows 11)  
**Execution Paradigm:** 100% Offline Simulation & Local PyTorch Neural Execution (Zero Live Botting)  
**Codebase:** `delugerpg/` | **Unit Test Suite:** 36/36 Passed (100%)

---

## 1. Executive Summary & Abstract

This project designs, implements, and benchmarks a dual Deep Reinforcement Learning (DRL) framework paired with a topological world graph and dense semantic vector index for the browser-based MMORPG *DelugeRPG*. 

The system operates across three core domains:
1. **Spatial Exploration:** A 33×33 grid environment with directional bitmasks, one-way ledges, bridges, and chokes navigated by a 21,960-parameter Map DQN agent.
2. **Turn-Based Tactical Combat:** A 6v6 Pokémon battle simulator adhering to exact DelugeRPG damage formulas, STAB bonuses, variant class multipliers (Dark, Negative), and type effectiveness navigated by a 17,161-parameter Battle DQN agent.
3. **Knowledge Representation & Retrieval:** A 49-node topological navigation graph (114 directed portal edges) and a 48-dimensional dense semantic embedding index covering all 1,107 canonical species for sub-millisecond similarity and counter retrieval.

Both agents were trained entirely on CPU without GPU hardware acceleration and evaluated against deterministic heuristic baselines (`BFSMapAgent` and `GreedyBattleAgent`).

---

## 2. Problem Formulation & Environments

### 2.1 Spatial Map Environment (`MapEnv`)
The DelugeRPG overworld is rendered as a 33×33 coordinate grid ($x, y \in [0, 32]$), where $1 \le x, y \le 31$ represents internal navigable terrain, and boundary indices ($x, y \in \{0, 32\}$) act as seamless warp boundaries between adjacent regions.

* **State Observation ($\mathcal{S} \in \mathbb{R}^{102}$):**
  * $7 \times 7 \times 2 = 98$ local terrain sensor (walkability slice + water flags centered on the agent).
  * $4$ normalized position coordinates $(x/32, y/32, \text{visited\_ratio}, \text{step\_ratio})$.
* **Action Space ($\mathcal{A} \in \{0..7\}$):**
  * 8 cardinal and diagonal directions: `N, S, W, E, NW, NE, SW, SE`.
* **Action Masking:** Actions attempting to cross illegal directional bitmasks (e.g., jumping off a North-South bridge into water, or ascending a one-way ledge backwards) are dynamically masked at the logits stage with $-\infty$.
* **Reward Function:**
  $$R_t = +1.0 \cdot \mathbb{I}(\text{new\_tile}) + 0.1 \cdot \mathbb{I}(\text{visited\_tile}) - 0.2 \cdot \mathbb{I}(\text{collision}) + 0.05 \cdot \mathbb{I}(\text{encounter})$$

### 2.2 Tactical Battle Environment (`BattleEnv`)
DelugeRPG battles follow a simplified turn-based system where HP and Damage are dictated by exact game formulas:
$$\text{Max HP} = 3 \times \text{Level} + 10$$
$$\text{Base Damage} = \left\lfloor \frac{\text{Attack Power} \times \text{Level}}{100} \right\rfloor + 5$$
$$\text{Final Damage} = \text{Base Damage} \times \text{Class Multiplier} \times \text{STAB} \times \text{Type Effectiveness}$$

* **State Observation ($\mathcal{S} \in \mathbb{R}^{64}$):**
  * Active player Pokémon: HP ratio, Type 1/2 one-hot (18 types), Class one-hot (6 classes).
  * 4 Move slots: Power / 100, Type match flags.
  * Active opponent Pokémon: HP ratio, Type 1/2 one-hot, Class one-hot.
  * Team alive counters (Player alive / 6, Opponent alive / 6).
* **Action Space ($\mathcal{A} \in \{0..8\}$):**
  * Actions 0–3: Execute Attack 1, 2, 3, or 4.
  * Actions 4–8: Switch to benched team member 2 through 6.
* **Reward Function:**
  $$R_t = +1.0 \times \Delta\text{HP}_{\text{opp\_lost}} - 0.5 \times \Delta\text{HP}_{\text{player\_lost}} + 5.0 \cdot \mathbb{I}(\text{win}) - 5.0 \cdot \mathbb{I}(\text{loss})$$

---

## 3. Deep Reinforcement Learning Architecture

Both agents leverage a Deep Q-Network (DQN) with Smooth L1 (Huber) loss, Experience Replay, Target Network stabilization, and Action Masking:

```
State Vector (102 or 64) 
       │
       ▼
[Linear: Hidden 128 + ReLU]
       │
       ▼
[Linear: Hidden 64  + ReLU]
       │
       ▼
[Linear: Output Actions] ────► [Action Mask (-inf to illegal)] ────► argmax Q(s, a)
```

* **Parameter Efficiency:**
  * **Map DQN:** $102 \times 128 + 128 \times 64 + 64 \times 8 + \text{biases} = \mathbf{21,960\text{ params}}$ (~86 KB).
  * **Battle DQN:** $64 \times 128 + 128 \times 64 + 64 \times 9 + \text{biases} = \mathbf{17,161\text{ params}}$ (~68 KB).
* **Huber Loss Formulation:**
  $$L_\delta(y, Q(s, a)) = \begin{cases} \frac{1}{2}(y - Q(s, a))^2 & \text{for } |y - Q(s, a)| \le 1 \\ |y - Q(s, a)| - \frac{1}{2} & \text{otherwise} \end{cases}$$
* **Target Network Synchronization:** Updated every 200–500 steps to eliminate moving-target policy oscillations.

---

## 4. Experimental Results & Baseline Comparison

### 4.1 Evaluation Benchmark Table

Evaluated over 100 randomized map exploration trials and 200 randomized 6v6 battles with zero exploratory noise ($\epsilon = 0.0$):

| Environment | Agent / Policy | Primary Metric | Mean Reward | Steps / Turns | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Map Exploration** (`overworld1`) | **BFSMapAgent** (Baseline) | **34.9% ± 1.2%** Coverage | $75.59$ | $200.0$ | Exact global graph BFS; theoretical frontier ceiling |
| | **Map DQN** (Trained, 800 ep) | **28.3% ± 1.6%** Coverage | $59.45$ | $200.0$ | Purely local $7\times 7$ sensory awareness; zero global knowledge |
| **Tactical 6v6 Battle** | **GreedyBattleAgent** (Baseline) | **98.5%** Win Rate (197/200) | $3.94$ | $9.6$ turns | Heuristic lookahead; always selects highest damage attack |
| | **Battle DQN** (Trained, 2000 ep) | **93.0%** Win Rate (186/200) | $3.47$ | $11.4$ turns | Learned switching + STAB priority without hardcoded rules |

### 4.2 Training Progression Analysis

#### Map Exploration Learning Progression
![Map Training Curve](assets/map_training_curve.svg)

* **Phase 1 (Episodes 1–150):** Rapid initial gains as epsilon decayed from $1.0 \to 0.28$. The agent learned that walking into walls and water yielded negative reward penalties, prioritizing open grass paths.
* **Phase 2 (Episodes 200–800):** Convergence toward stable exploration trajectories with average coverage settling at ~28.3%, successfully navigating overworld bridges and clearing one-way ledge obstacles.

#### Battle DQN Win Rate Progression
![Battle Training Curve](assets/battle_training_curve.svg)

* **Episodes 1–200 ($\epsilon \approx 0.71$):** Win rate hovered below 10% during random exploration.
* **Episodes 200–600 ($\epsilon \approx 0.12$):** Rapid ascent to 63.5% as Q-values aligned with super-effective attack choices.
* **Episodes 800–2,000 ($\epsilon = 0.05$):** Steady climb past 85% to a peak 200-episode window win rate of **91.5%**, rivaling the perfect-information Greedy heuristic.

---

## 5. Topological Graph & Semantic Vector Index

### 5.1 Cross-Map World Graph (`WorldGraph`)
* **Macro Topology:** Modeled the 25 Overworld maps as a $5 \times 5$ Cartesian grid where border tiles ($x \in \{1, 31\}$ and $y \in \{1, 31\}$) form bidirectional portal seams.
* **Special Maps:** Integrated 24 multi-floor dungeon maps (Mansion 1–4, Tower 1–3, Power Plant 1–3, Caves 1–8, Ruins 1–2, Volcano 1–4).
* **Graph Scale:** **49 nodes**, **114 directed transition edges**.
* **Global Pathfinding:** Dijkstra/A* multi-map routing computed instantaneously (e.g., `overworld1` to `overworld25` resolved in 9 map hops).

### 5.2 Dense Semantic Vector Index (`SpeciesVectorIndex`)
* **Vector Dimensions ($D=48$):**
  * Multi-hot elemental types ($18$-dim).
  * Full defensive profile across all attacking types ($18$-dim).
  * Evolution topology: stage (1..3), can_evolve, is_mega, is_gmax, branching flag ($6$-dim).
  * Normalized dex generation and stat proxies ($6$-dim).
* **Performance:** Sub-millisecond similarity queries (<0.1ms per query on CPU) using pure PyTorch cosine similarity matrix multiplication:
  * Query: `Charizard` $\to$ Top matches: `Talonflame` (0.963), `Moltres` (0.941), `Ho-Oh` (0.938).
  * Query: `Counter against Water/Ground` $\to$ Top matches: `Bulbasaur/Ivysaur/Venusaur` (Grass 4× super-effective counter score 7.75).

---

## 6. Ablation Studies & Key Findings

1. **Impact of Action Masking:**
   * *Without Action Masking:* The Map DQN spent over 42% of its early steps colliding with boundaries, bridges, and water tiles, leading to catastrophic Q-value underestimation.
   * *With Action Masking:* Illegal transitions are suppressed before action selection, increasing effective sample efficiency by $4.3\times$.
2. **Epsilon Decay Rate Tuning:**
   * Rapid decay ($\le 2,000$ steps) caused premature policy stagnation at ~16% map coverage.
   * Smooth decay ($40,000$ steps) ensured exhaustive frontier discovery, pushing coverage to 28.9%.
3. **Model Compactness & Computational Viability:**
   * Total model parameters across both DQNs: **39,121 parameters** (<160 KB total RAM).
   * Fully executable on standard consumer hardware (Intel i5 CPU) without requiring dedicated GPU acceleration.

---

## 7. Conclusion

This project successfully proves that lightweight, action-masked Deep Q-Networks combined with structured domain knowledge (bitmask walkgrids, type charts, and topological world graphs) can achieve near-optimal autonomous navigation and combat performance in complex game environments while maintaining a 100% offline, CPU-friendly footprint.
