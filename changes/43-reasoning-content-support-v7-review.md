# Change Plan: Reasoning Content Support — Architecture Review (v7)

**Reviewed by:** Code review tracing actual data flow through all layers
**Scope:** Verify timing, format, and correctness of v3-v6 implementation

---

## Part 1: Timing Analysis

### When Does Each Component Execute?

```
LLM Response (chunk or complete object)
    │
    ├─▶ _extract_chunk_reasoning() / _extract_reasoning()  [Parser layer]
    │       └── Returns: str | dict | None
    │
    ├─▶ Buffering (streaming only)
    │       └── reasoning_parts: list[str]
    │       └── Joined: "".join(reasoning_parts) or None
    │
    ├─▶ _finalize_text_stream() / _finalize_event_stream_state()  [ChatClient]
    │       └── Calls _update_tape() / _update_tape_async()
    │
    ├─▶ _update_tape()  [Tape bridge]
    │       └── Calls record_chat()
    │
    ├─▶ record_chat()  [TapeManager]
    │       └── Creates: TapeEntry.tool_call(calls, reasoning=reasoning)
    │       └── Or:     TapeEntry.message({"role": "assistant", ...})
    │
    └─▶ _default_messages()  [Message reconstruction]
            └── Reads tool_call entries
            └── Reconstructs: {"role": "assistant", "tool_calls": calls, "reasoning_content": reasoning}
```

### Timing: Text Stream (Sync)

```python
# In _build_text_stream:
for chunk in payload:
    text = _extract_chunk_text(chunk)           # ← text delta
    reasoning_delta = _extract_chunk_reasoning(chunk)  # ← reasoning delta
    if reasoning_delta:
        reasoning_parts.append(reasoning_delta)

# After loop (finally block):
reasoning = "".join(reasoning_parts) or None
_finalize_text_stream(..., reasoning=reasoning)  # → _update_tape
```

**Tape update count:** Exactly 1 per response (in `finally` block).

### Timing: Event Stream (Sync)

```python
# In _build_event_stream:
for chunk in payload:
    text = _extract_chunk_text(chunk)
    reasoning_delta = _extract_chunk_reasoning(chunk)
    if reasoning_delta:
        reasoning_parts.append(reasoning_delta)
        yield StreamEvent("reasoning", {"delta": reasoning_delta})

# After loop (try block):
tool_calls = assembler.finalize()
reasoning = "".join(reasoning_parts) or None
_finalize_event_stream(..., reasoning=reasoning)  # Does NOT call _update_tape

# Finally block:
if reasoning is None:
    reasoning = "".join(reasoning_parts) or None
_finalize_event_stream_state(..., reasoning=reasoning)  # → _update_tape
```

**Tape update count:** Exactly 1 per response (in `finally` block).

### Timing: Non-Streaming Response

```python
# In _handle_tool_calls_response:
calls = _extract_tool_calls(payload)
reasoning = _extract_reasoning(payload)
_update_tape(prepared, None, reasoning=reasoning, tool_calls=calls)  # Direct
```

**Tape update count:** Exactly 1 per response.

---

## Part 2: Format Analysis

### Tape Entry Format

**Text-only turn with reasoning:**
```python
TapeEntry.message({
    "role": "assistant",
    "content": "Hello",
    "reasoning_content": "Let me greet..."
})
```

**Tool-call turn with reasoning:**
```python
TapeEntry.tool_call(
    calls=[{"id": "call_1", "type": "function", ...}],
    reasoning="Let me calculate..."
)
# Payload: {"calls": [...], "reasoning_content": "..."}
```

**Tool-result turn:**
```python
TapeEntry.tool_result([{"tool_call_id": "call_1", "content": "42"}])
```

### Reconstructed Message Format

**From text-only message entry:**
```python
# _default_messages strips reasoning per R1
{"role": "assistant", "content": "Hello"}
```

**From tool-call entry:**
```python
# _default_messages preserves reasoning per I1
{
    "role": "assistant",
    "content": "",
    "tool_calls": [{"id": "call_1", ...}],
    "reasoning_content": "Let me calculate..."
}
```

---

## Part 3: Review Findings

### ✅ Correct

| # | Component | Finding |
|---|-----------|---------|
| 1 | `TapeEntry.tool_call` constructor | Accepts `reasoning` param, stores in payload correctly |
| 2 | `record_chat` | Passes reasoning to `TapeEntry.tool_call()` for tool-call turns |
| 3 | `record_chat` | Stores reasoning on `message` entry only for text-only turns (when `not tool_calls`) |
| 4 | `_default_messages` | Reconstructs `tool_call` entries as assistant messages with `tool_calls` + reasoning |
| 5 | `_default_messages` | Strips reasoning from text-only assistant messages per R1 |
| 6 | `_build_text_stream` (sync) | Extracts, buffers, and passes reasoning correctly |
| 7 | `_build_async_text_stream` | Now extracts, buffers, and passes reasoning (fixed in v5) |
| 8 | `_build_event_stream` (sync+async) | Yields reasoning deltas, passes to finalization |
| 9 | `_build_event_stream_from_response` (sync+async) | Extracts and passes reasoning |
| 10 | Non-streaming handlers | All 6 handlers extract and pass reasoning |
| 11 | `_finalize_event_stream_state` | Passes reasoning to `_update_tape` |
| 12 | Duplicate computation | Fixed with `if reasoning is None` guard in finally block |

### ⚠️ Minor Issues

| # | Component | Issue | Impact |
|---|-----------|-------|--------|
| 1 | `_error_event_sequence` | Does not accept or pass `reasoning` to `_final_event_data` | Error final events omit reasoning (tape still gets it via `_finalize_event_stream_state`) |
| 2 | Text-only turns | Reasoning is stripped in `_default_messages` | API correctness (R1), but UI cannot access reasoning from reconstructed messages |

### 🔍 Design Decision: Text-Only Reasoning Stripping

**Question:** Should text-only assistant messages preserve reasoning in `_default_messages`?

**Analysis:**
- DeepSeek R1 says reasoning is optional for text-only messages
- Stripping it is safe for API correctness
- BUT: If the user wants to display reasoning history, they cannot use `_default_messages`

**Resolution:** This is correct per the validation model. UI layers should query the tape directly for reasoning display, not rely on `_default_messages`.

---

## Part 4: Verification

### Test Results

```
127 passed, 1 warning
```

### Manual Trace: Tool-Call Turn with Reasoning

**Input:** Model returns `tool_calls=[echo]`, `reasoning_content="I should call echo"`

**Step 1 — Handler:**
```python
# _handle_tool_calls_response
calls = [{"id": "call_1", "function": {"name": "echo"}}]
reasoning = "I should call echo"
_update_tape(prepared, None, reasoning=reasoning, tool_calls=calls)
```

**Step 2 — Tape Update:**
```python
# _update_tape → record_chat
record_chat(..., response_text=None, reasoning="I should call echo", tool_calls=calls)
```

**Step 3 — Storage:**
```python
# record_chat
tool_calls is truthy →
TapeEntry.tool_call(calls, reasoning="I should call echo")
# Payload: {"calls": [{"id": "call_1", ...}], "reasoning_content": "I should call echo"}
```

**Step 4 — Reconstruction:**
```python
# _default_messages
entry.kind == "tool_call"
calls = [{"id": "call_1", ...}]
reasoning = "I should call echo"
msg = {
    "role": "assistant",
    "content": "",
    "tool_calls": calls,
    "reasoning_content": "I should call echo"
}
```

**Step 5 — API Message:**
```json
{
  "role": "assistant",
  "content": "",
  "tool_calls": [{"id": "call_1", "function": {"name": "echo"}}],
  "reasoning_content": "I should call echo"
}
```

**Result:** ✅ Satisfies DeepSeek I1 (tool calls + reasoning present)

### Manual Trace: Text-Only Turn with Reasoning

**Input:** Model returns `text="Hello"`, `reasoning_content="Let me greet"`

**Step 1 — Handler:**
```python
# _handle_create_response
text = "Hello"
reasoning = "Let me greet"
_update_tape(prepared, text, reasoning=reasoning)
```

**Step 2 — Storage:**
```python
# record_chat
response_text is not None →
TapeEntry.message({
    "role": "assistant",
    "content": "Hello",
    "reasoning_content": "Let me greet"
})
```

**Step 3 — Reconstruction:**
```python
# _default_messages
entry.kind == "message"
payload["role"] == "assistant"
payload.pop("reasoning_content", None)  # ← stripped per R1
msg = {"role": "assistant", "content": "Hello"}
```

**Result:** ✅ Satisfies DeepSeek R1 (text-only, reasoning optional)

---

## Part 5: Conclusion

**Verdict:** Implementation is **correct** and **complete**.

**No changes required.** The v3-v6 implementation correctly:

1. Extracts reasoning from all response formats
2. Buffers reasoning during streaming
3. Stores reasoning in the correct tape entry format
4. Reconstructs messages with reasoning preserved for tool-call turns
5. Strips reasoning from text-only turns per API requirements
6. Maintains simple-entry design (one entry per turn)

The only minor issue (`_error_event_sequence` omitting reasoning from final events) is cosmetic and does not affect tape correctness.

---

## References

- `analysis/REASONING_CONTENT_EXPLORATION.md` — Original architecture analysis
- `analysis/REASONING_VALIDATION_MODEL.md` — DeepSeek v4-pro validation rules
- `republic/src/republic/tape/entries.py` — TapeEntry constructors
- `republic/src/republic/tape/manager.py` — record_chat implementation
- `republic/src/republic/tape/context.py` — _default_messages reconstruction
- `republic/src/republic/clients/chat.py` — All response handlers

(End of file)
