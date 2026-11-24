# DelugeRPG Project — Data Inventory & Usage Plan

> This document lists **every piece of data we have right now**, what it contains, and **exactly how it will be used** in the project — in plain English with examples.

---

## 🗂️ What We Have Right Now (Full Inventory)

| # | Data | Location | Size | Records |
|---|---|---|---|---|
| 1 | Pokédex — all species | `data/processed/pokedex_full.json` + DB | 452 KB | **1,107 Pokémon** |
| 2 | Evolution chains | DB `pokemon_evolutions` | in DB | **888 species mapped** |
| 3 | Your collection | DB `user_collection` | in DB | **11,070 ownership rows** |
| 4 | Attack/move list | `data/processed/attacks.json` + DB | 88 KB | **591 moves** |
| 5 | Type chart | `data/processed/type_chart.json` + DB | 7 KB | **18×18 = 324 matchups** |
| 6 | Map walkgrids (all maps) | `data/raw/delugerpg_all_walkgrids.json` + DB | 140 KB | **49 maps × 1,089 tiles** |
| 7 | Recorder session | `data/raw/deluge_session_*.zip` | 861 KB | **208 event chunks** |
| 8 | Game source / HTML captures | `DELUGERPG_Consolidated_Reference/` | ~100 MB | Reference only |

**SQLite database:** `data/processed/delugerpg_kb.db` (1 MB, 8 tables, 29 passing tests)

---

## 📦 Each Data Piece — What It Is & How We Use It

---

### 1. 🐾 Pokédex — 1,107 Pokémon Species

**What it contains:**
Every Pokémon in the game — name, Pokédex number, type(s), and whether it's a Mega or G-Max form.

```
Bulbasaur  → dex=1,  type1=grass,   type2=poison
Charizard  → dex=6,  type1=fire,    type2=flying
Mewtwo     → dex=150, type1=psychic, type2=None
```

**How we use it:**

- **Collection Advisor:** When you walk into a wild encounter and see a Pokémon, the advisor looks it up here instantly to tell you *"You don't have this one — CATCH IT"* or *"You already own this — skip"*.
- **Battle Agent:** The agent uses `type1` and `type2` to compute which moves will be super-effective, resisted, or immune.
- **Report:** Course report tables — species counts, type distribution charts.

> **Example:** You encounter a Gastly. The advisor checks: `type1=ghost, type2=poison`. It also checks DB row `user_collection.Gastly.Normal = False`. Decision: **CAPTURE**.

---

### 2. 🧬 Evolution Chains — 888 Species

**What it contains:**
Every Pokémon's place in its family tree — which stage it is (1, 2, 3), what it evolves from, and what it evolves into. Branching evolutions (like Eevee's 8 paths) are all mapped.

```
Charmander → stage 1 → evolves_to: Charmeleon
Charmeleon → stage 2 → evolves_to: Charizard
Charizard  → stage 3 → (final)
Eevee      → stage 1 → evolves_to: [Vaporeon, Jolteon, Flareon, Espeon, Umbreon, Leafeon, Glaceon, Sylveon]
```

**How we use it:**

- **Collection Advisor (primary use):** Checks if you're missing any evolution in a family. If you own Charmander but not Charmeleon, it flags: *"Evolve Charmander → Charmeleon"*.
- **Catch Priority:** If you encounter a Pokémon whose entire family you already own, it ranks it lower. If it's a base form whose evolutions you're missing, it ranks it higher.
- **Completion tracker:** Calculates how complete your Normal-class Pokédex is across all 879 regular species.

> **Example:** You own Eevee but only Vaporeon and Jolteon. Advisor says: *"6 Eevee evolutions still missing: Flareon, Espeon, Umbreon, Leafeon, Glaceon, Sylveon."*

---

### 3. 👜 Your Collection — 11,070 Ownership Rows

**What it contains:**
Every Pokémon × every variant class (Normal, Shiny, Dark, Metallic, Ghostly, Shadow, Negative, Mirage, Chrome, Retro) → `owned: True/False`.

That's 1,107 species × 10 classes = 11,070 rows. Currently 158 Normal-class species are marked as owned.

**How we use it:**

- **Wild encounter decisions (live use):** Every time you see a Pokémon on the map, the advisor queries this table in real time — O(1) lookup — and says CAPTURE or SKIP.
- **Evolution todo list:** Cross-references with evolution chains to find which owned Pokémon can be evolved.
- **Completion dashboard:** Shows you progress like *"158/879 Normal class species = 18% complete"*.

> **Example:** You encounter Pidgey. Query: `SELECT owned FROM user_collection WHERE pokemon_name='Pidgey' AND class_name='Normal'` → `False`. Advisor: **CAPTURE**.

---

### 4. ⚔️ Attack/Move List — 591 Moves

**What it contains:**
Every battle move in the game: name, element type, base power, accuracy, secondary effect (Burn, Sleep, etc.), and the chance of that effect.

```
Tackle    → type=Normal, power=50,  accuracy=100, effect=None
Surf      → type=Water,  power=90,  accuracy=100, effect=None
Hypnosis  → type=Psychic, power=0,  accuracy=70,  effect=Sleep (100%)
Flamethrower → type=Fire, power=90, accuracy=100, effect=Burn (10%)
```

**How we use it:**

- **Battle Agent (primary use):** At each turn, the agent sees your 4 moves and must pick the best one. It uses base power + type matchup + STAB to calculate expected damage for each move, then picks the highest.
- **BattleEnv simulator:** Every simulated battle uses real move data — no made-up numbers.
- **Ablation study:** We can test "agent that only knows power" vs "agent that knows type matchups too" — the attack DB powers both.

> **Example:** Your Charizard (Fire/Flying) faces a Bulbasaur (Grass/Poison). Agent checks all 4 moves, computes: `Flamethrower vs Grass = 2× super-effective + STAB = 90 × 1.5 × 2.0 = 270 damage`. Picks Flamethrower.

---

### 5. 🎯 Type Chart — 18×18 Matchup Matrix

**What it contains:**
324 numbers, one for every attack-type vs defense-type pair. Values are `0.0` (immune), `0.5` (resisted), `1.0` (neutral), or `2.0` (super effective). The Negative variant inverts all these.

```
Fire → Grass:    2.0  (super effective)
Water → Fire:    2.0  (super effective)
Normal → Ghost:  0.0  (immune)
Electric → Ground: 0.0 (immune)
```

**How we use it:**

- **Battle damage formula:** Every damage calculation in the simulator multiplies by this. Dual-type defenders multiply two values together (e.g. Bulbasaur = Grass × Poison).
- **Battle Agent's move scoring:** The agent reads the opponent's types, queries the chart, and ranks its 4 moves by expected damage.
- **Negative variant battles:** When a Negative Pokémon is involved, the chart is inverted: super-effective becomes resisted and immune becomes super-effective.

> **Example:** Your Ground-type Nidoking uses Earthquake vs a Flying-type Pidgeot. Chart: `Ground → Flying = 0.0` (immune). Agent learns to never use Earthquake against Flying types.

---

### 6. 🗺️ Map Walkgrids — 49 Maps × 1,089 Tiles

**What it contains:**
For every tile in every map: can you walk there? is it water? and from which of 8 directions can you enter/exit?

```
overworld1:  454 land tiles, 78 water, 557 blocked obstacles, 4 WE-bridges, 54 one-way ledges
volcano1:    535 land tiles, 0 water, 554 blocked, 6 bridges, 36 ledges
```

Special tile types:
- **One-way ledges (2,472 tiles):** Jump south off a cliff — can never climb back north.
- **Bridges (52 tiles):** Narrow walkways — can only go left-right OR up-down, never diagonally off.
- **Ladder/stair exits (19 tiles):** Only one direction allowed when stepping off a staircase.
- **Corner guards (3,330 tiles):** Prevents diagonal clipping through building corners.

**How we use it:**

- **MapEnv simulator (primary use):** The RL agent runs INSIDE this grid. Every time it tries to move, the simulator checks the direction bitmask — if the move is blocked, the agent bounces back and gets a penalty (-0.2 reward).
- **BFS pathfinding:** `WalkGrid.find_path(x1,y1, x2,y2)` finds the shortest legal path respecting all bitmasks. Used for the non-learning baseline agent.
- **Action masking for RL:** Before each step, `get_action_mask()` tells the agent exactly which of its 8 moves are physically legal right now — this speeds up training massively (agent never wastes time learning that walls are walls).
- **Map graph (future):** Warp edge tiles (row 0/32 or col 0/32) connect overworld maps — we'll build a graph of all 25 overworld maps so the agent can plan cross-map routes.

> **Example:** Agent is on overworld15 at (21,15) — a bridge tile (Mask=12). It tries to move North. Simulator checks: `bit 1 (North) & 12 = 0` → blocked. Agent stays, gets -0.2. After training, it learns: *on bridge tiles, only go left or right*.

---

### 7. 📼 Recorder Session — 208 Event Chunks

**What it contains:**
A ZIP of compressed JSON files capturing everything that happened during one live game session: DOM mutations, button clicks, map changes, walkgrid snapshots, HP bar changes, Pokémon appearances/disappearances.

Event types: `P` (page snapshot), `+` (element appeared), `-` (element disappeared), `a` (attribute changed like HP bar width), `c` (button clicked), `m` (map changed), `g` (walkgrid captured).

**How we use it:**

- **Battle log extraction:** The recorder parser reads HP change events (`a` type, HP bar `width` attribute) and click events (`c` type, move buttons) to reconstruct real battle turn-by-turn logs. These go into the `battle_logs` DB table.
- **Real battle data for training:** Once we have enough sessions, the battle logs become training data. The battle agent can be pre-trained on "what a human does in real battles" before switching to RL.
- **Map event logs:** `m` and `g` events tell us which map you visited and in what order — useful for building the cross-map exploration graph.
- **Verification:** When we're unsure about a game mechanic (e.g. "does Paralysis skip turns or halve speed?"), we grep the session logs for real examples.

> **Example:** Session chunk shows: `c` event (clicked "Flamethrower"), then `a` event (opponent HP bar width changed from 100% to 25%). Parser reconstructs: *Turn 3: Charizard used Flamethrower → 75% damage to Bulbasaur.*

---

### 8. 📚 Game Source / HTML Captures (`DELUGERPG_Consolidated_Reference/`)

**What it contains:**
The raw JavaScript source (`map.js`, `essentials.js`, `battle.js`, etc.), captured HTML pages, API call logs, and the master reference document. This is the **ground truth** we used to understand all the other data.

**How we use it:**

- **Already used:** We read `map.js` to decode the walkgrid binary format, understand the PEEP_DIRBITS direction bitmask, and replicate `findPath()` exactly.
- **Verification source:** When a mechanic is unclear, we grep the source. No invention — everything is cited.
- **Not in runtime:** This folder is not loaded at runtime by any agent. It was the *research material* that let us build everything else.

> **Example:** `map.js` line `h = h ? (h[0] & 1 ? h[1] : 255) : 255` told us: *"if the tile is not walkable, treat its direction mask as 255 (all directions open) for pathfinding purposes."* Our `walkgrid.py` replicates this exactly.

---

## 🔄 How All the Data Connects — Big Picture

```
Your Recorder Session (ZIP)
        ↓ parser (recorder.py)
   Battle Logs (DB) ──────────────────────────────→ Pre-train BattleEnv agent
   Map event sequence ─────────────────────────────→ Cross-map exploration graph

Pokédex (1107 species)
        +
Your Collection (11070 rows)   →  Collection Advisor  →  Live CAPTURE / SKIP advice
        +                              (advisor.py)
Evolution Chains (888 species)   →  Evolution TODO list

Attack List (591 moves)
        +
Type Chart (18×18)              →  BattleEnv simulator  →  Train DQN/PPO battle agent
        +                           (battle_env.py)
Pokédex types

Map Walkgrids (49 maps)         →  MapEnv simulator     →  Train DQN/PPO map explorer
                                    (map_env.py)
```

---

## ✅ What's Built vs What's Next

| Component | Status | Needs |
|---|---|---|
| Pokédex DB | ✅ Done | — |
| Evolution chains | ✅ Done | — |
| Your collection | ✅ Done | Refresh after each play session |
| Attack DB | ✅ Done | — |
| Type chart | ✅ Done | — |
| Map walkgrids (all 49) | ✅ Done | — |
| MapEnv simulator | ✅ Done | Train agent on it |
| BattleEnv simulator | ✅ Done | Train agent on it |
| Collection Advisor | ✅ Done | Plug into live play |
| Battle log extraction | ✅ Parser done | More session ZIPs needed |
| DQN/PPO map agent | ⏳ Not started | Run training loop |
| DQN/PPO battle agent | ⏳ Not started | Run training loop |
| Cross-map world graph | ⏳ Not started | Warp edge analysis |
| FAISS vector index | ⏳ Not started | For advisor semantic search |
| Course report | ⏳ Not started | After training curves done |

---

*Last updated: 2026-11-24. Test suite: 29 passing, 0 failing.*
