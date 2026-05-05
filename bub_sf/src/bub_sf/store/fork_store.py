"""SQLite-backed ForkTapeStore implementation."""

from __future__ import annotations

import asyncio
import aiosqlite
import functools
import itertools
import json
import uuid

from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, override

from republic.core.errors import ErrorKind, RepublicError
from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery
from republic.tape.store import AsyncTapeStore

from bub_sf.store.query import BuildQuery


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DEFAULT_CREATED = "1970-01-01T00:00:00+00:00"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES tapes(id),
    parent_entry_id INTEGER,
    next_entry_id INTEGER DEFAULT 0,
    created TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00'
);

CREATE TABLE IF NOT EXISTS tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_tape_entry ON tape_entries(tape_id, entry_id);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    anchor_name TEXT NOT NULL,
    UNIQUE(tape_id, anchor_name),
    UNIQUE(tape_id, entry_id)
);
CREATE INDEX IF NOT EXISTS idx_anchors_lookup ON anchors(tape_id, anchor_name);
CREATE INDEX IF NOT EXISTS idx_anchors_entry ON anchors(tape_id, entry_id);

-- Views for merged tape queries
CREATE VIEW IF NOT EXISTS tape_ancestors AS
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

CREATE VIEW IF NOT EXISTS merged_entries AS
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

CREATE VIEW IF NOT EXISTS merged_anchors AS
SELECT
    a.leaf_id AS leaf_tape_id,
    an.entry_id,
    an.anchor_name,
    a.depth
FROM tape_ancestors a
INNER JOIN anchors an ON an.tape_id = a.tape_id;
"""


TAPE_FIELDS = "entry_id, kind, payload, meta, date"


class _E(Exception):
    """Helper exception to carry frozen RepublicError through async CM."""

    def __init__(self, err: RepublicError) -> None:
        super().__init__()
        self.err = err


P = ParamSpec("P")
T = TypeVar("T")


def _unwrap_e(
    fn: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Unwrap _E wrapper back to RepublicError."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await fn(*args, **kwargs)
        except _E as exc:
            raise exc.err from exc

    return wrapper


# ---------------------------------------------------------------------------
# CoreOps
# ---------------------------------------------------------------------------

class CoreOps:
    """Core write operations. Does not commit — caller manages transactions."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def _get_tape_id(self, tape_name: str) -> int | None:
        async with self._conn.execute(
            "SELECT id FROM tapes WHERE name = ?", (tape_name,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def _get_or_create_tape(self, tape_name: str) -> tuple[int, int]:
        async with self._conn.execute(
            "SELECT id, next_entry_id FROM tapes WHERE name = ?", (tape_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0], row[1]

        now = datetime.now(UTC).isoformat()
        async with self._conn.execute(
            "INSERT INTO tapes (name, next_entry_id, created) VALUES (?, 0, ?)",
            (tape_name, now),
        ) as cursor:
            if cursor.lastrowid is None:
                raise _E(RepublicError(ErrorKind.UNKNOWN, "Failed to create tape"))
            return cursor.lastrowid, 0

    async def create(self, name: str) -> None:
        """Create an empty tape. No-op if tape exists."""
        now = datetime.now(UTC).isoformat()
        await self._conn.execute(
            "INSERT OR IGNORE INTO tapes (name, next_entry_id, created) VALUES (?, 0, ?)",
            (name, now),
        )

    async def append(self, tape_name: str, entry: TapeEntry) -> None:
        """Append an entry to a tape. Auto-creates tape if needed."""
        tape_id, next_entry_id = await self._get_or_create_tape(tape_name)

        entry_id = next_entry_id
        new_next_entry_id = entry_id + 1

        if entry.kind == "anchor":
            anchor_name = entry.payload["name"]
            async with self._conn.execute(
                """
                SELECT 1 FROM merged_anchors
                WHERE leaf_tape_id = ? AND anchor_name = ?
                LIMIT 1
                """,
                (tape_id, anchor_name),
            ) as cursor:
                if await cursor.fetchone() is not None:
                    raise _E(RepublicError(
                        ErrorKind.INVALID_INPUT,
                        f"Anchor name '{anchor_name}' already exists in merged view"
                    ))

        await self._conn.execute(
            """
            INSERT INTO tape_entries (tape_id, entry_id, kind, payload, meta, date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tape_id,
                entry_id,
                entry.kind,
                json.dumps(entry.payload),
                json.dumps(entry.meta),
                entry.date,
            ),
        )
        if entry.kind == "anchor":
            anchor_name = entry.payload["name"]
            await self._conn.execute(
                "INSERT INTO anchors (tape_id, entry_id, anchor_name) VALUES (?, ?, ?)",
                (tape_id, entry_id, anchor_name),
            )
        await self._conn.execute(
            "UPDATE tapes SET next_entry_id = ? WHERE id = ?",
            (new_next_entry_id, tape_id),
        )

    async def rename(self, old_name: str, new_name: str) -> None:
        """Rename a tape."""
        tape_id = await self._get_tape_id(old_name)
        if tape_id is None:
            raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Tape '{old_name}' does not exist"))

        if await self._get_tape_id(new_name) is not None:
            raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Tape '{new_name}' already exists"))

        await self._conn.execute(
            "UPDATE tapes SET name = ? WHERE id = ?",
            (new_name, tape_id),
        )

    async def fork(self, source_name: str, entry_id: int, target_name: str) -> None:
        """Fork source tape at the given entry_id."""
        async with self._conn.execute(
            "SELECT id, next_entry_id FROM tapes WHERE name = ?",
            (source_name,),
        ) as cursor:
            source_row = await cursor.fetchone()
            if source_row is None:
                raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Source tape '{source_name}' does not exist"))

        source_id, next_entry_id = source_row

        if await self._get_tape_id(target_name) is not None:
            raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Target tape '{target_name}' already exists"))

        if entry_id >= next_entry_id:
            raise _E(RepublicError(
                ErrorKind.INVALID_INPUT,
                f"entry_id {entry_id} is out of range (0 to {next_entry_id - 1})"
            ))

        now = datetime.now(UTC).isoformat()
        await self._conn.execute(
            """
            INSERT INTO tapes (name, parent_id, parent_entry_id, next_entry_id, created)
            VALUES (?, ?, ?, ?, ?)
            """,
            (target_name, source_id, entry_id, entry_id + 1, now),
        )


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------

class BuildQueryImpl(BuildQuery):
    """Implements anchor resolution for SQL query building."""

    def __init__(self, conn: aiosqlite.Connection, ops: CoreOps) -> None:
        self._conn = conn
        self._ops = ops

    @override
    async def anchors(self, tape_id: int, names: list[str]) -> list[int | None]:
        """Resolve anchor names to entry_id.
        
        Returns list matching input order and size.
        Duplicates are preserved.
        """
        if not names:
            return []

        # Use a single query with IN clause for efficiency
        placeholders = ",".join("?" for _ in names)
        async with self._conn.execute(
            f"""
            SELECT anchor_name, entry_id
            FROM merged_anchors
            WHERE anchor_name IN ({placeholders}) AND leaf_tape_id = ?
            ORDER BY depth ASC
            """,
            list(itertools.chain(names, [tape_id])),
        ) as cursor:
            rows = await cursor.fetchall()

        # Build lookup: name -> entry_id taking first (shallowest)
        lookup: dict[str, int] = {}
        for anchor_name, entry_id in rows:
            if anchor_name not in lookup:
                lookup[anchor_name] = entry_id

        # Return in original order, preserving size
        return [lookup.get(name) for name in names]

    @override
    async def last_anchor(self, tape_id: int) -> int | None:
        """Return the last anchor as entry_id or None."""
        async with self._conn.execute(
            """
            SELECT entry_id
            FROM merged_anchors
            WHERE leaf_tape_id = ?
            ORDER BY entry_id DESC
            LIMIT 1
            """,
            (tape_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
        # For simplicity, return entry_id only - tape_id not needed for query
        return row[0]

    @override
    async def tape_id(self, tape_name: str) -> int | None:
        return await self._ops._get_tape_id(tape_name)


# ---------------------------------------------------------------------------
# SQLiteForkTapeStore
# ---------------------------------------------------------------------------


class SQLiteForkTapeStore(AsyncTapeStore):
    """Async SQLite-backed tape store with fork support."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn: aiosqlite.Connection = conn
        self._core: CoreOps = CoreOps(conn)
        self._query: BuildQueryImpl = BuildQueryImpl(conn, self._core)

    @staticmethod
    async def create_store(db_path: Path) -> SQLiteForkTapeStore:
        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 5000")
        await SQLiteForkTapeStore._ensure_schema(conn)
        return SQLiteForkTapeStore(conn)

    @staticmethod
    async def _ensure_schema(conn: aiosqlite.Connection) -> None:
        await conn.executescript(SCHEMA_SQL)

    async def close(self) -> None:
        """Close the database connection."""
        await self._conn.close()

    # -- Core operations (with transaction management) --

    async def create(self, name: str) -> None:
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:
                await self._core.create(name)
        return await _go()

    async def append(self, tape: str, entry: TapeEntry) -> None:
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:
                await self._core.append(tape, entry)
        return await _go()

    async def rename(self, old_name: str, new_name: str) -> None:
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:            
                await self._core.rename(old_name, new_name)
        return await _go()

    async def reset(self, tape: str) -> None:
        """Reset a tape by archiving it and creating a new empty tape."""
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:
                tape_id = await self._core._get_tape_id(tape)
                if tape_id is None:
                    raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Tape '{tape}' does not exist"))

                archived_name = f"{tape}_archived_{uuid.uuid4().hex[:8]}"
                await self._core.rename(tape, archived_name)
                await self._core.create(tape)
        return await _go()

    async def fork(self, source_name: str, entry_id: int, target_name: str) -> None:
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:
                await self._core.fork(source_name, entry_id, target_name)
        return await _go()
    
    async def fork_tape(self, source_name: str, target_name: str) -> None:
        """Fork a tape at the last entry."""
        @_unwrap_e
        async def _go():
            async with self._tranx() as _:
                source_tape_id = await self._core._get_tape_id(source_name)
                if source_tape_id is None:
                    raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Source tape '{source_name}' does not exist"))
                

                async with self._conn.execute("""
                        SELECT {TAPE_FIELDS}
                        FROM merged_entries
                        WHERE leaf_tape_id = ?
                        ORDER BY DEPTH, entry_id DESC
                        LIMIT 1
                        """, (source_tape_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row is None:
                        raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Source tape '{source_name}' has no entries to fork from"))
                    last_entry = _tape_entry(row)

                await self._core.fork(source_name, last_entry.id, target_name)
        return await _go()

    # -- Read operations --

    async def read(self, tape_name: str) -> list[TapeEntry] | None:
        tape_id = await self._core._get_tape_id(tape_name)  # Validate tape exists
        if tape_id is None:
            return None

        async with self._conn.execute(
            f"""
            SELECT {TAPE_FIELDS}
            FROM merged_entries
            WHERE leaf_tape_id = ? AND entry_id IS NOT NULL
            ORDER BY depth DESC, entry_id
            """,
            (tape_id,),
        ) as cursor:
            entries = []
            async for row in cursor:
                entries.append(_tape_entry(row))
        return entries

    async def fetch_all(self, query: TapeQuery) -> list[TapeEntry]:
        @_unwrap_e
        async def _go():
            async with self._tranx() as conn:
                match await self._query.build(query):
                    case (where_clause, params_):
                        sql = f"""
                        SELECT {TAPE_FIELDS}
                        FROM merged_entries
                        WHERE {where_clause}
                        ORDER BY depth DESC, entry_id
                        """
                        params = params_

                limit = query._limit
                if limit is not None:
                    sql = sql + "\nLIMIT ?"
                    params = params_ + [limit]

                async with conn.execute(sql, params) as cursor:
                    entries: list[TapeEntry] = []
                    async for row in cursor:
                        entries.append(_tape_entry(row))

                # limit filter

                return entries
        return await _go()

    async def list_tapes(self) -> list[str]:
        async with self._conn.execute("SELECT name FROM tapes ORDER BY name") as cursor:
            return [row[0] async for row in cursor]

    async def list_tapes_ext(self) -> list[tuple[str, dict[str, Any]]]:
        async with self._conn.execute(
            "SELECT name, created FROM tapes ORDER BY created DESC"
        ) as cursor:
            return [(row[0], {"created": row[1]}) async for row in cursor]
        
    @asynccontextmanager
    async def _tranx(self) -> AsyncGenerator[aiosqlite.Connection]:
        """Async context manager for transactions."""
        await self._conn.execute("BEGIN")
        try:
            yield self._conn
            await self._conn.commit()
        except Exception as e:
            await self._conn.rollback()
            raise e from e


def _tape_entry(row: aiosqlite.Row) -> TapeEntry:
    return TapeEntry(
        id=row[0],
        kind=row[1],
        payload=json.loads(row[2]),
        meta=json.loads(row[3]),
        date=row[4],
    )
