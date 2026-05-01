"""Performance benchmarks for ForkTapeStore.

These tests verify that critical operations meet performance thresholds.
They use time.perf_counter() for high-resolution timing.

Thresholds:
  - Fork speed: < 10ms for 1000-entry tape
  - Read merged view (3-level fork): < 50ms
  - Append throughput (100 entries): < 100ms total
  - Large tape read (10000 entries): < 100ms
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

import pytest
from republic.tape.entries import TapeEntry

from bub_sf.store.fork_store import SQLiteForkTapeStore


def make_entry(entry_id: int) -> TapeEntry:
    """Create a TapeEntry for benchmarking."""
    return TapeEntry(
        id=entry_id,
        kind="message",
        payload={"role": "user", "content": f"message-{entry_id}", "index": entry_id},
        date="2026-05-01T12:00:00+00:00",
    )


async def abenchmark(
    operation: Callable[[], Awaitable[None]],
    threshold_ms: float,
    warmup: int = 1,
    iterations: int = 5,
) -> tuple[float, str]:
    """Run an async benchmark and return (median_ms, status).

    Status is one of: "PASS", "WARN", "FAIL".
    """
    # Warmup
    for _ in range(warmup):
        await operation()

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await operation()
        elapsed_ms = (time.perf_counter() - start) * 1000
        times.append(elapsed_ms)

    median = sorted(times)[len(times) // 2]

    if median < threshold_ms * 0.8:
        status = "PASS"
    elif median < threshold_ms * 1.0:
        status = "WARN"
    else:
        status = "FAIL"

    return median, status


class TestPerformanceThresholds:
    """Performance validation tests."""

    @pytest.mark.asyncio
    async def test_fork_speed(self, tmp_path):
        """Fork a tape with 1000 entries. Should be < 10ms."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")

        # Setup: create a tape with 1000 entries
        for i in range(1000):
            await store.append("parent", make_entry(i))

        counter = [0]

        async def fork_once():
            name = f"child_{counter[0]}"
            counter[0] += 1
            parent_entries = await store.read("parent")
            await store.fork("parent", parent_entries[-1].id, name)

        median_ms, status = await abenchmark(
            fork_once,
            threshold_ms=10.0,
        )

        print(f"\n  Fork speed (1000 entries): {median_ms:.3f}ms [{status}]")
        assert status != "FAIL", f"Fork too slow: {median_ms:.3f}ms > 10ms threshold"
        await store.close()

    @pytest.mark.asyncio
    async def test_read_merged_view(self, tmp_path):
        """Read a 3-level fork (root: 1000, parent: 500, child: 200). Should be < 50ms."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")

        # Setup: root tape with 1000 entries
        for i in range(1000):
            await store.append("root", make_entry(i))

        root_entries = await store.read("root")
        await store.fork("root", root_entries[-1].id, "parent")

        # Parent adds 500 entries
        for i in range(500):
            await store.append("parent", make_entry(1000 + i))

        parent_entries = await store.read("parent")
        await store.fork("parent", parent_entries[-1].id, "child")

        # Child adds 200 entries
        for i in range(200):
            await store.append("child", make_entry(1500 + i))

        median_ms, status = await abenchmark(
            lambda: store.read("child"),
            threshold_ms=50.0,
        )

        print(f"\n  Read merged view (3-level, 1700 entries): {median_ms:.3f}ms [{status}]")
        assert status != "FAIL", f"Read merged too slow: {median_ms:.3f}ms > 50ms threshold"
        await store.close()

    @pytest.mark.asyncio
    async def test_append_throughput(self, tmp_path):
        """Append 100 entries. Should be < 100ms total."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")
        entries = [make_entry(i) for i in range(100)]

        async def append_all():
            for e in entries:
                await store.append("main", e)

        median_ms, status = await abenchmark(
            append_all,
            threshold_ms=100.0,
            iterations=3,
        )

        throughput = 100 / (median_ms / 1000)
        print(f"\n  Append throughput (100 entries): {median_ms:.3f}ms [{status}] ({throughput:.0f} ops/sec)")
        assert status != "FAIL", f"Append too slow: {median_ms:.3f}ms > 100ms threshold"
        await store.close()

    @pytest.mark.asyncio
    async def test_large_tape_read(self, tmp_path):
        """Read 10,000 entries from root tape. Should be < 100ms."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")

        # Setup: create a tape with 10,000 entries
        for i in range(10000):
            await store.append("main", make_entry(i))

        median_ms, status = await abenchmark(
            lambda: store.read("main"),
            threshold_ms=100.0,
        )

        print(f"\n  Large tape read (10000 entries): {median_ms:.3f}ms [{status}]")
        assert status != "FAIL", f"Large read too slow: {median_ms:.3f}ms > 100ms threshold"
        await store.close()

    @pytest.mark.asyncio
    async def test_fork_speed_scaling(self, tmp_path):
        """Fork time should be roughly constant regardless of tape size."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")

        sizes = [100, 1000, 5000]
        results = []
        counters = {size: 0 for size in sizes}

        for size in sizes:
            # Create fresh tape
            tape_name = f"tape_{size}"
            for i in range(size):
                await store.append(tape_name, make_entry(i))

            tn_entries = await store.read(tape_name)
            last_entry_id = tn_entries[-1].id

            async def fork_for_size(tn=tape_name, sz=size, entry_id=last_entry_id):
                name = f"{tn}_fork_{counters[sz]}"
                counters[sz] += 1
                await store.fork(tn, entry_id, name)

            median_ms, status = await abenchmark(
                fork_for_size,
                threshold_ms=10.0,
                iterations=3,
            )
            results.append((size, median_ms, status))

        print("\n  Fork scaling:")
        for size, ms, status in results:
            print(f"    {size:5d} entries: {ms:.3f}ms [{status}]")

        # Verify all pass or warn
        for size, ms, status in results:
            assert status != "FAIL", f"Fork at {size} entries too slow: {ms:.3f}ms"
        await store.close()

    @pytest.mark.asyncio
    async def test_read_scaling(self, tmp_path):
        """Read time should scale linearly with visible entries."""
        store = await SQLiteForkTapeStore.create_store(tmp_path / "perf.db")

        sizes = [1000, 5000, 10000]
        results = []

        for size in sizes:
            tape_name = f"tape_{size}"
            for i in range(size):
                await store.append(tape_name, make_entry(i))

            median_ms, status = await abenchmark(
                lambda tn=tape_name: store.read(tn),
                threshold_ms=100.0,
                iterations=3,
            )
            results.append((size, median_ms))

        print("\n  Read scaling:")
        for size, ms in results:
            per_entry_us = (ms * 1000) / size
            print(f"    {size:5d} entries: {ms:.3f}ms ({per_entry_us:.2f} us/entry)")

        # Verify roughly linear scaling: 10x entries should take ~10x time
        if len(results) >= 2:
            ratio = results[-1][1] / results[0][1]
            expected_ratio = results[-1][0] / results[0][0]
            # Allow 3x variance from linear
            assert ratio < expected_ratio * 3, (
                f"Read scaling non-linear: {results[0][0]} entries = {results[0][1]:.3f}ms, "
                f"{results[-1][0]} entries = {results[-1][1]:.3f}ms (ratio={ratio:.2f}x, expected ~{expected_ratio:.0f}x)"
            )
        await store.close()
