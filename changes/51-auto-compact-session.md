# 51: Auto-Compact at Session Level

**Date:** 2026-05-11
**Status:** Design in progress
**Area:** `bub/src/bub/channels/` (IdleTracker, channel integration), `bub/src/bub/builtin/agent.py` (turn lock), `bub/src/bub/builtin/hook_impl.py` (idle handling)

## Problem

Context compaction (tape handoff + summary) currently requires explicit user/SystemF action. For long-running sessions across multiple inbound messages, tape grows unboundedly until something triggers compaction. We want **automatic compaction** when a session becomes idle.

## Key Constraints

1. **Compact happens at session level** — the tape is scoped to a session_id
2. **Channel assigns session_id** — each inbound `ChannelMessage` carries the session identifier that maps to a tape
3. **No channel-side serialization** — ChannelManager must NOT queue or block messages per session.
4. **Two prerequisites for auto-compact:**
   - **Session queue in message processor** — BuiltinImpl/run_model hook maintains per-session queues; agent consumes serially from its queue
   - **Idle detection + registration** — when a session's queue empties and stays empty, trigger compaction

## Architecture: Message-Oriented Idle Detection

### Design Principle

Session is implicit in Bub — there is no `Session` object. The framework processes messages carrying `session_id`. Rather than introducing session lifecycle management into the framework, we extend the existing message-oriented pipeline.

**Key insight:** Channels own session identity and activity. They can track when a session was last active and send an **idle message** through the normal pipeline. The receiver (framework/hooks) decides what to do with it.

### IdleTracker

`IdleTracker` is a utility that channels integrate with to track session activity and emit idle signals.

**Responsibility:**
- Track per-session last-active timestamp
- Fire callback when session has been idle for configured duration
- Clean up on shutdown

**Interface:**
```python
class IdleTracker:
    def __init__(self, idle_timeout: float = 60.0):
        self._idle_timeout = idle_timeout
        self._last_active: dict[str, float] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._on_idle: Callable[[str], Coroutine[Any, Any, None]] | None = None

    def set_callback(self, callback: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        self._on_idle = callback

    def bump(self, session_id: str) -> None:
        """Channel calls this on every inbound message for the session."""
        self._last_active[session_id] = asyncio.get_event_loop().time()
        # Cancel existing timer, schedule new one
        if session_id in self._timers:
            self._timers[session_id].cancel()
        self._timers[session_id] = asyncio.get_event_loop().call_later(
            self._idle_timeout, lambda: asyncio.create_task(self._fire_idle(session_id))
        )

    async def _fire_idle(self, session_id: str) -> None:
        if self._on_idle:
            await self._on_idle(session_id)
        self._timers.pop(session_id, None)
        self._last_active.pop(session_id, None)

    def shutdown(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
```

### Channel Integration

Channels that want idle detection integrate with `IdleTracker`:

```python
class TelegramChannel(Channel):
    def __init__(self, ...):
        self._idle_tracker = IdleTracker(idle_timeout=60.0)

    async def start(self, stop_event: asyncio.Event) -> None:
        self._idle_tracker.set_callback(self._on_session_idle)
        # ... existing start logic ...

    async def _on_message(self, update) -> None:
        chat_id = str(update.message.chat.id)
        session_id = f"{self.name}:{chat_id}"
        
        # Bump activity before processing
        self._idle_tracker.bump(session_id)
        
        message = ChannelMessage(session_id=session_id, ...)
        await self._on_receive(message)

    async def _on_session_idle(self, session_id: str) -> None:
        """Send idle message through normal pipeline."""
        idle_message = ChannelMessage(
            session_id=session_id,
            channel=self.name,
            chat_id=session_id.split(":", 1)[1],
            content="",
            kind="idle",
        )
        await self._on_receive(idle_message)
```

### Framework/Hook Reception

The idle message flows through `process_inbound` like any other message. Hooks decide how to handle it:

```python
class BuiltinImpl:
    @hookimpl
    async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
        if message.kind == "idle":
            # Return special prompt or None to short-circuit
            return "__IDLE__"
        # ... normal handling ...

    @hookimpl
    async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
        if prompt == "__IDLE__":
            # Trigger compaction as a turn
            tape_name = get_tape_name(state)
            info = await self.agent.tapes.info(tape_name)
            if info.entries_since_last_anchor > THRESHOLD:
                await self.agent.tapes.handoff(tape_name, name="auto-compact")
                return "Context compacted."
            return "No compaction needed."
        # ... normal handling ...
```

### Session Queue (Serialization Point)

**ChannelManager does NOT serialize.** It continues to dispatch each message as an independent task. Serialization happens in the **message processor** (BuiltinImpl run_model hook):

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

    async def _on_session_idle(self, tape_name: str) -> None:
        """Called when session queue is empty after timeout."""
        # Check threshold, trigger compaction
        pass
```

**Why session queue in message processor:**
- This is where we know which agent/tape handles which session
- Agent can inspect queue length during its turn (`queue.qsize()`) to see if more messages are pending
- If queue is empty mid-turn, agent knows it's the last message
- `_ensure_agent()` starts a worker if none is running; existing worker continues consuming from the same queue
- Works for both `run_model` (blocking) and `run_model_stream` (streaming) since both go through the same queue
- Defense-in-depth: `Agent.run()` also uses a reentrant tape lock

**Inflight visibility for agent:**
During a turn, the agent can check if more messages are queued:

```python
class Agent:
    async def _loop(self, session: TapeSession, prompt: str, state: State, ...) -> str:
        # ... during turn ...
        queue = BuiltinImpl._session_queues.get(session.name)
        pending = queue.qsize() if queue else 0
        if pending == 0:
            # This is the last message in the queue; could trigger handoff here
            pass
```

## Compaction Strategy

The receiver (hooks) decides what compaction means. Options:

- **`BUB_AUTO_COMPACT_STRATEGY=simple`** — call `handoff("auto-compact")` only (fast, no LLM)
- **`BUB_AUTO_COMPACT_STRATEGY=summary`** — fork tape, summarize via LLM, handoff, append summary (requires `tape_handoff` primop)
- **Threshold:** only compact if `entries_since_last_anchor > N` or `token_count > M` (read from `TapeService.info()`)

**Hook design:** A new `on_idle_message` hook or handle `kind="idle"` in existing hooks:

```python
class BuiltinImpl:
    @hookimpl
    async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
        if message.kind == "idle":
            return "__IDLE__"  # signal to run_model
        # ... normal handling ...

    @hookimpl
    async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
        if prompt == "__IDLE__":
            tape_name = get_tape_name(state)
            info = await self.agent.tapes.info(tape_name)
            if info.entries_since_last_anchor > THRESHOLD:
                await self.agent.tapes.handoff(tape_name, name="auto-compact")
                return "Context compacted."
            return "No compaction needed."
        # ... normal handling ...
```

`bub_sf` can override this hook to implement SystemF-based compaction logic.

## Open Questions

1. **Should all channels implement IdleTracker?** CLI might not need it (interactive, short-lived). Telegram definitely does.
2. **Grace period?** If user sends messages sporadically (every 30-60s), idle may fire repeatedly. Configurable per-channel.
3. **Error handling in compaction?** If compaction fails (LLM error, tape error), log and continue. Do not crash the session.
4. **Should idle messages appear in the tape?** If `kind="idle"` is saved to tape, it becomes part of context. Might be useful for debugging, or might pollute context.
5. **How should agent use inflight visibility?** If agent sees inflight messages during its turn, should it abort, merge, or continue? This is agent behavior, not framework behavior.

## Implementation Order

1. Implement per-session queue in `BuiltinImpl.run_model()` / `run_model_stream()` (primary serialization)
2. Add `ReentrantAsyncLock` to `Agent.run()` / `run_stream()` (defense-in-depth)
3. Implement `IdleTracker` utility class
4. Integrate `IdleTracker` into `TelegramChannel` (prototype channel)
5. Handle queue idle timeout in `_session_worker()` — trigger compaction
6. Add configuration (`BUB_AUTO_COMPACT_STRATEGY`, `BUB_AUTO_COMPACT_THRESHOLD`, channel idle timeout)
7. Tests: verify session queue serializes turns, verify idle fires after timeout, verify compaction on idle, verify no compact below threshold

## Design Provenance (Raw Thoughts)

This section captures the thought process and design tensions explored during this change's development. It exists for future maintainers to understand why certain decisions were made and what alternatives were considered.

### Initial Intuition: ChannelManager Does It All

The first instinct was to put everything in `ChannelManager`: per-session queues for serialization + idle detection for auto-compact. Quick approach, but immediately felt wrong because:
- CLI `bub run` and tests bypass `ChannelManager` entirely
- Serialization should work for all entry points, not just gateway mode
- ChannelManager shouldn't own session lifecycle — it's a router

### Realization: Session is Implicit, Not First-Class

Bub has no `Session` object. Session is just a `session_id` string carried by messages. The framework processes messages, not sessions. State is ephemeral (per-turn via `load_state`/`save_state`). The only persistent session artifact is the tape (`session_tape_name(session_id, workspace)`).

This means session lifecycle management cannot be a first-class framework concept without major refactoring. The design must work within the message-oriented paradigm.

### Tension: Where to Serialize?

Three candidate layers for serialization:

1. **ChannelManager** — only covers gateway; CLI/tests bypass it
2. **BubFramework.process_inbound()** — covers all entry points, but streaming is awkward (lock released before stream consumed)
3. **Agent.run() / run_stream()** — covers all entry points; natural turn boundary; but idle detection is awkward (Agent doesn't know when no more messages are coming)

Initial lean toward #2 (framework-level lock), but streaming made it messy. Then considered #3 with a background idle detector.

### Key Insight: Channel is Session Owner, Not Session Manager

Channel assigns `session_id` and knows external context. But:
- Inbound and outbound are separate paths (no 1-1 correspondence)
- Channel cannot directly compact because it doesn't control the turn pipeline
- Channel should **signal** intent, not **execute** compaction

This led to the `IdleTracker` idea: channel tracks activity and sends an `kind="idle"` message through the normal pipeline. The receiver (hooks) decides what to do.

### Tension: We MUST NOT Serialize at Channel Side

Critical realization: The agent may need to know if there are inflight messages **during** its turn. If ChannelManager queues messages, the agent cannot see pending messages until after it finishes. This is a problem for:
- Merging rapid-fire messages into a single turn
- Deciding whether to abort a long-running turn because new messages arrived
- Context-aware compaction ("should I compact or wait for the next message?")

**Decision:** ChannelManager must NOT queue or block. Messages flow freely to the framework. Serialization happens deeper in the stack.

### The Streaming Problem

Attempted to put per-session queues in `BuiltinImpl` (the run_model hook). Works for `run_model` (blocking) via `Future`, but `run_model_stream` returns `AsyncStreamEvents` (generator). Can't queue a generator through a `Future`.

Options:
- **Queue blocking, lock streaming** — inconsistent mechanism
- **Queue both with stream relay** — proxy generator reading from `asyncio.Queue`; adds indirection
- **Serialize at Agent level only** — reentrant lock per tape; no hook queue

**Resolution:** The `_ensure_agent()` pattern with per-session queues handles both blocking and streaming turns uniformly. The worker serializes queue consumption, and Agent-level reentrant lock provides additional safety.

### Resolution: `_ensure_agent()` Pattern

The streaming concern was resolved by the `_ensure_agent()` pattern:
- All turns (blocking and streaming) go through the same per-session queue
- `_ensure_agent()` starts a worker if none exists; otherwise the existing worker continues
- The worker serializes consumption from the queue
- Streaming turns are queued like blocking turns; the worker handles them uniformly
- Agent-level reentrant lock provides defense-in-depth

This gives us the best of both worlds: queue-based serialization for idle detection, plus lock-based safety for tape access.

### Design Philosophy

This change embodies a tension in Bub's architecture: the framework is message-oriented, but the agent is turn-oriented. The session sits awkwardly between them — assigned by channels, consumed by agents, persisted as tapes.

The design principle is: **keep the framework message-oriented, but give the agent tools to reason about session state.** Don't force session lifecycle into the framework where it doesn't belong.

## References

- `changes/35-channel-manager-session-serialization.md` — session serialization design
- `changes/36-session-tape-sync.md` — why serialization is needed
- `changes/41-tape-handoff-primop.md` — tape handoff primitive for full compaction
- `bub/src/bub/channels/manager.py` — ChannelManager
- `bub/src/bub/builtin/agent.py` — Agent turn orchestration
- `bub/src/bub/framework.py` — BubFramework turn pipeline
- `bub/src/bub/builtin/tape.py` — TapeService
