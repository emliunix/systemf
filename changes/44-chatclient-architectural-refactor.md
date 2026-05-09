# ChatClient Architectural Refactor

## Design Overview

The new architecture separates concerns into three layers:

1. **ChatClient**: Pure transport parsing. Accepts execution config + messages, returns `LLMResult` or `StreamEvent[LLMResult]`.
2. **TapeSession**: Conversation state management. Reads/writes tape entries, builds message payloads, converts `LLMResult` to `TurnResult`.
3. **AgentRunner**: Orchestration. Controls the loop (LLM call → tool execution → repeat), delegates persistence to TapeSession.

## Design Goals

1. **Single-responsibility layers**: Parsing, execution, persistence, and orchestration are separate.
2. **Unified context object**: A `PreparedChat` carries intent; an `LLMResult` carries outcome.
3. **Isomorphic streaming/non-streaming**: Both APIs return the same information.
4. **Minimal event surface**: Only `TextEvent | FinalEvent | ErrorEvent` for streaming.
5. **Tape-agnostic core**: The chat layer reads from tape (to build payload) but does not write to it.

---

## Facts

### Current Architecture

```
ChatClient (1016 lines)
├─ Transport parsing (static methods, lines 212-309)
├─ Request preparation (lines 311-421)
│  ├─ _validate_chat_input: rejects prompt+messages, messages+tape
│  ├─ _prepare_request_from_prompt: fetches tape history
│  └─ _prepare_request_from_messages: wraps messages, disables tape
├─ Tool execution (lines 951-976)
│  └─ _execute_tool_calls_async → ToolExecutor.execute_async
├─ Tape logging (lines 465-510)
│  ├─ _update_tape_async: writes TapeEntry list
│  └─ _tape_entries: generates entries for single LLM call
├─ Stream building (lines 862-949)
│  └─ _build_async_event_stream: 80-line async generator
│     ├─ parses chunks
│     ├─ executes tools mid-stream (line 951)
│     ├─ writes tape in finally block (line 937)
│     └─ hides state in nonlocal closures
├─ Response handlers (lines 659-767)
│  ├─ _handle_create_response_async: text
│  ├─ _handle_tool_calls_response_async: tool calls
│  └─ _handle_tools_auto_response_async: tool calls + execute
└─ Public APIs (lines 769-842)
   ├─ run_tools_async: single turn, auto-execute
   └─ stream_events_async: single turn, streaming, auto-execute
```

### Current Type Hierarchy

```
republic/core/results.py (145 lines)
├─ StreamState
├─ TextStream / AsyncTextStream
├─ StreamEvent(kind: str, data: dict)  # tagged union via string
├─ AsyncStreamEvents  # wraps AsyncIterator[StreamEvent]
├─ ToolExecution
└─ ToolAutoResult
```

### Call Sites

**Files importing types from `core/results`:**
- `republic/src/republic/clients/chat.py` — uses all types
- `republic/src/republic/llm.py` — re-exports `ToolAutoResult`, `AsyncStreamEvents`
- `republic/src/republic/tape/session.py` — re-exports `ToolAutoResult`, `AsyncStreamEvents`
- `republic/src/republic/tools/executor.py` — uses `ToolExecution`
- `republic/src/republic/core/__init__.py` — re-exports all
- `republic/src/republic/__init__.py` — re-exports all

**Tests:**
- `tests/test_user_experience.py:348` — tests `stream_events_async` with tool execution
- No tests for agent loops (none exist in codebase).

### Existing Tape System

```
TapeEntry (dataclass)
├─ kind: "message" | "system" | "tool_call" | "tool_result" | "error" | "event" | "anchor"
├─ payload: dict
└─ meta: dict (includes run_id)

AsyncTapeManager
├─ read_messages(tape, context) → list[dict]  # builds messages from entries
└─ append_entry(tape, entry)
```

A "run" event is emitted per single LLM call with unique `run_id`, recording `status`, `usage`, `provider`, `model`.

---

## Design

### New Type System

Replace the tagged-union `StreamEvent` with a proper algebraic data type using `|` union.

```python
# republic/core/results.py

@dataclass
class PreparedChat:
    """Execution configuration for one LLM API call.
    
    Does NOT contain messages — messages are always retrieved from tape
    by TapeSession.run(). This enforces the single abstraction: the tape
    is the source of truth for conversation state.
    
    Users with fixed messages should use InMemoryTapeStore.
    
    Note: stream vs non-stream is encoded by which method is called (chat() vs stream()),
    not by a field in PreparedChat.
    
    Not frozen: kwargs is a mutable dict (common practice for **kwargs capture).
    Treated as immutable in practice; mutations are not supported.
    """
    tools: list[dict[str, Any]]         # Tool schemas for API
    model: str | None
    provider: str | None
    max_tokens: int | None
    reasoning_effort: Any | None
    kwargs: dict[str, Any]
    run_id: str                         # Correlation ID for tracing


@dataclass(frozen=True)
class LLMResult:
    """Complete outcome of a single LLM turn.
    
    This is the internal representation used by ChatClient.
    TapeSession.run() converts this to TurnResult (Finished | ToolCallNeeded)
    based on whether tool_calls are present.
    """
    request: PreparedChat
    text: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str | None = None
    usage: dict[str, Any] | None = None
    error: RepublicError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
    
    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


T = TypeVar('T')

@dataclass(frozen=True)
class TextEvent:
    content: str | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class FinalEvent(Generic[T]):
    result: T


@dataclass(frozen=True)
class ErrorEvent:
    error: RepublicError


# Generic union: ChatClient uses StreamEvent[LLMResult], TapeSession uses StreamEvent[TurnResult]
# type StreamEvent[T] = TextEvent | FinalEvent[T] | ErrorEvent  # Python 3.12+ syntax
```

### Tool Schema Helper

```python
def get_tool_schemas(tools: ToolInput) -> list[dict[str, Any]]:
    """Extract JSON schemas from ToolInput for LLM API payload.
    
    Separates schema extraction from runnable tool execution.
    ChatClient receives schemas; AgentRunner receives both schemas and runnable tools.
    """
    ...
```

**Separation of concerns**:
- `get_tool_schemas(tools)` → `PreparedChat.tools` → `ChatClient.chat()` (API payload)
- `normalize_tools(tools)` → `ToolSet` → `AgentRunner` + `ToolExecutor.execute_async()` (execution)

### PreparedChat Design Rationale

**Why `run_id` is part of `PreparedChat`**

`run_id` is a correlation ID for tracing. Putting it in `PreparedChat` makes every turn self-contained and traceable. `PreparedChat` is intentionally **not reusable** across turns — each turn gets its own `run_id` via `TapeSession.prepare()` or `TapeSession.add_tool_results()`. This is a type safety guarantee: you cannot accidentally reuse a `PreparedChat` from turn 1 in turn 2 (the `run_id` mismatch would be obvious in tape entries).

**Why `PreparedChat` has no messages field**

Messages are always retrieved from tape by `TapeSession`. This enforces the single abstraction: the tape is the source of truth. Users with fixed messages use `InMemoryTapeStore`.

**Why `PreparedChat` is not frozen**

`kwargs: dict[str, Any]` and `tools: list[dict]` are mutable — standard for **kwargs capture and tool schemas. Treated as immutable in practice.

### Retained Types (unchanged)

- `ToolExecution` — stays in `tools/executor.py` (not results)
- `ToolAutoResult` — **DEPRECATED**, replaced by `LLMResult`
- `StreamState` — **DELETED**, state moves to `LLMResult`
- `TextStream` / `AsyncTextStream` — **DELETED**, replaced by `AsyncIterator[TextEvent]`

### New ChatClient API

```python
class ChatClient:
    def __init__(self, core: LLMCore) -> None:
        self._core = core
    
    # ── Non-streaming ──
    async def chat(
        self,
        prepared: PreparedChat,
        messages: list[dict[str, Any]],
    ) -> LLMResult:
        """Execute single turn with given messages. Returns complete result.
        
        Messages are provided by the caller (typically TapeSession.run()).
        Does not execute tools.
        """
    
    # ── Streaming ──
    async def stream(
        self,
        prepared: PreparedChat,
        messages: list[dict[str, Any]],
    ) -> AsyncStreamEvents[LLMResult]:
        """Execute single turn with streaming. Returns wrapper over async generator.
        
        Messages are provided by the caller (typically TapeSession.run()).
        FinalEvent[LLMResult] contains complete LLMResult with parsed tool_calls.
        Does not execute tools.
        
        Returns AsyncStreamEvents wrapper (not raw AsyncIterator) to allow setup work
        (transport detection, error handling before first byte) in coroutine body.
        """
```

### Parser Helpers

`_extract_text`, `_extract_reasoning`, `_extract_usage` remain as module-level functions in `republic/clients/chat.py` (or `republic/parsing/` if extracted). They are pure parsing helpers used by `ChatClient` only.

`_extract_usage` standalone function (currently at end of chat.py) stays as module-level helper.

### ToolCallAssembler

Extract to `republic/parsing/assembler.py` or keep as inner class of `ChatClient`. It accumulates deltas and produces finalized `tool_calls` only when requested (at `FinalEvent` construction time).

### Parse State Ownership

Current: Hidden in `_build_async_event_stream` closure:
```python
parts: list[str] = []
assembler = ToolCallAssembler()
usage: dict | None = None
# ... nonlocal mutations
```

New: Explicit fields on a mutable accumulator (internal, not public API):
```python
@dataclass
class _ParseAccumulator:
    text_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    assembler: ToolCallAssembler = field(default_factory=ToolCallAssembler)
    usage: dict[str, Any] | None = None
    output_item_types: set[str] = field(default_factory=set)
    
    def to_result(self, prepared: PreparedChat, error: RepublicError | None = None) -> LLMResult:
        metadata_only = (
            len(self.output_item_types) > 0
            and self.output_item_types.issubset({"reasoning", "compaction"})
        )
        return LLMResult(
            request=prepared,
            text="".join(self.text_parts) if self.text_parts else None,
            tool_calls=self.assembler.finalize(),
            reasoning="".join(self.reasoning_parts) if self.reasoning_parts else None,
            usage=self.usage,
            error=error,
            metadata_only=metadata_only,
        )
```

### Isomorphic Mapping

Both APIs take `(prepared: PreparedChat, messages: list[dict])` — messages are read from tape by TapeSession.

| Information | Non-streaming (`chat`) | Streaming (`stream`) |
|-------------|------------------------|---------------------|
| Text content | `result.text` | Accumulated from `TextEvent.content` |
| Reasoning | `result.reasoning` | Accumulated from `TextEvent.reasoning` |
| Tool calls | `result.tool_calls` | Built by `ToolCallAssembler`, delivered in `FinalEvent.result.tool_calls` |
| Usage | `result.usage` | Last `usage` extracted, delivered in `FinalEvent.result.usage` |
| Error | `result.error` | `ErrorEvent` — stream terminates, error propagated. No `FinalEvent` follows. |

### Tape Integration

**Current**: `ChatClient` writes tape entries at 10+ call sites.

**New**: `ChatClient` is completely tape-agnostic. `TapeSession` handles all tape reads and writes. `TapeSession.run()` reads messages from tape and passes them to `ChatClient.chat()` / `ChatClient.stream()`. The orchestrator delegates to `TapeSession` for persistence.

### Dual Input Removal (User-Facing APIs)

**Remove** `messages` parameter from **user-facing** APIs (`LLM`, `Tape`). Users with fixed messages should use `InMemoryTapeStore`:

```python
from republic.tape import InMemoryTapeStore, AsyncTapeStore

store: AsyncTapeStore = InMemoryTapeStore()
# populate store with messages...
llm = LLM(model="gpt-4", tape_store=store)
result = await llm.chat("next prompt")
```

This eliminates the `prompt vs messages` branching in user-facing facades. `ChatClient` (internal) still accepts pre-assembled `messages: list[dict]` — this is intentional, as `TapeSession.run()` reads from tape and passes them in.

Eliminates:
- `_validate_chat_input` (no longer needed)
- `_prepare_request_from_messages` (deleted)
- Branching in `_prepare_request_async` (single path)
- `PreparedChat.should_update` (always true if tape is not None)

---

## Why It Works

### Boundary Clarity

| Layer | Owns | Does NOT Own |
|-------|------|-------------|
| `ChatClient` | Transport parsing, request building, stream event emission | Tool execution, tape writes, loop control |
| `ToolExecutor` | Tool execution | Parsing, tape |
| `TapeManager` | Read/write entries | LLM calls, tool execution |
| `AgentRunner` (new) | Loop control, tape logging, tool dispatch | Parsing |

### Backward Compatibility

The existing `LLM` facade (`republic/llm.py`) can preserve its public API during migration:
- `llm.run_tools_async()` → internally calls `chat_client.chat()` + `tool_executor.execute_async()` + loop
- `llm.stream_events_async()` → internally calls `chat_client.stream()` and re-emits events

Eventually these facade methods should move to `AgentRunner`.

### Type Safety

Union types (`TextEvent | FinalEvent[T] | ErrorEvent`) provide:
- Exhaustiveness checking via `match`/`case`
- No invalid states (impossible to have `kind="text"` with `result` field)
- Properly typed fields (no `dict[str, Any]` data bag)

---

## Files

### Modify

| File | Action | Details |
|------|--------|---------|
| `republic/core/results.py` | **Rewrite** | Replace `StreamEvent`, `AsyncStreamEvents`, `StreamState`, `TextStream`, `AsyncTextStream`, `ToolAutoResult` with `PreparedChat`, `LLMResult`, `TextEvent`, `FinalEvent`, `ErrorEvent`. Move `PreparedChat` from `clients/chat.py` to here. |
| `republic/core/__init__.py` | **Update exports** | Remove deleted types, add new types |
| `republic/__init__.py` | **Update exports** | Remove deleted types, add new types |
| `republic/clients/chat.py` | **Major refactor** | Remove `PreparedChat` (moved to results.py). Reduce to ~300 lines: `chat()`, `stream()`, `ToolCallAssembler`, static parsing helpers |
| `republic/llm.py` | **Adapt** | Update `run_tools_async` and `stream_events_async` to use new types; remove `ToolExecutor` from `LLM.__init__` (move to orchestrator later) |
| `republic/tape/session.py` | **Rewrite** | New TapeSession API with prepare/run/stream/add_tool_results/complete |
| `republic/tape/context.py` | **Adapt** | Update `build_messages()` for new entry format (tool_call in message + separate tool_call entry) |
| `republic/tools/executor.py` | **Adapt** | Add `ToolExecution` import (moved from results.py) |

### Delete (code within files)

| Code | Location | Rationale |
|------|----------|-----------|
| `_validate_chat_input` | `chat.py:311` | No more dual input |
| `_prepare_request_from_messages` | `chat.py:379` | No more `messages` input |
| `_execute_tool_calls_async` | `chat.py:951` | Tool execution moves out |
| `_update_tape_async` | `chat.py:465` | Tape writes move out |
| `_tape_entries` | `chat.py:473` | Tape writes move out |
| `_handle_create_response_async` | `chat.py:659` | Replaced by unified `chat()` |
| `_handle_tool_calls_response_async` | `chat.py:692` | Replaced by unified `chat()` |
| `_handle_tools_auto_response_async` | `chat.py:715` | Replaced by unified `chat()` |
| `_build_async_event_stream` closure pattern | `chat.py:862` | Use `_ParseAccumulator` instead |
| `_finalize_event_stream_async` | `chat.py:553` | Simplified to `accumulator.to_result()` |
| `_finalize_event_stream_state_async` | `chat.py:609` | Tape write removed |
| `_error_event_sequence` | `chat.py:636` | Inline in stream |
| `_event_async_error_result` | `chat.py:517` | Inline in stream |
| `run_tools_async` (from ChatClient) | `chat.py:769` | Moves to orchestrator |
| `_make_tool_context` | `chat.py:970` | Tool context construction moves to `AgentRunner` |
| `_extract_text`, `_extract_reasoning`, `_extract_usage` (static methods) | `chat.py:~978` | Become module-level functions (still in `clients/chat.py`) |
| `ToolAutoResult` | `results.py:90` | Replaced by `LLMResult` |
| `StreamState` | `results.py:12` | State moves to `LLMResult` |
| `TextStream` / `AsyncTextStream` | `results.py:18,35` | Replaced by `AsyncIterator[StreamEvent]` |
| `ToolExecution` | `results.py:83` | Move to `tools/executor.py` |
| `LLM` facade class | `llm.py` | **DEPRECATED** — forces coupling of ChatClient, ToolExecutor, TapeManager. Users should compose ChatClient + TapeSession + AgentRunner explicitly. Keep as migration shim only. |

### Create

| File | Purpose |
|------|---------|
| `republic/clients/_parse_accumulator.py` | Internal `_ParseAccumulator` dataclass (or inline in chat.py) |
| `tests/test_chat_client_refactor.py` | New tests for the refactored API |

---

## Tape Entry Design

### Entry Types ( republic/tape/entries.py )

The tape is append-only. Each entry is tagged with `kind`. The `TapeSession` knows how to convert application events into entries.

| `kind` | `payload` | Written by | Read by |
|--------|-----------|------------|---------|
| `system` | `{"content": str}` | `TapeSession.prepare()` | Recording/tracing only — NOT included in LLM payload (system_prompt is built at runtime) |
| `message` | `{"role": "user" \| "assistant", "content": ..., "reasoning_content": ..., "tool_calls": ...}` | `TapeSession.prepare()` (user), `TapeSession.run()` (assistant) | `build_messages` → OpenAI format messages |
| `tool_result` | `{"results": list[ToolResult]}` | `TapeSession.add_tool_results()` | `build_messages` → `role: "tool"` entries |
| `run` | `{"status": "ok" \| "error", "usage": dict, "provider": str, "model": str, "run_id": str}` | `TapeSession.run()` | (metadata) |
| `anchor` | `{"name": str, "state": dict}` | `TapeSession.handoff()` | `TapeQuery` slicing |
| `event` | `{"name": str, "data": dict}` | User / framework | (metadata) |

**Key changes from current design:**
- Keep `message` kind (single kind for all messages, vendor-neutral)
- Assistant messages include `reasoning_content` field in payload
- Tool calls are **dual saved**: inside assistant `message` entry AND as separate `tool_call` entries (for querying)
- `system` remains a separate entry (not mixed into `message`)

### Data Structure Detail

```python
# User message entry
TapeEntry.message(
    {"role": "user", "content": "hello"},
    run_id="abc123"
)

# Assistant message entry (with reasoning and tool calls)
TapeEntry.message(
    {
        "role": "assistant",
        "content": "I'll help you with that",
        "reasoning_content": "The user wants help, I should be friendly...",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "hello"}'}}
        ]
    },
    run_id="abc123"
)

# Tool result entry
TapeEntry.tool_result(
    [
        {"tool_call_id": "call_1", "content": "Found: Hello World"},
        {"tool_call_id": "call_2", "content": "Error: timeout"},
    ],
    run_id="abc123"
)

# Run metadata entry
TapeEntry.event(
    "run",
    {
        "status": "ok",
        "usage": {"total_tokens": 150, "prompt_tokens": 50, "completion_tokens": 100},
        "provider": "openai",
        "model": "gpt-4",
        "run_id": "abc123"
    },
    run_id="abc123"
)
```

### Reasoning Content Handling

```python
# When build_messages() reconstructs payload from tape:
{
    "role": "assistant",
    "content": text,
    "reasoning_content": reasoning,  # Preserved for latest assistant
    "tool_calls": tool_calls,
}

# Historical assistant messages have reasoning stripped (existing behavior):
# Pass 3 in build_messages strips reasoning_content from messages before last user
```

### Entry Ordering for a Complete Turn

```
[system prompt entry]          # once per session (optional) — TRACING ONLY, not in LLM payload
  ├── message entry            # role: "user" — "what user asked"
  ├── message entry            # role: "assistant" — "what LLM responded" + tool_calls + reasoning
  ├── tool_result entry        # "what tools returned" (only if tool_calls)
  ├── message entry            # role: "assistant" — "LLM response to tool results"
  ├── tool_result entry        # "more tool results"
  ├── ...
  └── event entry              # name: "run" — "metadata for this turn"
```

### Metadata-Only Response Handling

Current code has `_is_completed_responses_metadata_only` to handle Responses API replies that contain only reasoning/compaction items (no text output). This is preserved in the new design:

```python
@dataclass(frozen=True)
class LLMResult:
    # ... existing fields ...
    metadata_only: bool = False  # NEW: True if response has no text/tool_calls

# In _ParseAccumulator.to_result():
def to_result(self, prepared: PreparedChat, error: RepublicError | None = None) -> LLMResult:
    return LLMResult(
        request=prepared,
        text="".join(self.text_parts) if self.text_parts else None,
        tool_calls=self.assembler.finalize(),
        reasoning="".join(self.reasoning_parts) if self.reasoning_parts else None,
        usage=self.usage,
        error=error,
        metadata_only=self._is_metadata_only(),  # Check for reasoning-only responses
    )
```

When `metadata_only=True`, the turn is considered complete (returns `Finished` with empty text), not an error.

**Design Decision**: Tool calls are **dual saved**:
1. Inside the `message` entry (as `tool_calls` field in assistant payload) — for message reconstruction
2. As a separate `tool_call` entry — for explicit querying and inspection

This means a turn with tool calls produces:
```
message entry      # role: "assistant", content: "...", tool_calls: [...]
tool_call entry    # kind: "tool_call", payload: {"calls": [...]}
tool_result entry  # kind: "tool_result", payload: {"results": [...]}
```

The `tool_call` entry is redundant with the `tool_calls` field in the message, but provides:
- Easier querying (find all tool_call entries without parsing message payloads)
- Clearer semantics for tape inspection
- Backward compatibility with existing code that looks for `tool_call` kind

### Bub Agent Compatibility

Current bub agent (`bub/src/bub/builtin/agent.py`) does:
1. `tape.run_tools_async(prompt, system_prompt, tools)` — executes tools internally
2. `tape.stream_events_async(prompt, system_prompt, tools)` — streams events
3. Manual loop with `ToolAutoResult` parsing
4. Manual tape event appending (`append_event("loop.step", ...)`)

**New API for bub agent:**
```python
async def run(self, prompt: str, tape_name: str, ...) -> str:
    session = TapeSession(tape_name, self.store)
    runner = AgentRunner(self.chat_client, self.tool_executor)
    
    # The runner handles the loop; session handles all tape writes
    finished = await runner.run(prompt, session, tools=self.tools)
    
    # Framework-level events still possible:
    await session.append_event("loop.complete", {"steps": runner.step_count})
    
    return finished.text
```

The bub agent's manual event appending (`loop.step`, `loop.step.start`, `auto_handoff`) becomes **framework events** (`event` kind) that don't participate in message reconstruction but are available for inspection.

---

## Migration Path

1. **Phase 1**: Implement new types in `results.py` alongside old types (don't delete yet)
2. **Phase 2**: Refactor `ChatClient` to use new types. Old methods (`run_tools_async`, `stream_events_async`) move to `LLM` facade as temporary wrappers that delegate to `TapeSession` + new `ChatClient`.
3. **Phase 3**: Update `LLM` facade to delegate to new methods
4. **Phase 4**: Remove old types and methods
5. **Phase 5**: Build `AgentRunner` orchestrator with full loop support

---

## Open Questions

1. ~~Should `PreparedChat` be frozen?~~ **Resolved**: Not frozen. `kwargs` is a mutable dict — common practice for **kwargs capture. Treated as immutable in practice.
2. Should `_ParseAccumulator` be public (for advanced users who want to intercept parse state)?
3. Should `stream()` yield a `UsageEvent` when usage arrives mid-stream, or only in `FinalEvent`? **Decision**: only in `FinalEvent` to keep events minimal.
4. How do we handle multi-modal content (list[dict] parts) in user messages? Current `TapeEntry.message` supports `content: str | list[dict]`.
5. Should `assistant` entries with `tool_calls` also store `finish_reason` or other metadata?
6. How does `build_messages` handle `tool_result` entries that don't have a preceding `assistant` with `tool_calls`? **Decision**: Invalid state — skip with warning.

## Migration Notes

### `require_runnable` validation

Previously enforced by `ChatClient` before API call. After refactor, this validation moves to `AgentRunner.run()` (validates tools before first `session.prepare()`). Callers using `ChatClient` directly are responsible for their own validation.

### `StreamEvents` (sync variant)

**Removed**. Only async API (`AsyncStreamEvents` / `stream()`) is supported. Sync usage should wrap with `asyncio.run()` or use `chat()` (non-streaming).

---

## Design Note: LLMResult Boundaries

`LLMResult` contains only what the LLM API returned: text, tool_calls, reasoning, usage, error. Tool execution results are a separate concern handled by `ToolExecution`.

**Separation of concerns**:
- `LLMResult`: immutable snapshot of one LLM API response
- `ToolExecution`: immutable snapshot of one tool execution batch
- `TapeSession`: owns serialization of both into tape entries

### Typed Turn Result

```python
@dataclass(frozen=True)
class Finished:
    """LLM turn completed with final response."""
    result: LLMResult  # Full result — no field duplication


@dataclass(frozen=True)
class ToolCallNeeded:
    """LLM turn requires tool execution before continuing.
    
    Carries the tool calls extracted from the LLM result for the caller to execute.
    The session extracts _prepared internally to construct the next PreparedChat.
    Callers must NOT access _prepared directly — the only valid operation is
    passing this object to session.add_tool_results().
    """
    tool_calls: list[dict[str, Any]]  # What the caller needs to execute
    result: LLMResult  # Full result for metadata (text, reasoning, usage)
    _prepared: PreparedChat  # Internal: continuation context


# Union type: every LLM turn ends in one of these states
TurnResult = Finished | ToolCallNeeded
```

### Corrected TapeSession API

```python
class TapeSession:
    """Manages a single tape lifecycle. Owns serialization of all conversation turns."""
    
    def __init__(self, name: str, store: AsyncTapeStore, context: TapeContext | None = None):
        self._name = name
        self._store = store
        self._context = context or TapeContext()
    
    async def prepare(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        tools: ToolInput = None,
        model: str | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> PreparedChat:
        """Record user input and build request context.
        
        Side effects:
        - Appends system entry (if system_prompt provided)
        - Appends user message entry
        
        The system_prompt is NOT prepended to messages — it is recorded as a
        tape entry and included in message reconstruction by build_messages().
        
        Returns PreparedChat which is the only valid input to run()/stream().
        """
        ...
    
    async def run(
        self,
        chat: ChatClient,
        prepared: PreparedChat,
    ) -> TurnResult:
        """Execute LLM turn (non-streaming) and record result to tape.
        
        Reads messages from tape, passes to ChatClient.chat(), then records:
        - assistant message entry (text + reasoning + tool_calls)
        - tool_call entry (dual save)
        - run metadata entry (usage, provider, model, status)
        
        Returns either Finished (done) or ToolCallNeeded (must execute tools).
        """
        ...
    
    async def stream(
        self,
        chat: ChatClient,
        prepared: PreparedChat,
    ) -> AsyncIterator[StreamEvent[TurnResult]]:
        """Execute LLM turn (streaming) and record result to tape.
        
        Internally wraps ChatClient.stream() to:
        1. Read messages from tape
        2. Yield all ChatClient events (TextEvent, FinalEvent[LLMResult])
        3. On FinalEvent[LLMResult], append entries to tape
        4. Yield FinalEvent[TurnResult] (Finished | ToolCallNeeded)
        """
        ...
    
    async def add_tool_results(
        self,
        needed: ToolCallNeeded,
        results: list[Any],
    ) -> PreparedChat:
        """Record tool execution results to tape.
        
        Takes ToolCallNeeded as proof that tools were requested.
        Uses the embedded PreparedChat to preserve conversation context
        and returns a new PreparedChat ready for next run()/stream().
        
        Type enforcement: you cannot call run()/stream() after ToolCallNeeded
        without first calling add_tool_results().
        """
        ...
    
    async def handoff(
        self,
        name: str,
        *,
        state: dict[str, Any] | None = None,
        **meta: Any,
    ) -> list[TapeEntry]:
        """Append anchor and handoff event entries."""
        ...
    
    async def append_event(
        self,
        name: str,
        data: dict[str, Any] | None = None,
        **meta: Any,
    ) -> TapeEntry:
        """Append framework event entry (loop.step, auto_handoff, etc.).
        
        These events don't participate in message reconstruction but are
        available for inspection and debugging.
        """
        ...
        ...
    
    async def complete(
        self,
        *,
        extra_entries: list[TapeEntry] | None = None,
    ) -> None:
        """Mark the tape as complete. Optional extra entries for custom data."""
        ...
```

### Updated Boundary

| Layer | Owns | Does NOT Own |
|-------|------|-------------|
| `ChatClient` | Transport parsing, stream event emission | Tool execution, tape writes, loop control, request building |
| `ToolExecutor` | Tool execution | Parsing, tape |
| `TapeSession` | Read/write entries, **request building (prepare)**, **entry building from LLMResult AND ToolExecution**, payload reconstruction | LLM calls, tool execution, loop control |
| `AgentRunner` (new) | Loop control, tool dispatch | Parsing, entry building |

### Corrected Orchestrator Pattern

```python
class AgentRunner:
    def __init__(self, chat_client: ChatClient, tool_executor: ToolExecutor):
        self._chat = chat_client
        self._tools = tool_executor
    
    async def run(self, prompt: str, session: TapeSession, tools: list[Tool]) -> Finished:
        # Turn 1: prepare encodes user message, run executes + records
        prepared = await session.prepare(prompt=prompt, tools=tools)
        result = await session.run(self._chat, prepared)
        
        while isinstance(result, ToolCallNeeded):
            # Execute tools (separate concern from LLM)
            execution = await self._tools.execute_async(
                result.tool_calls, tools=tools
            )
            
            # Type enforcement: add_tool_results requires ToolCallNeeded
            # Uses the embedded PreparedChat to preserve context
            prepared = await session.add_tool_results(result, execution.tool_results)
            result = await session.run(self._chat, prepared)
        
        # Type enforcement: loop exits only when result is Finished
        await session.complete()
        return result
```

**Key insight**: Messages are never passed directly — they are always read from tape by TapeSession. This enforces the single abstraction: the tape is the source of truth for conversation state. Users with fixed messages should use InMemoryTapeStore.

**Key insight**: The tape layer knows the schema of entries (message, tool_call, tool_result, run event). The orchestrator just says "record this result" and "I'm done." The tape decides how to serialize.

**Key insight**: TapeSession internally wraps ChatClient.stream() to append entries on FinalEvent[LLMResult], then yields FinalEvent[TurnResult] to the caller. This hides the entry-building complexity from the consumer.

---

## Checklist

- [ ] All call sites of deleted types identified via grep: `StreamEvent` (old), `AsyncStreamEvents`, `ToolAutoResult`, `StreamState`, `TextStream`, `AsyncTextStream`, `StreamEvents` (sync)
- [ ] `ToolExecution` moved from `results.py` to `tools/executor.py`
- [ ] `PreparedChat` moved from `clients/chat.py` to `core/results.py`
- [ ] Test coverage for new `ChatClient.chat()` and `ChatClient.stream()` methods
- [ ] Test coverage for `TapeSession` lifecycle: prepare → run → add_tool_results → run → complete
- [ ] Backward compatibility: `LLM.run_tools_async()` and `LLM.stream_events_async()` still work (via delegation to TapeSession)
- [ ] `AgentRunner` validates `require_runnable` before first turn
- [ ] `build_messages()` updated for dual-save entry format
- [ ] Documentation update for new API (migration guide for LLM facade deprecation)
