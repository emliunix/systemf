"""Debug the CTE behavior for nested forks."""

import sqlite3
import json

conn = sqlite3.connect(":memory:")

conn.executescript("""
CREATE TABLE tapes (
    id INTEGER PRIMARY KEY,
    name TEXT,
    parent_id INTEGER,
    parent_entry_id INTEGER,
    next_entry_id INTEGER DEFAULT 0
);

CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY,
    tape_id INTEGER,
    entry_id INTEGER,
    kind TEXT,
    payload TEXT
);
""")

# Insert test data
conn.execute("INSERT INTO tapes (id, name, parent_id, parent_entry_id, next_entry_id) VALUES (1, 'main', NULL, NULL, 3)")
conn.execute("INSERT INTO tapes (id, name, parent_id, parent_entry_id, next_entry_id) VALUES (2, 'feature', 1, 1, 3)")
conn.execute("INSERT INTO tapes (id, name, parent_id, parent_entry_id, next_entry_id) VALUES (3, 'sub', 2, 2, 3)")

# main: entries 0,1,2
for i in range(3):
    conn.execute("INSERT INTO tape_entries (tape_id, entry_id, kind, payload) VALUES (1, ?, 'msg', ?)", (i, f"main-{i}"))

# feature: own entries 2,3
for i in range(2, 4):
    conn.execute("INSERT INTO tape_entries (tape_id, entry_id, kind, payload) VALUES (2, ?, 'msg', ?)", (i, f"feature-{i}"))

# sub: own entry 3
conn.execute("INSERT INTO tape_entries (tape_id, entry_id, kind, payload) VALUES (3, 3, 'msg', 'sub-3')")

print("=== CTE trace for sub (id=3) ===")
print("\nOriginal CTE (from core.md):")
for row in conn.execute("""
WITH RECURSIVE tape_ancestors(tape_id, parent_id, parent_entry_id, depth) AS (
    SELECT id, parent_id, parent_entry_id, 0 FROM tapes WHERE id = 3
    UNION ALL
    SELECT t.id, t.parent_id, a.parent_entry_id, a.depth + 1
    FROM tapes t
    INNER JOIN tape_ancestors a ON t.id = a.parent_id
    WHERE a.parent_id IS NOT NULL
)
SELECT * FROM tape_ancestors
"""):
    print(f"  tape_id={row[0]} parent_id={row[1]} parent_entry_id={row[2]} depth={row[3]}")

print("\nCorrect CTE (using t.parent_entry_id):")
for row in conn.execute("""
WITH RECURSIVE chain(tape_id, parent_id, fork_point, depth) AS (
    SELECT id, parent_id, parent_entry_id, 0 FROM tapes WHERE id = 3
    UNION ALL
    SELECT t.id, t.parent_id, t.parent_entry_id, c.depth + 1
    FROM tapes t
    INNER JOIN chain c ON t.id = c.parent_id
    WHERE c.parent_id IS NOT NULL
)
SELECT * FROM chain
"""):
    print(f"  tape_id={row[0]} parent_id={row[1]} fork_point={row[2]} depth={row[3]}")

print("\n=== Filtered results ===")
print("\nOriginal CTE filter (e.entry_id <= parent_entry_id):")
for row in conn.execute("""
WITH RECURSIVE tape_ancestors(tape_id, parent_id, parent_entry_id, depth) AS (
    SELECT id, parent_id, parent_entry_id, 0 FROM tapes WHERE id = 3
    UNION ALL
    SELECT t.id, t.parent_id, a.parent_entry_id, a.depth + 1
    FROM tapes t
    INNER JOIN tape_ancestors a ON t.id = a.parent_id
    WHERE a.parent_id IS NOT NULL
)
SELECT e.tape_id, e.entry_id, e.payload, ta.depth
FROM tape_ancestors ta
LEFT JOIN tape_entries e ON e.tape_id = ta.tape_id
WHERE ta.depth = 0 OR (ta.depth > 0 AND e.entry_id <= ta.parent_entry_id)
ORDER BY ta.depth DESC, e.entry_id
"""):
    print(f"  tape={row[0]} entry={row[1]} payload={row[2]} depth={row[3]}")

print("\nExpected for sub: main-0, main-1, feature-2, sub-3")
print("(main up to 1, feature up to 2, sub all own)")

print("\n=== The bug ===")
print("Original CTE passes child's parent_entry_id up the chain.")
print("For main (depth=2), parent_entry_id = 2 (from sub's row).")
print("But main should only show up to 1 (feature's fork point).")
print("This is a latent bug in nested forks!")
