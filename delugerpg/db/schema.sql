-- Schema for DelugeRPG Knowledge Base & Simulator Database

CREATE TABLE IF NOT EXISTS attacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    power INTEGER,
    accuracy INTEGER,
    effect TEXT,
    effect_accuracy INTEGER
);

CREATE INDEX IF NOT EXISTS idx_attacks_name ON attacks(name);
CREATE INDEX IF NOT EXISTS idx_attacks_type ON attacks(type);

CREATE TABLE IF NOT EXISTS pokemon_species (
    dex_no INTEGER NOT NULL,
    name TEXT PRIMARY KEY NOT NULL,
    type1 TEXT NOT NULL,
    type2 TEXT,
    is_mega BOOLEAN NOT NULL DEFAULT 0,
    is_gmax BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pokemon_dex_no ON pokemon_species(dex_no);

CREATE TABLE IF NOT EXISTS user_collection (
    pokemon_name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    owned BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY (pokemon_name, class_name),
    FOREIGN KEY (pokemon_name) REFERENCES pokemon_species(name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS type_effectiveness (
    defense_type TEXT NOT NULL,
    attack_type TEXT NOT NULL,
    multiplier REAL NOT NULL,
    PRIMARY KEY (defense_type, attack_type)
);

CREATE TABLE IF NOT EXISTS map_walkgrids (
    map_name TEXT PRIMARY KEY NOT NULL,
    walkgrid_b64 TEXT NOT NULL,
    total_walkable INTEGER NOT NULL,
    total_water INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS battle_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT,
    battle_type TEXT,
    raw_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
