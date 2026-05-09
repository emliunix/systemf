# Review: ChatClient Architectural Refactor (doc 44)

This is a review of the current on-disk content of `44-chatclient-architectural-refactor.md`.

The direction is sound. The separation into ChatClient / TapeSession / AgentRunner layers is the right shape. The following issues need resolution before implementation starts.

---

## Approved

- Removing tool execution and tape writes from `ChatClient`. The class genuinely does too much.
- `_ParseAccumulator` replacing closure-local `nonlocal` variables is a straightforward, correct improvement.
- Replacing `StreamEvent(kind: str, data: dict)` with a proper union type eliminates a class of runtime bugs.
- `LLMResult` as a unified outcome across streaming and non-streaming paths is clean.
- `metadata_only: bool` on `LLMResult` for Responses API reasoning-only replies — correctly preserved.
- `InMemoryTapeStore` already exists (`republic/tape/store.py:148`) — the doc's migration example is valid.

---

## Issues

### 1. `stream()` return type is not achievable with the declared signature

The doc declares:

```python
async def stream(
    self,
    prepared: PreparedChat,
    messages: list[dict[str, Any]],
) -> AsyncIterator[StreamEvent[LLMResult]]:
```

An `async def` function that `return`s a value is not an async generator; it is a coroutine. To return an `AsyncIterator` from a coroutine, the function must construct and return an iterator object explicitly (like the current `AsyncStreamEvents` wrapper). To be an async generator it must use `yield` and have no return type annotation of `AsyncIterator`. The doc must choose and commit to one:

- **Option A (object return)**: `async def stream(...) -> AsyncStreamEvents[LLMResult]` — coroutine returns a pre-built object (matches current pattern).
- **Option B (async generator)**: `async def stream(...)` with `yield` inside, annotated as `AsyncGenerator[StreamEvent[LLMResult], None]`.

Option A is safer because it allows set-up work (transport detection, error handling before first byte) to happen in the coroutine body before iteration begins. The doc should explicitly commit to this.

---

### 2. `TapeSession` rewrite has no API spec

The files table marks `tape/session.py` as **Rewrite** with the description "New TapeSession API with prepare/run/stream/add_tool_results/complete". The current `Tape` class delegates everything to `chat_client.run_tools_async()` and `chat_client.stream_events_async()`. The new design inverts this relationship — `TapeSession` becomes the driver that calls `ChatClient.chat()`.

No method signatures are defined. The Bub compatibility section shows aspirational pseudocode using `TapeSession(tape_name, self.store)`, `AgentRunner(...)`, and `runner.step_count`, none of which are specified anywhere. This is the largest gap in the document. A parallel design spec for the new `TapeSession` interface is required before implementation.

Minimum needed:
- Constructor signature (what does it accept — `AsyncTapeManager`? `AsyncTapeStore`? `TapeContext`?)
- `prepare(prompt, system_prompt) → None` or does it return something?
- `build_messages() → list[dict]` — confirmed return type
- `add_tool_results(execution: ToolExecution) → None`
- `complete(result: LLMResult) → None`

---

### 3. `ErrorEvent` vs `FinalEvent` stream contract is underspecified

The isomorphic mapping table says:

> Error: `ErrorEvent` (stream fatal) or `FinalEvent.result.error` (turn error)

This distinction is not enforced or clarified elsewhere. The current code always emits both — an `error` event followed by a `final` event — even on transport exceptions. The new design must decide:

**Option A (two-tier errors)**: `ErrorEvent` = unrecoverable, stream ends. `FinalEvent(result=LLMResult(error=...))` = normal turn-level error (e.g., empty response). Callers must handle both.

**Option B (single-tier)**: Drop `ErrorEvent`. All terminations go through `FinalEvent`. Transport exceptions that prevent constructing `LLMResult` raise a Python exception (not a stream event). This is simpler and exhaustiveness-checkable with `match`.

The doc should resolve this explicitly. Option B is preferred — it makes `FinalEvent` the single exit point and eliminates the dual-handling requirement in callers.

---

### 4. `PreparedChat` location and field changes are not in the migration table

Current location: `republic/clients/chat.py` (line 37).  
Designed location: `republic/core/results.py`.

The migration table does not list this move. Additionally, the current `PreparedChat` has fields that the new design removes — `payload`, `new_messages`, `should_update`, `context`, `system_prompt` — and adds new ones (`tools: list[dict]`, `kwargs: dict`, `reasoning_effort`). This is a significant structural change that affects every call site of `PreparedChat` construction. It needs to be in the table.

---

### 5. `system_prompt` ownership is undefined after removing it from `PreparedChat`

The current `PreparedChat.system_prompt` is used in `_tape_entries` to write the system entry to tape and in `_prepare_request_from_prompt` to prepend a `{"role": "system"}` message. The new `PreparedChat` has no `system_prompt` field.

The doc says the `system` tape entry is "written by `TapeSession.prepare()`" and "NOT included in LLM payload". But the current system message IS included in the LLM payload (prepended as `role: "system"` in `read_messages`). Who prepends it after the refactor? Presumably `TapeSession.build_messages()` does — but this must be stated explicitly.

---

### 6. Tool call dual-save is internally contradictory

Under "Key changes from current design" the doc says:

> `tool_call` is **merged into** assistant `message` entry (not a separate entry)

But under "Design Decision" later in the same section:

> Tool calls are **dual saved**:
> 1. Inside the `message` entry
> 2. As a separate `tool_call` entry

These two statements directly contradict each other. The "Key changes" section says no separate entry; the "Design Decision" section says there is one. Pick one and delete the other statement. (The dual-save rationale — easier querying, backward compatibility — is reasonable, but it must be the stated policy from the start, not buried after a contradicting claim.)

---

### 7. `_extract_reasoning` and `_extract_text` disposition not addressed

These are static methods on `ChatClient` used by every response handler. After the refactor, `ChatClient` still needs them (they're pure parsing). But the doc's description of the new `ChatClient` surface only mentions `chat()`, `stream()`, and `ToolCallAssembler`. Whether these helpers stay as private statics, move to a parsing module, or move into `_ParseAccumulator` is not stated. For a refactor of this size, the disposition of every current method should be explicit.

---

### 8. Migration phase 2 is structurally impossible as described

Phase 2 says: "Refactor `ChatClient` to use new types, keep old methods as wrappers."

The old methods (`run_tools_async`, `stream_events_async`) do tape writes. After making `ChatClient` tape-agnostic, these methods cannot be kept as wrappers inside `ChatClient` — they have no tape access. The wrappers must live in `LLM` or in a temporary `LegacyAdapter`. Phase 2 needs to specify where these compatibility shims live during migration.

---

### 9. `_make_tool_context` fate is unspecified

`_make_tool_context` (line 970) builds a `ToolContext` from `PreparedChat`. After the refactor, `ChatClient` doesn't execute tools, so this method is no longer needed in `ChatClient`. But `ToolContext` must still be constructed somewhere before `ToolExecutor.execute_async()` is called. This moves to `AgentRunner` or `TapeSession`. The method should appear in the delete table.

---

### 10. Open question 6 is actually a breaking change risk

Open question 6 asks:

> How does `build_messages` handle `tool_result` entries that don't have a preceding `assistant` with `tool_calls`?

This is not just an open question — the current `build_messages` in `context.py` (the three-pass algorithm) expects the existing entry order. The "tool_call merged into assistant message" change in the new entry design means `_build_full_messages` must change. This affects `TapeQuery` slicing, `TapeContext.select`, and any external code reading tapes. It must be in the files table as a modify to `tape/context.py`.

---

## Minor Points

- `PreparedChat` is declared `frozen=True` but `kwargs: dict[str, Any]` is mutable. Open question 1 asks about this but doesn't resolve it. The fix is straightforward: `kwargs: tuple[tuple[str, Any], ...]` or just accept shallow immutability. Should be resolved.
- The `_extract_usage` standalone function at the end of `chat.py` (line ~1006, marked `# TODO: check for deprecation`) is not mentioned in the delete table but is dead after the refactor.
- The `StreamEvents` (sync) type re-exported from `llm.py` is not listed for deletion in the call sites section, but it comes from `results.py` where `AsyncStreamEvents` is being deleted. Check whether `StreamEvents` (the sync variant) is also removed.
- `LLM.run_tools_async` currently passes `require_runnable=True` to enforce that tools are callable before any API call. After the refactor this validation responsibility moves somewhere — `AgentRunner`, `TapeSession`, or the caller. It should not silently disappear.

---

## Field Ownership Review

This section examines each dataclass and whether the fields it holds are consistent with its declared scope and usage.

---

### `PreparedChat` — execution config for one LLM call

Declared fields: `tools: list[dict]`, `model`, `provider`, `max_tokens`, `reasoning_effort`, `kwargs`, `run_id`.

**Issue A: `tools` carries only schemas, but `ToolSet` has two parts.**  
Currently `PreparedChat.toolset: ToolSet` holds both `schemas` (API payload) and `runnable` (callable `list[Tool]` for execution). In the new design `PreparedChat.tools: list[dict]` is only the schemas — `ChatClient` doesn't execute, so it doesn't need `runnable`. But `AgentRunner` needs `runnable: list[Tool]` to call `ToolExecutor.execute_async()`. The design silently splits `ToolSet` into two separate paths — `PreparedChat.tools` goes to `ChatClient`, and `runnable` must be passed separately to `AgentRunner`. This split is not documented anywhere. The `AgentRunner` pseudocode writes `tools=self.tools` but `self.tools` is never defined. Define where `runnable` lives and how it travels to `AgentRunner`.

**Issue B: `run_id` belongs to the invocation, not the config.**  
`run_id` is a correlation ID for a single API call. `PreparedChat` is described as "execution configuration". Config is typically reusable; `run_id` is unique per call, generated at construction time. This means `PreparedChat` cannot be reused across multiple calls (each turn needs its own `run_id`). The `AgentRunner` loop must construct a new `PreparedChat` each turn. This implication should be stated. Alternatively, `run_id` could be passed separately to `chat()` / `stream()` and removed from `PreparedChat`, keeping `PreparedChat` a reusable config object.

**Issue C: `frozen=False` with mutable fields.**  
The doc resolves open question 1 by making `PreparedChat` not frozen, because `kwargs` is a dict. But `tools: list[dict]` is also mutable. The type is documented as "treated as immutable in practice" — this should be explicitly noted for `tools` as well.

---

### `LLMResult` — complete outcome of a single LLM turn

Declared fields: `request: PreparedChat`, `text`, `tool_calls`, `reasoning`, `usage`, `error`, `metadata_only`.

**Issue D: `request: PreparedChat` is a wide back-reference.**  
`LLMResult` carries the full `PreparedChat` that produced it. The only downstream consumers of `result.request` are: `TapeSession` (needs `run_id`, `model`, `provider`) and `ToolCallNeeded._prepared` (see below). Carrying the full config object couples `LLMResult` to `PreparedChat` — you cannot create or test an `LLMResult` in isolation without constructing a `PreparedChat`. Consider flattening: `run_id: str`, `model: str | None`, `provider: str | None` directly on `LLMResult`. This decouples the result from the config and makes `LLMResult` independently constructable (important for tests and for callers using `ChatClient` without `AgentRunner`).

**Issue E: `frozen=True` with mutable field values.**  
`tool_calls: list[dict[str, Any]]` and `usage: dict[str, Any] | None` are mutable containers inside a frozen dataclass. `frozen=True` prevents reassignment of the fields but not mutation of the lists/dicts inside them. This is the same shallow-immutability issue as in `_ParseAccumulator`. The `LLMResult` docstring or design note should acknowledge this.

---

### `ToolCallNeeded` — LLM turn that requires tool execution

Declared fields: `result: LLMResult`, `_prepared: PreparedChat`.

**Issue F: `_prepared` is redundant — it equals `result.request`.**  
`ToolCallNeeded.result: LLMResult` and `LLMResult.request: PreparedChat`. Therefore `toolcallneeded._prepared == toolcallneeded.result.request`. The doc says `_prepared` is "internal: continuation context" and "callers should not access _prepared directly". But there is no information in `_prepared` that is not already accessible via `result.request`. This field should be dropped. `TapeSession` can use `tool_call_needed.result.request` instead.

---

### `Finished` — LLM turn with final text response

Declared fields: `result: LLMResult`.

**Observation (not a bug): `Finished` is a pure type tag.**  
`Finished` adds no fields beyond `LLMResult`. Its only role is to make `Finished | ToolCallNeeded` a discriminated union. This is a valid functional pattern, but it's worth documenting explicitly so implementors don't try to add fields to it. The alternative — returning `LLMResult` directly and letting callers branch on `result.has_tool_calls` — should be explicitly rejected in the design (it is valid but loses the exhaustiveness guarantee at the type level).

---

### `TextEvent` — streaming delta

Declared fields: `content: str | None`, `reasoning: str | None`.

**Issue G: A `TextEvent` with both fields `None` is structurally valid but semantically empty.**  
`TextEvent(content=None, reasoning=None)` is a valid instance by the type, but carries no information. The stream consumer would receive it and produce no output. Add a `__post_init__` validator or use a `assert content is not None or reasoning is not None` guard. Alternatively split into `ContentEvent(content: str)` and `ReasoningEvent(reasoning: str)` — distinct types with non-optional fields — which also enables separate `match` arms for callers that only care about one.

---

### `_ParseAccumulator` — internal streaming state

Declared fields: `text_parts`, `reasoning_parts`, `assembler`, `usage`.

**Issue H: `_is_metadata_only()` cannot be implemented from the declared fields.**  
The doc specifies `metadata_only=self._is_metadata_only()` in `to_result()`. But the current implementation computes this from `output_item_types: set[str]` and `response_completed: bool` — neither of which appears in `_ParseAccumulator`. For `_is_metadata_only()` to work, the accumulator needs:

```python
output_item_types: set[str] = field(default_factory=set)
response_completed: bool = False
```

These must be updated during iteration (the Responses API emits `response.output_item.added` and `response.completed` events). The `_ParseAccumulator` spec is incomplete without them.

---

### `ToolExecution` — outcome of one tool execution batch

Declared fields: `tool_calls: list[dict]`, `tool_results: list[Any]`, `error`.

**Issue I: `tool_calls` is redundant from `AgentRunner`'s perspective.**  
`AgentRunner` calls `ToolExecutor.execute_async(result.tool_calls, ...)` and gets back `ToolExecution`. At this point `AgentRunner` already has `result.tool_calls` — it doesn't need them again from `ToolExecution`. The only field `AgentRunner` needs from `ToolExecution` is `tool_results` (and `error`). `ToolExecution.tool_calls` was useful when `ChatClient` assembled both tool calls and results in one object (`ToolAutoResult`). After the refactor, the tool calls live on `LLMResult` and the results live on `ToolExecution` — pairing them is the caller's job, not `ToolExecution`'s. Consider dropping `tool_calls` from `ToolExecution` to match its new narrower role.

---

### `TapeEntry.meta` — open dict for cross-cutting concerns

`run_id` is stored in `meta` as a keyword argument (`**meta`). The trace is: `PreparedChat.run_id` → `TapeSession` writes it → `TapeEntry.meta["run_id"]`. This is an open dict key with no type-level enforcement. No change proposed here (it's existing infrastructure), but `TapeSession`'s responsibility to set `run_id` consistently on every entry it writes should be stated explicitly in the spec.

---

## Summary

| # | Issue | Severity |
|---|-------|----------|
| 1 | `stream()` return type vs. async generator ambiguity | Must resolve before impl |
| 2 | `TapeSession` rewrite has no API spec | Must resolve before impl |
| 3 | `ErrorEvent` vs `FinalEvent` termination contract underspecified | Must resolve before impl |
| 4 | `PreparedChat` move + field changes missing from migration table | Fix in doc |
| 5 | `system_prompt` ownership after removal from `PreparedChat` | Fix in doc |
| 6 | `tool_call` dual-save contradicts "merge into message" claim | Fix in doc |
| 7 | `_extract_reasoning`, `_extract_text` disposition not stated | Fix in doc |
| 8 | Phase 2 wrappers can't live in tape-agnostic `ChatClient` | Fix in doc |
| 9 | `_make_tool_context` not in delete table | Fix in doc |
| 10 | `build_messages` / `context.py` change not in files table | Fix in doc |
| A | `PreparedChat.tools` only holds schemas; `runnable` split path undocumented | Must resolve before impl |
| B | `run_id` in `PreparedChat` makes it non-reusable; consider moving to call site | Fix in doc |
| C | `PreparedChat` has mutable `tools: list[dict]` but is documented as immutable | Fix in doc |
| D | `LLMResult.request: PreparedChat` wide back-reference couples result to config | Fix in doc |
| E | `LLMResult` `frozen=True` with mutable `tool_calls: list` and `usage: dict` | Fix in doc |
| F | `ToolCallNeeded._prepared` is redundant — equals `result.request` | Fix in doc |
| G | `TextEvent(content=None, reasoning=None)` is structurally valid but empty | Fix in doc |
| H | `_ParseAccumulator` missing `output_item_types` and `response_completed` for `_is_metadata_only()` | Must resolve before impl |
| I | `ToolExecution.tool_calls` is redundant after refactor; consider dropping | Fix in doc |
