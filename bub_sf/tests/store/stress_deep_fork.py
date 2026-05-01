"""Stress test: 100 levels of nested forks.

Deep fork chains stress-test the CTE recursion performance.
100 levels is a realistic worst-case; 1000+ is pathological.
"""

import sqlite3
import time

conn = sqlite3.connect(":memory:")
conn.execute("PRAGMA foreign_keys = ON")

conn.executescript("""
CREATE TABLE tapes (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
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

CREATE VIEW tape_ancestors AS
WITH RECURSIVE chain(leaf_id, tape_id, parent_id, fork_point, depth) AS (
    SELECT id, id, parent_id, parent_entry_id, 0 FROM tapes
    UNION ALL
    SELECT c.leaf_id, t.id, t.parent_id,
           (SELECT parent_entry_id FROM tapes WHERE id = c.tape_id),
           c.depth + 1
    FROM tapes t
    INNER JOIN chain c ON t.id = c.parent_id
    WHERE c.parent_id IS NOT NULL
)
SELECT * FROM chain;

CREATE VIEW merged_entries AS
SELECT
    a.leaf_id AS leaf_tape_id,
    e.entry_id,
    e.kind,
    e.payload,
    a.depth
FROM tape_ancestors a
LEFT JOIN tape_entries e ON e.tape_id = a.tape_id
WHERE a.depth = 0 OR e.entry_id <= a.fork_point;
""")

# Build 100-level nested fork chain
DEPTH = 100
print(f"Building {DEPTH}-level fork chain...")
start = time.perf_counter()

# Root tape
conn.execute("INSERT INTO tapes (id, name, next_entry_id) VALUES (1, 'tape_0', 1)")
conn.execute("INSERT INTO tape_entries (tape_id, entry_id, kind, payload) VALUES (1, 0, 'msg', 'root')")

for i in range(1, DEPTH + 1):
    parent_id = i
    child_id = i + 1
    # Fork at entry 0 (only shared entry)
    conn.execute(
        "INSERT INTO tapes (id, name, parent_id, parent_entry_id, next_entry_id) VALUES (?, ?, ?, 0, 1)",
        (child_id, f'tape_{i}', parent_id)
    )
    # Each child adds one own entry
    conn.execute(
        "INSERT INTO tape_entries (tape_id, entry_id, kind, payload) VALUES (?, 1, 'msg', ?)",
        (child_id, f'own-{i}')
    )

conn.commit()
elapsed = time.perf_counter() - start
print(f"Created {DEPTH} levels in {elapsed:.3f}s")

# Test reading the deepest tape
leaf_id = DEPTH + 1
print(f"\nReading tape_{DEPTH} (deepest, id={leaf_id})...")
start = time.perf_counter()
try:
    rows = list(conn.execute(
        f"SELECT entry_id, payload, depth FROM merged_entries WHERE leaf_tape_id = {leaf_id} ORDER BY depth DESC, entry_id"
    ))
    elapsed = time.perf_counter() - start
    print(f"Read {len(rows)} entries in {elapsed*1000:.3f}ms")
    print(f"First 5: {rows[:5]}")
    print(f"Last 5: {rows[-5:]}")
except Exception as e:
    print(f"ERROR: {e}")

# Test ancestor chain
print(f"\nAncestor chain for tape_{DEPTH}:")
start = time.perf_counter()
try:
    rows = list(conn.execute(
        f"SELECT tape_id, depth FROM tape_ancestors WHERE leaf_id = {leaf_id} ORDER BY depth"
    ))
    elapsed = time.perf_counter() - start
    print(f"Chain length: {len(rows)} in {elapsed*1000:.3f}ms")
    print(f"First 5: {rows[:5]}")
    print(f"Last 5: {rows[-5:]}")
except Exception as e:
    print(f"ERROR: {e}")

# Test ancestor chain
print(f"\nAncestor chain for tape_{DEPTH}:")
start = time.perf_counter()
try:
    rows = list(conn.execute(
        "SELECT tape_id, depth FROM tape_ancestors WHERE leaf_id = 1001 ORDER BY depth"
    ))
    elapsed = time.perf_counter() - start
    print(f"Chain length: {len(rows)} in {elapsed*1000:.3f}ms")
    print(f"First 5: {rows[:5]}")
    print(f"Last 5: {rows[-5:]}")
except Exception as e:
    print(f"ERROR: {e}")

print("\nDone.")
