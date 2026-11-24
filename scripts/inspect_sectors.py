import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from delugerpg.parsers.walkgrid import WalkGrid

def inspect_clusters():
    c = sqlite3.connect('data/processed/delugerpg_kb.db')
    row = c.execute('SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?', ('overworld1',)).fetchone()
    wg = WalkGrid.from_base64(row[0], 'overworld1')
    
    walkable = [(x, y) for x in range(33) for y in range(33) if wg.get_tile(x, y).walkable]
    
    # Let's inspect density in a 4x4 grid of sectors
    sectors = {}
    for x, y in walkable:
        sx = x // 8
        sy = y // 8
        sectors[(sx, sy)] = sectors.get((sx, sy), 0) + 1
        
    for k, v in sorted(sectors.items()):
        print(f"Sector {k} (x: {k[0]*8}-{k[0]*8+7}, y: {k[1]*8}-{k[1]*8+7}): {v} walkable tiles")

if __name__ == "__main__":
    inspect_clusters()
