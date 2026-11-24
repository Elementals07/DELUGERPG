"""
SQLite Database manager for DelugeRPG knowledge base and game state.
"""

import sqlite3
import os
from typing import List, Dict, Optional, Tuple, Any
from ..core.types import Attack, PokemonSpecies

DEFAULT_DB_PATH = "data/processed/delugerpg_kb.db"

class DatabaseManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            self.conn.executescript(schema_sql)
            self.conn.commit()

    def insert_attacks(self, attacks: List[Attack]):
        cursor = self.conn.cursor()
        for atk in attacks:
            cursor.execute("""
                INSERT OR REPLACE INTO attacks (name, type, power, accuracy, effect, effect_accuracy)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (atk.name, atk.type, atk.power, atk.accuracy, atk.effect, atk.effect_accuracy))
        self.conn.commit()

    def insert_pokemon(self, species_list: List[PokemonSpecies]):
        cursor = self.conn.cursor()
        for p in species_list:
            cursor.execute("""
                INSERT OR REPLACE INTO pokemon_species (dex_no, name, type1, type2, is_mega, is_gmax)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (p.dex_no, p.name, p.type1, p.type2, int(p.is_mega), int(p.is_gmax)))

            for class_name, owned in p.classes_owned.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO user_collection (pokemon_name, class_name, owned)
                    VALUES (?, ?, ?)
                """, (p.name, class_name, int(owned)))
        self.conn.commit()

    def insert_type_effectiveness(self, matrix: Dict[str, Dict[str, float]]):
        cursor = self.conn.cursor()
        for def_t, atks in matrix.items():
            for atk_t, mult in atks.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO type_effectiveness (defense_type, attack_type, multiplier)
                    VALUES (?, ?, ?)
                """, (def_t, atk_t, mult))
        self.conn.commit()

    def insert_walkgrid(self, map_name: str, b64_str: str, walkable: int, water: int, blocked: int = 0, restricted: int = 0):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO map_walkgrids (map_name, walkgrid_b64, total_walkable, total_water, total_blocked, total_restricted)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (map_name, b64_str, walkable, water, blocked, restricted))
        self.conn.commit()

    def get_walkgrid(self, map_name: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM map_walkgrids WHERE LOWER(map_name) = LOWER(?)", (map_name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_maps(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT map_name, total_walkable, total_water, total_blocked, total_restricted FROM map_walkgrids ORDER BY map_name")
        return [dict(r) for r in cursor.fetchall()]

    def get_attack(self, name: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM attacks WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_pokemon(self, name: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM pokemon_species WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_collection(self, pokemon_name: str) -> Dict[str, bool]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT class_name, owned FROM user_collection WHERE LOWER(pokemon_name) = LOWER(?)", (pokemon_name,))
        return {row["class_name"]: bool(row["owned"]) for row in cursor.fetchall()}

    def get_missing_classes(self, pokemon_name: str) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT class_name FROM user_collection WHERE LOWER(pokemon_name) = LOWER(?) AND owned = 0", (pokemon_name,))
        return [row["class_name"] for row in cursor.fetchall()]

    def close(self):
        self.conn.close()
