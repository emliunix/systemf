# Change Plan: ForkTapeStore Core Cleanup

## Facts

### Current Implementation State

`bub_sf/src/bub_sf/store/fork_store.py` (530 lines) implements `SQLiteForkTapeStore` with these methods:

**Present but NOT in core2.md spec:**
- `reset(tape_name)` — deletes entries, breaks immutability principle
- `snapshot(source_name, target_name)` — physical copy, not needed per design
- `_read_merged()` — inline recursive CTE (duplicates schema view logic)
- `_fetch_root_after_anchor()` — root-specific anchor query
- `_fetch_forked_after_anchor()` — inline recursive CTE (duplicates schema view logic)
- `_get_next_entry_id()` — test helper only
- `_get_or_create_tape()` — append auto-creates; no explicit `create` operation

**Present and aligned with core2.md:**
- `append(tape_name, entry)` — works, returns int
- `fork(source_name, entry_id, target_name)` — works
- `read(tape_name)` — works but uses inline CTE instead of views
- `fetch_all(query)` — works but uses inline CTEs instead of views
- `list_tapes()` — works

**Missing from core2.md:**
- `create(name)` — core operation not implemented
- `rename(old_name, new_name)` — needed to implement reset immutably

### Call Site Inventory

```
reset:      tests/store/test_fork_tape_store.py:128,139,283
            tests/store/test_async_adapter.py:84,188
            src/bub_sf/store/async_adapter.py:74
            src/bub_sf/store/fork_store.py:448

snapshot:   tests/store/test_fork_tape_store.py:371,376,382,388,393,397,405,408
            tests/store/test_async_adapter.py:103,108,196
            src/bub_sf/store/async_adapter.py:95-106
            src/bub_sf/store/fork_store.py:497-530
            src/bub_sf/store/types.py:45-46

_get_next_entry_id:
            tests/store/test_fork_tape_store.py:61 (assert_next_entry_id helper)

ForkTapeStore class:
            tests/store/test_fork_tape_store.py:8,17
            tests/store/test_performance.py:20,71,95,125,144,160,197
            src/bub_sf/store/async_adapter.py:13,32
            src/bub_sf/store/fork_store.py:9,12
            src/bub_sf/store/types.py:36-65

TapeEntry/TapeQuery imports:
            tests/store/test_*.py (all test files)
            src/bub_sf/store/async_adapter.py
            src/bub_sf/store/fork_store.py
            src/bub_sf/store/types.py (defines them)
```

### Schema Views Already Defined

The schema already has three views that encapsulate the recursive CTE:
- `tape_ancestors` — ancestor chain with correct fork_point propagation
- `merged_entries` — all entries visible to each tape
- `merged_anchors` — all anchors visible to each tape

The inline CTEs in `_read_merged` and `_fetch_forked_after_anchor` duplicate this logic.

### Protocol Requirements

`republic/src/republic/tape/store.py` defines:
- `TapeStore(Protocol)` with `list_tapes`, `reset`, `fetch_all`, `append`
- `AsyncTapeStore(Protocol)` with async versions
- `reset(tape)` is a required protocol method

Our current `reset` mutates data (deletes entries), violating immutability.

### Type Differences (republic vs bub_sf)

| Field | republic.TapeEntry | bub_sf.TapeEntry |
|-------|-------------------|------------------|
| id field | `id` | `entry_id` |
| date default | `utc_now()` | `utc_now()` |

| Field | republic.TapeQuery | bub_sf.TapeQuery |
|-------|-------------------|------------------|
| tape name | `tape` | `tape_name` |
| kinds | `_kinds` (private) | `kinds` (public) |
| limit | `_limit` (private) | `limit` (public) |
| after_anchor | `_after_anchor` (private) | `after_anchor` (public) |
| builder pattern | Yes (`.kinds()`, `.limit()`, etc.) | No |

## Design

### 1. Remove `snapshot` Method

**Rationale:** Double-fork achieves the same effect. Snapshot is redundant.

**Migration:** Delete all snapshot tests. Remove `snapshot` from:
- `fork_store.py`
- `async_adapter.py`
- `types.py`
- Test files

### 2. Add `create(name)` Core Operation

**Signature:** `def create(self, name: str) -> None`

**Behavior:** Insert into `tapes` with `next_entry_id = 0`. No-op if exists.

**Rationale:** Explicit creation separates setup from append. Required for reset implementation.

### 3. Add `rename(old_name, new_name)` Core Operation

**Signature:** `def rename(self, old_name: str, new_name: str) -> None`

**Behavior:** `UPDATE tapes SET name = ? WHERE name = ?`

**Rationale:** All references are by `tape.id`, so renaming is safe and O(1).

### 4. Reimplement `reset(tape)` Using rename + create

**Signature:** `def reset(self, tape: str) -> None`

**Behavior:**
```python
def reset(self, tape: str) -> None:
    tape_id = self._get_tape_id(tape)
    if tape_id is None:
        raise ValueError(f"Tape '{tape}' does not exist")
    archived_name = f"{tape}_archived_{uuid4().hex[:8]}"
    self.rename(tape, archived_name)
    self.create(tape)
```

**Rationale:** Preserves immutability. Old tape data remains intact under archived name.

### 5. Remove Inline Recursive CTEs, Use Views

**Refactor `read(tape)`:**
Replace `_read_merged()` inline CTE with:
```sql
SELECT entry_id, kind, payload, meta, date
FROM merged_entries
WHERE leaf_tape_id = ?
ORDER BY depth DESC, entry_id
```

**Refactor `fetch_all(query)` for forked tapes:**
Replace `_fetch_forked_after_anchor()` inline CTE with two queries:
1. Resolve anchor via `merged_anchors` view
2. Fetch entries via `merged_entries` view with depth/entry_id filter

**Delete:** `_read_merged`, `_fetch_root_after_anchor`, `_fetch_forked_after_anchor`

### 6. Add `republic` Dependency, Use Its Types

**In `pyproject.toml`:** Add `"republic"` to dependencies.

**In `types.py`:**
- Remove `TapeEntry` dataclass (import from `republic.tape.entries`)
- Remove `TapeQuery` dataclass (import from `republic.tape.query`)
- Define `ForkTapeStore(AsyncTapeStore, Protocol)` with fork-specific methods

**Note on `TapeEntry.id` vs `entry_id`:** republic uses `id`. Our code uses `entry_id`. After importing republic's type, update all `entry.entry_id` to `entry.id` across the codebase.

**Note on `TapeQuery`:** republic's `TapeQuery` has private fields (`_kinds`, `_limit`, `_after_anchor`) and uses `tape` instead of `tape_name`. Update `fetch_all` to access these fields.

### 7. Rename Class to `SqliteForkTapeStore`

Match Python naming convention (SQLite → Sqlite).

### 8. Update `AsyncTapeStoreAdapter`

- Remove `snapshot` method
- Update to use republic types
- Keep lock + `to_thread()` pattern (per async.md analysis)

## Why It Works

1. **Immutability preserved:** reset renames instead of deleting. All entries remain in DB.
2. **Views reduce duplication:** Schema views define recursive logic once. Application code queries views with simple WHERE clauses.
3. **Protocol compliance:** `reset` still satisfies `TapeStore` protocol. `ForkTapeStore` extends `AsyncTapeStore` properly.
4. **Type alignment:** Using republic types ensures compatibility with the broader ecosystem.
5. **No behavior change for append/fork/read:** These operations remain identical; only internal implementation changes.

## Files

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `republic` to dependencies |
| `src/bub_sf/store/types.py` | Modify | Import republic types; define ForkTapeStore protocol |
| `src/bub_sf/store/fork_store.py` | Modify | Add create/rename; remove snapshot; use views; rename class |
| `src/bub_sf/store/async_adapter.py` | Modify | Remove snapshot; update types |
| `tests/store/test_fork_tape_store.py` | Modify | Remove snapshot tests; update reset tests; update type imports |
| `tests/store/test_async_adapter.py` | Modify | Remove snapshot tests; update type imports |
| `tests/store/test_performance.py` | Modify | Update type imports |
| `changes/1-fork-store-cleanup.md` | Create | This change plan |

## Migration Patterns

### snapshot → double fork
```python
# Before:
store.snapshot("source", "copy")

# After:
entries = store.read("source")
store.fork("source", entries[-1].id, "copy")
```

### TapeEntry.entry_id → TapeEntry.id
```python
# Before:
entry.entry_id

# After:
entry.id
```

### TapeQuery.tape_name → TapeQuery.tape
```python
# Before:
query.tape_name

# After:
query.tape
```

### TapeQuery public fields → private fields
```python
# Before:
query.kinds, query.limit, query.after_anchor

# After:
query._kinds, query._limit, query._after_anchor
```
