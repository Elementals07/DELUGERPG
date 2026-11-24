import os, sqlite3, json, zipfile

print("=== DATA FILES ===")
for root, dirs, files in os.walk("data"):
    for f in files:
        path = os.path.join(root, f)
        size = os.path.getsize(path)
        print(f"{path:<60} {size/1024:.1f} KB")

print()
print("=== SQLITE TABLES ===")
conn = sqlite3.connect("data/processed/delugerpg_kb.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    count = cur.fetchone()[0]
    cur.execute(f"PRAGMA table_info({t})")
    cols = [c[1] for c in cur.fetchall()]
    print(f"  {t:<30} {count:>6} rows  cols={cols}")
conn.close()

print()
print("=== JSON FILES ===")
for f in ["data/processed/pokedex_full.json", "data/processed/attacks.json", "data/processed/type_chart.json"]:
    if os.path.exists(f):
        with open(f) as fh:
            d = json.load(fh)
        if isinstance(d, list):
            print(f"  {f}: {len(d)} entries")
        elif isinstance(d, dict):
            print(f"  {f}: {len(d)} keys  sample={list(d.keys())[:5]}")

print()
print("=== RECORDER SESSION ZIP ===")
zp = "data/raw/deluge_session_20261124-113227.zip"
if os.path.exists(zp):
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        print(f"  {zp}: {len(names)} files inside")
        for n in names[:10]:
            print(f"    {n}")

print()
print("=== PYTHON MODULES ===")
for root, dirs, files in os.walk("delugerpg"):
    for f in files:
        if f.endswith(".py") and f != "__init__.py":
            path = os.path.join(root, f)
            size = os.path.getsize(path)
            print(f"  {path:<55} {size/1024:.1f} KB")

print()
print("=== TESTS ===")
for f in os.listdir("tests"):
    if f.endswith(".py"):
        with open(os.path.join("tests", f)) as fh:
            lines = fh.readlines()
        tests = [l.strip() for l in lines if l.strip().startswith("def test_")]
        print(f"  {f}: {len(tests)} tests")
        for t in tests:
            print(f"    {t}")
