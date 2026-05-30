"""Unit tests for SessionInfo.ensure_task sequencing."""

from __future__ import annotations

import asyncio

from bub_sf.hook import TaskBase


def make_controlled_task(event: asyncio.Event, log: list[str], name: str):
    """Return a task_fn that blocks on *event* then appends *name* to *log*."""
    async def task_fn() -> None:
        await event.wait()
        log.append(name)
    return task_fn


async def test_single_task_runs_and_clears():
    """A single task runs and active_task is None afterwards."""
    si = TaskBase()
    done = asyncio.Event()
    log: list[str] = []

    await si.ensure_task(make_controlled_task(done, log, "A"))
    assert si.active_task is not None  # task is pending

    done.set()
    await asyncio.gather(si.active_task)

    assert log == ["A"]
    # allow the cleanup callback inside the task to run
    await asyncio.sleep(0)
    assert si.active_task is None


async def test_two_tasks_run_in_order():
    """Second task waits for first and they execute in submission order."""
    si = TaskBase()
    gate1 = asyncio.Event()
    gate2 = asyncio.Event()
    log: list[str] = []

    await si.ensure_task(make_controlled_task(gate1, log, "A"))
    await si.ensure_task(make_controlled_task(gate2, log, "B"))

    final_task = si.active_task
    assert log == []  # neither has run yet

    gate1.set()
    # yield to let T1 finish and T2 start waiting on gate2
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert log == ["A"]  # T1 done, T2 waiting

    gate2.set()
    await asyncio.gather(final_task)

    assert log == ["A", "B"]
    await asyncio.sleep(0)
    assert si.active_task is None


async def test_three_tasks_run_in_order():
    """Three concurrent submits all run in order; only the last clears active_task."""
    si = TaskBase()
    gates = [asyncio.Event() for _ in range(3)]
    log: list[str] = []
    names = ["A", "B", "C"]

    for gate, name in zip(gates, names):
        await si.ensure_task(make_controlled_task(gate, log, name))

    final_task = si.active_task

    # release one at a time and verify ordering
    for i, gate in enumerate(gates):
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert log == names[: i + 1], f"after gate {i}: {log}"

    await asyncio.gather(final_task)
    await asyncio.sleep(0)
    assert si.active_task is None


async def test_early_tasks_do_not_clear_active_task_prematurely():
    """T1 completing must not clear active_task when T2/T3 are still pending."""
    si = TaskBase()
    gates = [asyncio.Event() for _ in range(3)]
    log: list[str] = []

    for gate, name in zip(gates, ["A", "B", "C"]):
        await si.ensure_task(make_controlled_task(gate, log, name))

    # let T1 finish
    gates[0].set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # active_task must still be set (T2 and T3 are queued)
    assert si.active_task is not None, "active_task was cleared prematurely by T1"

    # finish the rest
    gates[1].set()
    gates[2].set()
    await asyncio.gather(si.active_task)
    await asyncio.sleep(0)
    assert si.active_task is None


async def test_new_task_after_completion_runs_independently():
    """A task submitted after all previous tasks complete starts fresh."""
    si = TaskBase()
    gate1 = asyncio.Event()
    gate2 = asyncio.Event()
    log: list[str] = []

    await si.ensure_task(make_controlled_task(gate1, log, "A"))
    gate1.set()
    await asyncio.gather(si.active_task)
    await asyncio.sleep(0)
    assert si.active_task is None  # fully settled

    # submit a second task after the first has fully completed
    await si.ensure_task(make_controlled_task(gate2, log, "B"))
    assert si.active_task is not None

    gate2.set()
    await asyncio.gather(si.active_task)
    await asyncio.sleep(0)

    assert log == ["A", "B"]
    assert si.active_task is None
