# State Passing Audit: AsyncTapeManager ↔ Agent

> Last updated after `anchor_state` rename (2026-05-11).

## Executive Summary

There are **two** semantically unrelated bags of data that used to share the name `state` and the type `dict[str, Any]`:

1. **Runtime session state** — `_runtime_agent`, `_runtime_workspace`, `session_id`, `allowed_skills`
2. **Anchor payload state** — `{"owner": "human"}`, `{"summary": "..."}` — now called `anchor_state` everywhere

A third dead field, **`TapeContext.state`**, receives #1 but is **never read** by the tape system.

The disaster is structural: the tape machinery (`TapeService` → `AsyncTapeManager` → `TapeSession`) acts as a **cargo-cult conduit** for runtime state it never uses, while the actual consumer (`ToolContext`) receives the same state via a completely separate path.

---

## 1. The Dead Field: `TapeContext.state`

### Proof it is never read

```
republic/tape/session.py:66    self._context = manager.default_context
republic/tape/session.py:113   messages = await self._manager.read_messages(self._name, context=self._context)
republic/tape/manager.py:49-53  active_context = context or self._global_context
                                 query = active_context.build_query(query)
                                 entries = await self._tape_store.fetch_all(query)
                                 messages = build_messages(entries, active_context)
republic/tape/context.py:60-63  def build_messages(entries, context):
                                    if context.select is not None: return context.select(entries, context)
                                    return _default_messages(entries, context.reasoning_strategy)
```

`build_messages` accesses `context.anchor`, `context.select`, and `context.reasoning_strategy`.  
**`context.state` is never touched.** It is dead weight.

### How the corpse gets there

```python
# tape.py:73-75
def _make_mgr(self, state: State | None = None) -> AsyncTapeManager:
    ctx = replace(self._framework.build_tape_context(), state=state or {})
    return AsyncTapeManager(store=self._store, default_context=ctx)
```

The runtime god dict (with `_runtime_agent`, `session_id`, etc.) is stuffed into `TapeContext.state`, passed to `AsyncTapeManager`, copied into `TapeSession._context`, and then **completely ignored** by `read_messages` / `build_messages`.

**`AsyncTapeManager` does not need `_runtime_agent`. It does not need `session_id`. It does not need `allowed_skills`. It needs nothing from the runtime state.**

---

## 2. `anchor_state` Rename — Done

All `handoff()` methods and their call sites now use `anchor_state` instead of `state`:

| Layer | Before | After |
|-------|--------|-------|
| `AsyncTapeManager.handoff()` | `state=` | `anchor_state=` |
| `TapeSession.handoff()` | `state=` | `anchor_state=` |
| `TapeService.handoff()` | `state=` | `anchor_state=` |
| `NeedHandOffError` | `.state` | `.anchor_state` |
| Agent call sites | `session.handoff(..., state=...)` | `session.handoff(..., anchor_state=...)` |
| Tool call sites | `agent.tapes.handoff(..., state={"summary": ...})` | `agent.tapes.handoff(..., anchor_state={"summary": ...})` |

The **only** remaining `state` key inside the tape system is the **serialized payload key** in `TapeEntry.event("handoff", {"name": name, "state": anchor_state or {}})` and `TapeEntry.anchor(name, state=anchor_state)` — this is the tape schema, not the method parameter.

---

## 3. The Actual Consumer: `ToolContext`

The runtime state has exactly one consumer: **tool execution**. But it bypasses the tape machinery entirely.

```python
# agent.py:446-449
execution = await self._executor.execute_async(
    needed.tool_calls, renamed,
    context=ToolContext(tape=session.name, run_id=run_id, state=state),
)
```

`ToolContext.state` is a **separate** `dict[str, Any]` field in a **different** dataclass. It is populated directly from the `state` parameter of `_execute_tools`, not from `session._context.state`.

### What tools actually read from `context.state`

| Tool | Key | Purpose |
|------|-----|---------|
| `_get_agent` | `_runtime_agent` | Retrieve the Agent singleton |
| `bash` | `_runtime_workspace` | Resolve shell working directory |
| `skill_describe` | `_runtime_workspace` | Resolve skill search path |
| `skill_describe` | `allowed_skills` | Filter skill access |
| `run_subagent` | `session_id` | Derive subagent session ID |
| `quit_session` | `session_id` | Target session to quit |
| `read_file`/`write_file`/... | `_runtime_workspace` | File I/O base path |

None of these keys are needed by `AsyncTapeManager`, `TapeSession`, or `TapeContext`.

---

## 4. The Full Data Flow

### Path A: Runtime state → ToolContext (the only path that matters)

```
Framework.dispatch_inbound()
  └─> state = {"_runtime_workspace": ...}
  └─> load_state hook adds "session_id", "_runtime_agent", "context"
  └─> run_model hook
        └─> Agent.run(state=state)
              └─> _loop(state=state)
                    └─> _execute_tools(session, needed, renamed, state)
                          └─> ToolContext(tape=..., run_id=..., state=state)  ← CONSUMED HERE
                                └─> tools read _runtime_agent, _runtime_workspace, session_id
```

### Path B: Runtime state → TapeContext.state → 🗑️ (dead)

```
Agent.run(state=state)
  └─> self.tapes.session(tape_name, merge_back=merge, state=state)
        └─> TapeService.session(state=state)
              └─> _make_mgr(state=state)
                    └─> TapeContext(state=state)  ← DEAD ON ARRIVAL
                          └─> AsyncTapeManager(default_context=ctx)
                                └─> TapeSession._context = ctx
                                      └─> read_messages(context=self._context) ignores ctx.state
```

### Path C: Anchor payload → TapeEntry.anchor (completely separate)

```
Agent.run()
  └─> session.handoff("session/start", anchor_state={"owner": "human"})
        └─> TapeSession.handoff(name, anchor_state={"owner": "human"})
              └─> AsyncTapeManager.handoff(tape, name, anchor_state={"owner": "human"})
                    └─> TapeEntry.anchor(name, state={"owner": "human"})  ← PERSISTED
```

---

## 5. What Is Still Wrong

### `TapeService.session()` still takes `state: State`

```python
# tape.py:78-86
async def session(
    self, tape_name: str, state: State, *, merge_back: bool = True,
) -> AsyncGenerator[TapeSession, None]:
    async with self._store.fork(tape_name, merge_back=merge_back):
        mgr = self._make_mgr(state)     # ← passes runtime state into dead field
        async with mgr.session(tape_name) as session:
            await self._bootstrap(session)
            yield session
```

### `TapeService._make_mgr()` still takes `state: State | None = None`

```python
# tape.py:73-75
def _make_mgr(self, state: State | None = None) -> AsyncTapeManager:
    ctx = replace(self._framework.build_tape_context(), state=state or {})
    return AsyncTapeManager(store=self._store, default_context=ctx)
```

Both of these should be stateless. The tape machinery does not need runtime state.

### `Agent.run()` / `Agent.run_stream()` still pass `state` to `tapes.session()`

```python
# agent.py:129
async with self.tapes.session(tape_name, merge_back=merge, state=state) as session:

# agent.py:153
session = await stack.enter_async_context(self.tapes.session(tape_name, merge_back=merge, state=state))
```

The `state` parameter here is forwarded into `TapeContext.state` (dead). The agent should not pass it to the tape service.

---

## 6. Fix Strategy

### Do NOT touch anchor payloads
Anchor state is already clean. Keep it that way.

### Remove runtime state from the tape machinery
1. **`TapeService.session()`** should not take `state: State`. It only needs `tape_name` and `merge_back`.
2. **`TapeService._make_mgr()`** should not take `state`. `TapeContext.state` should be removed or defaulted to empty.
3. **`AsyncTapeManager`** and **`TapeSession`** should be ignorant of agent runtime concerns.
4. **`Agent.run()` / `run_stream()`** should not pass `state` to `self.tapes.session()`.

### Separate the types
```python
# Runtime context for tools (currently called "state")
@dataclass(frozen=True)
class AgentRuntimeContext:
    session_id: str
    workspace: Path
    agent: Agent
    message_context: str | None = None
    allowed_skills: set[str] | None = None

# Anchor payload (keep as dict, but call it payload, not state)
AnchorPayload: TypeAlias = dict[str, Any]
```

### Inject `Agent` directly into `ToolContext`
Instead of `context.state["_runtime_agent"]`, pass the agent as a proper field or use DI:
```python
@dataclass(frozen=True)
class ToolContext:
    tape: str | None
    run_id: str
    agent: Agent  # explicit, not smuggled
    workspace: Path
    session_id: str
    meta: dict[str, Any] = field(default_factory=dict)
```

---

## 7. Key Files and Line References

### State creation & passing
| File | Lines | Role |
|------|-------|------|
| `bub/src/bub/framework.py` | 113-138 | Creates state, passes to hooks |
| `bub/src/bub/builtin/hook_impl.py` | 115-122, 161-174 | `load_state`, `run_model` |
| `bub/src/bub/builtin/agent.py` | 113-134, 164-174, 218-270 | `run`, `run_stream`, `_loop` |
| `bub/src/bub/builtin/tools.py` | 257-285 | `run_subagent` forks state |

### State → TapeContext (dead path)
| File | Lines | Role |
|------|-------|------|
| `bub/src/bub/builtin/tape.py` | 73-75, 78-86 | `_make_mgr`, `session` |
| `republic/src/republic/tape/manager.py` | 24-44, 64-76 | `AsyncTapeManager.__init__`, `handoff` |
| `republic/src/republic/tape/context.py` | 38-50 | `TapeContext` dataclass |
| `republic/src/republic/tape/session.py` | 57-66, 76-106, 182-189 | `TapeSession` init, prepare, handoff |

### State consumption (actual consumers)
| File | Lines | Role |
|------|-------|------|
| `bub/src/bub/builtin/tape.py` | 28-36 | `get_tape_name(state)` |
| `bub/src/bub/builtin/tools.py` | 36-38, 81, 163, 321 | `_get_agent`, workspace, skills |
| `bub/src/bub/utils.py` | 33-35 | `workspace_from_state(state)` |
| `bub/src/bub/builtin/agent.py` | 395-406 | `_system_prompt` reads `state` |
| `republic/src/republic/tools/context.py` | 9-14 | `ToolContext` dataclass |
