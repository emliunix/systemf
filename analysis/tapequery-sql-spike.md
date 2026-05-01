# TapeQuery Support Analysis

Analysis of how republic's `TapeQuery` parameters map to SQL execution in `SQLiteForkTapeStore`, and what remains to be implemented.

## Query Parameters

### 1. `kinds` — Filter by entry kind

**Current:** ✅ Implemented in SQL for both root and forked tapes.

**Implementation:**
- Root: `WHERE kind IN (?)` on `tape_entries`
- Forked: `AND e.kind IN (?)` in CTE query

**Optimization opportunity:** Already optimal — uses SQL filtering.

---

### 2. `limit` — Limit result count

**Current:** ⚠️ Applied in Python (`entries[:limit]`)

**Implementation:**
- Fetches all matching entries from SQL, then slices in Python.

**Optimization opportunity:** Push `LIMIT ?` into SQL queries.

**Why it matters:** For tapes with 10k+ entries, this avoids materializing rows we discard.

**SQL approach:**
- Root: `SELECT ... ORDER BY entry_id LIMIT ?`
- Forked: Add `LIMIT ?` to the outer CTE query.
- ⚠️ Note: For forked tapes, `LIMIT` must be applied after the merged view is assembled (after `ORDER BY ta.depth DESC, e.entry_id ASC`). SQLite handles this correctly when `LIMIT` is placed after `ORDER BY`.

**Priority:** Medium. Current Python slice is O(limit) not O(N), but wastes I/O.

---

### 3. `after_anchor` — Entries after named anchor

**Current:** ✅ Implemented in SQL for both root and forked tapes.

**Implementation:**
- Root: `SELECT entry_id FROM anchors WHERE anchor_name = ?`, then `WHERE entry_id > ?`
- Forked: CTE resolves anchor depth, filters merged view

**See:** `core.md` for full CTE query specification.

**Optimization opportunity:** None — already O(log N) indexed lookup.

---

### 4. `after_last` — Entries after the most recent anchor

**Current:** ❌ NOT IMPLEMENTED — silently returns all entries.

**Semantics:** Find the last anchor in the tape (highest entry_id), return all entries after it.

**SQL approach (root tapes):**
```sql
-- Step 1: Find the last anchor
SELECT entry_id FROM anchors
WHERE tape_id = ?
ORDER BY entry_id DESC
LIMIT 1;

-- Step 2: If found, filter entries after it
SELECT entry_id, kind, payload, meta, date
FROM tape_entries
WHERE tape_id = ? AND entry_id > ?
ORDER BY entry_id;
```

**SQL approach (forked tapes):**
Similar to `after_anchor` but the anchor resolution CTE needs to find the *last* anchor in the merged view, not a named one.

Option A — CTE-based (complex):
- Extend `anchor_info` CTE to find the highest `entry_id` across all ancestors, then filter.

Option B — Read merged view, scan backwards (simpler but O(N)):
- Fetch merged entries in reverse order, find first anchor, then return subsequent entries.

Option C — Two-pass SQL:
1. Build merged view CTE as normal
2. Find the anchor with the highest `entry_id` in the merged view
3. Filter entries after it

**Recommendation:** Start with Option B (Python scan) since `after_last` is typically called on recently-active tapes where the last anchor is near the end. For tapes with 10k entries, scanning backwards from the end is ~O(100) on average, not O(10k).

**Priority:** High — `TapeContext` defaults to `LAST_ANCHOR`, so this is the most common query path.

---

### 5. `between_anchors` — Entries between two named anchors

**Current:** ❌ NOT IMPLEMENTED — silently returns all entries.

**Semantics:** Given start anchor `A` and end anchor `B`, return entries after `A` and before `B` (exclusive of both anchors).

**Example:**
```
Entries: [msg0, anchor(A), msg1, msg2, anchor(B), msg3]
Result:  [msg1, msg2]
```

**SQL approach (root tapes):**
```sql
-- Step 1: Resolve both anchors
SELECT entry_id FROM anchors WHERE tape_id = ? AND anchor_name = ?;  -- A
SELECT entry_id FROM anchors WHERE tape_id = ? AND anchor_name = ?;  -- B

-- Step 2: Filter between
SELECT entry_id, kind, payload, meta, date
FROM tape_entries
WHERE tape_id = ? AND entry_id > ? AND entry_id < ?
ORDER BY entry_id;
```

**SQL approach (forked tapes):**
Complex. Anchors may live in different ancestor tapes. Need to:
1. Resolve both anchors in the merged view (find their depths and entry_ids)
2. Compute the inclusive range in merged view coordinates
3. Filter the CTE results

**Algorithm for forked tapes:**
```
1. Resolve anchor A → (depth_A, entry_id_A)
2. Resolve anchor B → (depth_B, entry_id_B)
3. For each ancestor tape in merged view:
   - If depth > depth_A: include all visible entries
   - If depth == depth_A: include entries with entry_id > entry_id_A
   - If depth < depth_A and depth > depth_B: include all visible entries
   - If depth == depth_B: include entries with entry_id < entry_id_B
   - If depth < depth_B: exclude
```

This is a significant CTE extension. Consider deferring to Python filtering for forked tapes.

**Priority:** Medium — used by `build_messages_between_anchors` but less common than `after_anchor`.

---

### 6. `between_dates` — Date range filter

**Current:** ❌ NOT IMPLEMENTED — silently returns all entries.

**Semantics:** Return entries whose `date` field falls within `[start, end]` (inclusive).

**SQL approach:**
```sql
SELECT entry_id, kind, payload, meta, date
FROM tape_entries
WHERE tape_id = ?
  AND date >= ? AND date <= ?
ORDER BY entry_id;
```

**Requirements:**
- Need index on `date` column: `CREATE INDEX idx_entries_date ON tape_entries(tape_id, date)`
- `date` is ISO 8601 string — lexicographic comparison works correctly for ISO timestamps

**For forked tapes:**
Apply `date` filter in the CTE WHERE clause:
```sql
AND e.date >= ? AND e.date <= ?
```

**Priority:** Low — not heavily used in current codebase.

---

### 7. `query` — Text search across all fields

**Current:** ❌ NOT IMPLEMENTED — silently returns all entries.

**Semantics:** Case-insensitive substring search across `kind`, `date`, `payload` (JSON), and `meta` (JSON).

**InMemoryQueryMixin implementation:**
```python
haystack = json.dumps({"kind": entry.kind, "date": entry.date, "payload": entry.payload, "meta": entry.meta}).casefold()
needle = query.casefold()
return needle in haystack
```

**SQL approaches:**

**Option A — SQLite LIKE (simple but slow):**
```sql
SELECT entry_id, kind, payload, meta, date
FROM tape_entries
WHERE tape_id = ?
  AND (kind LIKE '%?%' 
       OR payload LIKE '%?%'
       OR meta LIKE '%?%'
       OR date LIKE '%?%')
ORDER BY entry_id;
```
- O(N) scan per query
- No index benefit
- Works for small tapes

**Option B — SQLite FTS5 (fast but requires new virtual table):**
```sql
-- Create FTS5 virtual table
CREATE VIRTUAL TABLE tape_entries_fts USING fts5(
    tape_id,
    entry_id,
    kind,
    payload,
    meta,
    date,
    content='tape_entries'
);

-- Query
SELECT e.* FROM tape_entries e
JOIN tape_entries_fts f ON e.tape_id = f.tape_id AND e.entry_id = f.entry_id
WHERE f.tape_entries_fts MATCH ?;
```
- Requires maintaining FTS index (INSERT triggers or manual sync)
- Adds complexity
- Best for large tapes with frequent text search

**Option C — Hybrid (recommended):**
- For small tapes (< 1000 entries): Python-level filtering (fetch all, filter)
- For large tapes: LIKE query (still O(N) but avoids Python overhead)
- FTS5 only if text search becomes a hot path

**Priority:** Low — `query()` method is not called in current chat paths. Used mainly for debugging/inspection.

---

## Implementation Roadmap

| Parameter | Priority | Complexity | Approach |
|-----------|----------|------------|----------|
| `after_last` | **High** | Medium | SQL for roots; Python scan for forks (iterate backwards) |
| `between_anchors` | Medium | High | SQL for roots; CTE extension or Python for forks |
| `limit` | Medium | Low | Add `LIMIT ?` to all SQL queries |
| `between_dates` | Low | Low | Add `date` index, filter in SQL |
| `query` | Low | Medium | Python-level or LIKE; defer FTS5 |

---

## Schema Additions Needed

### Index for date filtering
```sql
CREATE INDEX IF NOT EXISTS idx_entries_date ON tape_entries(tape_id, date);
```

### FTS5 (optional, for query parameter)
```sql
-- Only if text search becomes critical
CREATE VIRTUAL TABLE IF NOT EXISTS tape_entries_fts USING fts5(
    kind, payload, meta, date,
    content='tape_entries',
    content_rowid='id'
);
-- Triggers to keep FTS in sync
CREATE TRIGGER ...
```

---

## Interaction Matrix

Multiple query parameters can be combined. The order of operations matters:

```
1. Anchor resolution (after_anchor, after_last, between_anchors)
   → Determines the entry range
2. Date filtering (between_dates)
   → Subset of the range
3. Kind filtering (kinds)
   → Further subset
4. Text search (query)
   → Further subset
5. Limit
   → Final truncation
```

**Correct composition:**
```sql
-- Example: after_anchor + kinds + limit
WITH RECURSIVE ...
SELECT ...
WHERE ...
  AND kind IN (?)
  AND date >= ? AND date <= ?
ORDER BY entry_id
LIMIT ?;
```

**For forked tapes:** All filters should be applied inside the CTE or on the merged result, not on individual ancestor tapes (which would incorrectly filter before merge).

---

## Performance Implications

| Query | Root Tape | Forked Tape (3-level) |
|-------|-----------|----------------------|
| `kinds` | O(log N + M) with index | O(N + M) — CTE scan |
| `limit` | O(log N + limit) if pushed | O(N + limit) |
| `after_anchor` | O(log N + M) ✅ | O(depth × log N + M) ✅ |
| `after_last` | O(log N + M) (with index) | O(N) scan backwards |
| `between_anchors` | O(2×log N + M) | O(N) |
| `between_dates` | O(log N + M) with index | O(N) |
| `query` | O(N) LIKE or Python | O(N) |

**N** = total entries, **M** = result count, **depth** = fork chain length.

---

## Compatibility Note

Current `bub_sf.store.TapeQuery` has a different shape from `republic.tape.query.TapeQuery`:

| Parameter | bub_sf TapeQuery | republic TapeQuery |
|-----------|------------------|-------------------|
| Tape name | `tape_name: str` | `tape: str` |
| Kinds | `kinds: tuple[str, ...]` | `_kinds: tuple[str, ...]` (private) |
| Limit | `limit: int \| None` | `_limit: int \| None` (private) |
| After anchor | `after_anchor: str \| None` | `_after_anchor: str \| None` (private) |
| After last | ❌ Missing | `_after_last: bool` |
| Between anchors | ❌ Missing | `_between_anchors: tuple[str, str] \| None` |
| Between dates | ❌ Missing | `_between_dates: tuple[str, str] \| None` |
| Text query | ❌ Missing | `_query: str \| None` |

**To be a drop-in replacement for republic's store, `bub_sf` must either:**
1. Accept `republic.tape.query.TapeQuery` directly (duck typing on private fields)
2. Extend `bub_sf.store.TapeQuery` with the missing parameters
3. Provide an adapter layer

## Protocol Compatibility with Republic/Bub

Republic defines two protocols: `TapeStore` (sync) and `AsyncTapeStore` (async). Bub uses both — hooks provide `TapeStore`, and the agent wraps it in `ForkTapeStore` which always exposes an async interface.

### Current Architecture

```
republic.TapeStore (sync protocol)
  └── bub_sf.SQLiteForkTapeStore (implements sync interface + fork/snapshot)
        └── bub_sf.AsyncTapeStoreAdapter (wraps sync → async)
              └── bub.ForkTapeStore (runtime fork layer)
                    └── bub.Agent (async consumer)
```

### Incompatibilities

| Aspect | republic/bub expects | bub_sf provides | Issue |
|--------|---------------------|-----------------|-------|
| **Query tape field** | `query.tape: str` | `query.tape_name: str` | **CRITICAL**: bub's `ForkTapeStore.fetch_all()` accesses `query.tape` directly |
| **append return** | `None` | `int` (entry_id) | Minor: bub ignores return value |
| **fetch_all return** | `Iterable[TapeEntry]` | `list[TapeEntry]` | Minor: `list` is `Iterable` |
| **Query: after_last** | `query._after_last: bool` | ❌ Missing | **HIGH**: default query path in `TapeContext` |
| **Query: between_anchors** | `query._between_anchors: tuple[str, str] \| None` | ❌ Missing | Medium |
| **Query: between_dates** | `query._between_dates: tuple[str, str] \| None` | ❌ Missing | Low |
| **Query: text search** | `query._query: str \| None` | ❌ Missing | Low |

### Critical Issue: `query.tape` vs `query.tape_name`

Bub's `ForkTapeStore.fetch_all()` (line 62):
```python
if query.tape == self._fork_tape and self._current_was_reset:
    ...
```

This will raise `AttributeError` on bub_sf's `TapeQuery` which has `tape_name` instead of `tape`.

### Recommended Fix

**Option A**: Rename `tape_name` → `tape` in `bub_sf.store.TapeQuery` to match republic's convention.

**Option B**: Provide a compatibility shim that maps field names.

**Strongly recommend Option A** — the `tape_name` naming is arbitrary and matching the ecosystem convention avoids surprises.

### `append` Return Type

Republic's protocol: `def append(self, tape: str, entry: TapeEntry) -> None`
Bub_sf's implementation: `def append(...) -> int`

Bub ignores the return value, so this is not a runtime issue. But for strict protocol conformance, we should either:
- Change return type to `None` and drop the entry_id return
- Or accept the deviation (pragmatic: entry_id is useful for callers)

### Missing Query Parameters

Bub's `ForkTapeStore.fetch_all()` accesses these private fields:
- `query._after_last` — **most critical**, used by default `TapeContext(anchor=LAST_ANCHOR)`
- `query._between_anchors` — used by `build_messages_between_anchors`
- `query._between_dates` — date range filtering
- `query._query` — text search
- `query._kinds` — kind filtering (already supported via public `kinds`)
- `query._limit` — result limit (already supported via public `limit`)
- `query._after_anchor` — anchor filtering (already supported via public `after_anchor`)

**Fix**: Extend `TapeQuery` to include all missing fields, matching republic's dataclass exactly. The store's `fetch_all()` can then check all fields and delegate appropriately.

### Async Adapter

`AsyncTapeStoreAdapter` already provides the async interface correctly. However, it doesn't implement the `AsyncTapeStore` protocol explicitly (no `typing.Protocol` inheritance). Since Python protocols use structural typing, this is fine at runtime but may cause type checker warnings.

### Protocol Checklist

To be a full drop-in replacement for republic's store:

- [x] `list_tapes() -> list[str]`
- [x] `reset(tape: str) -> None`
- [x] `fetch_all(query: TapeQuery) -> list[TapeEntry]` (returns `list`, compatible with `Iterable`)
- [x] `append(tape: str, entry: TapeEntry) -> int` (deviation: returns `int` instead of `None`)
- [ ] `query.tape` field (currently `query.tape_name`)
- [ ] `query._after_last` field
- [ ] `query._between_anchors` field
- [ ] `query._between_dates` field
- [ ] `query._query` field
- [x] `AsyncTapeStoreAdapter` provides async wrapper

**Strongly recommend:**
1. Rename `TapeQuery.tape_name` → `TapeQuery.tape`
2. Add all missing query parameters to `TapeQuery`
3. Implement `after_last` support (default query path)
4. Consider making `append` return `None` for strict protocol conformance
