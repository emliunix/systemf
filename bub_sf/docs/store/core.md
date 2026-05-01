# ForkTapeStore Core Design

## Goal

SQLite-backed append-only tape store implementing `AsyncTapeStore` protocol from `republic`.

Key properties: instant fork (O(1) metadata), shared history via copy-on-write, gap-free merged entry IDs across fork chains.

## Principles

**Immutable entries.** Tape entries are never deleted or modified. Only `append` writes to `tape_entries`.

**Core-Interface split.** Core operations (`create`, `append`, `fork`) are the only code that writes to the database. Interface operations (`read`, `fetch_all`, `list_tapes`) are read-only. Core maintains invariants; interface consumes them.

**Persistent forks.** Forks are database records, not runtime context. They survive process restarts and can be nested to arbitrary depth.

## Source Reference

| Type | Path |
|------|------|
| `TapeEntry` | `republic/src/republic/tape/entries.py` |
| `TapeQuery` | `republic/src/republic/tape/query.py` |

`ForkTapeStore` accepts `TapeEntry` instances with fields: `entry_id`, `kind`, `payload`, `meta`, `date`. The `entry_id` passed to `append` is ignored; the store assigns sequential IDs. (The entry object is not mutated to signal new_id. The caller discards it anyway and fetches entries back via `read`/`fetch_all`.)

## Schema

### tapes

```sql
CREATE TABLE tapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES tapes(id),
    parent_entry_id INTEGER,        -- fork point: last shared entry in parent
    next_entry_id INTEGER DEFAULT 0 -- next assigned entry_id for this tape
);
```

`next_entry_id` starts at 0 for roots. After fork, starts at `parent_entry_id + 1`.

### tape_entries

```sql
CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON
    meta TEXT NOT NULL DEFAULT '{}',-- JSON
    date TEXT NOT NULL              -- ISO timestamp
);

CREATE INDEX idx_entries_tape_entry ON tape_entries(tape_id, entry_id);
```

`entry_id` is scoped to the tape (not a global sequence). Guaranteed contiguous by allocation logic.

### anchors

```sql
CREATE TABLE anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    anchor_name TEXT NOT NULL,
    UNIQUE(tape_id, anchor_name),   -- catches duplicates within same tape
    UNIQUE(tape_id, entry_id)
);

CREATE INDEX idx_anchors_lookup ON anchors(tape_id, anchor_name);
CREATE INDEX idx_anchors_entry ON anchors(tape_id, entry_id);
```

Curated key-field extraction for O(log N) anchor resolution. Populated from `kind="anchor"` entries during `append`. No anchor copying on fork — child resolves parent anchors via ancestor CTE.

`UNIQUE(tape_id, anchor_name)` catches same-tape duplicates, but the merged-view uniqueness (I5) requires a code check against ancestors.

### Views

Views encapsulate the recursive CTE logic, keeping queries in `fetch_all` and `read` declarative.

**Critical:** The CTE must propagate the immediate child's fork point at each level, not inherit from the leaf. A subquery looks up the child's `parent_entry_id` from the database at each recursion step.

```sql
-- Ancestor chain for every tape (root to leaf, depth ascending)
-- leaf_id: the tape you query (add WHERE leaf_id = ? condition)
-- tape_id: changes as we walk up ancestors (root, ..., parent, leaf)
-- fork_point: the entry where the child forked from this ancestor
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

-- Merged entries for every tape (includes inherited parent entries)
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

-- Merged anchors for every tape (includes inherited parent anchors)
CREATE VIEW merged_anchors AS
SELECT
    a.leaf_id AS leaf_tape_id,
    an.entry_id,
    an.anchor_name,
    a.depth
FROM tape_ancestors a
INNER JOIN anchors an ON an.tape_id = a.tape_id;
```

**Why views:** They separate the recursive traversal (core schema concern) from the filtering (interface concern). Queries become simple `SELECT ... WHERE leaf_tape_id = ?` without repeating CTEs.

**Performance note:** SQLite evaluates the recursive CTE in the view for all tapes, then filters by `leaf_tape_id`. For databases with many tapes, inline CTEs (scoped to one tape) may be faster. The view approach trades some performance for query simplicity. For typical workloads (hundreds of tapes, not millions), the difference is negligible.

**Correctness note:** The subquery `(SELECT parent_entry_id FROM tapes WHERE id = c.tape_id)` is critical for nested forks. Without it, the leaf's fork point propagates up the entire chain, causing root ancestors to show entries beyond their actual fork point.

## Invariants

### I1 — Sequential allocation

For every tape T:

- `T.next_entry_id` is the next assigned `entry_id`
- Own entries use IDs `{0, …, K-1}` for roots, `{N+1, …, N+K-1}` for forks (where `N = parent_entry_id`)
- Allocation: `new_id = T.next_entry_id`; then `T.next_entry_id += 1` in the same transaction
- `append` is the only operation that increments it

Consequence: merged view is always gap-free.

### I2 — Fork boundary

For fork tape F with `parent_entry_id = N`:

- F's merged view includes parent entries only up to `entry_id = N` (inclusive)
- F's own entries start at `N+1`
- Parent entries with `id > N` are invisible in F

Enforced by CTE filter `e.entry_id <= ta.fork_point` on ancestor rows.

### I3 — anchors table is consistent

Every `kind="anchor"` entry has a corresponding `anchors` row with matching `(tape_id, entry_id, anchor_name = payload["name"])`, and vice versa.

This is maintained by `append` (dual-write) and queried by `fetch_all` for `after_anchor` resolution.

### I4 — Anchor name uniqueness (merged view)

An anchor name may appear at most once in the entire merged view of any tape. This includes the tape's own anchors and all ancestor anchors visible through the fork chain.

**Why:** `after_anchor` queries resolve by name. If multiple anchors share a name in the merged view, the query is ambiguous.

**Enforcement:** Application code in `append`, not a DB constraint. Before inserting an anchor, query `merged_anchors` view for the name. If found in any ancestor, raise `ValueError`.

(Note: SQLite views cannot enforce uniqueness. The check must be in code.)

## Core Operations

Only these operations write to the database.

**NOTE:** Core operations do not commit transactions internally. The caller is responsible for transaction boundaries. This allows mixing multiple core operations (e.g., `append` + `fork`) in a single transaction for atomicity.

### create(name: str) → None

Create empty tape with `next_entry_id = 0`. No-op if tape exists.

### append(tape: str, entry: TapeEntry) → int

1. Get or create tape, read `next_entry_id`
2. If `entry.kind == "anchor"`:
   - Extract `anchor_name = entry.payload["name"]`
   - Query `merged_anchors` view for existing `anchor_name` (I4)
   - If found, raise `ValueError`
   - Insert into `anchors`
3. Insert entry into `tape_entries` with assigned `entry_id = next_entry_id`
4. Increment `next_entry_id`

Returns assigned `entry_id`.

(Caller must commit the transaction.)

### fork(source: str, entry_id: int, name: str) → None

Fork source tape at the given entry. The child tape shares all entries up to and including `entry_id`.

**Precondition:** `entry_id` must be a valid entry in the source tape (i.e., `entry_id < source.next_entry_id`).

1. Look up source tape
2. Validate: `entry_id < source.next_entry_id`
3. `fork_point = entry_id`
4. Insert new tape: `parent_id = source.id`, `parent_entry_id = fork_point`, `next_entry_id = fork_point + 1`

No data copying. No anchor copying. Fork is O(1).

## Interface Operations

Read-only. Never write to the database.

### read(tape: str) → list[TapeEntry] | None

Return all entries (merged view for forks). `None` if tape doesn't exist.

Using views:
```sql
SELECT entry_id, kind, payload, meta, date
FROM merged_entries
WHERE leaf_tape_id = ?
ORDER BY depth DESC, entry_id;
```

### fetch_all(query: TapeQuery) → list[TapeEntry]

Apply query filters on top of `read` or direct SQL.

Supported filters:
- `kinds` — filter by entry kind
- `limit` — truncate result
- `after_anchor` — entries after named anchor (O(log N) indexed)

Using views for `after_anchor` on forked tapes:
```sql
-- Resolve anchor (leaf-first)
SELECT entry_id, depth
FROM merged_anchors
WHERE leaf_tape_id = ? AND anchor_name = ?
ORDER BY depth ASC
LIMIT 1;

-- Fetch entries after anchor
SELECT entry_id, kind, payload, meta, date
FROM merged_entries
WHERE leaf_tape_id = ?
  AND (depth < ? OR (depth = ? AND entry_id > ?))
ORDER BY depth DESC, entry_id;
```

### list_tapes() → list[str]

Return sorted tape names.

## Implementation

### Thread Safety

SQLite connection opened with `check_same_thread=False`. `AsyncTapeStoreAdapter` serializes access via `threading.Lock`.

### Entry ID in Merged View

Original entry IDs are preserved. No `ROW_NUMBER()` renumbering — the contiguous allocation guarantee (I1) ensures merged views are gap-free.

### Async Adapter

```python
store = AsyncTapeStoreAdapter(Path("/tmp/tape.db"))
await store.append("main", TapeEntry(...))
entries = await store.read("main")
```

Wraps sync core with `asyncio.to_thread()`. Exposes `AsyncTapeStore` protocol.

## Performance

| Operation | Complexity | Typical |
|-----------|-----------|---------|
| create | O(1) | < 1ms |
| append | O(1) | ~0.03ms |
| fork | O(1) | ~0.03ms |
| read root | O(N) | ~2μs/entry |
| read merged (3-level) | O(N) | ~2μs/entry |
| after_anchor root | O(log N + M) | ~0.5ms |
| after_anchor forked | O(depth × log N + M) | ~2ms |

## Future Plans

### Garbage Collection

With metadata-only forks, parent entries cannot be deleted while any child references them. A reference counting or lineage tracking mechanism would be needed for GC.

For now, entries are kept indefinitely (true append-only). If storage becomes a concern, a background sweep can:
1. Identify root tapes with no active forks referencing them
2. Archive or delete their unreferenced entries
