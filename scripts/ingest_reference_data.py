"""
Ingestion script: parses AttackDex, PokeDex, Type Chart, and Walkgrids from
DELUGERPG_Consolidated_Reference and stores them into SQLite and JSON.
"""

import os
import sys
import json
import re

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from delugerpg.parsers.attackdex import AttackDexParser
from delugerpg.parsers.pokedex import PokeDexParser
from delugerpg.parsers.typechart import TypeChart
from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.db.database import DatabaseManager

def main():
    db_path = "data/processed/delugerpg_kb.db"
    db = DatabaseManager(db_path)
    print(f"Initialized database at: {db_path}")

    # 1. Ingest AttackDex
    attackdex_file = "DELUGERPG_Consolidated_Reference/pages/24_attackdex.html"
    if os.path.exists(attackdex_file):
        with open(attackdex_file, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        attacks = AttackDexParser.parse_html(html)
        db.insert_attacks(attacks)
        print(f"Ingested {len(attacks)} attacks into database.")

        # Export attacks JSON
        with open("data/processed/attacks.json", "w", encoding="utf-8") as f:
            json.dump([a.to_dict() for a in attacks], f, indent=2)
    else:
        print(f"Warning: {attackdex_file} not found.")

    # 2. Ingest PokeDex (Page 1)
    pokedex_file = "DELUGERPG_Consolidated_Reference/pages/25_pokedex.html"
    if os.path.exists(pokedex_file):
        with open(pokedex_file, "r", encoding="utf-8", errors="ignore") as f:
            p_html = f.read()
        species = PokeDexParser.parse_html(p_html)
        db.insert_pokemon(species)
        print(f"Ingested {len(species)} Pokemon species into database.")

        # Export pokedex JSON
        with open("data/processed/pokedex_p1.json", "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in species], f, indent=2)
    else:
        print(f"Warning: {pokedex_file} not found.")

    # 3. Ingest Type Chart
    typechart_file = "DELUGERPG_Consolidated_Reference/pages/23_pages_type_chart.html"
    if os.path.exists(typechart_file):
        with open(typechart_file, "r", encoding="utf-8", errors="ignore") as f:
            tc_html = f.read()
        tc = TypeChart.from_html(tc_html)
        db.insert_type_effectiveness(tc.matrix)
        print(f"Ingested {len(tc.matrix)} defense types x 18 attack types into database.")

        # Export type chart JSON
        with open("data/processed/type_chart.json", "w", encoding="utf-8") as f:
            json.dump(tc.matrix, f, indent=2)
    else:
        print(f"Warning: {typechart_file} not found.")

    # 4. Ingest Walkgrid (overworld12)
    walkgrid_file = "DELUGERPG_Consolidated_Reference/source/javascript/inline/inline/script_003__084447d5c3.js"
    if os.path.exists(walkgrid_file):
        with open(walkgrid_file, "r", encoding="utf-8", errors="ignore") as f:
            script_content = f.read()
        m = re.search(r'"([A-Za-z0-9+/=]{100,})"', script_content)
        if m:
            b64_str = m.group(1)
            wg = WalkGrid.from_base64(b64_str, map_name="overworld12")
            walkable_count = sum(t.walkable for row in wg.tiles for t in row)
            water_count = sum(t.is_water for row in wg.tiles for t in row)
            db.insert_walkgrid("overworld12", b64_str, walkable_count, water_count)
            print(f"Ingested walkgrid for overworld12 (walkable={walkable_count}, water={water_count}).")

            # Save map ASCII visualization
            with open("data/maps/overworld12_ascii.txt", "w", encoding="utf-8") as f:
                f.write(wg.to_ascii_map())
    else:
        print(f"Warning: {walkgrid_file} not found.")

    db.close()
    print("Ingestion completed successfully.")

if __name__ == "__main__":
    main()
