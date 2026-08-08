import sqlite3

c = sqlite3.connect("data/vanguard.db")
c.row_factory = sqlite3.Row

rows = c.execute(
    "SELECT term, outcome, score FROM gaps "
    "WHERE score IS NOT NULL ORDER BY score DESC"
).fetchall()

print(f"{len(rows)} terms reached stage 3 (embedding fallback)")
print()
for r in rows:
    print(f"{r['score']:.3f}  {r['outcome']:<9} {r['term'][:55]}")

total = c.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]
print()
print(f"{total} gap rows in total")