import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from delugerpg.parsers.walkgrid import WalkGrid

def find_representative_waypoints():
    c = sqlite3.connect('data/processed/delugerpg_kb.db')
    row = c.execute('SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?', ('overworld1',)).fetchone()
    wg = WalkGrid.from_base64(row[0], 'overworld1')
    
    walkable = [(x, y) for x in range(33) for y in range(33) if wg.get_tile(x, y).walkable]
    
    # Group tiles by 8x8 sectors
    sectors = {}
    for x, y in walkable:
        s = (x // 8, y // 8)
        sectors.setdefault(s, []).append((x, y))
        
    waypoints = []
    for s, tiles in sorted(sectors.items()):
        # Find tile closest to centroid of the sector
        cx = sum(t[0] for t in tiles) / len(tiles)
        cy = sum(t[1] for t in tiles) / len(tiles)
        best_tile = min(tiles, key=lambda t: (t[0]-cx)**2 + (t[1]-cy)**2)
        waypoints.append((s, best_tile, len(tiles)))
        
    print(f"Total waypoints: {len(waypoints)}")
    for s, tile, count in waypoints:
        print(f"Sector {s}: Waypoint {tile} (sector has {count} tiles)")

if __name__ == "__main__":
    find_representative_waypoints()
