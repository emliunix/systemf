# Change Plan: Reasoning Content Support (v3)

**Reviewed by:** Empirical validation via `analysis/test_state_machine_validation.py` and `analysis/test_complex_boundary.py`  
**Changes from v2:** Refined DeepSeek v4-pro rules based on empirical testing; corrected message reconstruction logic; added invariant documentation

---

## Facts

### Current State

Bub/Republic stack currently **does not extract, buffer, or store reasoning content** from LLM responses. The `reasoning_effort` parameter exists in Republic's `LLMCore` but is never set by Bub.

**API formats supported:**
- **OpenAI Chat Completions API** (via `CompletionTransportParser`) — used by most providers including DeepSeek
- **OpenAI Responses API** (via `ResponseTransportParser`) — used by OpenAI o-series models

### Empirical Findings (DeepSeek v4-pro, OpenAI format, Thinking Mode Enabled)

**Test Date:** 2025-05-07  
**Test Files:**
- `analysis/test_state_machine_validation.py` — 6 formal state machine tests
- `analysis/test_complex_boundary.py` — multi-turn boundary conditions
- `analysis/test_anthropic_combinations.py` — Anthropic endpoint thinking+signature matrix

#### Invariant I1 (Strict, Confirmed)

For any assistant message with `tool_calls` in the request payload:

```
m.role = "assistant" ∧ m.tool_calls ≠ ∅ ⟹ m.reasoning_content ≠ null ∧ m.reasoning_content ≠ ""
```

**Violation result:** HTTP 400 Bad Request
```json
{
  "error": {
    "message": "The `reasoning_content` in the thinking mode must be passed back to the API.",
    "type": "invalid_request_error",
    "code": "invalid_request_error"
  }
}
```

**Scope:** I1 is enforced **per-message**, not globally. Every assistant message with `tool_calls` in the array must have `reasoning_content`, including historical ones.

#### Relaxation R1 (Confirmed)

For text-only assistant messages (no `tool_calls`):

```
m.role = "assistant" ∧ m.tool_calls = ∅ ⟹ m.reasoning_content optional
```

Text-only assistant messages MAY omit `reasoning_content` without error.

#### Relaxation R2 (Refined)

Historical tool-call assistant messages may omit `reasoning_content` **only if** they are not followed by their corresponding `tool` result message in the current request. In practice: if the message array contains `[assistant(tool_calls), tool_result]`, the assistant MUST have `reasoning_content`.

#### Provider Comparison

| Provider | API | Reasoning Field | Tool Calls Require Reasoning | Text Requires Reasoning |
|----------|-----|-----------------|------------------------------|------------------------|
| DeepSeek v4-pro | OpenAI | `reasoning_content` | **YES** (I1) | No (R1) |
| DeepSeek | Anthropic | `thinking` block | **YES** | **YES** (if thinking mode on) |
| OpenAI o-series | Responses | `output` reasoning item | Yes (via previous_response_id) | Yes |

### Call Site Inventory

**Bub (top of stack):**
```
bub/src/bub/builtin/agent.py:104        _agent_loop → tape.run_tools_async / tape.stream_events_async
bub/src/bub/builtin/hook_impl.py:161    run_model → agent.run
bub/src/bub/builtin/hook_impl.py:169    run_model_stream → agent.run_stream
bub/src/bub/builtin/settings.py         AgentSettings (no reasoning_effort field)
```

**Republic LLM layer:**
```
republic/src/republic/llm.py:244        run_tools → _chat_client.run_tools
republic/src/republic/llm.py:271        run_tools_async → _chat_client.run_tools_async
republic/src/republic/llm.py:408        stream_events → _chat_client.stream_events
republic/src/republic/llm.py:435        stream_events_async → _chat_client.stream_events_async
```

**Republic ChatClient (response handling — ALL paths):**
```
republic/src/republic/clients/chat.py:583     _update_tape
republic/src/republic/clients/chat.py:720     _finalize_text_stream
republic/src/republic/clients/chat.py:759     _finalize_text_stream_async
republic/src/republic/clients/chat.py:798     _finalize_event_stream
republic/src/republic/clients/chat.py:853     _finalize_event_stream_async
republic/src/republic/clients/chat.py:909     _finalize_event_stream_state
republic/src/republic/clients/chat.py:936     _finalize_event_stream_state_async
republic/src/republic/clients/chat.py:986     _handle_create_response
republic/src/republic/clients/chat.py:1016    _handle_create_response_async
republic/src/republic/clients/chat.py:1046    _handle_tool_calls_response
republic/src/republic/clients/chat.py:1067    _handle_tool_calls_response_async
republic/src/republic/clients/chat.py:1088    _handle_tools_auto_response
republic/src/republic/clients/chat.py:1137    _handle_tools_auto_response_async
republic/src/republic/clients/chat.py:1554    _build_text_stream
republic/src/republic/clients/chat.py:1627    _build_async_text_stream
republic/src/republic/clients/chat.py:1722    _build_event_stream
republic/src/republic/clients/chat.py:1805    _build_async_event_stream
republic/src/republic/clients/chat.py:1890    _build_event_stream_from_response
republic/src/republic/clients/chat.py:1953    _build_async_event_stream_from_response
```

**Republic parsers (extraction):**
```
republic/src/republic/clients/parsing/completion.py:33     extract_text
republic/src/republic/clients/parsing/responses.py:95      extract_text
republic/src/republic/clients/parsing/types.py:25           extract_text interface
```

**Republic tape (storage):**
```
republic/src/republic/tape/manager.py:78      record_chat (sync)
republic/src/republic/tape/manager.py:204     record_chat (async)
republic/src/republic/tape/entries.py:30      TapeEntry.message
republic/src/republic/tape/context.py:51      build_messages / _default_messages
```

**Republic execution (API call):**
```
republic/src/republic/core/execution.py:697   run_chat_sync (has reasoning_effort param)
republic/src/republic/core/execution.py:753   run_chat_async (has reasoning_effort param)
republic/src/republic/core/execution.py:412   _with_responses_reasoning
```

### What Gets Stored Today

`record_chat` stores:
- `system_prompt` → `system` entry
- `new_messages` → `message` entries
- `response_text` → `message` entry (`{"role": "assistant", "content": text}`)
- `tool_calls` / `tool_results` → `tool_call` / `tool_result` entries
- `run` event → `{"status", "usage", "provider", "model"}`

The raw `response` object is passed to `record_chat` but only used for `_extract_usage(response)`. Reasoning content is discarded.

### Message Reconstruction Today

`_default_messages()` (context.py:51) filters to `kind == "message"` only and copies the payload verbatim. It does not strip or transform fields.

### User-Provided Messages

`_prepare_messages()` (chat.py:346) copies user-provided `messages` verbatim into the payload. If those messages contain `reasoning_content` from a prior DeepSeek call, they will be sent to the API.

---

## Design

### 1. Add Reasoning Configuration to Bub

**File:** `bub/src/bub/builtin/settings.py`

Add `reasoning_effort` to `AgentSettings`:
```python
reasoning_effort: str | None = None  # "low", "medium", "high", "xhigh", etc.
```

Load from environment/config: `BUB_REASONING_EFFORT`.

### 2. Pass Reasoning Effort Through the Stack

**Files:** 
- `bub/src/bub/builtin/agent.py`
- `republic/src/republic/llm.py`

Pass `reasoning_effort` as a kwarg through:
```python
# In agent loop
tape.run_tools_async(prompt, reasoning_effort=self.settings.reasoning_effort, ...)
```

`ChatClient` already splits `reasoning_effort` from kwargs (chat.py:510). `LLMCore` already accepts it. Only the top-level call sites need to pass it.

### 3. Extract Reasoning Content from Responses

**Files:**
- `republic/src/republic/clients/parsing/types.py`
- `republic/src/republic/clients/parsing/completion.py`
- `republic/src/republic/clients/parsing/responses.py`

Add `extract_reasoning()` to `BaseTransportParser` with **default implementation** (non-breaking):
```python
def extract_reasoning(self, response: Any) -> str | dict | None:
    return None
```

Add `extract_chunk_reasoning()` with **default implementation**:
```python
def extract_chunk_reasoning(self, chunk: Any) -> str:
    return ""
```

**CompletionTransportParser** (DeepSeek / Chat Completions):
```python
def extract_reasoning(self, response: Any) -> str | None:
    choices = field(response, "choices")
    if not choices:
        return None
    message = field(choices[0], "message")
    if message is None:
        return None
    return field(message, "reasoning_content") or None

def extract_chunk_reasoning(self, chunk: Any) -> str:
    choices = field(chunk, "choices")
    if not choices:
        return ""
    delta = field(choices[0], "delta")
    if delta is None:
        return ""
    return field(delta, "reasoning_content", "") or ""
```

**ResponseTransportParser** (OpenAI Responses API):
```python
def extract_reasoning(self, response: Any) -> dict | None:
    output = response if isinstance(response, list) else field(response, "output")
    if not isinstance(output, list):
        return None
    for item in output:
        if field(item, "type") == "reasoning":
            return dict(item)
    return None

def extract_chunk_reasoning(self, chunk: Any) -> str:
    # Reasoning in Responses API is not streamed as text deltas.
    return ""
```

### 4. Buffer Reasoning During Streaming

**Files:** `republic/src/republic/clients/chat.py`

**Non-streaming paths** (`_handle_create_response`, `_handle_create_response_async`, `_handle_tool_calls_response`, `_handle_tool_calls_response_async`, `_handle_tools_auto_response`, `_handle_tools_auto_response_async`):
- Extract reasoning via `_extract_reasoning(response)` 
- Pass to `_update_tape(..., reasoning=reasoning)` / `_update_tape_async(..., reasoning=reasoning)`

**Streaming paths** (`_build_text_stream`, `_build_async_text_stream`, `_build_event_stream`, `_build_async_event_stream`):
- Add `reasoning_parts: list[str] = []` alongside `parts: list[str] = []`
- Extract reasoning deltas via `_extract_chunk_reasoning(chunk, transport=transport)`
- Yield `StreamEvent("reasoning", {"delta": reasoning_delta})` for real-time display
- In `finally` block, pass `reasoning="".join(reasoning_parts) or None` to `_finalize_*`

**Event stream from response** (`_build_event_stream_from_response`, `_build_async_event_stream_from_response`):
- Extract reasoning via `_extract_reasoning(response, transport=transport)`
- Include reasoning in `StreamEvent("final", ...)` data
- Pass reasoning to `_update_tape` / `_update_tape_async`

### 5. Store Reasoning in Tape

**Files:** `republic/src/republic/tape/manager.py`

Update `record_chat` (both sync and async) signature:
```python
def record_chat(
    self,
    *,
    ...,
    response_text: str | None,
    reasoning: str | dict | None = None,  # NEW
    ...
) -> None:
```

Store reasoning as part of the assistant message payload:
```python
if response_text is not None:
    payload = {"role": "assistant", "content": response_text}
    if reasoning:
        if isinstance(reasoning, dict):
            payload["reasoning"] = reasoning
        else:
            payload["reasoning_content"] = reasoning
    self._tape_store.append(tape, TapeEntry.message(payload, **meta))
```

Note: Empty string `""` is treated as falsy and not stored.

### 6. Handle Reasoning in Message Reconstruction

**Critical insight (from empirical testing):** DeepSeek v4-pro enforces I1 **per-message**. Every assistant message with `tool_calls` must have `reasoning_content`. Text-only messages can omit it.

**Current Republic tape structure:**
- `message` entry: assistant text response
- `tool_call` entry: assistant tool calls (separate from message)
- `tool_result` entry: tool execution results

**Problem:** Since tool calls are stored separately, `_default_messages()` must reconstruct assistant messages that include `tool_calls` to determine whether to preserve `reasoning_content`.

**Files:** `republic/src/republic/tape/context.py`, `republic/src/republic/clients/chat.py`

**Tape context:** Replace `_default_messages()` with a smarter builder that:
1. Groups `message` entries with adjacent `tool_call` entries
2. Reconstructs assistant messages with `tool_calls` field when applicable
3. Conditionally preserves/strips reasoning based on tool_calls presence

```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    entry_list = list(entries)
    
    i = 0
    while i < len(entry_list):
        entry = entry_list[i]
        
        if entry.kind == "message":
            payload = dict(entry.payload)
            
            # Check if next entry is tool_call (belongs to this assistant message)
            if (payload.get("role") == "assistant" 
                and i + 1 < len(entry_list) 
                and entry_list[i + 1].kind == "tool_call"):
                # This assistant message made tool calls - preserve reasoning (I1)
                tool_calls = entry_list[i + 1].payload.get("calls", [])
                payload["tool_calls"] = tool_calls
                # reasoning_content MUST be preserved for tool-call messages
                messages.append(payload)
                i += 2  # Skip both message and tool_call
                continue
            else:
                # Normal turn - strip reasoning fields (R1)
                payload.pop("reasoning_content", None)
                payload.pop("reasoning", None)
                messages.append(payload)
        
        elif entry.kind == "tool_result":
            results = entry.payload.get("results", [])
            for result in results:
                messages.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": result.get("tool_call_id", "")
                })
        
        i += 1
    
    return messages
```

**ChatClient message preparation:** Update `_prepare_messages()` and `_prepare_messages_async()` to strip `reasoning_content` from user-provided messages (prevent accidental 400 errors):
```python
if messages is not None:
    payload = []
    for message in messages:
        msg = dict(message)
        msg.pop("reasoning_content", None)
        msg.pop("reasoning", None)
        payload.append(msg)
    return payload, []
```

### 7. Update Event Stream Finalization

**Files:** `republic/src/republic/clients/chat.py`

Update all finalization methods to accept `reasoning` parameter:
- `_finalize_text_stream` (line 720)
- `_finalize_text_stream_async` (line 759)
- `_finalize_event_stream` (line 798)
- `_finalize_event_stream_async` (line 853)
- `_finalize_event_stream_state` (line 909)
- `_finalize_event_stream_state_async` (line 936)

Each passes `reasoning` to `_update_tape` / `_update_tape_async`.

Update `_final_event_data` to include reasoning:
```python
def _final_event_data(self, ..., reasoning=None):
    data = {...}
    if reasoning is not None:
        data["reasoning"] = reasoning
    return data
```

### 8. Update `_update_tape` Helpers

**Files:** `republic/src/republic/clients/chat.py`

Update `_update_tape` (line 583) and `_update_tape_async` (line 616) signatures to accept `reasoning` parameter and pass it to `record_chat`:
```python
def _update_tape(
    self,
    prepared: PreparedChat,
    response_text: str | None,
    *,
    reasoning: str | dict | None = None,  # NEW
    tool_calls: list[dict[str, Any]] | None = None,
    ...
) -> None:
```

---

## Why It Works

1. **DeepSeek v4-pro compatibility:** By storing `reasoning_content` in the message payload and reconstructing assistant messages with `tool_calls` when adjacent to `tool_call` entries, we preserve reasoning for tool-call turns (satisfying I1) while stripping it for text-only turns (R1).

2. **OpenAI Responses compatibility:** Storing the full reasoning item dict allows future support for stateless mode. For now, stateful mode via `previous_response_id` handles reasoning persistence automatically.

3. **Streaming support:** Buffering reasoning deltas separately from content deltas allows real-time display of reasoning while ensuring the final tape entry has complete reasoning text.

4. **Backward compatibility:** Default implementations return `None`/`""`. Existing code paths without reasoning models continue to work unchanged. No breaking changes to parser interface.

5. **Provider-agnostic:** The design works for both DeepSeek (`reasoning_content` string) and OpenAI Responses (`reasoning` dict), with the transport parser handling provider-specific extraction.

6. **User-provided messages safe:** Stripping reasoning fields from user-provided messages prevents accidental 400 errors when users pass pre-constructed message arrays.

7. **Validated empirically:** All rules confirmed via `analysis/test_state_machine_validation.py` (5/6 tests pass; 6c expected failure confirms I1 strictness).

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub/src/bub/builtin/settings.py` | Modify | Add `reasoning_effort` field to `AgentSettings` |
| `bub/src/bub/builtin/agent.py` | Modify | Pass `reasoning_effort` to LLM calls |
| `republic/src/republic/clients/parsing/types.py` | Modify | Add `extract_reasoning()` and `extract_chunk_reasoning()` with defaults |
| `republic/src/republic/clients/parsing/completion.py` | Modify | Implement reasoning extraction for DeepSeek format |
| `republic/src/republic/clients/parsing/responses.py` | Modify | Implement reasoning extraction for Responses API format |
| `republic/src/republic/clients/chat.py` | Modify | Extract/buffer reasoning in ALL response paths; update ALL finalization methods |
| `republic/src/republic/tape/manager.py` | Modify | Accept and store `reasoning` in `record_chat` (sync + async) |
| `republic/src/republic/tape/context.py` | Modify | Reconstruct assistant messages with tool_calls; preserve/strip reasoning conditionally |
| `changes/43-reasoning-content-support-v3.md` | Create | This change plan |

---

## Migration Patterns

### Call sites that pass `reasoning_effort`
```python
# Before:
tape.run_tools_async(prompt, tools=tools)

# After:
tape.run_tools_async(prompt, tools=tools, reasoning_effort="medium")
```

### Tape entry payload with reasoning
```python
# Before:
{"role": "assistant", "content": "9.11 is greater"}

# After (DeepSeek text-only):
{"role": "assistant", "content": "9.11 is greater", "reasoning_content": "Let me compare..."}

# After (DeepSeek tool-call, reconstructed):
{"role": "assistant", "content": "", "reasoning_content": "I need to calculate...", "tool_calls": [{"id": "call_1", ...}]}

# After (OpenAI Responses):
{"role": "assistant", "content": "Paris", "reasoning": {"id": "rs_...", "type": "reasoning", ...}}
```

### Message reconstruction (automatic)
```python
# Text-only historical messages sent to API (reasoning stripped):
{"role": "assistant", "content": "9.11 is greater"}

# Tool-call historical messages sent to API (reasoning preserved):
{"role": "assistant", "content": "", "reasoning_content": "I need to calculate...", "tool_calls": [{"id": "call_1", ...}]}
```

---

## Testing Plan

1. **Unit test:** `CompletionTransportParser.extract_reasoning()` with DeepSeek response shape
2. **Unit test:** `CompletionTransportParser.extract_chunk_reasoning()` with DeepSeek streaming chunk
3. **Unit test:** `ResponseTransportParser.extract_reasoning()` with OpenAI Responses shape
4. **Integration test:** Streaming buffer accumulates reasoning + content separately
5. **Integration test:** `record_chat` stores reasoning in message payload
6. **Integration test:** `_default_messages` preserves reasoning for tool-call turns, strips for text turns
7. **Integration test:** `_prepare_messages` strips reasoning from user-provided messages
8. **End-to-end test:** Agent loop with `reasoning_effort="low"` produces tape with reasoning entries
9. **Validation test:** Message array with tool_calls but no reasoning returns 400 (confirm I1)
10. **Validation test:** Message array with text-only and no reasoning returns 200 (confirm R1)

---

## Out of Scope

- OpenAI Responses API stateless mode (ZDR / `store=false`) with encrypted reasoning items
- Reasoning summary extraction (`reasoning.summary` field)
- Displaying reasoning in CLI output (UI layer)
- Support for other reasoning providers (Gemini thinking, Claude extended thinking)
- Anthropic endpoint (`thinking` blocks vs `reasoning_content`) — separate change plan needed

---

## References

- `analysis/REASONING_VALIDATION_MODEL.md` — Consolidated empirical findings
- `analysis/test_state_machine_validation.py` — Formal state machine tests
- `analysis/test_complex_boundary.py` — Multi-turn boundary tests
- `analysis/FOLLOW_UP_TEST_PLAN.md` — Original test plan with results
- `analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` — Deep trace analysis

**Validation Date:** 2025-05-07  
**Model Tested:** `deepseek-v4-pro` (OpenAI format)  
**Total Test Cases:** 20/22 passed (2 expected failures confirming I1 strictness)
