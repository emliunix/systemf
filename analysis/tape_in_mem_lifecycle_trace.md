# In-Memory Tape Store Full Lifecycle Trace

> Topic: How `ForkTapeStore` manages the in-memory buffer during an agent turn  
> Date: 2026-05-11  
> Scope: `bub/src/bub/builtin/tape.py`, `bub/src/bub/builtin/store.py`, `republic/src/republic/tape/{manager,session,store}.py`

---

## Notes

### Note 1: Investigation Goal

Trace the complete lifecycle of the in-memory tape store buffer: when it is created, how writes accumulate during an agent turn, how reads chain parent + buffer, and how entries are merged back to the persistent parent store. Also verify whether the `state` parameter passed into `TapeService.session()` is actually used by the tape machinery.

### Note 2: Architecture Context

The tape system sits between the agent (`Agent.run()`) and persistent storage (`FileTapeStore`). `ForkTapeStore` implements copy-on-write forking using `contextvars` — not instance state — to support concurrent async operations. All tape writes during an agent turn are buffered in memory and merged back atomically (or as close as the implementation gets) when the turn completes.

### Note 3: The State Parameter Mystery

`Agent.run(state=state)` passes a runtime state dict into `TapeService.session(tape_name, state=state)`, which forwards it to `_make_mgr(state)` → `TapeContext(state=state)` → `TapeSession._context`. But `build_messages()` (the only consumer of `TapeContext` in the read path) never accesses `context.state`. We need to verify whether this is truly dead code or if there is a hidden consumer.

---

## Facts

### Fact 1: ForkTapeStore uses three contextvars for fork state

`bub/src/bub/builtin/store.py:22-24`

```python
current_store: contextvars.ContextVar[AsyncTapeStore] = contextvars.ContextVar("current_store")
current_fork_tape: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_fork_tape", default=None)
current_tape_was_reset: contextvars.ContextVar[bool] = contextvars.ContextVar("current_tape_was_reset", default=False)
```

### Fact 2: ForkTapeStore.fork() creates a fresh InMemoryTapeStore and sets contextvars

`bub/src/bub/builtin/store.py:99-104`

```python
@contextlib.asynccontextmanager
async def fork(self, tape: str, merge_back: bool = True) -> AsyncGenerator[None, None]:
    store = InMemoryTapeStore()
    token = current_store.set(store)
    tape_token = current_fork_tape.set(tape)
    reset_token = current_tape_was_reset.set(False)
    try:
        yield
```

### Fact 3: ForkTapeStore._current returns the active store via contextvar

`bub/src/bub/builtin/store.py:35-37`

```python
@property
def _current(self) -> AsyncTapeStore:
    return current_store.get(_empty_store)
```

### Fact 4: EmptyTapeStore is a no-op sentinel used as fallback

`bub/src/bub/builtin/store.py:132-145`

```python
class EmptyTapeStore(AsyncTapeStore):
    async def list_tapes(self) -> list[str]:
        return []
    async def reset(self, tape: str) -> None:
        pass
    async def fetch_all(self, query: TapeQuery) -> Iterable[TapeEntry]:
        return []
    async def append(self, tape: str, entry: TapeEntry) -> None:
        pass
```

### Fact 5: ForkTapeStore.append() redacts prompts and writes to current store

`bub/src/bub/builtin/store.py:95-97`

```python
async def append(self, tape: str, entry: TapeEntry) -> None:
    self._redact_payload(entry.payload)
    await self._current.append(tape, entry)
```

### Fact 6: Redaction mutates the entry payload in-place

`bub/src/bub/builtin/store.py:88-93`

```python
@staticmethod
def _redact_payload(payload: dict) -> None:
    if "content" in payload:
        payload["content"] = ForkTapeStore._redact_prompt(payload["content"])
    elif "prompt" in payload:
        payload["prompt"] = ForkTapeStore._redact_prompt(payload["prompt"])
```

### Fact 7: InMemoryTapeStore.append() copies the entry and assigns sequential IDs

`republic/src/republic/tape/store.py:179-183`

```python
async def append(self, tape: str, entry: TapeEntry) -> None:
    next_id = self._next_id.get(tape, 1)
    self._next_id[tape] = next_id + 1
    stored = TapeEntry(next_id, entry.kind, dict(entry.payload), dict(entry.meta), entry.date)
    self._tapes.setdefault(tape, []).append(stored)
```

### Fact 8: ForkTapeStore.fetch_all() chains parent entries + fork buffer entries

`bub/src/bub/builtin/store.py:57-76`

```python
async def fetch_all(self, query: TapeQuery[AsyncTapeStore]) -> Iterable[TapeEntry]:
    parent_entries: Iterable[TapeEntry] = []
    if not (query.tape == self._fork_tape and self._current_was_reset):
        try:
            parent_entries = await self._parent.fetch_all(query)
        except Exception:
            parent_entries = []
    this_entries: list[TapeEntry] = []
    if hasattr(self._current, "read"):
        for entry in cast(list[TapeEntry], self._current.read(query.tape) or []):
            if query._kinds and entry.kind not in query._kinds:
                continue
            if entry.kind == "anchor":
                if query._after_last or (query._after_anchor and entry.payload.get("name") == query._after_anchor):
                    this_entries.clear()
                    parent_entries = []
                    continue
            this_entries.append(entry)
    return itertools.chain(parent_entries, this_entries)
```

### Fact 9: Merge back bulk-appends buffered entries to parent in finally block

`bub/src/bub/builtin/store.py:107-129`

```python
finally:
    was_reset = current_tape_was_reset.get()
    try:
        current_store.reset(token)
    except ValueError:
        pass
    try:
        current_fork_tape.reset(tape_token)
    except ValueError:
        pass
    try:
        current_tape_was_reset.reset(reset_token)
    except ValueError:
        pass
    if merge_back:
        if was_reset:
            await self._parent.reset(tape)
        entries = store.read(tape)
        if entries:
            count = len(entries)
            for entry in entries:
                await self._parent.append(tape, entry)
            logger.info(f'Merged {count} entries into tape "{tape}"')
```

### Fact 10: TapeService.session() is a double context manager nesting

`bub/src/bub/builtin/tape.py:77-86`

```python
@contextlib.asynccontextmanager
async def session(
    self, tape_name: str, state: State, *, merge_back: bool = True,
) -> AsyncGenerator[TapeSession, None]:
    async with self._store.fork(tape_name, merge_back=merge_back):
        mgr = self._make_mgr(state)
        async with mgr.session(tape_name) as session:
            await self._bootstrap(session)
            yield session
```

### Fact 11: _make_mgr() embeds runtime state into TapeContext.state

`bub/src/bub/builtin/tape.py:73-75`

```python
def _make_mgr(self, state: State | None = None) -> AsyncTapeManager:
    ctx = replace(self._framework.build_tape_context(), state=state or {})
    return AsyncTapeManager(store=self._store, default_context=ctx)
```

### Fact 12: TapeSession copies manager.default_context on initialization

`republic/src/republic/tape/session.py:56-65`

```python
def __init__(
    self,
    name: str,
    store: AsyncTapeStore,
    manager: TapeManagerProto,
) -> None:
    self._name = name
    self._store = store
    self._manager = manager
    self._context = manager.default_context
```

### Fact 13: TapeSession.run() calls read_messages with session context

`republic/src/republic/tape/session.py:107-112`

```python
async def run(
    self,
    chat: ChatClient,
    prepared: PreparedChat,
) -> TurnResult:
    messages = await self._manager.read_messages(self._name, context=self._context)
```

### Fact 14: AsyncTapeManager.read_messages() builds messages from entries + context

`republic/src/republic/tape/manager.py:48-56`

```python
async def read_messages(self, tape: str, *, context: TapeContext | None = None) -> list[dict[str, Any]]:
    active_context = context or self._global_context
    query = TapeQuery(tape=tape)
    query = active_context.build_query(query)
    entries = await self._tape_store.fetch_all(query)
    messages = build_messages(entries, active_context)
    if inspect.isawaitable(messages):
        messages = await messages
    return messages
```

### Fact 15: build_messages() only accesses context.anchor, context.select, and context.reasoning_strategy

`republic/src/republic/tape/context.py:60-63`

```python
def build_messages(entries, context):
    if context.select is not None:
        return context.select(entries, context)
    return _default_messages(entries, context.reasoning_strategy)
```

### Fact 16: TapeContext dataclass has a state field but no code reads it

`republic/src/republic/tape/context.py:38-50`

```python
@dataclass(frozen=True)
class TapeContext:
    anchor: str | None = None
    select: Callable | None = None
    reasoning_strategy: str = "default"
    state: dict[str, Any] = field(default_factory=dict)
```

### Fact 17: Agent.run() passes state to tapes.session() and separately to _loop()

`bub/src/bub/builtin/agent.py:115-136`

```python
async def run(
    self,
    *,
    tape_name: str,
    prompt: str | list[dict],
    state: State,
    model: str | None = None,
    allowed_skills: Collection[str] | None = None,
    allowed_tools: Collection[str] | None = None,
) -> str:
    merge = not state.get("session_id", "").startswith("temp/")
    text = prompt if isinstance(prompt, str) else _extract_text_from_parts(prompt)

    async with self.tapes.session(tape_name, merge_back=merge, state=state) as session:
        return await self._loop(
            session, text, state, model,
            allowed_skills, allowed_tools,
        )
```

### Fact 18: _execute_tools() creates ToolContext with state

`bub/src/bub/builtin/agent.py:446-449`

```python
execution = await self._executor.execute_async(
    needed.tool_calls, renamed,
    context=ToolContext(tape=session.name, run_id=run_id, state=state),
)
```

### Fact 19: ToolContext is a separate dataclass from TapeContext

`republic/src/republic/tools/context.py:9-14`

```python
@dataclass(frozen=True)
class ToolContext:
    tape: str | None = None
    run_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
```

### Fact 20: _bootstrap() writes initial anchor if tape has none

`bub/src/bub/builtin/tape.py:88-92`

```python
async def _bootstrap(self, session: TapeSession) -> None:
    entries = await self._store.fetch_all(TapeQuery(tape=session.name))
    if not any(e.kind == "anchor" for e in entries):
        await session.handoff("session/start", anchor_state={"owner": "human"})
```

### Fact 21: TapeService.handoff() bypasses the fork mechanism

`bub/src/bub/builtin/tape.py:157-160`

```python
async def handoff(self, tape_name: str, *, name: str, anchor_state: dict[str, Any] | None = None) -> list[TapeEntry]:
    mgr = self._make_mgr()
    entries = await mgr.handoff(tape_name, name, anchor_state=anchor_state)
    return cast(list[TapeEntry], entries)
```

### Fact 22: ForkTapeStore.reset() marks was_reset for merge handling

`bub/src/bub/builtin/store.py:50-55`

```python
async def reset(self, tape: str) -> None:
    await self._current.reset(tape)
    if self._current is _empty_store or self._fork_tape != tape:
        await self._parent.reset(tape)
        return
    current_tape_was_reset.set(True)
```

---

## Claims

### Claim 1: The in-memory buffer is created fresh per fork and discarded after merge

**Reasoning:** `ForkTapeStore.fork()` creates a new `InMemoryTapeStore` instance (Fact 2), sets it as the active store via `current_store` contextvar (Fact 2), and all writes during the fork go to this buffer through `ForkTapeStore.append()` → `_current.append()` (Fact 5). In the `finally` block, the buffer is read and its entries are bulk-appended to the parent store (Fact 9), then the contextvar is reset and the local `store` variable goes out of scope (Fact 9).

**References:** Fact 2, Fact 5, Fact 9

### Claim 2: Reads during a fork see a merged view of parent + buffer, with anchor slicing

**Reasoning:** `ForkTapeStore.fetch_all()` first attempts to read from the parent store (unless the tape was reset during the fork) (Fact 8), then reads from the in-memory buffer (Fact 8). If an anchor is encountered in the buffer and the query requests entries after an anchor (`_after_last` or `_after_anchor`), both the parent entries and prior buffer entries are cleared, so only entries after the anchor are returned (Fact 8). The final result chains parent entries first, then buffer entries (Fact 8).

**References:** Fact 8

### Claim 3: The `state` parameter in `TapeService.session()` is dead weight

**Reasoning:** `Agent.run()` passes `state` to `TapeService.session()` (Fact 17), which forwards it to `_make_mgr(state)` (Fact 10), which embeds it into `TapeContext.state` (Fact 11). `TapeSession` copies this context (Fact 12) and passes it to `read_messages()` (Fact 13). `AsyncTapeManager.read_messages()` passes the context to `build_messages()` (Fact 14). `build_messages()` only accesses `context.select` and `context.reasoning_strategy` (Fact 15). The `TapeContext.state` field is never read by any code in the tape system (Fact 16). The actual consumer of runtime state is `ToolContext` in `_execute_tools()` (Fact 18), which is a completely separate dataclass (Fact 19).

**References:** Fact 10, Fact 11, Fact 12, Fact 13, Fact 14, Fact 15, Fact 16, Fact 17, Fact 18, Fact 19

### Claim 4: Prompt redaction mutates entries in-place before buffering

**Reasoning:** `ForkTapeStore.append()` calls `self._redact_payload(entry.payload)` (Fact 5), which mutates the payload dictionary directly by replacing `content` or `prompt` values with redacted versions (Fact 6). This is a side effect on the caller's `TapeEntry` object. Because `InMemoryTapeStore.append()` makes a copy of the entry (Fact 7), the mutation happens before copying, so the buffered copy also has the redacted payload.

**References:** Fact 5, Fact 6, Fact 7

### Claim 5: Merge back is not atomic and has edge cases

**Reasoning:** The merge loop in `ForkTapeStore.fork()` iterates over buffered entries and calls `self._parent.append()` for each one sequentially (Fact 9). There is no transaction wrapper. If the process crashes mid-merge, some entries are persisted and others are lost. Additionally, if `reset()` was called during the fork, the parent is reset before merge (Fact 9, Fact 22), which means the merge replaces all parent entries. If `reset()` was not called, entries are appended to existing parent entries, which could lead to duplicates if a previous partial merge occurred.

**References:** Fact 9, Fact 22

### Claim 6: Operations outside an active fork context silently drop writes

**Reasoning:** `ForkTapeStore._current` returns `current_store.get(_empty_store)` (Fact 3), where `_empty_store` is an `EmptyTapeStore` sentinel (Fact 4). `EmptyTapeStore.append()` is a no-op (Fact 4). When `TapeService.handoff()` creates a new `AsyncTapeManager` with `store=self._store` (the `ForkTapeStore`) and calls `append()` outside any fork context, `ForkTapeStore.append()` delegates to `_current.append()` which is `EmptyTapeStore.append()` — a no-op. This means service-level `handoff()` calls outside a `session()` context lose data. However, in practice, `handoff()` is typically called from within an active `TapeSession` where the fork context is active.

**References:** Fact 3, Fact 4, Fact 5, Fact 21

---

## Full Picture Summary Note

### Note 4: How the In-Memory Tape Buffer Works

The tape system implements **copy-on-write forking** through `ForkTapeStore`, which wraps a persistent parent store (typically `FileTapeStore`). When an agent turn begins, `TapeService.session()` opens a fork context that:

1. **Creates** a fresh `InMemoryTapeStore` buffer via `contextvars`
2. **Intercepts** all reads to merge parent entries + buffered entries, with anchor-aware slicing
3. **Buffers** all writes (with in-place prompt redaction) in the in-memory store
4. **Merges** buffered entries back to the parent store in a sequential loop when the context exits

The fork mechanism is **not atomic** — a crash during merge leaves partial data. It also **silently drops writes** made outside an active fork context via the `EmptyTapeStore` sentinel.

### Note 5: The Dead State Path

A significant structural issue exists: `Agent.run()` passes a runtime `state` dict into `TapeService.session(state=state)`, which embeds it into `TapeContext.state`. This field flows through `TapeSession` → `read_messages()` → `build_messages()`, but **is never accessed**. The tape machinery has no use for `_runtime_agent`, `session_id`, or `allowed_skills`. The actual consumer of runtime state is `ToolContext` in `_execute_tools()`, which receives the same state through a completely separate path. `TapeContext.state` is dead weight and should be removed.

### Note 6: Call Chain for a Typical Agent Turn

```
Agent.run(tape_name, state)
  └─> TapeService.session(tape_name, state=state)
        └─> ForkTapeStore.fork(tape_name)
              ├─> InMemoryTapeStore() created
              ├─> current_store set
              └─> _bootstrap() → writes "session/start" anchor to buffer
              └─> yield TapeSession
                    └─> Agent._loop(session, text, state)
                          ├─> session.prepare() → writes system + user messages to buffer
                          ├─> session.run() → read_messages() merges parent+buffer
                          │     └─> chat.chat() → LLM call
                          │     └─> _record_result() → writes assistant + event to buffer
                          ├─> _execute_tools() → ToolContext(state=state) ← STATE USED HERE
                          └─> loop or return
              └─> finally: merge_back → bulk append buffer to parent
```

### Note 7: Cleanup Targets

1. **Remove `state` from `TapeService.session()` and `_make_mgr()`** — the tape machinery doesn't need runtime state
2. **Remove `state` field from `TapeContext`** — or at least stop populating it
3. **Consider making merge atomic** — wrap in a transaction if the parent store supports it
4. **Document the EmptyTapeStore fallback** — writes outside fork contexts are silently dropped
