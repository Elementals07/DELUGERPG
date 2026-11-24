import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from delugerpg.parsers.walkgrid import WalkGrid

WAYPOINTS = [
    (4, 28),   # 0: NE Pine Forest
    (7, 22),   # 1: North Snow Ridge
    (8, 29),   # 2: East Upper Trail (User's location!)
    (11, 28),  # 3: East Cliff Path
    (11, 19),  # 4: Upper Snowfield
    (14, 12),  # 5: North Central Plains
    (14, 2),   # 6: Ice Cavern Entrance
    (20, 4),   # 7: West Upper Bridge
    (20, 11),  # 8: Central Crossroads
    (19, 19),  # 9: East Central Terraces
    (19, 26),  # 10: Far East Ridge Overlook
    (28, 4),   # 11: Southwest Lower Bridge
    (28, 11),  # 12: South Valley
    (28, 20),  # 13: Southeast Rock Field
    (28, 27),  # 14: Southeast Dirt Plateau
    (24, 16),  # 15: Lower Central Basin
]

def test_connectivity():
    c = sqlite3.connect('data/processed/delugerpg_kb.db')
    row = c.execute('SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?', ('overworld1',)).fetchone()
    wg = WalkGrid.from_base64(row[0], 'overworld1')
    
    # Check each waypoint is walkable
    for i, (wx, wy) in enumerate(WAYPOINTS):
        tile = wg.get_tile(wx, wy)
        assert tile and tile.walkable, f"Waypoint {i} ({wx}, {wy}) not walkable!"
        
    print("All 16 waypoints are walkable!")
    
    # Check all pairs connectivity
    disconnected = 0
    for i in range(len(WAYPOINTS)):
        for j in range(len(WAYPOINTS)):
            if i != j:
                p = wg.find_path(WAYPOINTS[i][0], WAYPOINTS[i][1], WAYPOINTS[j][0], WAYPOINTS[j][1])
                if p is None:
                    print(f"Disconnection: {i} -> {j}")
                    disconnected += 1
    print(f"All-pairs check complete. Disconnections: {disconnected} / {16*15}")

if __name__ == "__main__":
    test_connectivity()
