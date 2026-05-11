# 56: Per-Session Message Serialization

**Date:** 2026-05-11
**Status:** Design in progress
**Area:** `bub/src/bub/builtin/agent.py` (turn lock), `bub/src/bub/builtin/hook_impl.py` (session queue)

## Problem

Multiple inbound messages for the same session can arrive concurrently (e.g., rapid user messages, multiple channel events). Without serialization, these trigger overlapping agent turns on the same tape, causing race conditions and corrupted context.

## Design: Message Processor Queue + `_ensure_agent()`

Serialization happens in the **message processor** (the hook implementation that receives messages), not at the channel level. This ensures it works for all entry points (gateway, CLI, tests).

### Session Queue

```python
class BuiltinImpl:
    _session_queues: ClassVar[dict[str, asyncio.Queue]] = {}
    _session_workers: ClassVar[dict[str, asyncio.Task]] = {}

    @hookimpl
    async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
        tape_name = get_tape_name(state)

        # Always queue the turn request
        queue = self._session_queues.setdefault(tape_name, asyncio.Queue())
        fut = asyncio.get_event_loop().create_future()
        await queue.put((prompt, state, fut))

        # Ensure agent worker is running for this session
        self._ensure_agent(tape_name)

        # Wait for this turn's result
        return await fut

    def _ensure_agent(self, tape_name: str) -> None:
        """Start session worker if not already running."""
        if tape_name not in self._session_workers or self._session_workers[tape_name].done():
            self._session_workers[tape_name] = asyncio.create_task(
                self._session_worker(tape_name)
            )

    async def _session_worker(self, tape_name: str) -> None:
        """Consume turns from the session queue serially."""
        agent = self._get_agent()
        queue = self._session_queues[tape_name]
        while True:
            try:
                prompt, state, fut = await asyncio.wait_for(queue.get(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                # Queue empty for IDLE_TIMEOUT → session idle
                await self._on_session_idle(tape_name)
                break

            try:
                result = await agent.run(tape_name=tape_name, prompt=prompt, state=state)
                fut.set_result(result)
            except Exception as exc:
                fut.set_exception(exc)
            finally:
                queue.task_done()

        # Cleanup
        self._session_queues.pop(tape_name, None)
        self._session_workers.pop(tape_name, None)
```

### Defense-in-Depth: Reentrant Tape Lock

Agent.run() also uses a reentrant lock per tape to prevent nested turn issues:

```python
class Agent:
    _tape_locks: dict[str, ReentrantAsyncLock] = {}

    async def run(self, tape_name: str, ...):
        lock = self._tape_locks.setdefault(tape_name, ReentrantAsyncLock())
        async with lock:
            # ... turn execution ...
```

### Inflight Visibility

During a turn, the agent can check if more messages are queued:

```python
class Agent:
    async def _loop(self, session: TapeSession, prompt: str, state: State, ...) -> str:
        # ... during turn ...
        queue = BuiltinImpl._session_queues.get(session.name)
        pending = queue.qsize() if queue else 0
        if pending == 0:
            # This is the last message in the queue
            pass
```

## Why Message Processor, Not ChannelManager

- **All entry points covered**: CLI `bub run` and tests bypass `ChannelManager` entirely
- **Agent knows tape mapping**: Only the message processor knows which agent/tape handles which session
- **Inflight visibility**: Agent can inspect queue length during its turn to see if more messages are pending
- **Channel freedom**: Channels don't need to implement queuing; they just fire messages

## Streaming Support

The `_ensure_agent()` pattern handles both `run_model` (blocking) and `run_model_stream` (streaming) uniformly:
- Both turn types go through the same per-session queue
- The worker serializes consumption from the queue
- Streaming turns are queued like blocking turns; the worker handles them uniformly

## Implementation Order

1. Implement `ReentrantAsyncLock` utility
2. Add `_session_queues` and `_ensure_agent()` to `BuiltinImpl`
3. Implement `_session_worker()` with idle timeout detection
4. Add reentrant lock to `Agent.run()` / `run_stream()`
5. Tests: verify session queue serializes turns, verify no overlapping turns on same tape

## References

- `changes/35-channel-manager-session-serialization.md` — why channel-level serialization was rejected
- `changes/36-session-tape-sync.md` — session-to-tape mapping
- `bub/src/bub/builtin/agent.py` — Agent turn orchestration
- `bub/src/bub/framework.py` — BubFramework turn pipeline
