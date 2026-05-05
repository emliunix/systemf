"""Tests for ForkTapeStore implementation."""

from __future__ import annotations

import pytest
from republic.core.errors import ErrorKind, RepublicError
from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery

from bub_sf.store.fork_store import SQLiteForkTapeStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def store(tmp_path):
    """Create a fresh ForkTapeStore backed by a temporary database."""
    store = await SQLiteForkTapeStore.create_store(tmp_path / "test.db")
    yield store
    await store.close()


@pytest.fixture
async def populated_store(store):
    """Create a store with two entries on the 'main' tape."""
    await store.append(
        "main",
        TapeEntry(
            id=0,
            kind="message",
            payload={"role": "user", "content": "hello"},
            date="2024-01-01T00:00:00",
        ),
    )
    await store.append(
        "main",
        TapeEntry(
            id=1,
            kind="message",
            payload={"role": "assistant", "content": "hi"},
            date="2024-01-01T00:00:01",
        ),
    )
    return store


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def make_entry(entry_id=0, kind="message", payload=None):
    """Create a TapeEntry with sensible defaults for testing."""
    return TapeEntry(
        id=entry_id,
        kind=kind,
        payload=payload or {"role": "user", "content": "hello"},
        date="2026-05-01T12:00:00+00:00",
    )


def assert_merged_view_valid(entries):
    """Verify that a merged view has no duplicate entry_ids and is strictly increasing."""
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids)), f"Duplicate entry_ids found: {ids}"
    assert ids == sorted(ids), f"Entry IDs not sorted: {ids}"
    if ids:
        assert ids == list(range(min(ids), max(ids) + 1)), f"Gaps in IDs: {ids}"


async def assert_parent_unchanged(store, tape_name, expected_entries):
    """Verify that a parent tape's entries are exactly as expected."""
    actual = await store.read(tape_name) or []
    assert actual == expected_entries, (
        f"Parent tape {tape_name} was modified. "
        f"Expected {len(expected_entries)} entries, got {len(actual)}"
    )


# ---------------------------------------------------------------------------
# Core Operations
# ---------------------------------------------------------------------------

class TestCoreOperations:

    @pytest.mark.asyncio
    async def test_create_new_tape(self, store):
        """create() creates a new empty tape."""
        await store.create("new_tape")
        assert "new_tape" in await store.list_tapes()
        assert await store.read("new_tape") == []

    @pytest.mark.asyncio
    async def test_create_idempotent(self, store):
        """create() is a no-op if tape already exists."""
        await store.append("main", make_entry(0))
        await store.create("main")
        assert len(await store.read("main")) == 1

    @pytest.mark.asyncio
    async def test_rename_success(self, store):
        """rename() changes tape name."""
        await store.append("old", make_entry(0))
        await store.rename("old", "new")
        assert "old" not in await store.list_tapes()
        assert "new" in await store.list_tapes()
        assert len(await store.read("new")) == 1

    @pytest.mark.asyncio
    async def test_rename_nonexistent_raises(self, store):
        """rename() raises ValueError if source doesn't exist."""
        with pytest.raises(RepublicError, match="does not exist"):
            await store.rename("missing", "new")

    @pytest.mark.asyncio
    async def test_rename_to_existing_raises(self, store):
        """rename() raises RepublicError if target already exists."""
        await store.create("old")
        await store.create("new")
        with pytest.raises(RepublicError, match="already exists"):
            await store.rename("old", "new")

    @pytest.mark.asyncio
    async def test_append_to_root_tape(self, store):
        """Appending entries to a root tape assigns sequential entry IDs."""
        entry_a = make_entry(0)
        entry_b = make_entry(1)

        await store.append("main", entry_a)
        await store.append("main", entry_b)

        assert entry_a.id == 0
        assert entry_b.id == 1
        assert await store.read("main") == [entry_a, entry_b]

    @pytest.mark.asyncio
    async def test_fetch_all_root_tape(self, store):
        """fetch_all returns entries for a root tape."""
        entries = [make_entry(i) for i in range(3)]
        for e in entries:
            await store.append("main", e)

        result = await store.fetch_all(TapeQuery(tape="main", store=store))
        assert len(result) == 3
        assert [e.id for e in result] == [0, 1, 2]
        assert result == entries

    @pytest.mark.asyncio
    async def test_list_tapes(self, store):
        """list_tapes returns correct tape names in various states."""
        assert await store.list_tapes() == []

        await store.append("alpha", make_entry(0))
        assert set(await store.list_tapes()) == {"alpha"}

        await store.append("beta", make_entry(0))
        assert set(await store.list_tapes()) == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_list_tapes_ext(self, store):
        """list_tapes_ext returns tuples sorted by created DESC."""
        assert await store.list_tapes_ext() == []

        await store.append("alpha", make_entry(0))
        await store.append("beta", make_entry(0))

        tapes = await store.list_tapes_ext()
        names = [t[0] for t in tapes]
        assert set(names) == {"alpha", "beta"}
        # Verify created dates are present and look like ISO timestamps
        for name, meta in tapes:
            created = meta["created"]
            assert "T" in created
            assert "1970-01-01" not in created  # New tapes should have real timestamps

    @pytest.mark.asyncio
    async def test_reset_tape(self, store):
        """Resetting a tape archives old data and creates a new empty tape."""
        for i in range(3):
            await store.append("main", make_entry(i))

        await store.reset("main")
        assert await store.read("main") == []

        # Old data archived
        tapes = await store.list_tapes()
        archived = [t for t in tapes if t.startswith("main_archived_")]
        assert len(archived) == 1
        assert len(await store.read(archived[0])) == 3

    @pytest.mark.asyncio
    async def test_reset_nonexistent_raises(self, store):
        """reset() raises ValueError if tape doesn't exist."""
        with pytest.raises(RepublicError, match="does not exist"):
            await store.reset("missing")

    @pytest.mark.asyncio
    async def test_read_empty_tape(self, store):
        """Reading a tape with no entries returns an empty list."""
        await store.create("main")
        result = await store.read("main")
        assert result == []

    @pytest.mark.asyncio
    async def test_read_nonexistent_tape(self, store):
        """Reading a tape that has never been created returns None."""
        result = await store.read("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_duplicate_tape_name(self, store):
        """Appending to the same tape name doesn't create duplicates."""
        await store.append("main", make_entry(0))
        await store.append("main", make_entry(1))

        assert len(await store.list_tapes()) == 1
        assert await store.list_tapes() == ["main"]
        assert len(await store.read("main")) == 2

    @pytest.mark.asyncio
    async def test_entry_id_monotonicity(self, store):
        """Entry IDs always increase by exactly 1."""
        for i in range(5):
            await store.append("main", make_entry(i))

        entries = await store.read("main")
        ids = [e.id for e in entries]
        assert ids == [0, 1, 2, 3, 4]
        assert len(set(ids)) == len(ids)  # No duplicates

    @pytest.mark.asyncio
    async def test_auto_assigned_entry_ids(self, store):
        """append() auto-assigns sequential entry IDs without explicit id."""
        entry = TapeEntry(
            id=-1,  # Should be ignored
            kind="message",
            payload={"role": "user", "content": "hello"},
            date="2026-05-01T12:00:00+00:00",
        )

        await store.append("main", entry)
        await store.append("main", entry)

        entries = await store.read("main")
        assert [e.id for e in entries] == [0, 1]

    @pytest.mark.asyncio
    async def test_fork_auto_assigns_correct_ids(self, store):
        """After fork, child tape auto-assigns IDs continuing from fork point."""
        for i in range(3):
            await store.append("parent", make_entry(i))

        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")

        # Child should auto-assign starting from 3
        await store.append("child", make_entry(-1))
        await store.append("child", make_entry(-1))

        entries = await store.read("child")
        assert [e.id for e in entries] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Fork Operations
# ---------------------------------------------------------------------------

class TestMigration:

    @pytest.mark.asyncio
    async def test_new_tape_has_created(self, store):
        """Newly created tapes have a created timestamp."""
        await store.create("fresh")
        tapes = await store.list_tapes_ext()
        assert len(tapes) == 1
        name, meta = tapes[0]
        assert name == "fresh"
        assert "T" in meta["created"]
        assert "1970-01-01" not in meta["created"]

    @pytest.mark.asyncio
    async def test_fork_inherits_created(self, store):
        """Forked tapes have their own created timestamp."""
        await store.append("parent", make_entry(0))
        entries = await store.read("parent")
        await store.fork("parent", entries[-1].id, "child")

        tapes = await store.list_tapes_ext()
        names = {t[0] for t in tapes}
        assert names == {"parent", "child"}
        for name, meta in tapes:
            assert "T" in meta["created"]
            assert "1970-01-01" not in meta["created"]


class TestForkOperations:

    @pytest.mark.asyncio
    async def test_fork_creates_child(self, store):
        """Forking creates a new tape with correct metadata."""
        for i in range(3):
            await store.append("parent", make_entry(i))

        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")

        assert "parent" in await store.list_tapes()
        assert "child" in await store.list_tapes()
        assert len(await store.read("child")) == 3

    @pytest.mark.asyncio
    async def test_fork_shares_parent_entries(self, store):
        """A forked tape can read all parent entries up to the fork point."""
        entries = [make_entry(i) for i in range(3)]
        for e in entries:
            await store.append("parent", e)

        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")

        assert await store.read("child") == entries

    @pytest.mark.asyncio
    async def test_fork_independent_appends(self, store):
        """Appending to a child doesn't affect the parent."""
        entries = [make_entry(i) for i in range(2)]
        for e in entries:
            await store.append("parent", e)

        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(2))

        assert await store.read("parent") == entries
        assert len(await store.read("child")) == 3
        await assert_parent_unchanged(store, "parent", entries)

    @pytest.mark.asyncio
    async def test_fork_parent_unchanged(self, store):
        """Parent entries remain exactly the same after forking and child writes."""
        for i in range(3):
            await store.append("parent", make_entry(i))
        parent_before = await store.read("parent")

        await store.fork("parent", parent_before[-1].id, "child")
        for i in range(2):
            await store.append("child", make_entry(i + 3))

        parent_after = await store.read("parent")
        assert parent_after == parent_before
        await assert_parent_unchanged(store, "parent", parent_before)

    @pytest.mark.asyncio
    async def test_nested_fork(self, store):
        """Forking a fork creates a three-level tree with correct visibility."""
        await store.append("root", make_entry(0))
        await store.append("root", make_entry(1))
        root_entries = await store.read("root")
        await store.fork("root", root_entries[-1].id, "level1")
        await store.append("level1", make_entry(2))

        level1_entries = await store.read("level1")
        await store.fork("level1", level1_entries[-1].id, "level2")
        await store.append("level2", make_entry(3))

        assert await store.read("root") == [make_entry(i) for i in range(2)]
        assert await store.read("level1") == [make_entry(i) for i in range(3)]
        assert await store.read("level2") == [make_entry(i) for i in range(4)]
        assert_merged_view_valid(await store.read("level2"))

    @pytest.mark.asyncio
    async def test_fork_at_empty_tape(self, store):
        """Forking a tape with no entries raises an error."""
        await store.create("empty")

        with pytest.raises(RepublicError):
            await store.fork("empty", 0, "empty_fork")

    @pytest.mark.asyncio
    async def test_fork_nonexistent_source(self, store):
        """Forking from a nonexistent source raises an appropriate error."""
        with pytest.raises(RepublicError):
            await store.fork("missing", 0, "child")


# ---------------------------------------------------------------------------
# Merged View
# ---------------------------------------------------------------------------

class TestMergedView:

    @pytest.mark.asyncio
    async def test_merged_view_monotonic_ids(self, store):
        """Entry IDs in merged view are continuous (no gaps)."""
        for i in range(3):
            await store.append("parent", make_entry(i))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        for i in range(2):
            await store.append("child", make_entry(i + 3))

        entries = await store.read("child")
        assert [e.id for e in entries] == [0, 1, 2, 3, 4]
        assert_merged_view_valid(entries)

    @pytest.mark.asyncio
    async def test_merged_view_no_gaps(self, store):
        """No entry IDs are missing in the merged view."""
        for i in range(5):
            await store.append("parent", make_entry(i))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        for i in range(3):
            await store.append("child", make_entry(i + 5))

        entries = await store.read("child")
        ids = [e.id for e in entries]
        assert ids == list(range(8))

    @pytest.mark.asyncio
    async def test_merged_view_correct_order(self, store):
        """Parent entries appear before child entries."""
        await store.append("parent", make_entry(0))
        await store.append("parent", make_entry(1))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(2))
        await store.append("child", make_entry(3))

        entries = await store.read("child")
        assert [e.id for e in entries] == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_merged_view_with_anchors(self, store):
        """Anchor filtering works correctly on forked tapes."""
        await store.append("parent", make_entry(0))
        await store.append("parent", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("parent", make_entry(2))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(3))

        result = await store.fetch_all(TapeQuery(tape="child", store=store).after_anchor("a1"))
        assert [e.id for e in result] == [2, 3]

    @pytest.mark.asyncio
    async def test_merged_view_parent_appends_visible(self, store):
        """Parent appends after fork are NOT visible to child."""
        await store.append("parent", make_entry(0))
        await store.append("parent", make_entry(1))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")

        await store.append("parent", make_entry(2))

        assert [e.id for e in await store.read("child")] == [0, 1]
        assert [e.id for e in await store.read("parent")] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Query Filtering
# ---------------------------------------------------------------------------

class TestQueryFiltering:

    @pytest.mark.asyncio
    async def test_fetch_with_kinds_filter(self, store):
        """fetch_all filters entries by kind."""
        await store.append("main", make_entry(0, kind="message"))
        await store.append("main", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("main", make_entry(2, kind="message"))

        result = await store.fetch_all(TapeQuery(tape="main", store=store).kinds("message"))
        assert [e.id for e in result] == [0, 2]
        assert all(e.kind == "message" for e in result)

    @pytest.mark.asyncio
    async def test_fetch_with_limit(self, store):
        """fetch_all respects the limit parameter."""
        for i in range(5):
            await store.append("main", make_entry(i))

        result = await store.fetch_all(TapeQuery(tape="main", store=store).limit(2))
        assert len(result) == 2
        assert [e.id for e in result] == [0, 1]

    @pytest.mark.asyncio
    async def test_fetch_with_after_anchor(self, store):
        """fetch_all filters entries after a given anchor."""
        await store.append("main", make_entry(0))
        await store.append("main", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("main", make_entry(2))
        await store.append("main", TapeEntry(id=3, kind="anchor", payload={"name": "a2"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("main", make_entry(4))

        result = await store.fetch_all(TapeQuery(tape="main", store=store).after_anchor("a1"))
        assert [e.id for e in result] == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_fetch_combined_filters(self, store):
        """Kinds, limit, and after_anchor can be combined."""
        await store.append("main", make_entry(0, kind="message"))
        await store.append("main", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("main", make_entry(2, kind="message"))
        await store.append("main", make_entry(3, kind="event"))
        await store.append("main", TapeEntry(id=4, kind="anchor", payload={"name": "a2"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("main", make_entry(5, kind="message"))

        result = await store.fetch_all(
            TapeQuery(tape="main", store=store).kinds("message").after_anchor("a1").limit(1)
        )
        assert [e.id for e in result] == [2]

    @pytest.mark.asyncio
    async def test_fetch_all_order_on_forked_tape(self, store):
        """fetch_all returns entries in chronological order across forks."""
        await store.append("parent", make_entry(0))
        await store.append("parent", make_entry(1))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(2))
        await store.append("child", make_entry(3))

        result = await store.fetch_all(TapeQuery(tape="child", store=store))
        assert [e.id for e in result] == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_fetch_all_limit_on_forked_tape(self, store):
        """fetch_all limit truncates from the latest end on forked tapes."""
        await store.append("parent", make_entry(0))
        await store.append("parent", make_entry(1))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(2))
        await store.append("child", make_entry(3))

        result = await store.fetch_all(TapeQuery(tape="child", store=store).limit(2))
        assert [e.id for e in result] == [0, 1]


# ---------------------------------------------------------------------------
# Anchor-specific tests
# ---------------------------------------------------------------------------

class TestAnchors:

    @pytest.mark.asyncio
    async def test_after_anchor_on_forked_tape(self, store):
        """after_anchor works correctly on forked tapes."""
        await store.append("parent", make_entry(0))
        await store.append("parent", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("parent", make_entry(2))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        await store.append("child", make_entry(3))
        await store.append("child", make_entry(4))

        result = await store.fetch_all(TapeQuery(tape="child", store=store).after_anchor("a1"))
        assert [e.id for e in result] == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_anchor_shadowing_rejected(self, store):
        """Child cannot shadow parent anchor — merged view uniqueness (I4)."""
        await store.append("parent", make_entry(0))
        await store.append("parent", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("parent", make_entry(2))
        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")
        # Child cannot redefine anchor "a1" — would violate I4
        with pytest.raises(RepublicError):
            await store.append("child", TapeEntry(id=3, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))

    @pytest.mark.asyncio
    async def test_append_anchor_creates_anchor_row(self, store):
        """Appending an anchor entry creates a row in the anchors table."""
        await store.append("main", TapeEntry(id=0, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))

        # Verify anchor exists by querying after it
        result = await store.fetch_all(TapeQuery(tape="main", store=store).after_anchor("a1"))
        assert result == []

        # Add another entry and verify after_anchor works
        await store.append("main", make_entry(1))
        result = await store.fetch_all(TapeQuery(tape="main", store=store).after_anchor("a1"))
        assert [e.id for e in result] == [1]

    @pytest.mark.asyncio
    async def test_after_anchor_in_grandparent(self, store):
        """after_anchor resolves anchor in grandparent tape through nested forks."""
        # root: [msg0, anchor(a1), msg1]
        await store.append("root", make_entry(0))
        await store.append("root", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
        await store.append("root", make_entry(2))
        root_entries = await store.read("root")

        # level1 fork from root
        await store.fork("root", root_entries[-1].id, "level1")
        await store.append("level1", make_entry(3))
        level1_entries = await store.read("level1")

        # level2 fork from level1
        await store.fork("level1", level1_entries[-1].id, "level2")
        await store.append("level2", make_entry(4))

        # Query level2 for entries after anchor "a1" (which is in root)
        result = await store.fetch_all(TapeQuery(tape="level2", store=store).after_anchor("a1"))
        assert [e.id for e in result] == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_duplicate_anchor_name_raises(self, store):
        """Duplicate anchor names on the same tape should raise ValueError."""
        await store.append("main", TapeEntry(id=0, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))

        with pytest.raises(RepublicError):
            await store.append("main", TapeEntry(id=1, kind="anchor", payload={"name": "a1"}, date="2026-05-01T12:00:00+00:00"))
