# Async SQLite Support Spike

## Status: IN PROGRESS

Spiking correct async SQLite support for ForkTapeStore, which implements AsyncTapeStore protocol.

## Key Findings

### 1. SQLite Does NOT Natively Support Async

SQLite is a C library with entirely **synchronous, blocking APIs**. There is no native async I/O support in SQLite itself. All operations (open, read, write, commit) block the calling thread until completion.

### 2. Python sqlite3 Module is Sync Only

The standard library `sqlite3` module provides **no async support**. It's a thin wrapper around the C SQLite library.

**Available options for async SQLite in Python:**

| Library | Approach | Thread Safety |
|---------|----------|---------------|
| `aiosqlite` | Wraps `sqlite3` with `asyncio`, uses background thread per connection | Thread-safe via serialization |
| `sqlite-worker` | Single dedicated worker thread with queue-based architecture | Single-threaded access |
| Custom `to_thread()` | Use `asyncio.to_thread()` with standard `sqlite3` | Requires manual synchronization |

**Reference:** [aiosqlite on GitHub](https://github.com/omnilib/aiosqlite) - "aiosqlite provides a friendly, async interface to sqlite databases. It replicates the standard sqlite3 module, but with async versions of all the standard..."

### 3. SQLite Threading Model

From [SQLite threading docs](https://www.sqlite.org/threadsafe.html) and Python docs:

**SQLite compile-time modes:**
- **Single-thread** (`SQLITE_THREADSAFE=0`): All mutexes disabled, unsafe in multi-threaded
- **Multi-thread** (`SQLITE_THREADSAFE=2`): Multiple threads can use SQLite, but no single connection can be used simultaneously by multiple threads
- **Serialized** (`SQLITE_THREADSAFE=1`): Safe to use by multiple threads with no restriction

**Python `sqlite3.threadsafety` mapping:**
- `0` = Single-thread
- `1` = Multi-thread  
- `3` = Serialized

**Current environment:** `sqlite3.threadsafety = 3` (Serialized mode)

**Critical:** Even with Serialized mode, SQLite only allows **one writer at a time**. Multiple readers can proceed concurrently, but writes are globally locked.

### 4. Current Implementation Analysis

#### Sync Core: `SQLiteForkTapeStore` (`bub_sf/src/bub_sf/store/fork_store.py`)

```python
class SQLiteForkTapeStore(ForkTapeStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
```

**Assessment:** The sync core uses `check_same_thread=False` which disables Python's thread-ownership check. With SQLite in Serialized mode (`threadsafety=3`), this is safe **IF** access to the connection is serialized externally.

#### Async Adapter: `AsyncTapeStoreAdapter` (`bub_sf/src/bub_sf/store/async_adapter.py`)

```python
class AsyncTapeStoreAdapter:
    def __init__(self, db_path: Path) -> None:
        self._store = ForkTapeStore(db_path)
        self._lock = threading.Lock()

    async def append(self, tape_name: str, entry: TapeEntry) -> int:
        def _append():
            with self._lock:
                try:
                    result = self._store.append(tape_name, entry)
                    self._store._conn.commit()
                    return result
                except Exception:
                    self._store._conn.rollback()
                    raise
        return await asyncio.to_thread(_append)
```

**Assessment:** This adapter IS technically correct:

1. **`threading.Lock()` serializes access** - Only one thread can access the connection at a time
2. **`check_same_thread=False` is safe with Serialized mode** - SQLite handles internal locking
3. **`asyncio.to_thread()` dispatches to thread pool** - Each operation runs in a worker thread
4. **Auto-commit/rollback inside the lock** - Transaction boundaries are correct

**However, there are concerns:**

1. **Thread pool churn** - `asyncio.to_thread()` grabs a thread from the pool for EACH operation
2. **All operations serialized** - Even reads block behind writes due to the coarse lock
3. **Connection shared across many threads** - While safe in Serialized mode, it's not ideal
4. **No connection lifecycle management** - Connection is never explicitly closed
5. **WAL mode benefits not fully utilized** - WAL allows concurrent reads during writes, but the lock prevents this

#### Republic's Generic Adapter (`republic/src/republic/tape/store.py`)

```python
class AsyncTapeStoreAdapter:
    async def append(self, tape: str, entry: TapeEntry) -> None:
        return await asyncio.to_thread(self._store.append, tape, entry)
```

**Assessment:** This generic adapter does NOT have a lock and does NOT set `check_same_thread=False`. It is **NOT safe** for SQLiteForkTapeStore because:
- Multiple coroutines can dispatch to different threads simultaneously
- The same connection would be accessed concurrently without serialization
- This would corrupt data or raise `sqlite3.ProgrammingError`

**The bub_sf-specific adapter with `threading.Lock()` is the correct approach.**

### 5. Test Results

Running `bub_sf/tests/store/test_async_adapter.py`:

```
test_async_append PASSED
test_async_read PASSED
test_async_fetch_all PASSED
test_async_list_tapes PASSED
test_async_reset PASSED
test_async_fork FAILED          # Signature mismatch
test_async_snapshot PASSED
test_concurrent_appends PASSED
test_concurrent_reads PASSED
test_concurrent_fork_and_append FAILED  # Signature mismatch
test_return_types FAILED        # Signature mismatch
```

**Failures (3/11):**

```
TypeError: AsyncTapeStoreAdapter.fork() missing 1 required positional argument: 'target_name'
```

**Root cause:** The async adapter's `fork()` signature is:
```python
async def fork(self, source_name: str, entry_id: int, target_name: str) -> None:
```

**Current signature:** `fork(source_name, entry_id, target_name)` — forks at a specific entry_id.

All tests updated to pass `entry_id` (int) instead of `entry` (TapeEntry).

## Design Options

### Option A: Thread-Per-Connection with Lock (Recommended)

Use a dedicated thread for all SQLite operations with an asyncio queue or lock.

```python
import asyncio
import sqlite3
from threading import Lock

class AsyncSQLiteForkTapeStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
    
    async def append(self, tape_name: str, entry: TapeEntry) -> int:
        def _append():
            with self._lock:
                # ... sync implementation
                self._conn.commit()
                return entry_id
        
        return await asyncio.to_thread(_append)
```

**Pros:**
- Simple implementation
- All SQLite ops serialized through one connection
- WAL mode allows readers to proceed during writes

**Cons:**
- All operations serialized (even reads)
- Single connection bottleneck

### Option B: aiosqlite (Dedicated Worker Thread)

`aiosqlite` provides an async bridge by running SQLite operations in a **single dedicated worker thread** per connection.

**How aiosqlite works internally:**

```python
# From aiosqlite/core.py
class Connection:
    def __init__(self, connector, ...):
        self._tx: SimpleQueue = SimpleQueue()
        self._thread = Thread(target=_connection_worker_thread, args=(self._tx,))
    
    async def _execute(self, fn, *args, **kwargs):
        function = partial(fn, *args, **kwargs)
        future = asyncio.get_event_loop().create_future()
        self._tx.put_nowait((future, function))
        return await future

def _connection_worker_thread(tx):
    while True:
        future, function = tx.get()
        result = function()
        future.get_loop().call_soon_threadsafe(set_result, future, result)
```

**Key insight:** aiosqlite is essentially a production-ready implementation of **Option C** (dedicated worker thread). It:
- Creates one thread per connection
- Queues operations via `SimpleQueue`
- Returns results via `asyncio.Future`
- Never shares the connection across threads

```python
import aiosqlite

class AsyncSQLiteForkTapeStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
    
    async def initialize(self):
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
    
    async def append(self, tape_name: str, entry: TapeEntry) -> int:
        cursor = await self._conn.execute("SELECT ...")
        row = await cursor.fetchone()
        # ...
        await self._conn.commit()
```

**Pros:**
- True async/await API
- Single dedicated thread per connection (no thread pool churn)
- Connection never leaves the worker thread (cleanest threading model)
- No manual locking needed (serialization via queue)
- Production-tested (used by Home Assistant, Chia blockchain)

**Cons:**
- Additional dependency (~1.5k stars, actively maintained)
- Still serializes writes at SQLite level (inherent limitation)

### Option C: Custom Dedicated Thread (Manual Implementation)

Same architecture as aiosqlite but hand-rolled.

**Not recommended** - aiosqlite already provides this perfectly.

## Recommended Approach: Use aiosqlite

Given the analysis:

1. **Current approach (`to_thread()` + `threading.Lock()`) works but is suboptimal**
   - Thread pool churn (grabs new thread per operation)
   - Coarse locking (all ops serialized, even reads)
   - Connection passed between threads

2. **aiosqlite is the better implementation of the same concept**
   - Dedicated worker thread (no pool churn)
   - Queue-based serialization (no explicit locks)
   - Connection stays in one thread
   - Cleaner lifecycle management

3. **For ForkTapeStore specifically:**
   - Use `aiosqlite` for the async adapter
   - Single connection is sufficient (SQLite serializes writes anyway)
   - Keep WAL mode for reader concurrency
   - Fix the `fork()` signature mismatch (see Test Results above)

### Implementation Sketch

```python
import aiosqlite
from pathlib import Path

class AsyncSQLiteForkTapeStore:
    """Async SQLite-backed tape store with fork support."""
    
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
    
    async def initialize(self) -> None:
        """Initialize the database connection and schema."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._ensure_schema()
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
    
    async def _ensure_schema(self) -> None:
        """Create tables, indexes, and views if they don't exist."""
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
    
    async def append(self, tape_name: str, entry: TapeEntry) -> int:
        """Append an entry to a tape. Returns the assigned entry_id."""
        # Core operations use aiosqlite's async API
        cursor = await self._conn.execute(
            "SELECT id, next_entry_id FROM tapes WHERE name = ?",
            (tape_name,)
        )
        row = await cursor.fetchone()
        # ... rest of implementation
        await self._conn.commit()
        return entry_id
    
    async def fetch_all(self, query: TapeQuery) -> list[TapeEntry]:
        """Return entries matching the given query."""
        cursor = await self._conn.execute(
            "SELECT entry_id, kind, payload, meta, date FROM tape_entries WHERE tape_id = ?",
            (tape_id,)
        )
        rows = await cursor.fetchall()
        # ... construct entries
        return entries
```

### Protocol Compliance

The `AsyncTapeStore` protocol requires:
- `async def list_tapes(self) -> list[str]`
- `async def reset(self, tape: str) -> None`
- `async def fetch_all(self, query: TapeQuery) -> Iterable[TapeEntry]`
- `async def append(self, tape: str, entry: TapeEntry) -> None`

The async implementation should directly implement this protocol rather than using `AsyncTapeStoreAdapter`.

## Open Questions (Answered)

### 1. Transaction Boundaries

**Current state:** The sync `SQLiteForkTapeStore` core operations (append, fork) do NOT commit internally. The `AsyncTapeStoreAdapter` wraps them with explicit commit/rollback inside the lock.

**With aiosqlite:** Same pattern works. The adapter layer handles transaction boundaries:
```python
async def append(self, tape_name, entry):
    async with self._conn:  # aiosqlite context manager handles commit/rollback
        return await self._store.append(tape_name, entry)
```

Or manually:
```python
try:
    result = await self._store.append(tape_name, entry)
    await self._conn.commit()
    return result
except Exception:
    await self._conn.rollback()
    raise
```

### 2. Connection Lifecycle

**Recommended:** Long-lived connection, opened in `__init__` or first use, closed explicitly via `close()` method or async context manager.

```python
class AsyncSQLiteForkTapeStore:
    async def __aenter__(self):
        self._conn = await aiosqlite.connect(self._db_path)
        return self
    
    async def __aexit__(self, *args):
        await self._conn.close()
```

### 3. Error Handling (SQLITE_BUSY)

With WAL mode + single connection + queue-based access (aiosqlite), `SQLITE_BUSY` should be rare. The queue serializes all operations, so there's no contention between our own operations.

If multiple processes access the same DB file, `SQLITE_BUSY` can still occur. In that case, a simple retry with exponential backoff is sufficient:

```python
import sqlite3
import asyncio

async def execute_with_retry(conn, sql, params, retries=3):
    for i in range(retries):
        try:
            return await conn.execute(sql, params)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and i < retries - 1:
                await asyncio.sleep(0.1 * (2 ** i))
            else:
                raise
```

### 4. Fork Operation Atomicity

**Current bug:** The async adapter's `fork()` signature is `(source_name, entry, target_name)` but the sync store expects `(source_name, target_name)`.

**Design decision needed:** Should fork take an entry (to fork at a specific point) or always fork at the current tip?
- `core2.md` design: `fork(source, entry, name)` - fork at specific entry
- Current sync impl: `fork(source_name, entry_id, target_name)` - fork at specific entry
- Current tests use: `fork("parent", parent_entries[-1].entry_id, "child")` - 3 args

**Recommendation:** Match the `core2.md` design (3 args). Update sync store and tests to support forking at a specific entry.

### 5. Read Concurrency

**Answer:** Not needed for our use case.

With aiosqlite's single worker thread, all operations are serialized anyway. WAL mode allows concurrent readers from OTHER processes, but within our single connection, reads and writes are queued.

For high-read scenarios, a separate read-only connection could help, but adds complexity. Given our workload (append-heavy, occasional reads), a single connection is sufficient.

## Migration Plan

### Phase 1: Fix Immediate Bugs

1. Fix `AsyncTapeStoreAdapter.fork()` signature to match tests and sync store
2. Ensure all tests pass

### Phase 2: Evaluate aiosqlite Migration

1. Add `aiosqlite` dependency
2. Rewrite `AsyncTapeStoreAdapter` to use aiosqlite instead of `to_thread()` + `Lock`
3. Keep sync `SQLiteForkTapeStore` unchanged (it remains the source of truth)
4. Benchmark: compare `to_thread()` vs aiosqlite performance

### Phase 3: Long-term (Optional)

1. Consider native async store implementation if performance demands it
2. Multiple connections (read replicas) if needed

## Summary

| Aspect | Current (`to_thread` + Lock) | Recommended (aiosqlite) |
|--------|------------------------------|------------------------|
| Correctness | Correct but suboptimal | Correct and clean |
| Thread model | Thread pool + manual lock | Dedicated worker thread |
| Connection sharing | Across pool threads | Single thread only |
| Performance | Thread churn overhead | Minimal overhead |
| Complexity | Medium (manual locking) | Low (library handles it) |
| Dependencies | None (stdlib only) | `aiosqlite` |

**Verdict:** Current implementation is functionally correct. Migration to `aiosqlite` is recommended for cleaner architecture and better performance, but not urgent.

## References

- [aiosqlite Documentation](https://github.com/omnilib/aiosqlite)
- [SQLite Threading Docs](https://www.sqlite.org/threadsafe.html)
- [Using SQLite and asyncio effectively - Piccolo ORM](https://piccolo-orm.readthedocs.io/en/1.11.0/piccolo/tutorials/using_sqlite_and_asyncio_effectively.html)
- [SQLite Worker - Medium Article](https://medium.com/@roshanlamichhane/sqlite-worker-supercharge-your-sqlite-performance-in-multi-threaded-python-applications-01e2e43cc406)
- [aiosqlitepool - Hacker News Discussion](https://news.ycombinator.com/item?id=44530518)
