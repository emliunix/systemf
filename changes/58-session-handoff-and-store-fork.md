# 58: Session-Scoped Tape Operations & Store-Level Fork

**Date:** 2026-05-11  
**Status:** Implemented  
**Area:** `republic/tape/`, `bub/builtin/`, `bub_sf/`

## Problem

`tape.handoff` as a tool breaks the turn structure: the anchor entry is inserted between `tool_call` and `tool_result`, causing `tool_result` messages to lack `tool_call_id` on the next turn (deepseek rejects with `missing field 'tool_call_id'`).

Current `ForkTapeStore` conflates session buffering with actual fork semantics.

## Design

### C: Session as the Core Primitive

A session scopes ALL tape writes. `with session` is the single primitive — it acquires a per-tape lock, marks the tape as active via ContextVar, buffers writes, and flushes atomically on exit.

```python
# republic/tape/session.py
class TapeSession:
    _deferred_entries: list[TapeEntry]

    def __init__(self, name: str, store: AsyncTapeStore, context: TapeContext):
        ...

    def append_entry(self, entry: TapeEntry) -> None:
        """Buffer entry for deferred flush."""
        self._deferred_entries.append(entry)

    def handoff(self, name: str, *, anchor_state: dict[str, Any] | None = None, **meta: Any) -> list[TapeEntry]:
        """Buffer anchor+event entries for deferred flush."""
        ...

    async def append_event(self, name: str, data: dict[str, Any] | None = None, **meta: Any) -> TapeEntry:
        """Immediate write — events are logs, no integrity concern."""
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not exc_val:
            for entry in self._deferred_entries:
                await self._append_entry(entry)
            self._deferred_entries.clear()

# republic/tape/manager.py
class AsyncTapeManager:
    def __init__(self, *, store: AsyncTapeStore) -> None:
        self._tape_store = store

    async def read_messages(self, tape: str, *, context: TapeContext) -> list[dict[str, Any]]:
        ...

    async def append_entry(self, tape: str, entry: TapeEntry) -> None:
        await self._tape_store.append(tape, entry)

    @staticmethod
    def handoff(tape: str, name: str, *, anchor_state: dict[str, Any] | None = None, **meta: Any) -> list[TapeEntry]:
        """Pure constructor — returns entries without writing."""
        ...

# bub/builtin/tape.py
contextvar_session = contextvars.ContextVar[TapeSession | None]("session")

class TapeService:
    _store: AsyncTapeStore
    _framework: BubFramework
    _tape_locks: dict[str, asyncio.Lock]

    @contextlib.asynccontextmanager
    async def session(self, tape_name: str, *, wait: bool = True) -> AsyncGenerator[TapeSession, None]:
        """Two-phase session: bootstrap anchor, then yield session with ContextVar set."""
        if not wait and self._tape_locks[tape_name].locked():
            raise RuntimeError(f"Tape {tape_name} is currently in use")
        async with self._tape_locks[tape_name]:
            async with self._mk_session(tape_name) as session:
                await self._bootstrap(session)  # ensures bootstrap anchor
            async with self._mk_session(tape_name) as session:
                token = contextvar_session.set(session)
                try:
                    yield session
                finally:
                    contextvar_session.reset(token)

    def _mk_session(self, tape_name: str) -> TapeSession:
        """Uses framework hook for TapeContext — respects extensions."""
        return TapeSession(
            name=tape_name,
            store=self._store,
            context=self._framework.build_tape_context(),
        )

    @contextlib.asynccontextmanager
    async def _obtain_session(self, tape_name: str) -> AsyncGenerator[TapeSession, None]:
        """Reuses active session if same tape, else creates temporary session."""
        if (session := contextvar_session.get(None)) is not None and session.name == tape_name:
            yield session
        else:
            async with self.session(tape_name, wait=False) as session:
                yield session

    async def handoff(self, tape_name: str, *, name: str, anchor_state: dict[str, Any] | None = None) -> list[TapeEntry]:
        async with self._obtain_session(tape_name) as session:
            entries = session.handoff(name, anchor_state=anchor_state)
        return entries

    async def append_event(self, tape_name: str, name: str, payload: dict[str, Any], **meta: Any) -> None:
        async with self._obtain_session(tape_name) as session:
            await session.append_event(name=name, data=payload, **meta)

# bub/builtin/agent.py
class Agent:
    async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
        async with self.tapes.session(tape_name) as session:
            return await self._loop(session, text, state, model, allowed_skills, allowed_tools)

    async def _tool_call(self, state, tools, start, session, step, handoffs_left, tool_call, provider, model_id, prompt, system_prompt) -> tuple[PreparedChat, int]:
        """Handles tool execution, auto-handoff, and continue logging."""
        prepared = await self._execute_tools(session, tool_call, tools, state, run_id=...)
        await self._log_step(session, step, start, "continue", **prepared.metas)
        return prepared, handoffs_left
```

### D: Store-Level Fork

Moved `fork_tape` from `ForkTapeStore` (bub) to `AsyncTapeStore` (republic) protocol. Only `fork_tape(source, target)` was implemented; `fork(source, entry_id, target)` was deferred.

```python
# republic/tape/store.py
class AsyncTapeStore(Protocol):
    async def fork_tape(self, source_name: str, target_name: str) -> None: ...
```

**Note:** `FileTapeStore` inherits `NotImplementedError` from `InMemoryQueryMixin`. This is acceptable for now — fork is primarily used by SQLite-backed stores.

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `republic/src/republic/core/results.py` | Add `metas` property | To `PreparedChat`, `Finished`, `ToolCallNeeded` |
| `republic/src/republic/tape/store.py` | Add `fork_tape` to `AsyncTapeStore` | Protocol method with `NotImplementedError` default |
| `republic/src/republic/tape/manager.py` | Simplify | Remove session context manager, make `handoff` static |
| `republic/src/republic/tape/session.py` | Add buffering + deferred flush | `_deferred_entries`, `append_entry`, `handoff`, `__aexit__`, `add_tool_error` |
| `bub/src/bub/builtin/store.py` | Mark deprecated | `ForkTapeStore` kept but marked deprecated; `EmptyTapeStore` gets `fork_tape` stub |
| `bub/src/bub/builtin/tape.py` | Rewrite session management | Per-tape locks, `contextvar_session`, `_obtain_session`, framework hook for context |
| `bub/src/bub/builtin/tools.py` | Minor | Remove `archive` param from `tape_reset` |
| `bub/src/bub/builtin/agent.py` | Refactor loop | Extract `_tool_call`, use new session API, remove dead state passing |
| `bub/src/bub/builtin/hook_impl.py` | No changes | `provide_tape_store` no longer wraps in `ForkTapeStore` — handled by `TapeService.from_framework` |
| `bub_sf/src/bub_sf/bub_ext.py` | Adapt to new API | Use `agent.tapes.*` instead of direct store access; add session-aware primops |
| `bub_sf/src/bub_sf/store/query.py` | Fix | Handle missing tapes gracefully (dummy id instead of error) |
| `systemf/src/systemf/elab3/types/protocols.py` | Add `@runtime_checkable` | To `REPLSessionProto` |
| `main.sf` | Add `compact` function | Tape summarization via handoff + append |

## Key Decisions

1. **ContextVar in bub layer, not republic**: `contextvar_session` lives in `TapeService` rather than `AsyncTapeManager`. This keeps the session concept at the orchestration layer where locking and framework hooks live.

2. **Two-phase session creation**: Bootstrap anchor is written in a separate session before yielding the active session. This ensures the bootstrap anchor is persisted even if the agent crashes before the first turn completes.

3. **`append_entry` buffers, `append_event` is immediate**: Events (logs) don't need transactional integrity and are written immediately for debugging.

4. **`_obtain_session` pattern**: All `TapeService` methods (`handoff`, `append_event`, etc.) route through `_obtain_session` which checks for an active session before creating a temporary one. This prevents deadlocks when tools call tape operations during agent execution.

5. **Framework hook respected**: `_mk_session()` calls `self._framework.build_tape_context()` to preserve custom message builders (`_select_messages`) and reasoning strategies from extensions.

6. **`ForkTapeStore` not deleted**: Kept as deprecated code. Deletion is deferred to a future cleanup pass to avoid breaking any remaining references.

## Remaining Issues

1. **`FileTapeStore` doesn't implement `fork_tape`**: Will raise `NotImplementedError` at runtime if called.
2. **`reset()` during active session**: Buffer is not cleared, so deferred entries may re-appear after reset.
3. **No transactionality in flush**: `__aexit__` writes entries one-by-one. A crash mid-flush leaves partial data.

## Commits

- **republic** `870768d`: Session-scoped tape operations and store-level fork
- **bub** `7ce3adc`: Session-scoped tape operations with active session routing  
- **main** `23fb227`: Adapt bub_sf to new tape service API and add compaction support
