# 57: Idle-Triggered Auto-Compaction

**Date:** 2026-05-11
**Status:** Implementation in progress
**Area:** `bub/src/bub/channels/idle_tracker.py`, `bub/src/bub/channels/telegram.py`

## Problem

Context compaction (tape handoff + summary) currently requires explicit user/SystemF action. For long-running sessions across multiple inbound messages, tape grows unboundedly until something triggers compaction. We want **automatic compaction** when a session becomes idle.

## Design: Channel-Side Idle Detection + Idle Messages

Session is implicit in Bub — there is no `Session` object. The framework processes messages carrying `session_id`. Rather than introducing session lifecycle management, we extend the message-oriented pipeline.

### IdleTracker

`IdleTracker` is a utility that channels integrate with to track session activity and emit idle signals through the normal message pipeline.

**Responsibility:**
- Track per-session last-active timestamp
- Fire callback when session has been idle for configured duration
- Clean up on shutdown

**Timer Abstraction:**
```python
class TimerHandle(Protocol):
    def cancel(self) -> None: ...

class Timer(Protocol):
    async def call_later(self, delay: float, callback: Callable[[], None]) -> TimerHandle: ...

class AsyncIOTimer:
    async def call_later(self, delay: float, callback: Callable[[], None]) -> asyncio.TimerHandle:
        loop = asyncio.get_running_loop()
        return loop.call_later(delay, callback)
```

**IdleTracker Interface:**
```python
class IdleTracker:
    def __init__(self, timer: Timer) -> None:
        self._timer = timer
        self._timers: dict[str, TimerHandle] = {}
        self._sessions: dict[str, tuple[Callable[[], None], float]] = {}

    async def register(
        self,
        session_id: str,
        callback: Callable[[], None],
        idle_duration: float,
    ) -> None:
        """Register session. Does NOT schedule timer — only stores callback and duration."""

    async def heartbeat(self, session_id: str) -> None:
        """Cancel existing timer and reschedule. Only schedules on first call."""

    async def unregister(self, session_id: str) -> None:
        """Cancel timer and remove session."""

    def has_session(self, session_id: str) -> bool:
        """Check if session is registered."""

    async def start(self) -> None:
        """Async initialization."""

    async def shutdown(self) -> None:
        """Cancel all timers, clear all sessions."""
```

**Key Design Decision:**
- `register()` stores session config but does NOT schedule timer
- `heartbeat()` is the only place that schedules/resets timers
- This separates registration (one-time setup) from activity tracking (called per-message)

### Channel Integration (TelegramChannel)

```python
class TelegramChannel(Channel):
    def __init__(self, on_receive: MessageHandler) -> None:
        self._idle_tracker = IdleTracker.create()

    async def start(self, stop_event: asyncio.Event) -> None:
        await self._idle_tracker.start()

    async def _on_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        session_id = f"{self.name}:{chat_id}"
        
        # Register idle callback on first message (no timer scheduled yet)
        if not self._idle_tracker.has_session(session_id):
            await self._idle_tracker.register(
                session_id,
                lambda: asyncio.create_task(self._on_session_idle(session_id)),
                60.0,
            )
        
        # Heartbeat resets idle timer for this session
        await self._idle_tracker.heartbeat(session_id)
        
        # Process normal message through framework
        await self._on_receive(await self._build_message(update.message))

    async def _on_session_idle(self, session_id: str) -> None:
        """Send idle message without lifespan (no typing indicator)."""
        chat_id = session_id.split(":", 1)[1]
        idle_message = ChannelMessage(
            session_id=session_id,
            channel=self.name,
            chat_id=chat_id,
            content="",
            kind="idle",
            lifespan=None,  # No typing indicator for idle messages
        )
        await self._on_receive(idle_message)
```

**Key Design Decision:**
- Normal messages call `heartbeat()` directly in `_on_message`
- Idle messages bypass `heartbeat()` (they ARE the idle signal)
- Idle messages have no `lifespan` (no typing indicator)

### Framework/Hook Reception

The idle message flows through `process_inbound` like any other message. Hooks decide how to handle it:

```python
class BuiltinImpl:
    @hookimpl
    async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
        if message.kind == "idle":
            return "__IDLE__"
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

## Compaction Strategy

The receiver (hooks) decides what compaction means:

- **`BUB_AUTO_COMPACT_STRATEGY=simple`** — call `handoff("auto-compact")` only (fast, no LLM)
- **`BUB_AUTO_COMPACT_STRATEGY=summary`** — fork tape, summarize via LLM, handoff, append summary (requires `tape_handoff` primop)
- **Threshold:** only compact if `entries_since_last_anchor > N` or `token_count > M` (read from `TapeService.info()`)

## Open Questions

1. **Should idle messages appear in the tape?** If `kind="idle"` is saved to tape, it becomes part of context. Might be useful for debugging, or might pollute context.
2. **Grace period?** If user sends messages sporadically (every 30-60s), idle may fire repeatedly. Configurable per-channel.
3. **Error handling in compaction?** If compaction fails (LLM error, tape error), log and continue. Do not crash the session.

## Implementation Order

1. ✅ Implement `IdleTracker` utility class
2. ✅ Integrate `IdleTracker` into `TelegramChannel`
3. ⬜ Handle `kind="idle"` in `BuiltinImpl` hooks
4. ⬜ Update `MessageKind` Literal to include `"idle"`
5. ⬜ Add configuration (`BUB_AUTO_COMPACT_STRATEGY`, `BUB_AUTO_COMPACT_THRESHOLD`, channel idle timeout)
6. ✅ Tests: verify idle fires after timeout, verify no compact below threshold

## References

- `changes/56-per-session-message-serialization.md` — session queue serialization (prerequisite)
- `changes/41-tape-handoff-primop.md` — tape handoff primitive for full compaction
- `changes/34-channel-events-design.md` — channel events design
- `bub/src/bub/channels/manager.py` — ChannelManager
- `bub/src/bub/builtin/tape.py` — TapeService
