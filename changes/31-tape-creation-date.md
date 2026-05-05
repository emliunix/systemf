# Change Plan: Add Tape Creation Date to Schema and CLI

## Facts

1. The `tapes` table in `bub_sf/src/bub_sf/store/fork_store.py` has columns: `id`, `name`, `parent_id`, `parent_entry_id`, `next_entry_id`. There is **no creation date column** (`bub_sf/src/bub_sf/store/fork_store.py:30-36`).
2. Tape creation happens in three places:
   - `CoreOps.create()` (`fork_store.py:163-168`) — `INSERT OR IGNORE INTO tapes (name, next_entry_id) VALUES (?, 0)`
   - `CoreOps._get_or_create_tape()` (`fork_store.py:147-161`) — same insert pattern
   - `CoreOps.fork()` (`fork_store.py:232-259`) — inserts with `parent_id`, `parent_entry_id`, `next_entry_id`
3. The `list_tapes()` method returns `list[str]` (`fork_store.py:477-479`). It is called from tests (`test_fork_tape_store.py`), `TapeManager` (`republic/src/republic/tape/manager.py`), and the CLI (`hook_cli.py:60`).
4. The `AsyncTapeStore` protocol defines `list_tapes() -> list[str]` (`republic/src/republic/tape/store.py:36`). Changing this would require updating all implementations.
5. The `list-tapes` CLI command currently prints just tape names (`hook_cli.py:54-68`).
6. `tape_entries` table has `date TEXT NOT NULL` for entry-level dates, but tape-level creation date is missing.
7. The store is async and uses `aiosqlite`. Schema is applied via `_ensure_schema()` with `SCHEMA_SQL` (`fork_store.py:29-97`).

## Design

### Schema Migration

Add `created` column to the `tapes` table schema with a default value for backfill:

```sql
CREATE TABLE IF NOT EXISTS tapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES tapes(id),
    parent_entry_id INTEGER,
    next_entry_id INTEGER DEFAULT 0,
    created TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00'
);
```

SQLite supports `ALTER TABLE ADD COLUMN` with `NOT NULL` when a `DEFAULT` is provided. The one-off migration SQL is provided in `changes/31-tape-creation-date-migration.sql`:

```sql
ALTER TABLE tapes ADD COLUMN created TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';
```

This is run manually against existing databases before deploying the new code. No automatic migration in `_ensure_schema()`.

### Update Creation Code

Update all three tape creation sites to set `created = datetime.now(UTC).isoformat()`:

- `create()`: change INSERT to include `created`
- `_get_or_create_tape()`: change INSERT to include `created`  
- `fork()`: change INSERT to include `created`

### New Store Method

Add `list_tapes_ext() -> list[tuple[str, dict[str, Any]]]` to `SQLiteForkTapeStore`:

```python
async def list_tapes_ext(self) -> list[tuple[str, dict[str, Any]]]:
    async with self._conn.execute(
        "SELECT name, created FROM tapes ORDER BY created DESC"
    ) as cursor:
        return [(row[0], {"created": row[1]}) async for row in cursor]
```

Returns a list of `(name, metadata)` tuples where metadata is a dict. This avoids changing the protocol or breaking existing `list_tapes()` callers, and is extensible for future tape metadata.

### CLI Enhancement

Update `list-tapes` command to:
1. Use `list_tapes_ext()` instead of `list_tapes()`
2. Print in a two-column format: `<name>  <created>`
3. Sort by created date descending (newest first)

Format:
```
tape-name-1   2025-05-05T10:30:00+00:00
tape-name-2   2025-05-04T08:15:00+00:00
```

### Error Handling

- Empty list: still print `(no tapes)`
- Long names: pad to reasonable width or use tab separation

## Why It Works

1. **Simple schema migration:** SQLite supports `ALTER TABLE ADD COLUMN` with `NOT NULL` when a `DEFAULT` is provided. One statement, no table rebuild, no view drops.
2. **Default backfill:** `1970-01-01T00:00:00+00:00` makes pre-existing tapes clearly identifiable as "legacy" while satisfying `NOT NULL`.
3. **Protocol preservation:** Adding `list_tapes_ext()` instead of changing `list_tapes()` avoids breaking `TapeManager`, tests, and the `AsyncTapeStore` protocol. Returning `dict[str, Any]` metadata is extensible for future fields.
4. **UTC timestamps:** Using `datetime.now(UTC).isoformat()` ensures consistent, timezone-aware ISO format matching existing entry dates.
5. **Rich CLI formatting:** Using `rich.table.Table` and `rich.panel.Panel` makes both `list-tapes` and `print-tape` output readable and styled, consistent with the `bub` CLI channel's use of `rich`. `rich` added as explicit dependency to `bub_sf`.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_sf/src/bub_sf/store/fork_store.py` | Modify | Add `created` column to schema, update `create()`/`_get_or_create_tape()`/`fork()` to set `created`, add `list_tapes_ext()` |
| `bub_sf/src/bub_sf/hook_cli.py` | Modify | Update `list-tapes` to use `list_tapes_ext()` and display dates |
| `bub_sf/tests/store/test_fork_tape_store.py` | Modify | Update tests to verify `created` is set on new tapes, verify migration backfills old tapes |
| `bub_sf/tests/test_hook_cli.py` | Modify | Update `list-tapes` CLI tests to expect date output |

## Checklist

- [x] Inventory call sites — `list_tapes()` called from manager, builtin store, tests, CLI; `create()`, `_get_or_create_tape()`, `fork()` are the only tape creation sites.
- [x] Categorize migration patterns — Schema migration requires table rebuild in SQLite. No API signature changes (new method added instead).
- [x] Decide delete vs migrate — N/A; additive change.
- [x] Identify pre-existing debt vs new bugs — N/A.
- [x] Check production code separately from tests — Tests need updates for new behavior.
- [x] Verify line numbers match actual files — Verified against current codebase.
- [x] List all files to modify, delete, or create — Listed above.
