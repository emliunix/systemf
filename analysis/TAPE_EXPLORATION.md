# Tape System Exploration

**Status:** Validated
**Last Updated:** 2026-04-30
**Session Merged:** TAPE_HOOK_SCOPE_2026-04-30_001_TEMP.md
**Central Question:** What are the tape primitives, how do implementations extend them, and what higher-level operations compose them?
**Topics:** tape, primitives, hierarchy, fork, anchor, query, composition

## Planning

**Scopes:** 
- Covers: Protocol primitives, implementation hierarchy, all operations classified as primitive vs composed
- Excludes: LLM client internals, message rendering, chat protocols

**Entry Points:**
- `republic/tape/store.py:21` — TapeStore protocol
- `republic/tape/store.py:160` — InMemoryTapeStore
- `bub/src/bub/builtin/store.py:31` — ForkTapeStore
- `bub/src/bub/builtin/store.py:144` — FileTapeStore
- `bub/src/bub/builtin/tape.py:36` — TapeService

## Summary

The tape system has **4 protocol primitives**: `append`, `fetch_all`, `reset`, `list_tapes`. A 5th primitive `read` exists at the implementation level. All other operations — fork, handoff, info, search, anchor management — are compositions of these primitives plus `TapeEntry` constructors and `TapeQuery` filters.

## Protocol Primitives

These are the only operations defined in the `TapeStore` protocol (`republic/tape/store.py:21-30`):

| # | Primitive | Signature | Semantics |
|---|---|---|---|
| P1 | `append` | `(tape: str, entry: TapeEntry) -> None` | Append entry to named tape. Store assigns monotonic ID. |
| P2 | `fetch_all` | `(query: TapeQuery) -> Iterable[TapeEntry]` | Query entries with filters. |
| P3 | `reset` | `(tape: str) -> None` | Delete all entries for tape name. |
| P4 | `list_tapes` | `() -> list[str]` | Return all tape names. |

`AsyncTapeStore` (`republic/tape/store.py:33-42`) is the async version of the same 4 primitives.

## Implementation Hierarchy

```
TapeStore (Protocol)
├── P1: append
├── P2: fetch_all  
├── P3: reset
└── P4: list_tapes

    InMemoryQueryMixin (helper)
    └── fetch_all implementation using read()

    InMemoryTapeStore(InMemoryQueryMixin)
    ├── read(tape) -> list[TapeEntry] | None   [P5]
    ├── append(tape, entry)                     [P1]
    ├── fetch_all(query)                        [P2]
    ├── reset(tape)                             [P3]
    └── list_tapes()                            [P4]

    FileTapeStore(InMemoryQueryMixin)
    ├── read(tape)                              [P5]
    ├── append(tape, entry)                     [P1]
    ├── fetch_all(query) with fuzzy search      [P2 extended]
    ├── reset(tape)                             [P3]
    └── list_tapes()                            [P4]

    AsyncTapeStoreAdapter
    └── Wraps sync TapeStore → async versions of P1-P4

    UnavailableTapeStore
    └── All P1-P4 raise RepublicError

    EmptyTapeStore
    └── All P1-P4 are no-ops / return empty

    ForkTapeStore
    ├── Wraps parent AsyncTapeStore
    ├── list_tapes() -> delegates to parent           [P4]
    ├── reset(tape) -> overlay or parent              [P3 extended]
    ├── fetch_all(query) -> merge parent + overlay    [P2 extended]
    ├── append(tape, entry) -> writes to overlay      [P1 extended]
    └── fork(tape, merge_back) -> context manager     [COMPOSITION]
```

### P5: `read(tape)`

Not in the protocol but fundamental. Returns all entries for a tape without filtering.

- `InMemoryTapeStore.read()` — returns copy of internal list
- `FileTapeStore.read()` — reads JSONL from disk with read-ahead caching
- Used by `ForkTapeStore` during merge to read overlay entries

### P2 Extensions

**InMemoryQueryMixin.fetch_all()** (`republic/tape/store.py:117`):
Implements filtering pipeline: anchor position → date range → text search → kinds → limit. Text search is substring match on JSON representation.

**FileTapeStore.fetch_all()** (`bub/src/bub/builtin/store.py:152`):
Extends mixin with fuzzy text search using rapidfuzz when `query._query` is set. Also deduplicates by payload text.

**ForkTapeStore.fetch_all()** (`bub/src/bub/builtin/store.py:60`):
Merges parent entries + overlay entries via `itertools.chain`. If reset was called inside fork, hides parent entries. Anchors in overlay clear the view (simulate truncation).

### P1 Extensions

**ForkTapeStore.append()** (`bub/src/bub/builtin/store.py:97`):
Redacts prompt content, then writes to current overlay (via contextvar). Never writes directly to parent during fork.

### P3 Extensions

**ForkTapeStore.reset()** (`bub/src/bub/builtin/store.py:53`):
If outside fork: delegates to parent. If inside fork: resets overlay and sets reset flag (defers actual parent reset until merge time).

## Higher-Level Operations: Primitive or Composed?

All operations in `TapeService` (`bub/src/bub/builtin/tape.py`) are **compositions** of P1–P5 plus `TapeEntry` constructors.

| Operation | Classification | Composed From |
|---|---|---|
| `handoff(tape, name, state)` | **Composed** | `P1: append(tape, TapeEntry.anchor(name, state))` |
| `ensure_bootstrap_anchor(tape)` | **Composed** | `P2: fetch_all(kinds="anchor")` → check empty → `P1: append(anchor)` |
| `append_event(tape, name, payload)` | **Composed** | `P1: append(tape, TapeEntry.event(name, payload))` |
| `info(tape)` | **Composed** | `P2: fetch_all()` → count entries, count anchors, find last anchor, scan for token usage |
| `search(query)` | **Composed** | Direct `P2: fetch_all(query)` delegation |
| `anchors(tape, limit)` | **Composed** | `P2: fetch_all(kinds="anchor")` → slice last N in memory |
| `reset(tape, archive)` | **Composed** | `P2: fetch_all()` (for backup) → `P3: reset()` → `P1: append(anchor)` |
| `session_tape(session_id, workspace)` | **Composed** | Pure function: name = hash(workspace) + "__" + hash(session_id) |
| `fork_tape(tape_name, merge_back)` | **Composed** | Delegates to `ForkTapeStore.fork()` |
| `fork(tape, merge_back)` | **Composed** | `P5: new InMemoryTapeStore()` + contextvar swap + during: P1→overlay, P2→merge, on exit: `P5: read()` + optional `P3: reset()` + `P1: append` loop |

## TapeEntry Constructors

These are pure data constructors, not store operations:

```python
TapeEntry.message(message_dict)     # kind="message"
TapeEntry.system(content)           # kind="system"
TapeEntry.anchor(name, state)       # kind="anchor"
TapeEntry.tool_call(calls)          # kind="tool_call"
TapeEntry.tool_result(results)      # kind="tool_result"
TapeEntry.error(error)              # kind="error"
TapeEntry.event(name, data)         # kind="event"
```

All constructors set `id=0` — the store assigns the real monotonic ID on `append()`.

## TapeQuery Filters

These are pure data builders, not store operations:

```python
query.after_anchor(name)       # entries after named anchor
query.last_anchor()            # entries after most recent anchor
query.between_anchors(s, e)    # entries between two anchors
query.between_dates(s, e)      # date range filter
query.kinds("event", "anchor") # kind filter
query.query("text")            # text search
query.limit(n)                 # cap results
```

The filtering is executed by `fetch_all()` implementations (P2).

## Handoff vs Fork

These are fundamentally different mechanisms:

| Aspect | Handoff | Fork |
|---|---|---|
| **Scope** | Same tape | Temporary overlay store |
| **Entries written** | Exactly 2 (anchor + event) | Arbitrary number |
| **Persistence** | Permanent | Optional (merge_back=True/False) |
| **Read isolation** | None — all reads see parent entries | Parent entries hidden if reset inside fork |
| **Purpose** | Context truncation marker | Isolated sub-computation |
| **Storage** | Direct append to parent | In-memory overlay, merged later |

**Handoff** (`republic/tape/manager.py:64-76`):
```python
def handoff(self, tape, name, *, state=None, **meta):
    entry = TapeEntry.anchor(name, state=state, **meta)
    event = TapeEntry.event("handoff", {"name": name, "state": state or {}}, **meta)
    self._tape_store.append(tape, entry)   # P1
    self._tape_store.append(tape, event)   # P1
    return [entry, event]
```

**Fork** (`bub/src/bub/builtin/store.py:101-122`):
```python
async def fork(self, tape, merge_back=True):
    store = InMemoryTapeStore()              # new P5
    token = current_store.set(store)          # redirect P1
    try:
        yield                                   # P2 merges parent+overlay
    finally:
        if merge_back:
            entries = store.read(tape)            # P5
            for entry in entries:
                await self._parent.append(tape, entry)  # P1 to parent
```

## Hook Scope and Agent Boundaries

### Claim H1: Main Agent Is the Only Path That Triggers Full Hook Suite

`BubFramework.process_inbound()` (`bub/src/bub/framework.py:105-144`) is the exclusive entry point for the full hook sequence: `resolve_session` → `load_state` → `build_prompt` → model execution → `save_state` → `render_outbound` → `dispatch_outbound`. Any code that calls `Agent.run()` or `Agent.run_stream()` directly bypasses this entire sequence.

### Claim H2: Subagents Bypass All Framework-Level Hooks Except system_prompt

The `run_subagent` tool (`bub/src/bub/builtin/tools.py:256-277`) calls `agent.run_stream()` directly. `Agent.run_stream()` (`bub/src/bub/builtin/agent.py:110-150`) sets up the tape and runs the agent loop without any framework hook calls. The only hook still triggered is `system_prompt` (`bub/src/bub/builtin/agent.py:563-566`), which is called from within `Agent._run_once()` during model execution. This means `load_state`/`save_state` hooks never see subagent turns.

### Claim H3: Hook Scope Is Determined by Call Site, Not Hook Type

The same hook mechanism is invoked from different scopes. `provide_tape_store` is called once during framework initialization (via `cached_property`). `system_prompt` is called every time the agent runs a model (from `Agent._run_once()`). `load_state`/`save_state` are called once per inbound message turn (from `Framework.process_inbound()`). Subagents, which bypass `process_inbound()`, never trigger `load_state`/`save_state` even though they still trigger `system_prompt`.

### Claim H4: All Agent Runs Share the Same Persistent Storage Backend

`Agent.tapes` is a `cached_property` (`bub/src/bub/builtin/agent.py:57-66`). It calls `framework.get_tape_store()` once, wraps it in `ForkTapeStore`, and caches the result. The `provide_tape_store` hook is app-level (`bub/src/bub/framework.py:256-257`). All subsequent calls to `agent.run()` or `agent.run_stream()` reuse this same `TapeService`. The `fork_tape()` context manager provides per-run isolation via an in-memory overlay, but the underlying store is shared application-wide.

### Claim H5: Session/Workspace Isolation Is Pure Naming Convention

The `TapeStore` protocol (`republic/tape/store.py:21-30`) operates on flat string names with zero awareness of session or workspace. The `FileTapeStore` stores ALL tapes in a single directory (`~/.bub/tapes/`). The only "isolation" comes from `session_tape()` embedding workspace and session hashes into the tape name string. Any code with knowledge of a tape name string can read/write it.

---

## Tape ID Hardwiring and Extension Strategy

**Current limitation:** Tape names are hardwired as `hash(workspace) + "__" + hash(session_id)`. No `tape_id` state key exists. Extensions cannot customize the tape name.

**Workaround for extensions:** Since the tape ID cannot be changed, extensions should use **entry namespacing** to isolate their data within the shared tape:

```python
# Instead of custom tape, use prefixed entry names
TapeEntry.event("sf:eval", {"expr": "1 + 2"})
TapeEntry.event("sf:result", {"value": 3})
TapeEntry.event("sf:error", {"message": "type mismatch"})
```

**Query for extension entries only:**
```python
query = TapeQuery(tape=tape_name, store=store)
    .query("sf:")           # text search in JSON
    .kinds("event")
```

**Alternative:** Create a separate `InMemoryTapeStore` for truly private extension data, but this loses persistence and LLM context integration.

**Recommended fix:** Add `tape_id` to the agent state:
```python
# In Agent.run():
tape_name = state.get("_tape_id") or self.tapes.session_tape(session_id, workspace).name
```

This would allow extensions to inject `state["_tape_id"] = "custom_tape"` and fully control their storage.

## SystemF Primitives Needed

For SystemF integration, expose the 4 protocol primitives + `read`:

| Primitive | SF Type | Notes |
|---|---|---|
| `tape_append` | `String -> String -> Dict -> Unit` | tape name, kind, payload |
| `tape_read` | `String -> List Entry` | all entries (P5) |
| `tape_query` | `String -> Query -> List Entry` | filtered (P2) |
| `tape_reset` | `String -> Unit` | clear (P3) |
| `tape_list` | `Unit -> List String` | all names (P4) |

**All higher-level ops should be implemented in SF** using the primitives, not as additional builtins.

## Open Questions

- [ ] Should `TapeEntry` be a SystemF ADT or opaque JSON dict?
- [ ] Should tape primitives be async (return `VAsync`) in the CEK evaluator?
- [ ] Should `fork` be a primitive or handled by the runtime around LLM calls?
- [ ] Can we add `tape_id` override to `Agent.run()` without breaking existing behavior?
- [ ] Should subagents route through `framework.process_inbound()` for hook parity?
- [ ] If an extension provides a custom `TapeStore`, does it replace the shared one or supplement it?

## Related Topics

- `analysis/ELAB3_PROJECT_STATUS.md` — Next step #2: "Bub primitives for tape"
- `analysis/TAPE_HOOK_SCOPE_2026-04-30_001_TEMP.md` — Hook scope and customization exploration (validated, merged)
