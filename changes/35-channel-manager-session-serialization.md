# 35: Channel Manager Session Serialization

**Date:** 2026-05-05
**Status:** Todo
**Area:** `bub/src/bub/channels/manager.py`

## Problem

`ChannelManager` uses a single `asyncio.Queue` and spawns independent `asyncio.Task` per inbound message with no per-session ordering. Multiple messages from the same session (same tape) can be processed concurrently, causing:

1. **Interleaved agent turns** — the same "brain" (tape) runs multiple LLM loops simultaneously, producing conflicting or duplicate outputs.
2. **Race conditions** — tape fork/merge operations can overlap, corrupting context.
3. **Duplicate outbound messages** — observed in Telegram where both the main tape continuation and a temp tape independently send replies.

## Current Behavior

```
on_receive(msg) → _messages.put(msg)
listen_and_run():
    msg = await _messages.get()
    task = create_task(process_inbound(msg))  # no coordination between tasks
```

Sessions share the same tape. When two messages arrive for the same session before the first finishes, both start independent agent loops on the same tape.

## Proposed Design

Enforce **per-session serialization** in `ChannelManager`: at most one `process_inbound` task runs per session at a time. Subsequent messages for the same session are queued until the current task completes.

### Option A: Per-Session Queue

Replace the single `_messages` queue with per-session queues. A "dispatcher" task per session pulls from its queue serially.

```python
class ChannelManager:
    def __init__(self, ...):
        self._session_queues: dict[str, asyncio.Queue[ChannelMessage]] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}

    async def on_receive(self, message: ChannelMessage):
        session_id = message.session_id
        if session_id not in self._session_queues:
            q = asyncio.Queue()
            self._session_queues[session_id] = q
            # Start a session worker
            self._session_tasks[session_id] = asyncio.create_task(
                self._session_worker(session_id, q)
            )
        await self._session_queues[session_id].put(message)

    async def _session_worker(self, session_id: str, queue: asyncio.Queue):
        while True:
            message = await queue.get()
            try:
                await self.framework.process_inbound(message, self._stream_output)
            except Exception:
                logger.exception("session.worker.error session_id={}", session_id)
            finally:
                queue.task_done()
```

### Option B: Lock-Based Serialization (simpler)

Keep the single queue and dispatch loop, but add a per-session lock. New messages for a locked session are re-queued.

```python
class ChannelManager:
    def __init__(self, ...):
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def _process_serialized(self, message: ChannelMessage):
        session_id = message.session_id
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self.framework.process_inbound(message, self._stream_output)
```

**Issue with Option B:** re-queuing blocks the dispatch loop or requires spawning tasks that wait on the lock, which is equivalent to Option A.

### Recommendation

**Option A** is cleaner — per-session worker tasks with per-session queues. Benefits:

- Clear ownership: one task owns the session at a time
- Natural backpressure: queue grows if messages arrive faster than processing
- Easy cleanup: when a session worker drains its queue and sits idle, it can be garbage collected
- Preserves cross-session concurrency: different sessions still run in parallel

### Cleanup

Idle session workers should be cleaned up after a timeout:

```python
async def _session_worker(self, session_id: str, queue: asyncio.Queue):
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), timeout=self._idle_timeout)
        except asyncio.TimeoutError:
            break  # Clean up idle worker
        # ... process message ...
    self._session_queues.pop(session_id, None)
    self._session_tasks.pop(session_id, None)
```

## Scope

- `bub/src/bub/channels/manager.py` — main change
- Tests: verify messages from same session are serialized, different sessions run concurrently
