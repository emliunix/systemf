# Tape System Exploration

**Status:** Validated
**Last Updated:** 2026-04-29
**Central Question:** How does the tape system work in bub/republic, and what primitives are needed for SystemF integration?
**Topics:** tape, fork, anchor, session, workspace, context-building

## Planning

**Scopes:** 
- Covers: Tape storage, entries, queries, forking, anchors, context building, session/workspace isolation
- Excludes: LLM client internals, specific chat implementations beyond tape interaction

**Entry Points:**
- `bub/src/bub/builtin/tape.py:36` — TapeService class
- `bub/src/bub/builtin/store.py:31` — ForkTapeStore class
- `republic/tape/store.py:21` — TapeStore protocol
- `republic/tape/session.py:52` — Tape class
- `republic/tape/context.py:24` — TapeContext class
- `republic/tape/query.py:16` — TapeQuery class
- `republic/tape/entries.py:16` — TapeEntry class

## Summary

The tape system is an append-only event log that records all interactions (messages, tool calls, events, anchors) for a session. Each session gets a unique tape name derived from workspace + session_id hash. Tapes support fork/merge semantics for isolated sub-computations (e.g., subagents). Anchors act as context truncation points — the LLM only sees entries after the last anchor when building context. SystemF needs primitives for append, read, and query operations to interact with this model.

## Claims

### Claim 1: Tape Name Derivation from Workspace and Session
**Statement:** Tape names are derived as `md5(workspace)[:16] + "__" + md5(session_id)[:16]`, ensuring workspace-scoped isolation of sessions.
**Source:** `bub/src/bub/builtin/tape.py:120-125`
**Evidence:**
```python
def session_tape(self, session_id: str, workspace: Path) -> Tape:
    workspace_hash = hashlib.md5(str(workspace.resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    tape_name = (
        workspace_hash + "__" + hashlib.md5(session_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    )
    return self._llm.tape(tape_name)
```
**Status:** Validated
**Confidence:** High

### Claim 2: TapeEntry Kinds and Structure
**Statement:** Tape entries have kinds: "message", "system", "anchor", "tool_call", "tool_result", "error", "event". Each entry has an auto-assigned monotonic id, kind, payload dict, meta dict, and ISO timestamp.
**Source:** `republic/tape/entries.py:16-61`
**Evidence:**
```python
@dataclass(frozen=True)
class TapeEntry:
    id: int
    kind: str
    payload: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    date: str = field(default_factory=utc_now)
```
**Status:** Validated
**Confidence:** High

### Claim 3: Fork/Merge Semantics for Isolated Computations
**Statement:** `ForkTapeStore.fork()` creates an in-memory overlay. With `merge_back=True` (default), entries appended during the fork are merged back to the parent store on exit. With `merge_back=False`, the overlay is discarded. Reset during fork with merge_back=True replaces parent entries.
**Source:** `bub/src/bub/builtin/store.py:101-122`, `bub/tests/test_fork_store_merge_back.py`
**Evidence:**
```python
@contextlib.asynccontextmanager
async def fork(self, tape: str, merge_back: bool = True) -> AsyncGenerator[None, None]:
    store = InMemoryTapeStore()
    token = current_store.set(store)
    tape_token = current_fork_tape.set(tape)
    # ... yield ...
    if merge_back:
        if was_reset:
            await self._parent.reset(tape)
        entries = store.read(tape)
        if entries:
            for entry in entries:
                await self._parent.append(tape, entry)
```
**Status:** Validated
**Confidence:** High

### Claim 4: Temp Sessions Do Not Merge
**Statement:** Sessions with IDs starting with "temp/" use `merge_back=False`, meaning their tape entries are ephemeral and not persisted to the parent tape.
**Source:** `bub/src/bub/builtin/agent.py:101`, `bub/tests/test_builtin_agent.py:130-139`
**Evidence:**
```python
merge_back = not session_id.startswith("temp/")
async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
```
**Status:** Validated
**Confidence:** High

### Claim 5: Anchors Truncate Context for LLM Prompts
**Statement:** The `TapeContext` uses `LAST_ANCHOR` by default. When building messages, only entries AFTER the most recent anchor are included. This prevents unbounded context growth.
**Source:** `republic/tape/context.py:24-43`
**Evidence:**
```python
@dataclass(frozen=True)
class TapeContext:
    anchor: AnchorSelector = LAST_ANCHOR  # default: last anchor
    
def build_query(self, query: TapeQuery) -> TapeQuery:
    if self.anchor is None:
        return query
    if isinstance(self.anchor, _LastAnchor):
        return query.last_anchor()
    return query.after_anchor(self.anchor)
```
**Status:** Validated
**Confidence:** High

### Claim 6: TapeQuery Supports Filtering by Anchor, Date, Kind, Text
**Statement:** `TapeQuery` provides a fluent API for filtering: `after_anchor()`, `between_anchors()`, `between_dates()`, `kinds()`, `query()` (text search), `limit()`.
**Source:** `republic/tape/query.py:16-60`
**Evidence:**
```python
@dataclass(frozen=True)
class TapeQuery(Generic[T]):
    tape: str
    store: T
    _query: str | None = None
    _after_anchor: str | None = None
    _after_last: bool = False
    _between_anchors: tuple[str, str] | None = None
    _between_dates: tuple[str, str] | None = None
    _kinds: tuple[str, ...] = field(default_factory=tuple)
    _limit: int | None = None
```
**Status:** Validated
**Confidence:** High

### Claim 7: Agent Run Lifecycle Appends Events
**Statement:** During agent execution, events are appended to tape: "loop.start", "loop.step.start", "loop.step" (with status: ok/continue/error/auto_handoff), and command events.
**Source:** `bub/src/bub/builtin/agent.py:228-365`
**Evidence:**
```python
await self.tapes.append_event(
    tape.name,
    "loop.step",
    {
        "step": step,
        "elapsed_ms": elapsed_ms,
        "status": "ok",
        "date": datetime.now(UTC).isoformat(),
    },
)
```
**Status:** Validated
**Confidence:** High

### Claim 8: Bootstrap Anchor Auto-Creation
**Statement:** If a tape has no anchors, `ensure_bootstrap_anchor()` creates one with `handoff_async("session/start", state={"owner": "human"})`.
**Source:** `bub/src/bub/builtin/tape.py:69-73`
**Evidence:**
```python
async def ensure_bootstrap_anchor(self, tape_name: str) -> None:
    tape = self._llm.tape(tape_name)
    anchors = list(await tape.query_async.kinds("anchor").all())
    if not anchors:
        await tape.handoff_async("session/start", state={"owner": "human"})
```
**Status:** Validated
**Confidence:** High

## SystemF Primitives Needed

Based on the tape system, SystemF needs these primitive operations:

1. **tape_append** — Append an event entry (name + data payload)
2. **tape_read** — Read all entries from a tape (or filtered)
3. **tape_query** — Query entries with filters (after anchor, by kind, text search, limit)
4. **tape_handoff** — Create an anchor (context truncation point)
5. **tape_reset** — Clear tape (with optional archive)
6. **tape_info** — Get metadata (entry count, anchors, last anchor)

## Open Questions

- [ ] Should SystemF expose the fork/merge mechanism directly, or is that handled by the runtime?
- [ ] How should SystemF represent TapeEntry payloads — as JSON strings or structured types?
- [ ] Should tape primitives be async in SystemF's evaluator?

## Related Topics

- `analysis/ELAB3_PROJECT_STATUS.md` — Next step #2: "Bub primitives for tape"
