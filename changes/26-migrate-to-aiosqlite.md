# Change Plan: Native Async SqliteForkTapeStore with aiosqlite

## Facts

### Current Architecture

We have **two separate classes** for sync and async:

1. **`SqliteForkTapeStore`** (`fork_store.py:14`) — sync store using `sqlite3`
2. **`AsyncTapeStoreAdapter`** (`async_adapter.py:19`) — async wrapper using `asyncio.to_thread()` + `threading.Lock()`

**Problems with current approach:**
- `AsyncTapeStoreAdapter` is an adapter pattern that adds indirection
- Thread pool churn from `to_thread()`
- Coarse locking blocks reads behind writes
- Connection passed between threads
- Two classes to maintain for one store

### Design Intent (from async.md:330)

> "The async implementation should directly implement this protocol rather than using `AsyncTapeStoreAdapter`."

### Core Design Reference (core2.md)

Per `core2.md`, the store implements `AsyncTapeStore` protocol with these key principles:
- **Immutable entries:** Never delete or modify entries
- **Core-Interface split:** Core ops (`create`, `append`, `fork`) write; interface ops (`read`, `fetch_all`) read-only
- **Views for queries:** `merged_entries`, `merged_anchors` views encapsulate recursive CTE logic
- **Transaction boundaries:** Core ops don't commit internally; caller manages transactions

The async migration must preserve these invariants while making all operations async-native.

### aiosqlite Already Added

`aiosqlite==0.22.1` is now in dependencies (added via `uv add`).

## Design

### 1. Eliminate AsyncTapeStoreAdapter

**Delete:** `src/bub_sf/store/async_adapter.py`

**Rationale:** The adapter pattern is unnecessary. aiosqlite provides native async SQLite support.

### 2. Three-Class Architecture

Following `core2.md` Core-Interface split and query builder pattern:

**`CoreOps`** — Core write operations only (no commit):
```python
class CoreOps:
    """Core operations that write to the database."""
    
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
    
    async def create(self, name: str) -> None:
        """Create empty tape. Optional; append() auto-creates if needed."""
        ...
    
    async def append(self, tape_name: str, entry: TapeEntry) -> None:
        """Auto-creates tape if needed (implicit creation)."""
        ...
    
    async def rename(self, old_name: str, new_name: str) -> None:
        ...
    
    async def reset(self, tape: str) -> None:
        ...
    
    async def fork(self, source_name: str, entry_id: int, target_name: str) -> None:
        ...
```

**`QueryBuilder`** — Extends `BuildQuery` from `query.py`:
```python
class QueryBuilder(BuildQuery):
    """Implements anchor resolution for SQL query building."""
    
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
    
    async def anchors(self, names: list[str]) -> list[tuple[int, int] | None]:
        """Resolve anchor names to (tape_id, entry_id).
        
        Returns list matching input order and size.
        Duplicates are preserved: anchors(["a1", "a2", "a1"]) 
        returns [info_a1, info_a2, info_a1].
        """
        ...
    
    async def last_anchor(self) -> tuple[int, int] | None:
        ...
```

**`SqliteForkTapeStore`** — Full async store implementing `AsyncTapeStore`:
```python
class SqliteForkTapeStore(AsyncTapeStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._core: CoreOps | None = None
        self._query: QueryBuilder | None = None

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._core = None
            self._query = None
```

**All methods become async:**
- `async def create(self, name: str) -> None`
- `async def rename(self, old_name: str, new_name: str) -> None`
- `async def append(self, tape_name: str, entry: TapeEntry) -> None`
- `async def read(self, tape_name: str) -> list[TapeEntry] | None`
- `async def fetch_all(self, query: TapeQuery) -> list[TapeEntry]`
- `async def list_tapes(self) -> list[str]`
- `async def reset(self, tape: str) -> None`
- `async def fork(self, source_name: str, entry_id: int, target_name: str) -> None`

**Transaction handling:** Per `core2.md`, core operations do NOT commit internally. The outer `SqliteForkTapeStore` manages transaction boundaries:

```python
async def reset(self, tape: str) -> None:
    conn = await self._get_conn()
    try:
        await self._core.rename(tape, archived_name)
        await self._core.create(tape)
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
```

Single operations like `append` also commit at the store level for simplicity:
```python
async def append(self, tape_name: str, entry: TapeEntry) -> None:
    conn = await self._get_conn()
    try:
        await self._core.append(tape_name, entry)
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
```

Read operations (`read`, `fetch_all`, `list_tapes`) don't need explicit transactions.

### 3. Lazy Initialization

```python
async def _get_conn(self) -> aiosqlite.Connection:
    if self._conn is None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        await self._ensure_schema()
                self._core = CoreOps(self._conn)
    return self._conn

async def init(self) -> None:
    """Explicitly initialize the store. Optional; lazy init on first use."""
    await self._get_conn()
```

**Race condition protection:** Add `asyncio.Lock` for concurrent initialization:

```python
def __init__(self, db_path: Path) -> None:
    self._db_path = db_path
    self._conn: aiosqlite.Connection | None = None
    self._core: CoreOps | None = None
    self._init_lock = asyncio.Lock()

async def _get_conn(self) -> aiosqlite.Connection:
    if self._conn is None:
        async with self._init_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                await self._conn.execute("PRAGMA journal_mode = WAL")
                await self._conn.execute("PRAGMA busy_timeout = 5000")
                await self._ensure_schema()
                self._core = CoreOps(self._conn)
                self._query = QueryBuilder(self._conn)
    return self._conn
```

Each public method calls `conn = await self._get_conn()` at start. The explicit `init()` method allows callers to eagerly initialize if desired, but is not required.

### 5. Update Types

**Modify:** `src/bub_sf/store/types.py`
- Change `ForkTapeStore` to extend `AsyncTapeStore` instead of `TapeStore`
- All methods are async:
```python
class ForkTapeStore(AsyncTapeStore, Protocol):
    async def create(self, name: str) -> None: ...
    async def rename(self, old_name: str, new_name: str) -> None: ...
    async def fork(self, source_name: str, entry_id: int, target_name: str) -> None: ...
```

### 6. Update Tests

**Delete:** `tests/store/test_async_adapter.py` (no longer needed - adapter eliminated)

**Merge:** Move async adapter tests into `test_fork_tape_store.py`:
- Make all test methods async
- Use `async def` fixtures with `yield`
- Use `async with store:` for proper lifecycle
- Convert sync test calls to `await store.append(...)`, etc.

**Update:** `tests/store/test_performance.py`:
- Use `async`/`await` for store operations
- Use pytest-asyncio markers
- Benchmarks now measure aiosqlite performance

## Why It Works

1. **Three-class architecture:** Separates core writes (`CoreOps`), query building (`QueryBuilder`), and the full store interface (`SqliteForkTapeStore`)
2. **aiosqlite architecture:** Single dedicated worker thread, queue-based serialization — no thread pool churn, no manual locking
3. **Lazy init:** Preserves simple `SqliteForkTapeStore(path)` constructor
4. **Context manager:** Proper lifecycle management with `async with`
5. **WAL mode + busy_timeout:** Handles multi-process contention gracefully
6. **Query builder integration:** Reuses `BuildQuery` from `query.py` for consistent query construction

## Files

| File | Action | Details |
|------|--------|---------|
| `bub_sf/pyproject.toml` | Already done | `aiosqlite` added |
| `bub_sf/src/bub_sf/store/fork_store.py` | Major refactor | CoreOps + QueryBuilder + SqliteForkTapeStore |
| `bub_sf/src/bub_sf/store/query.py` | Already exists | BuildQuery base class, no changes needed |
| `bub_sf/src/bub_sf/store/async_adapter.py` | **Delete** | No longer needed |
| `bub_sf/src/bub_sf/store/__init__.py` | Modify | Remove `AsyncTapeStoreAdapter` export |
| `bub_sf/src/bub_sf/store/types.py` | Modify | `ForkTapeStore` protocol with async methods |
| `bub_sf/tests/store/test_fork_tape_store.py` | Major refactor | Make all tests async |
| `bub_sf/tests/store/test_async_adapter.py` | **Delete** | Move relevant tests to test_fork_tape_store.py |
| `bub_sf/tests/store/test_performance.py` | Modify | Make async |
| `bub_sf/docs/store/async.md` | Update | Mark as COMPLETE, update recommendations |

## Decisions

1. **No sync API.** The store implements `AsyncTapeStore` protocol directly. All methods are async. Sync usage is not supported.
2. **Test fixtures use `async with store:`**. This ensures proper initialization and cleanup.
3. **No custom exceptions yet.** Use `PRAGMA busy_timeout = 5000` to handle SQLITE_BUSY. Custom exception wrapping deferred until needed.
