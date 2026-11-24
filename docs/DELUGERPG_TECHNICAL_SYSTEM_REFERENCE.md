# DelugeRPG Technical System Reference

**Author:** Vamsi (3rd-Year Software Engineering Project)  
**System Scope:** Reverse-Engineered DelugeRPG Mechanics, Client Code, Endpoints, DOM Inventory, Evolution Trees, and Data Models  
**Status:** Comprehensive Technical Reference from Captures, Telemetry, and Decompiled Source Analysis  

---

## 1. System & Architecture Overview

DelugeRPG is an online Pokémon browser game built with a **server-rendered backend** (PHP templates) paired with **client-side jQuery (3.7.1 / 4.x)** and **Bootstrap 5**.

### 1.1 Architecture Characteristics
- **Rendering Model:** Standard server-side rendering with AJAX dynamic region swaps. Key containers (e.g. `#battle`, `#show-poke`, `#teamchange`, `#boxselect`, `#mapnum`) are updated via jQuery AJAX calls without full page reloads.
- **Security & Session Tokens:** Observed in inline JavaScript and DOM templates:
  - `logouttok`: Session validation token for logout.
  - `BATT_HASH`: Battle context validation hash bound to the active battle instance.
  - `m_h1`, `m_h2`, `m_h3`: Coordinate and movement verification hashes used in map transitions (`/ajax/map/move/update/`).
  - `teammovetok`: CSRF/action token for updating party rosters.
  - `TS_SITEKEY`, `tsv`, `tsw`: Cloudflare Turnstile bot verification callbacks embedded in capture forms.
- **Content Security Policy (Report-Only):**
  - Observed directive: `Content-Security-Policy-Report-Only: script-src 'unsafe-inline' 'unsafe-eval'`.
  - The browser logs warnings to the developer console whenever external CDN scripts load (e.g. jQuery, Bootstrap), but **does not block or restrict script execution or AJAX requests**.
- **Sanitization Rule:** All actual token strings and personal account names must remain strictly sanitized and redacted in project models and public documentation.

---

## 2. API Endpoints Catalog (42 Endpoints)

All client-to-server communication is channeled through **41 `/ajax/...` endpoints** and **1 `/api/pokedex/` endpoint**.

### 2.1 Map & Navigation Endpoints
1. `POST /ajax/map/move/update/{m_h3}/{m_h1}`
   - **Source:** `map.js:Move()`
   - **Payload:** `direction` (`n`, `s`, `e`, `w`, `nw`, `ne`, `sw`, `se`), `maphash` (`m_h2`), `mhx` (packed client coordinate, timestamp, visibility telemetry), `usess` (encoded session note).
   - **Response:** JSON `{ gox: int, goy: int, showpoke: string (html), ... }`
   - **Purpose:** Commits player step, validates server coordinates, triggers wild encounters.
2. `GET /ajax/map/positions/{mapfile}`
   - **Source:** `map.js:startPeepPoll()`
   - **Polling Interval:** 5000ms – 6500ms jittered (`5E3 + Math.floor(Math.random() * 1500)`).
   - **Response:** JSON `{ walkgrid: string (base64, optional), mappos: array of players, mapcount: int }`
   - **Purpose:** Real-time synchronization of nearby trainers on the active map.
3. `POST /ajax/profile/edit/peepanim`
   - **Source:** `map.js`
   - **Payload:** `{ enabled: 0 | 1 }`
   - **Purpose:** Persists animation toggle for player movement on the map.
4. `POST /ajax/profile/edit/keyboardnav`
   - **Source:** `map-desktop.js`
   - **Payload:** `{ enabled: 0 | 1 }`
   - **Purpose:** Persists keyboard WASD / Arrow / Numpad navigation preferences.

### 2.2 Battle Endpoints
5. `POST /ajax/battle/{loca}`
   - **Source:** `battle.js:battleSubmit()`
   - **Payload:** Serialized battle form (attack selection, item selection, or switch action) + `usess` + `mobile` flag.
   - **Response:** HTML snippet replacing `#battle` container or redirect `/unlock`.
   - **Purpose:** Executes a single battle turn (wild, trainer, gym, or NPC) server-side.
6. `POST /ajax/livebattle/new`
   - **Source:** `live.js`
   - **Purpose:** Initiates a live player-vs-player (PvP) battle challenge.
7. `GET /ajax/livebattle/poll`
   - **Source:** `live.js`
   - **Purpose:** Polls real-time turn status in PvP live battles.
8. `POST /ajax/livebattle/update`
   - **Source:** `live.js`
   - **Purpose:** Sends player action in live PvP battle.
9. `GET /ajax/livebattle/checknew`
   - **Source:** `common.js`
   - **Purpose:** Global polling for pending live battle challenges.
10. `GET /ajax/livebattle/lbupdate`
    - **Source:** `common.js`
    - **Purpose:** Periodic state check for pending live battle lobby status.
11. `GET /ajax/livebattle/ucheck/user/{username}`
    - **Source:** `live.js`
    - **Purpose:** Verifies opponent availability for live battle.

### 2.3 PokeDex & Info API
12. `GET /api/pokedex/info/{pokemon_name}`
    - **Source:** `common.js` (triggered by `.dexpop` click)
    - **Response:** JSON object:
      - `dexid`: National Dex integer (1 to 1025).
      - `generation`: Integer generation (1–9).
      - `name`: Clean species name.
      - `types`: Array of strings (`["Grass", "Poison"]`).
      - `height`, `weight`: Formatted physical dimensions.
      - `classes_owned`: Dictionary of classes unlocked on the account.

### 2.4 Team & Box Management Endpoints
13. `POST /ajax/teamchange/`
    - **Source:** `teamchange.js`
    - **Payload:** `oldorder`, `neworder`, `teammovetok`.
    - **Purpose:** Reorders active 6-member team.
14. `POST /ajax/box/select/`
    - **Source:** `pokebox.js`
    - **Purpose:** Selects box page and filters stored Pokémon.
15. `POST /ajax/evolve/`
    - **Source:** `yourpokes.js` / `/yourpokes.php`
    - **Payload:** `poke_id`, `target_evo`.
    - **Purpose:** Triggers evolution for an eligible Pokémon.
16. `POST /ajax/release/`
    - **Source:** `yourpokes.js`
    - **Payload:** `poke_id`, confirmation token.
    - **Purpose:** Releases a Pokémon from box storage.

---

## 3. DelugeRPG Complete Map Catalog (49 Maps)

DelugeRPG consists of **49 distinct maps**, categorized into open-world exploration zones and specialized dungeon/cave instances:

### 3.1 Overworld Maps (25 Maps)
* `overworld1` to `overworld25`: The primary continental grid routes containing diverse terrain (grass, water, forests, urban roads, elevation ledges).

### 3.2 Special Caves, Towers & Dungeons (24 Maps)
1. **Pokémon Mansion (4 Maps):** `pkmnmansion1`, `pkmnmansion2`, `pkmnmansion3`, `pkmnmansion4`
2. **Pokémon Tower (3 Maps):** `pkmntower1`, `pkmntower2`, `pkmntower3`
3. **Power Plant (3 Maps):** `powerplant1`, `powerplant2`, `powerplant3`
4. **Rock Cave (4 Maps):** `rockcave1`, `rockcave2`, `rockcave3`, `rockcave4`
5. **Snow Cave (4 Maps):** `snowcave1`, `snowcave2`, `snowcave3`, `snowcave4`
6. **Unown Ruins (2 Maps):** `unownruins1`, `unownruins2`
7. **Volcano (4 Maps):** `volcano1`, `volcano2`, `volcano3`, `volcano4`

---

## 4. Walkgrid Specification & Movement Physics

### 4.1 Walkgrid Storage & Matrix Dimensions
- **Matrix Dimensions:** Exactly $33 \text{ rows} \times 33 \text{ columns} = 1,089 \text{ tiles}$.
- **Byte Storage:** 2 bytes per tile $\implies 33 \times 33 \times 2 = 2,178$ raw bytes ($2,904$ Base64 characters).
- **Inline Declaration:** Injected in page HTML as `<script>window.mapWalkgrid = "...";</script>`.
- **Indexing Formula:**
  $$\text{Byte Offset for Tile } (x, y) = (x \times 33 + y) \times 2$$

### 4.2 Byte 0: Terrain Walkability Flags
Empirical analysis of all 53,361 tiles across all 49 game maps reveals exactly three discrete states:
- `0` ($0x00$, 19,244 tiles / 36.1%): **Solid Obstacle / Void**. Impassable terrain (mountain walls, dense trees, building exteriors, boundary chasms). Byte 1 is always `0`.
- `1` ($0x01$, 24,513 tiles / 45.9%): **Walkable Land**. Standard grass, paths, indoor floors, and bridges.
- `3` ($0x03 = 0x01 \mid 0x02$, 9,604 tiles / 18.0%): **Surfable Water**. Water tiles where both walkable (Bit 0) and water (Bit 1) flags are asserted.

### 4.3 Byte 1: 8-Directional Movement Bitmasks (`PEEP_DIRBITS`)
Defines legal exit directions from tile $(x, y)$:
- North (`n`): $1$ ($0x01$, offset $(-1, 0)$)
- South (`s`): $2$ ($0x02$, offset $(+1, 0)$)
- West (`w`): $4$ ($0x04$, offset $(0, -1)$)
- East (`e`): $8$ ($0x08$, offset $(0, +1)$)
- Northwest (`nw`): $16$ ($0x10$, offset $(-1, -1)$)
- Northeast (`ne`): $32$ ($0x20$, offset $(-1, +1)$)
- Southwest (`sw`): $64$ ($0x40$, offset $(+1, -1)$)
- Southeast (`se`): $128$ ($0x80$, offset $(+1, +1)$)

Internal navigation limits player coordinates to $1 \le x, y \le 31$. Boundary tiles ($x, y \in \{0, 32\}$) serve as warp transition triggers between maps.

### 4.4 Comprehensive 49-Map Terrain & Architectural Analysis
Across the 49 maps (53,361 tiles), directional masks partition gameplay terrain into distinct physical behaviors:

#### 1. One-Way Ledges & Elevation Cliffs (3,861 tiles)
- **South Jump Ledges (Mask 206 / `0xCE`, 1,167 tiles):** Classic Pokémon one-way ledges. Players can jump downward South (`s`), or move along the ridge (`w`, `e`, `sw`, `se`), but are strictly blocked from returning North (`n`, `nw`, `ne`).
- **North Cliff Boundaries (Mask 61 / `0x3D`, 1,305 tiles):** Blocks movement downward South (`s`, `sw`, `se`) at northern boundaries and elevated fences.
- **West / East Cliff Sides (Mask 171 / `0xAB` [704 tiles] & Mask 87 / `0x57` [685 tiles]):** Wall and ridge borders blocking lateral traversal onto elevated ridges.

#### 2. Bridges & Planking Walkways (52 tiles)
- **East-West Bridges (Mask 12 / `0x0C`, 26 tiles):** Planks over water or chasms where only horizontal movement (`w`, `e`) is permitted. Any attempt to step North or South off the bridge into water is physically rejected. Observed in `overworld1`, `overworld15` (5-tile span at $x=21, y=14..18$), `overworld17`, `volcano1` (5-tile span at $x=1, y=4..8$), and `pkmnmansion1,3,4`.
- **North-South Bridges (Mask 3 / `0x03`, 26 tiles):** Vertical footpaths where only vertical movement (`n`, `s`) is permitted. Observed in `overworld2`, `overworld17` (4-tile span at $y=10, x=11..14$), `overworld18`, `overworld19`, `overworld25`, and `pkmntower3`.

#### 3. Ladders, Staircases & Choke Exits (19 tiles)
Degree 1 tiles permitting only a single directional exit vector upon entering a new elevation or room:
- `pkmntower2` (18, 30): Mask 4 (`w` only) — stepping off spiral staircase.
- `powerplant3` (14, 30): Mask 1 (`n` only) — exiting access ladder into generator room.
- `rockcave2` (25, 31): Mask 4 (`w` only) — stepping out of dark cave entrance tunnel.
- `unownruins2` (11, 31): Mask 4 (`w` only) — chamber descent step.
- `volcano2` (19, 31): Mask 4 (`w` only) — rim exit footpath.

#### 4. Anti-Clipping Corner Buffers (3,330 tiles)
Masks 239 (`0xEF`, -nw), 127 (`0x7F`, -se), 223 (`0xDF`, -ne), and 191 (`0xBF`, -sw) selectively eliminate a single diagonal vector touching building vertices, ensuring agents and players cannot diagonally clip through solid corner geometry.

### 4.5 Zone-by-Zone Walkgrid Distribution Summary Table

| Zone Category | Map Count | Walkable Land | Surfable Water | Solid Obstacles | Bridges | One-Way Ledges | Ladders/Exits |
|---|---|---|---|---|---|---|---|
| **Overworld (1–25)** | 25 | 11,097 (40.8%) | 8,089 (29.7%) | 8,039 (29.5%) | 38 | 861 | 9 |
| **Pokémon Mansion (1–4)** | 4 | 2,348 (53.9%) | 0 (0.0%) | 2,008 (46.1%) | 3 | 467 | 0 |
| **Pokémon Tower (1–3)** | 3 | 1,343 (41.1%) | 0 (0.0%) | 1,924 (58.9%) | 5 | 153 | 2 |
| **Power Plant (1–3)** | 3 | 1,487 (45.5%) | 0 (0.0%) | 1,780 (54.5%) | 0 | 177 | 4 |
| **Rock Cave (1–4)** | 4 | 2,248 (51.6%) | 1,026 (23.6%) | 1,082 (24.8%) | 0 | 148 | 1 |
| **Snow Cave (1–4)** | 4 | 2,693 (61.8%) | 489 (11.2%) | 1,174 (27.0%) | 0 | 234 | 1 |
| **Unown Ruins (1–2)** | 2 | 1,273 (58.4%) | 0 (0.0%) | 905 (41.6%) | 0 | 277 | 1 |
| **Volcano (1–4)** | 4 | 2,024 (46.5%) | 0 (0.0%) | 2,332 (53.5%) | 6 | 155 | 1 |
| **Total Game World** | **49** | **24,513 (45.9%)** | **9,604 (18.0%)** | **19,244 (36.1%)** | **52** | **2,472** | **19** |

---

## 5. Pokémon Variants, Mechanics & Stat Formulations

DelugeRPG replaces Game Freak's complex EV/IV/nature system with an elegant, deterministic model tailored for fast turn-based browser combat.

### 5.1 The 10 Pokémon Variant Classes
Every species exists in 10 possible variant classes with concrete functional multipliers:
1. `Normal`: Standard stats; baseline damage and health (Parity: $+1$).
2. `Shiny`: **+25% Maximum Health** ($1.25\times$ HP) (Parity: $+1$).
3. `Dark`: **+25% Attack Power** ($1.25\times$ damage dealt) (Parity: $+1$).
4. `Ghostly`: Innate **20% flinch chance** on direct attacks, canceling opponent turns (Parity: $+1$).
5. `Metallic`: Completely **immune to all status ailments** (`Burn`, `Confuse`, `Freeze`, `Paralyz`, `Poison`, `Sleep`) (Parity: $+1$).
6. `Shadow`: **Neutralizes Metallic and Ghostly passives** (bypasses Metallic status immunity and Ghostly flinch) (Parity: $+1$).
7. `Negative`: **Inverts the entire type effectiveness matrix** (weaknesses become resistances and vice versa) (Parity: $-1$).
8. `Mirage`: Rare event variant (Parity: $+1$).
9. `Chrome`: Rare promotional metallic-reflective variant (Parity: $+1$).
10. `Retro`: Classic Gen 1/2 sprite presentation (Parity: $+1$).

### 5.2 Stat Formulations
- **Maximum HP Formula:**
  $$\text{Max HP} = \text{Level} \times 4 \times (1.25 \text{ if Shiny else } 1.0)$$
  *Example:* Level 100 Normal Charizard = $400\text{ HP}$; Level 100 Shiny Charizard = $500\text{ HP}$.
- **Damage Formula:**
  $$\text{Damage} = \left\lfloor \frac{\text{Level} \times \text{Power}}{50} \right\rfloor \times \text{STAB} \times \text{VariantMult} \times \text{TypeMult}$$
  - $\text{STAB} = 1.5$ if attack type matches attacker `type1` or `type2`, else $1.0$.
  - $\text{VariantMult} = 1.25$ if attacker is `Dark`, else $1.0$.
  - $\text{TypeMult} = \text{Matrix}[\text{Def}_1][\text{Atk}] \times \text{Matrix}[\text{Def}_2][\text{Atk}]$.
  - In Negative battles / Negative defender, $\text{TypeMult}$ is inverted ($2.0\times \to 0.5\times$, $0.5\times \to 2.0\times$, $0.0\times \to 2.0\times$).

---

## 6. Evolution Hierarchy & Rarity Tiers

DelugeRPG encompasses **1,107 species** (Gen 1 to 9), structured into canonical evolutionary lines:

### 6.1 Evolution Stages
- **Stage 1 (Base/Starter):** E.g. Bulbasaur, Pichu, Charmander, Pidgey, Eevee, Rhyhorn.
- **Stage 2 (Middle/First Evo):** E.g. Ivysaur, Pikachu, Charmeleon, Pidgeotto, Rhydon.
- **Stage 3 (Final Evo):** E.g. Venusaur, Raichu, Charizard, Pidgeot, Rhyperior.
- **Branching Evolutions:**
  - Eevee $\to$ 8 evolutions (`Vaporeon`, `Jolteon`, `Flareon`, `Espeon`, `Umbreon`, `Leafeon`, `Glaceon`, `Sylveon`).
  - Gloom $\to$ `Vileplume`, `Bellossom`.
  - Poliwhirl $\to$ `Poliwrath`, `Politoed`.
  - Slowpoke $\to$ `Slowbro`, `Slowking`.
  - Tyrogue $\to$ `Hitmonlee`, `Hitmonchan`, `Hitmontop`.
  - Applin $\to$ `Flapple`, `Appletun`, `Dipplin`.
  - Charcadet $\to$ `Armarouge`, `Ceruledge`.

### 6.2 Rarity Tiers
1. `starter`: 81 species across 27 canonical 3-stage starter lines.
2. `legendary`: 70+ species (Birds, Mewtwo, Beasts, Weather Trio, Creation Trio, Swords of Justice, Tao Trio, Aura Trio, Light Trio, Box Legends).
   - *Unlock Rule:* Spawns unlock on maps only after clearing all regional Gyms, Elite Four, and Dojos.
   - *Duplicate Constraint:* Players may own different variants of a legendary, but **duplicate identical variants of the same legendary are strictly prohibited**.
3. `mythical`: 23 species (Mew, Celebi, Jirachi, Deoxys, Darkrai, Arceus, Victini, Pecharunt, etc.).
4. `ultra_beast`: 11 extradimensional species (Nihilego, Buzzwole, Kartana, Blacephalon, etc.).
5. `paradox`: Ancient and Future Pokémon (Great Tusk, Roaring Moon, Iron Valiant, Iron Crown, etc.).
6. `regular`: All standard wild spawn species.

---

## 7. Account Box & Team Architecture (`/yourpokes.php`, `/team`)

### 7.1 Team Composition
- Maximum of 6 active Pokémon.
- Controlled via `teamchange.js` (Promote, Demote, Replace, Remove).
- Removing a Pokémon returns it to the box storage; Pokémon never disappear unless explicitly released.

### 7.2 Box Inventory Fields
Each owned Pokémon in storage possesses:
- `poke_id`: Unique alphanumeric identifier (e.g. `5nqz7n`).
- `name`: Species name (e.g. `Croagunk`).
- `level`: Integer level (1 to 100).
- `exp`: Accumulated experience points.
- `attacks`: Exactly 4 known moves.
- `can_evolve`: Boolean flag enabling the `/ajax/evolve/` button when level/item conditions are met.
