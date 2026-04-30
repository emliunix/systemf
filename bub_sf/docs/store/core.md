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
    next_entry_id INTEGER DEFAULT 0 -- Next entry ID assigned to new entry in the tape
);
```

Fields:
- `id`: Internal surrogate key
- `name`: Human-readable unique tape identifier
- `parent_id`: NULL for root tapes; references parent tape for forks
- `parent_entry_id`: The last entry ID inherited from parent. Forked tape's own entries start from `parent_entry_id + 1`.
- `parents_cache`: Pre-computed JSON array of all ancestor fork points, eagerly maintained to avoid CTE recursion on hot paths. Format: `[[ancestor_id, fork_entry_id], ...]` ordered from root to immediate parent.
- `next_entry_id`: Next entry ID to allocate. Starts at 0 for root tapes. After fork, starts at `parent_entry_id + 1`.

### tape_entries Table

Actual append-only entries. Entry IDs are scoped per tape.

```sql
CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,      -- Sequential within this tape
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON (maps to republic TapeEntry.payload)
    meta TEXT NOT NULL DEFAULT '{}',-- JSON (maps to republic TapeEntry.meta)
    date TEXT NOT NULL              -- ISO timestamp (maps to republic TapeEntry.date)
);

CREATE INDEX idx_entries_tape_entry ON tape_entries(tape_id, entry_id);
```

**Notes:**
- The `UNIQUE(tape_id, entry_id)` constraint is not yet enforced by the implementation (to be added).
- Field names match republic's `TapeEntry` model directly: `payload`, `meta`, `date`.
- There is no `anchor` column. Anchor metadata lives exclusively in the `anchors` table, populated when an entry with `kind="anchor"` is appended.

### anchors Table

**New in this design.** Extracted anchor metadata for O(log N) anchor resolution.

```sql
CREATE TABLE anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,      -- Matches tape_entries.entry_id
    anchor_name TEXT NOT NULL,
    UNIQUE(tape_id, anchor_name),   -- No duplicate names within a tape
    UNIQUE(tape_id, entry_id)       -- One anchor per entry max
);

CREATE INDEX idx_anchors_lookup ON anchors(tape_id, anchor_name);
CREATE INDEX idx_anchors_entry ON anchors(tape_id, entry_id);
```

**Rationale:** The `anchors` table separates anchor metadata from entry content, enabling indexed lookups for the most common query pattern (`after_anchor`). Without this table, `after_anchor` queries require O(N) linear scan in Python.

**Key design decisions:**
- **Populated from `kind="anchor"` entries**: When `append` receives an entry with `kind="anchor"`, it extracts `payload["name"]` and writes a row to `anchors`. No separate anchor field on `tape_entries` is needed.
- **Foreign key to tapes, not tape_entries**: Anchors reference `tapes(id)` because the natural query key is `(tape_id, anchor_name)`. A foreign key to `tape_entries` would require a composite key or surrogate `id` lookup, adding indirection without benefit.
- **UNIQUE(tape_id, anchor_name)**: Prevents duplicate anchor names within a tape. Attempting to append a second anchor entry with the same name fails with an integrity error.
- **UNIQUE(tape_id, entry_id)**: Enforces one anchor per entry, consistent with anchors being a distinct entry kind.
- **No anchor copying on fork**: Forked tapes do NOT copy parent anchors into their own `anchors` table. Anchor resolution walks the ancestor chain via CTE (see [Query: after_anchor for Forked Tapes](#query-after_anchor-for-forked-tapes)). This avoids write amplification and keeps fork O(1).
- **Anchor shadowing**: If a child tape defines an anchor with the same name as a parent anchor, the child's anchor takes precedence during resolution. The CTE resolves leaf-first (depth ascending), so the closest definition wins.

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

## Invariants

These invariants must hold at all times. Each operation is responsible for maintaining them.

### I1 — next_entry_id equals own physical entry count

For every tape T:

```
T.next_entry_id = |{ e in tape_entries | e.tape_id = T.id }|
```

- Root tapes start at 0.
- A fresh fork starts at `parent_entry_id + 1` (zero own entries initially).
- `append` is the only operation that increments it; `reset` sets it back to 0.

### I2 — Own entry_ids form a contiguous range

For tape T with `next_entry_id = K`:

- Root tape: own `entry_id` values are exactly `{0, 1, …, K-1}`.
- Fork tape with `parent_entry_id = N`: own `entry_id` values are exactly `{N+1, N+2, …, N+K-1}` where K counts own rows.

Consequence: the merged view `[0..N]` (from parent) + `[N+1..]` (own) is always gap-free.

### I3 — Fork entry_id ranges do not overlap with the inherited range

For fork tape F with `parent_entry_id = N`:

- The merged view of F uses the parent's entries **only up to and including** `entry_id = N`.
- F's own physical entries start at `N+1`.
- Even if the parent tape later appends entries with `entry_id > N`, those are invisible in F's merged view.

This is enforced by the CTE query's `e.entry_id <= ta.parent_entry_id` filter on ancestor rows.

### I4 — parents_cache is the complete, ordered ancestor chain

For any tape C with immediate parent P:

```
C.parents_cache = P.parents_cache + [[P.id, C.parent_entry_id]]
```

Root tapes have `parents_cache = NULL` (equivalent to `[]`).

This is a denormalized mirror of the recursive `parent_id` chain. It must be computed and stored atomically at fork time. It is never modified after creation.

### I5 — anchors table is consistent with kind="anchor" entries

For every tape T, the `anchors` table must be kept in sync with `tape_entries` rows of `kind="anchor"`:

- **Forward**: every row in `anchors` with `tape_id = T.id` has a corresponding `tape_entries` row with the same `(tape_id, entry_id)` and `kind = "anchor"` and `payload["name"] = anchor_name`.
- **Reverse**: every `tape_entries` row with `tape_id = T.id` and `kind = "anchor"` has a corresponding row in `anchors` with `anchor_name = payload["name"]`.

Operations responsible:
- `append` with `entry.kind == "anchor"`: dual-write — INSERT into `tape_entries` and INSERT into `anchors` with `anchor_name = entry.payload["name"]`, atomically in one transaction.
- `reset`: must delete from both `tape_entries` and `anchors`.
- `snapshot`: must copy `tape_entries` rows (full merged view) and their corresponding `anchors` rows.
- `fork`: no anchor copy needed — parent anchors remain accessible via CTE traversal.

### I6 — Anchor names are unique within a tape's own rows

`(tape_id, anchor_name)` is UNIQUE in `anchors`. A tape may use the same anchor name as an ancestor (shadowing), but within one tape's own physical rows a name appears at most once. Enforced by the UNIQUE constraint; `append` raises an integrity error on violation.

### Operation × Invariant responsibility

| Operation | I1 | I2 | I3 | I4 | I5 | I6 |
|-----------|----|----|----|----|----|----|
| `append` | +1 to `next_entry_id` | extends range by 1 | unaffected | unaffected | dual-write if kind="anchor" | UNIQUE constraint |
| `fork` | sets child initial value | sets child start to N+1 | enforced by fork_point choice | must compute & store chain | no copy needed | unaffected |
| `snapshot` | copies from merged view | physical copy, contiguous from 0 | n/a (new root) | sets to NULL | must copy full anchor set | inherits uniqueness |
| `reset` | sets to 0 | deletes all own rows | unaffected | unaffected | must delete anchor rows | unaffected |

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

## Query: after_anchor for Root Tapes

**New in this design.** For root tapes, `after_anchor` resolves in O(log N) via the `anchors` table index.

```sql
-- Step 1: Resolve anchor to entry_id (O(log N) via idx_anchors_lookup)
SELECT entry_id 
FROM anchors 
WHERE tape_id = ? AND anchor_name = ?;

-- Step 2: Fetch entries after that point (O(M) where M = result size)
SELECT entry_id, kind, payload, meta, date
FROM tape_entries
WHERE tape_id = ? AND entry_id > ?
ORDER BY entry_id;
```

**Performance:** O(log N + M) vs O(N) previously. The index lookup replaces the linear scan.

## Query: after_anchor for Forked Tapes

**New in this design.** For forked tapes, anchor resolution walks the ancestor chain via CTE, then filters the merged view.

```sql
WITH RECURSIVE 
-- Build ancestor chain from leaf to root
tape_ancestors(tape_id, parent_id, parent_entry_id, depth) AS (
    SELECT id, parent_id, parent_entry_id, 0
    FROM tapes
    WHERE name = ?
    
    UNION ALL
    
    SELECT t.id, t.parent_id, t.parent_entry_id, a.depth + 1
    FROM tapes t
    INNER JOIN tape_ancestors a ON t.id = a.parent_id
    WHERE a.parent_id IS NOT NULL
),
-- Resolve anchor: find leaf-most occurrence (child shadows parent)
anchor_info(tape_id, entry_id, anchor_depth) AS (
    SELECT a.tape_id, a.entry_id, ta.depth
    FROM anchors a
    INNER JOIN tape_ancestors ta ON a.tape_id = ta.tape_id
    WHERE a.anchor_name = ?
    ORDER BY ta.depth ASC          -- Leaf-first resolution
    LIMIT 1
)
SELECT 
    ROW_NUMBER() OVER (ORDER BY ta.depth DESC, e.entry_id ASC) - 1 as entry_id,
    e.kind, e.payload, e.meta, e.date
FROM tape_ancestors ta
LEFT JOIN tape_entries e ON e.tape_id = ta.tape_id
CROSS JOIN anchor_info ai
WHERE 
    -- Normal visibility constraints (same as merged view)
    (ta.depth = 0 OR e.entry_id <= ta.parent_entry_id)
    AND
    -- Anchor-based filtering:
    -- Descendants (after anchor in merged view): include all visible entries
    (ta.depth < ai.anchor_depth
     -- Anchor tape itself: only entries after the anchor point
     OR (ta.depth = ai.anchor_depth AND e.entry_id > ai.entry_id))
    -- Older ancestors (before anchor in merged view): implicitly excluded
ORDER BY ta.depth DESC, e.entry_id ASC;
```

**Semantics:**
- The merged view orders entries by `depth DESC` (root first, leaf last).
- An anchor in an ancestor tape at entry_id `X` means all entries from that tape with entry_id ≤ `X` come before the anchor in the merged view and are excluded.
- All entries from descendant tapes come after the anchor in the merged view and are included.
- If the anchor is in the leaf tape, only leaf entries after the anchor are returned.

**Example:**
```
Root tape:      [R0, R1(anchor="a1"), R2]
Fork at R2 → Intermediate: [I3, I4]
Fork at I4 → Leaf: [L5, L6]

Merged view: [R0, R1, R2, I3, I4, L5, L6]

Query after_anchor="a1" on leaf:
- Anchor resolved to root at entry_id=1, depth=2
- Root (depth=2 = anchor_depth): include entry_id > 1 → [R2]
- Intermediate (depth=1 < 2): include all → [I3, I4]
- Leaf (depth=0 < 2): include all → [L5, L6]
- Result: [R2, I3, I4, L5, L6]
```

**Performance:** O(depth × log N + M) where `depth` = fork chain length, `N` = entries per tape, `M` = result size. The CTE recursion is O(depth) and the anchor lookup is O(log N) per tape in the chain due to the index.

## Query: Read Merged Tape (Cached Version)

> **Status:** Not yet implemented. The `parents_cache` column is eagerly maintained on fork, but all reads currently use the CTE recursive query above.
>
> This is acceptable because CTE performance is sufficient (see benchmarks: ~4.5ms for 1700 entries across 3 levels). The cached read path is planned for future optimization if needed.

For frequently-read tapes, a pre-computed `parents_cache` can avoid recursion:

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

This version would be O(1) complexity for the metadata lookup and O(N) for the entry scan, where N is the total visible entries.

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

**Anchor behavior on fork:**
- No anchors are copied from parent to child.
- The child's `anchors` table is empty initially.
- Anchor resolution on the child walks the ancestor chain via CTE, so parent anchors remain resolvable.
- This keeps fork O(1) — no additional INSERTs into `anchors`.

**Time complexity:** O(1) — single INSERT, no data copying
**Space complexity:** O(1) — metadata only

### snapshot(source_name: str, target_name: str) → None

Create an independent physical copy of the source tape. The new tape has no parent.

**Algorithm:**
1. Create new root tape (`parent_id = NULL`)
2. Copy all entries from source tape into new tape, preserving entry_ids
3. Set `next_entry_id` on new tape to match source
4. **Copy all anchors** from source to new tape (preserve `anchor_name` → `entry_id` mapping)

**Time complexity:** O(N) where N = number of entries
**Space complexity:** O(N)

### append(tape_name: str, entry: TapeEntry) → int

Append a new entry to a tape. Returns the assigned `entry_id`.

**Algorithm:**
1. Look up tape by name (create if it doesn't exist)
2. Use `tape.next_entry_id` as the entry ID (the `id` field of the passed `TapeEntry` is ignored)
3. Insert entry into `tape_entries` with auto-assigned `entry_id`
4. **If `entry.kind == "anchor"`:**
   - Extract `anchor_name = entry.payload["name"]`
   - Insert into `anchors` table: `(tape_id, entry_id, anchor_name)`
   - This is a dual write within the same transaction
5. Increment `tape.next_entry_id`

**Invariant:** If `entry.kind == "anchor"`, the `(tape_id, anchor_name)` pair must be unique. Duplicate anchor names within the same tape raise an integrity error.

**Returns:** The assigned `entry_id` (sequential integer starting from 0 for root tapes).

**Invariant:** `entry_id` is always sequential and gap-free within the tape's own entries.

### fetch_all(query: TapeQuery) → list[TapeEntry]

Read entries from a tape, applying filters from the TapeQuery.

**Algorithm:**
1. Resolve tape by name
2. If root tape: query `tape_entries` directly
3. If fork: use CTE recursive query for merged view
4. Apply additional filters (kinds, limit, after_anchor) from TapeQuery
5. **If `after_anchor` is specified:**
   - For root tapes: resolve via `anchors` table index (O(log N)), then filter
   - For forked tapes: use the CTE-based anchor resolution query (see above)
   - If anchor not found: return empty list

### read(tape_name: str) → list[TapeEntry] | None

Convenience method: return all entries for a tape (merged view).

Equivalent to `fetch_all(TapeQuery(tape_name=tape_name))`.

### reset(tape_name: str) → None

Clear all entries from a tape and reset its state.

**Algorithm:**
1. Delete all entries from `tape_entries` where `tape_id = ?`
2. **Delete all anchors from `anchors` where `tape_id = ?`**
3. Reset `next_entry_id` to 0

**Note:** Reset only affects the target tape. Parent entries shared via fork are not modified (they belong to the parent tape).

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

## Implementation Design Changes

### ROW_NUMBER() Approach

The merged view uses SQLite's `ROW_NUMBER()` window function to generate continuous entry IDs at query time:

```sql
SELECT 
    ROW_NUMBER() OVER (ORDER BY e.depth DESC, e.entry_id ASC) - 1 as entry_id,
    e.kind, e.payload, e.meta, e.date
```

This approach:
- Avoids storing merged view IDs in the database
- Handles any depth of nesting transparently
- Works with both CTE and cached query paths
- Is O(N) where N = visible entries

### Connection Thread Safety

The SQLite connection is opened with `check_same_thread=False` to support the async adapter, which delegates operations to worker threads via `asyncio.to_thread()`. A `threading.Lock` in the async adapter serializes access to ensure SQLite thread safety.

## Performance Characteristics

Benchmarked on typical development hardware:

| Operation | Threshold | Typical |
|-----------|-----------|---------|
| Fork (1000 entries) | < 10ms | ~0.03ms |
| Read merged (3-level, 1700 entries) | < 50ms | ~4.5ms |
| Append throughput (100 entries) | < 100ms | ~3ms |
| Large tape read (10000 entries) | < 100ms | ~22ms |
| **after_anchor root (10000 entries)** | **< 5ms** | **~0.5ms** |
| **after_anchor forked (3-level, 1700 entries)** | **< 10ms** | **~2ms** |

**Fork** is O(1) — a single INSERT into the `tapes` table. Time is independent of tape size.

**Read merged** is O(N) where N = visible entries. Linear scaling observed: ~2 microseconds per entry.

**Append** is O(1) per entry — INSERT into `tape_entries` plus UPDATE `next_entry_id`.

**Snapshot** is O(N) — copies all entries from source to target.

**after_anchor (root)** is O(log N) — indexed lookup in `anchors` table plus O(M) result fetch. Previously O(N) linear scan.

**after_anchor (forked)** is O(depth × log N + M) — CTE recursion over ancestor chain with indexed anchor lookups at each level. Previously O(N) linear scan of full merged view.

## Async Adapter

For async contexts, use `AsyncTapeStoreAdapter`:

```python
from pathlib import Path
from bub_sf.store import AsyncTapeStoreAdapter, TapeEntry

store = AsyncTapeStoreAdapter(Path("/tmp/tape.db"))

# All methods are async
await store.append("main", TapeEntry(...))
entries = await store.read("main")
await store.fork("main", "main-v2")
```

The adapter wraps the sync store with `asyncio.to_thread()` and uses a `threading.Lock` to serialize concurrent access.

## Usage Examples

### Basic tape operations

```python
from bub_sf.store import ForkTapeStore, TapeEntry
from pathlib import Path

store = ForkTapeStore(Path("app.db"))

# Append entries — entry_id is auto-assigned
entry_id = store.append("chat", TapeEntry(
    kind="message",
    payload={"role": "user", "content": "hello"},
    date="2024-01-01T00:00:00",
))
assert entry_id == 0  # First entry in a new tape

# Read all entries
entries = store.read("chat")

# List tapes
names = store.list_tapes()

# Reset (clear) a tape
store.reset("chat")
```

### Forking a tape

```python
# Create a parent tape
for i in range(5):
    store.append("parent", TapeEntry(
        kind="message",
        payload={"index": i},
        date="2024-01-01T00:00:00",
    ))

# Fork at current tip
store.fork("parent", "child")

# Child sees all parent entries
assert len(store.read("child")) == 5

# Child appends independently — IDs continue from fork point
entry_id = store.append("child", TapeEntry(
    kind="message",
    payload={"index": 5},
    date="2024-01-01T00:00:00",
))
assert entry_id == 5  # Auto-assigned, continues from fork point

# Parent is unchanged
assert len(store.read("parent")) == 5
```

### Query with filters

```python
from bub_sf.store import TapeQuery

# Fetch only "message" entries after anchor "a1"
# anchor "a1" was appended as TapeEntry(kind="anchor", payload={"name": "a1"}, ...)
result = store.fetch_all(TapeQuery(
    tape_name="chat",
    kinds=("message",),
    after_anchor="a1",
    limit=10,
))
```

### Snapshot (deep copy)

```python
# Create an independent copy
store.snapshot("parent", "backup")

# Modifying parent does not affect backup
store.append("parent", TapeEntry(...))
assert len(store.read("backup")) == len(store.read("parent")) - 1
```

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
| Async support | Not supported | AsyncTapeStoreAdapter |
| **Anchor resolution** | **O(N) scan** | **O(log N) index** |
