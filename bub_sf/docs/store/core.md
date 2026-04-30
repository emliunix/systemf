# ForkTapeStore Core Design

## Overview

ForkTapeStore is a SQLite-backed append-only tape store that supports instant branching via copy-on-write semantics. A fork creates a new tape that shares history with its parent up to a specific point, then diverges independently.

## Key Properties

- **Instant fork**: O(1) metadata operation, no data copying
- **Shared history**: Parent entries are read transparently through the child
- **Monotonic entry IDs**: Merged view presents continuous, gap-free entry IDs
- **Nested forks**: Forks can be forked, creating trees of arbitrary depth
- **Physical snapshot**: Optional deep copy for independent lifecycle

## Schema

### tapes Table

Metadata for each tape, including fork relationships.

```sql
CREATE TABLE tapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES tapes(id),
    parent_entry_id INTEGER,        -- Last shared entry in parent (fork point)
    parents_cache TEXT,             -- JSON: [[tape_id, entry_id], ...] eagerly computed
    next_entry_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
```

Fields:
- `id`: Internal surrogate key
- `name`: Human-readable unique tape identifier
- `parent_id`: NULL for root tapes; references parent tape for forks
- `parent_entry_id`: The last entry ID inherited from parent. Forked tape's own entries start from `parent_entry_id + 1`.
- `parents_cache`: Pre-computed JSON array of all ancestor fork points, eagerly maintained to avoid CTE recursion on hot paths. Format: `[[ancestor_id, fork_entry_id], ...]` ordered from root to immediate parent.
- `next_entry_id`: Next entry ID to allocate. Starts at 0 for root tapes. After fork, starts at `parent_entry_id + 1`.
- `created_at`: ISO timestamp

### tape_entries Table

Actual append-only entries. Entry IDs are scoped per tape.

```sql
CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,      -- Sequential within this tape
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON
    meta TEXT,                      -- JSON
    date TEXT NOT NULL,
    UNIQUE(tape_id, entry_id)
);

CREATE INDEX idx_entries_tape ON tape_entries(tape_id, entry_id);
```

## Entry ID Semantics

### Within a Single Tape

Entry IDs are monotonically increasing integers starting from 0 for root tapes:

```
Root tape "main":
  entry_id: 0, 1, 2, 3, 4, 5, ...
  next_entry_id: 6
```

### Fork Point

When forking at entry ID `N`, the child tape:
- Inherits entries `0..N` from parent (shared)
- Starts its own entries at `N + 1`
- `parent_entry_id = N`
- `next_entry_id = N + 1` initially

```
Parent "main" (next_entry_id = 6):
  entry_id: 0, 1, 2, 3, 4, 5

Fork "main-fork" at entry_id = 3:
  parent_entry_id = 3
  next_entry_id = 4
  Own entries: 4, 5, 6, ...
  
Merged view of "main-fork":
  entry_id: 0, 1, 2, 3 (from parent), 4, 5, 6 (own)
```

### Monotonic Merged View

When reading a forked tape, the merged view presents a continuous sequence without gaps:

```
Root "main":
  0: system
  1: message "hello"
  2: message "world"
  3: handoff "phase1"

Fork "main-v2" at entry_id = 1:
  parent_entry_id = 1
  Merged view:
    0: system
    1: message "hello"
    2: message (own) "new direction"
    3: message (own) "continuing"
```

The entry IDs in the merged view are gap-free and monotonically increasing, making them suitable for offset-based addressing (e.g., "fork from offset 5").

## Query: Read Merged Tape (CTE Version)

Read all entries from a tape, including inherited parent entries up to each fork point.

```sql
WITH RECURSIVE tape_ancestors(tape_id, parent_id, parent_entry_id, depth) AS (
    -- Start with the target tape
    SELECT id, parent_id, parent_entry_id, 0
    FROM tapes
    WHERE name = ?
    
    UNION ALL
    
    -- Recurse into parent
    SELECT t.id, t.parent_id, t.parent_entry_id, a.depth + 1
    FROM tapes t
    INNER JOIN tape_ancestors a ON t.id = a.parent_id
    WHERE a.parent_id IS NOT NULL
)
SELECT 
    e.entry_id,
    e.kind,
    e.payload,
    e.meta,
    e.date
FROM tape_ancestors ta
LEFT JOIN tape_entries e ON e.tape_id = ta.tape_id
WHERE 
    -- Leaf tape (depth=0): include ALL its own entries
    ta.depth = 0
    OR
    -- Ancestor tapes: only include entries UP TO the fork point
    (ta.depth > 0 AND e.entry_id <= ta.parent_entry_id)
ORDER BY ta.depth DESC, e.entry_id;
```

Result ordering:
- `ta.depth DESC` puts root tape first, leaf tape last
- `e.entry_id ASC` within each tape level
- Combined: continuous monotonic sequence from root to leaf

## Query: Read Merged Tape (Cached Version)

For frequently-read tapes, use the pre-computed `parents_cache` to avoid recursion:

```sql
WITH 
-- Parse parents_cache JSON into rows
parent_chain(tape_id, entry_id, ord) AS (
    SELECT 
        json_extract(value, '$[0]'),
        json_extract(value, '$[1]'),
        key
    FROM json_each(?)  -- parents_cache value
),
-- Entries from ancestors (each up to their fork point)
ancestor_entries(entry_id, kind, payload, meta, date, ord) AS (
    SELECT e.entry_id, e.kind, e.payload, e.meta, e.date, p.ord
    FROM tape_entries e
    INNER JOIN parent_chain p ON e.tape_id = p.tape_id
    WHERE e.entry_id <= p.entry_id
),
-- Entries from leaf tape (all of them)
leaf_entries(entry_id, kind, payload, meta, date, ord) AS (
    SELECT entry_id, kind, payload, meta, date, 999999
    FROM tape_entries
    WHERE tape_id = ?
)
SELECT entry_id, kind, payload, meta, date
FROM ancestor_entries
UNION ALL
SELECT entry_id, kind, payload, meta, date
FROM leaf_entries
ORDER BY ord, entry_id;
```

This version is O(1) complexity for the metadata lookup and O(N) for the entry scan, where N is the total visible entries.

## Operations

### fork(source_name: str, target_name: str) → None

Create a new tape that shares history with the source up to the current latest entry.

**Algorithm:**
1. Look up source tape by name
2. `fork_point = source.next_entry_id - 1` (last entry before fork)
3. Compute `parents_cache`:
   - If source is root: `[[source.id, fork_point]]`
   - If source is fork: append `[source.id, fork_point]` to source.parents_cache
4. Insert new tape row with:
   - `parent_id = source.id`
   - `parent_entry_id = fork_point`
   - `parents_cache = computed_chain`
   - `next_entry_id = fork_point + 1`

**Time complexity:** O(1) — single INSERT, no data copying
**Space complexity:** O(1) — metadata only

### snapshot(source_name: str, target_name: str) → None

Create an independent physical copy of the source tape. The new tape has no parent.

**Algorithm:**
1. Create new root tape (`parent_id = NULL`)
2. Copy all entries from source tape into new tape, preserving entry_ids
3. Set `next_entry_id` on new tape to match source

**Time complexity:** O(N) where N = number of entries
**Space complexity:** O(N)

### append(tape_name: str, entry: TapeEntry) → None

Append a new entry to a tape.

**Algorithm:**
1. Look up tape by name
2. Insert entry with `entry_id = tape.next_entry_id`
3. Increment `tape.next_entry_id`

**Invariant:** `entry_id` is always sequential and gap-free within the tape's own entries.

### fetch_all(query: TapeQuery) → list[TapeEntry]

Read entries from a tape, applying filters from the TapeQuery.

**Algorithm:**
1. Resolve tape by name
2. If root tape: query `tape_entries` directly
3. If fork with `parents_cache`: use cached union query
4. If fork without cache: use CTE recursive query
5. Apply additional filters (kinds, limit, etc.) from TapeQuery

### read(tape_name: str) → list[TapeEntry] | None

Convenience method: return all entries for a tape (merged view).

Equivalent to `fetch_all(TapeQuery(tape=tape_name))`.

## Parents Cache Maintenance

The `parents_cache` column is eagerly maintained on fork:

```python
def compute_parents_cache(source_id, source_parent_entry_id, source_parents_cache):
    chain = json.loads(source_parents_cache or "[]")
    chain.append([source_id, source_parent_entry_id])
    return json.dumps(chain)
```

**Example:**

```
tape_a (id=1, root): parents_cache = "[]"
  
tape_b forked from tape_a at entry 50:
  parents_cache = "[[1, 50]]"
  
tape_c forked from tape_b at entry 10:
  parents_cache = "[[1, 50], [2, 10]]"
```

When reading `tape_c` with cached query:
- Read entries from tape_1 (id=1) up to entry_id 50
- Read entries from tape_2 (id=2) up to entry_id 10
- Read all entries from tape_3 (id=3, the leaf)

## Garbage Collection Consideration

With metadata-only forks, parent entries cannot be deleted while any child references them. A reference counting or lineage tracking mechanism would be needed for GC.

For now, entries are kept indefinitely (true append-only). If storage becomes a concern, a background sweep can:
1. Identify root tapes with no active forks referencing them
2. Archive or delete their unreferenced entries

## Comparison with Current ForkTapeStore

| Aspect | Current (bub) | New (bub_sf) |
|--------|---------------|--------------|
| Fork cost | Instant (contextvar) | Instant (metadata) |
| Fork scope | Temporary (context manager) | Persistent |
| Merge back | Automatic on context exit | Explicit (not needed) |
| Storage sharing | In-memory buffer | SQL-level metadata |
| Nested forks | Not supported | Full tree support |
| Read performance | O(N) merge | O(N) union query |
| Entry IDs | Per-session | Global monotonic in merged view |
