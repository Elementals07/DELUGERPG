import sys, os, time
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from delugerpg.parsers.walkgrid import WalkGrid

def benchmark_find_path():
    c = sqlite3.connect('data/processed/delugerpg_kb.db')
    row = c.execute('SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?', ('overworld1',)).fetchone()
    wg = WalkGrid.from_base64(row[0], 'overworld1')
    
    t0 = time.time()
    for _ in range(500):
        wg.find_path(8, 29, 28, 11)
        wg.find_path(28, 11, 4, 28)
    elapsed = time.time() - t0
    print(f"1000 find_path calls took {elapsed:.3f}s ({1000/elapsed:.1f} calls/sec)")

if __name__ == "__main__":
    benchmark_find_path()
