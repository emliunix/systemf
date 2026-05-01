"""Validate core2.md schema with dummy data (corrected views)."""

import sqlite3
import json

conn = sqlite3.connect(":memory:")
conn.execute("PRAGMA foreign_keys = ON")

# Schema from core2.md with corrected views
conn.executescript("""
CREATE TABLE tapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES tapes(id),
    parent_entry_id INTEGER,
    next_entry_id INTEGER DEFAULT 0
);

CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    date TEXT NOT NULL
);

CREATE INDEX idx_entries_tape_entry ON tape_entries(tape_id, entry_id);

CREATE TABLE anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    anchor_name TEXT NOT NULL,
    UNIQUE(tape_id, anchor_name),
    UNIQUE(tape_id, entry_id)
);

CREATE INDEX idx_anchors_lookup ON anchors(tape_id, anchor_name);
CREATE INDEX idx_anchors_entry ON anchors(tape_id, entry_id);

-- CORRECTED views with proper fork point propagation
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
    e.meta,
    e.date,
    a.depth,
    a.fork_point
FROM tape_ancestors a
LEFT JOIN tape_entries e ON e.tape_id = a.tape_id
WHERE a.depth = 0 OR e.entry_id <= a.fork_point;

CREATE VIEW merged_anchors AS
SELECT
    a.leaf_id AS leaf_tape_id,
    an.entry_id,
    an.anchor_name,
    a.depth
FROM tape_ancestors a
INNER JOIN anchors an ON an.tape_id = a.tape_id;
""")

def insert_tape(name, parent_id=None, parent_entry_id=None, next_entry_id=0):
    cursor = conn.execute(
        "INSERT INTO tapes (name, parent_id, parent_entry_id, next_entry_id) VALUES (?, ?, ?, ?)",
        (name, parent_id, parent_entry_id, next_entry_id)
    )
    return cursor.lastrowid

def insert_entry(tape_id, entry_id, kind, payload, date):
    conn.execute(
        "INSERT INTO tape_entries (tape_id, entry_id, kind, payload, meta, date) VALUES (?, ?, ?, ?, ?, ?)",
        (tape_id, entry_id, kind, json.dumps(payload), "{}", date)
    )

def insert_anchor(tape_id, entry_id, name):
    conn.execute(
        "INSERT INTO anchors (tape_id, entry_id, anchor_name) VALUES (?, ?, ?)",
        (tape_id, entry_id, name)
    )

# Build test data: 3-level fork with different fork points
# main: [0:system, 1:anchor"start", 2:message]
# feature (fork@1): [2:msg, 3:msg]
# sub (fork@2): [3:msg]

main_id = insert_tape("main", next_entry_id=3)
insert_entry(main_id, 0, "system", {"content": "hello"}, "2024-01-01T00:00:00")
insert_entry(main_id, 1, "anchor", {"name": "start"}, "2024-01-01T00:01:00")
insert_anchor(main_id, 1, "start")
insert_entry(main_id, 2, "message", {"role": "user", "content": "hi"}, "2024-01-01T00:02:00")

feature_id = insert_tape("feature", parent_id=main_id, parent_entry_id=1, next_entry_id=3)
insert_entry(feature_id, 2, "message", {"role": "assistant", "content": "feature work"}, "2024-01-02T00:00:00")
insert_entry(feature_id, 3, "message", {"role": "user", "content": "more"}, "2024-01-02T00:01:00")

sub_id = insert_tape("sub", parent_id=feature_id, parent_entry_id=2, next_entry_id=3)
insert_entry(sub_id, 3, "message", {"role": "assistant", "content": "sub work"}, "2024-01-03T00:00:00")

conn.commit()

print("=== Ancestor chain for sub ===")
for row in conn.execute("SELECT tape_id, parent_id, fork_point, depth FROM tape_ancestors WHERE leaf_id = ? ORDER BY depth", (sub_id,)):
    print(f"  tape={row[0]} parent={row[1]} fork_point={row[2]} depth={row[3]}")

print("\n=== Test 1: Read root (main) ===")
for row in conn.execute("SELECT entry_id, kind, payload FROM merged_entries WHERE leaf_tape_id = ? ORDER BY depth DESC, entry_id", (main_id,)):
    print(f"  {row[0]}: {row[1]} {row[2]}")

print("\n=== Test 2: Read feature (fork@1 from main) ===")
print("Expected: 0(system), 1(anchor), 2(feature msg), 3(feature msg)")
for row in conn.execute("SELECT entry_id, kind, payload, depth FROM merged_entries WHERE leaf_tape_id = ? ORDER BY depth DESC, entry_id", (feature_id,)):
    print(f"  {row[0]}: {row[1]} {row[2]} (depth={row[3]})")

print("\n=== Test 3: Read sub (fork@2 from feature) ===")
print("Expected: 0(system), 1(anchor), 2(feature msg), 3(sub msg)")
for row in conn.execute("SELECT entry_id, kind, payload, depth FROM merged_entries WHERE leaf_tape_id = ? ORDER BY depth DESC, entry_id", (sub_id,)):
    print(f"  {row[0]}: {row[1]} {row[2]} (depth={row[3]})")

print("\n=== Test 4: after_anchor for sub ===")
rows = list(conn.execute(
    "SELECT entry_id, depth FROM merged_anchors WHERE leaf_tape_id = ? AND anchor_name = ? ORDER BY depth ASC LIMIT 1",
    (sub_id, "start")
))
if rows:
    anchor_entry_id, anchor_depth = rows[0]
    print(f"  Anchor 'start' at entry_id={anchor_entry_id}, depth={anchor_depth}")
    print("  Entries after anchor:")
    for r in conn.execute(
        "SELECT entry_id, kind, payload, depth FROM merged_entries WHERE leaf_tape_id = ? AND (depth < ? OR (depth = ? AND entry_id > ?)) ORDER BY depth DESC, entry_id",
        (sub_id, anchor_depth, anchor_depth, anchor_entry_id)
    ):
        print(f"    {r[0]}: {r[1]} {r[2]} (depth={r[3]})")
else:
    print("  Anchor not found!")

print("\n=== Test 5: Bug verification ===")
print("Main entry 2 should NOT be visible in sub (main forked at 1)")
rows = list(conn.execute("SELECT entry_id FROM merged_entries WHERE leaf_tape_id = ? AND tape_id = ? AND entry_id = 2", (sub_id, main_id)))
if rows:
    print("  FAIL: main entry 2 visible in sub!")
else:
    print("  PASS: main entry 2 is correctly hidden")

print("\n=== Test 6: I5 constraint check ===")
# Check if "start" exists in merged view of "sub"
rows = list(conn.execute(
    "SELECT anchor_name FROM merged_anchors WHERE leaf_tape_id = ? AND anchor_name = ?",
    (sub_id, "start")
))
if rows:
    print(f"  Anchor 'start' exists in merged view of sub: I5 would reject")
else:
    print("  Anchor 'start' not in merged view: OK to insert")

# Check if "checkpoint" exists
dupe_check = list(conn.execute(
    "SELECT anchor_name FROM merged_anchors WHERE leaf_tape_id = ? AND anchor_name = ?",
    (sub_id, "checkpoint")
))
if not dupe_check:
    print("  'checkpoint' not in merged view: inserting...")
    insert_entry(sub_id, 4, "anchor", {"name": "checkpoint"}, "2024-01-03T00:01:00")
    insert_anchor(sub_id, 4, "checkpoint")
    conn.commit()
    print("  Inserted: OK")
else:
    print("  'checkpoint' already exists: would reject")

# Verify checkpoint is now visible in merged view
print("\n  Verifying checkpoint in merged_anchors:")
for row in conn.execute("SELECT entry_id, anchor_name, depth FROM merged_anchors WHERE leaf_tape_id = ? AND anchor_name = ?", (sub_id, "checkpoint")):
    print(f"    entry={row[0]} name={row[1]} depth={row[2]}")

print("\n=== All tests completed ===")
