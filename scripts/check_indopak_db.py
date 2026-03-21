#!/usr/bin/env python3
"""Show which tables are inside a QUL SQLite file (layout vs word-by-word)."""
import sqlite3
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "indopak-13-lines-layout-qudratullah.db"
if p.is_dir():
    print(f"That path is a folder, not the .db file. Use the actual sqlite file inside the zip.")
    sys.exit(1)
if not p.is_file():
    print(f"Not a file: {p}")
    sys.exit(1)
c = sqlite3.connect(str(p))
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(f"File: {p.name} ({p.stat().st_size // 1024} KB)")
print("Tables:", ", ".join(tabs))
if "pages" in tabs and "words" in tabs:
    print("\n* Combined: pages + words. One file is enough for import.")
elif "pages" in tabs:
    n = c.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    print(f"\n* Mushaf LAYOUT only ({n} page-line rows). Pair with indopak-nastaleeq.db.")
elif "words" in tabs:
    n = c.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    print(f"\n* WORD-BY-WORD only ({n} words). Pair with layout 236 .db.")
else:
    print("\n* Unknown schema.")
c.close()
