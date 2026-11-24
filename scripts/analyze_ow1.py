import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from delugerpg.parsers.walkgrid import WalkGrid

def analyze_overworld1():
    c = sqlite3.connect('data/processed/delugerpg_kb.db')
    row = c.execute('SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?', ('overworld1',)).fetchone()
    wg = WalkGrid.from_base64(row[0], 'overworld1')
    
    walkable = [(x, y) for x in range(33) for y in range(33) if wg.get_tile(x, y).walkable]
    print(f"Total walkable: {len(walkable)}")
    
    # Check reachable tiles from (8, 29)
    reachable = []
    for wx, wy in walkable:
        p = wg.find_path(8, 29, wx, wy)
        if p is not None:
            reachable.append((wx, wy))
    print(f"Reachable from (8, 29): {len(reachable)} / {len(walkable)}")

if __name__ == "__main__":
    analyze_overworld1()
