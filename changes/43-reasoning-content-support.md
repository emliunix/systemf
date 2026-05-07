# Change Plan: Reasoning Content Support

## Facts

### Current State

Bub/Republic stack currently **does not extract, buffer, or store reasoning content** from LLM responses. The `reasoning_effort` parameter exists in Republic's `LLMCore` but is never set by Bub.

**API formats supported:**
- **OpenAI Chat Completions API** (via `CompletionTransportParser`) — used by most providers including DeepSeek
- **OpenAI Responses API** (via `ResponseTransportParser`) — used by OpenAI o-series models

**Reasoning formats by provider:**

| Provider | API | Reasoning Location | Pass Back Required |
|----------|-----|-------------------|-------------------|
| DeepSeek | Chat Completions | `message.reasoning_content` | No (normal turns); Yes (tool call turns) |
| OpenAI (o-series) | Responses API | Separate `output` item (`type: "reasoning"`) | Yes (always, via `previous_response_id` or explicit items) |

**Critical constraint:** For reasoning models, the reasoning chain must be preserved across API calls within the same turn (especially for tool-calling flows). If reasoning is dropped, the model may re-reason from scratch or the API may return 400.

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

**Republic ChatClient (response handling):**
```
republic/src/republic/clients/chat.py:583     _update_tape
republic/src/republic/clients/chat.py:720     _finalize_text_stream
republic/src/republic/clients/chat.py:798     _finalize_event_stream
republic/src/republic/clients/chat.py:986     _handle_create_response
republic/src/republic/clients/chat.py:1046    _handle_tool_calls_response
republic/src/republic/clients/chat.py:1554    _build_text_stream
republic/src/republic/clients/chat.py:1722    _build_event_stream
republic/src/republic/clients/chat.py:1890    _build_event_stream_from_response
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

Add `extract_reasoning()` to `BaseTransportParser`:
```python
@abstractmethod
def extract_reasoning(self, response: Any) -> str | None: ...
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
```

**ResponseTransportParser** (OpenAI Responses API):
```python
def extract_reasoning(self, response: Any) -> dict | None:
    output = response if isinstance(response, list) else field(response, "output")
    if not isinstance(output, list):
        return None
    for item in output:
        if field(item, "type") == "reasoning":
            return dict(item)  # Return full reasoning item for replay
    return None
```

### 4. Buffer Reasoning During Streaming

**Files:** `republic/src/republic/clients/chat.py`

**Non-streaming paths** (`_handle_create_response`, `_handle_tool_calls_response`):
- Extract reasoning via `_extract_reasoning(response)` 
- Pass to `_update_tape(..., reasoning=reasoning)`

**Streaming paths** (`_build_text_stream`, `_build_event_stream`):
- Add `reasoning_parts: list[str] = []` alongside `parts: list[str] = []`
- Extract reasoning deltas from chunks (new `_extract_chunk_reasoning()` method on parser)
- Yield `StreamEvent("reasoning", {"delta": reasoning_delta})` for real-time display
- In `finally` block, pass `reasoning="".join(reasoning_parts)` to `_finalize_*`

**New parser method** (both parsers):
```python
def extract_chunk_reasoning(self, chunk: Any) -> str:
    # Completion: delta.reasoning_content
    # Responses: response.reasoning_summary_text.delta or similar
    ...
```

### 5. Store Reasoning in Tape

**Files:** `republic/src/republic/tape/manager.py`

Update `record_chat` signature:
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
    if reasoning is not None:
        if isinstance(reasoning, dict):
            # OpenAI Responses API format
            payload["reasoning"] = reasoning
        else:
            # DeepSeek format
            payload["reasoning_content"] = reasoning
    self._tape_store.append(tape, TapeEntry.message(payload, **meta))
```

### 6. Handle Reasoning in Message Reconstruction

**Files:** `republic/src/republic/tape/context.py`

Update `_default_messages()` to strip reasoning from historical messages for DeepSeek compatibility:
```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in entries:
        if entry.kind != "message":
            continue
        payload = dict(entry.payload)
        # DeepSeek: must NOT pass reasoning_content back in messages array
        # (API returns 400). Strip it from historical messages.
        payload.pop("reasoning_content", None)
        # OpenAI Responses: reasoning items are handled separately via
        # previous_response_id or explicit output items. Strip from messages.
        payload.pop("reasoning", None)
        messages.append(payload)
    return messages
```

**Note:** For OpenAI Responses API with stateless mode (ZDR), reasoning items must be explicitly passed back in the `input` array. This requires a separate code path that collects reasoning entries from the tape and formats them as `{"type": "reasoning", ...}` items. This is **out of scope** for this change — the current implementation uses `previous_response_id` for stateful mode.

### 7. Update Event Stream Finalization

**Files:** `republic/src/republic/clients/chat.py`

Update `_finalize_text_stream`, `_finalize_text_stream_async`, `_finalize_event_stream` to accept `reasoning` parameter and pass it to `_update_tape` / `_update_tape_async`.

Update `_final_event_data` to include reasoning in the final event:
```python
def _final_event_data(self, ..., reasoning=None):
    data = {...}
    if reasoning is not None:
        data["reasoning"] = reasoning
    return data
```

## Why It Works

1. **DeepSeek compatibility:** By storing `reasoning_content` in the message payload but stripping it during message reconstruction, we capture reasoning for display/storage while avoiding the 400 error on subsequent calls.

2. **OpenAI Responses compatibility:** Storing the full reasoning item dict allows future support for stateless mode. For now, stateful mode via `previous_response_id` handles reasoning persistence automatically.

3. **Streaming support:** Buffering reasoning deltas separately from content deltas allows real-time display of reasoning while ensuring the final tape entry has complete reasoning text.

4. **Backward compatibility:** The `reasoning` parameter defaults to `None`. Existing code paths without reasoning models continue to work unchanged.

5. **Provider-agnostic:** The design works for both DeepSeek (`reasoning_content` string) and OpenAI Responses (`reasoning` dict), with the transport parser handling provider-specific extraction.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub/src/bub/builtin/settings.py` | Modify | Add `reasoning_effort` field to `AgentSettings` |
| `bub/src/bub/builtin/agent.py` | Modify | Pass `reasoning_effort` to LLM calls |
| `republic/src/republic/clients/parsing/types.py` | Modify | Add `extract_reasoning()` to `BaseTransportParser` |
| `republic/src/republic/clients/parsing/completion.py` | Modify | Implement `extract_reasoning()` for DeepSeek format |
| `republic/src/republic/clients/parsing/responses.py` | Modify | Implement `extract_reasoning()` for Responses API format |
| `republic/src/republic/clients/chat.py` | Modify | Buffer reasoning deltas in streams; pass reasoning to tape |
| `republic/src/republic/tape/manager.py` | Modify | Accept and store `reasoning` in `record_chat` |
| `republic/src/republic/tape/context.py` | Modify | Strip reasoning fields from reconstructed messages |
| `changes/43-reasoning-content-support.md` | Create | This change plan |

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

# After (DeepSeek):
{"role": "assistant", "content": "9.11 is greater", "reasoning_content": "Let me compare..."}

# After (OpenAI Responses):
{"role": "assistant", "content": "Paris", "reasoning": {"id": "rs_...", "type": "reasoning", ...}}
```

### Message reconstruction (automatic)
```python
# Historical messages sent to API (reasoning stripped):
{"role": "assistant", "content": "9.11 is greater"}
```

## Testing Plan

1. **Unit test:** `CompletionTransportParser.extract_reasoning()` with DeepSeek response shape
2. **Unit test:** `ResponseTransportParser.extract_reasoning()` with OpenAI Responses shape
3. **Integration test:** Streaming buffer accumulates reasoning + content separately
4. **Integration test:** `record_chat` stores reasoning in message payload
5. **Integration test:** `build_messages` strips reasoning from historical messages
6. **End-to-end test:** Agent loop with `reasoning_effort="low"` produces tape with reasoning entries

## Out of Scope

- OpenAI Responses API stateless mode (ZDR / `store=false`) with encrypted reasoning items
- Reasoning summary extraction (`reasoning.summary` field)
- Displaying reasoning in CLI output (UI layer)
- Support for other reasoning providers (Gemini thinking, Claude extended thinking)
