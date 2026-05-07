# Tape Entry Timeline Exploration

## Notes

**Goal:** Trace the exact sequence of tape entries during a single user turn that involves reasoning, tool calls, tool results, and assistant replies.

**Key finding:** Bub does NOT use Republic's `_default_messages`. It uses a custom `_select_messages` in `bub/src/bub/builtin/context.py` that reconstructs OpenAI-format messages from separate tape entry kinds.

## Facts

### Fact 1: Bub uses custom message selector

From `bub/src/bub/builtin/context.py:12-16`:
```python
def default_tape_context() -> TapeContext:
    return TapeContext(select=_select_messages)
```

### Fact 2: `_select_messages` reconstructs tool calls into assistant messages

From `bub/src/bub/builtin/context.py:18-33`:
```python
def _select_messages(entries: Iterable[TapeEntry], _context: TapeContext) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []

    for entry in entries:
        match entry.kind:
            case "anchor":
                _append_anchor_entry(messages, entry)
            case "message":
                _append_message_entry(messages, entry)
            case "tool_call":
                pending_calls = _append_tool_call_entry(messages, entry)
            case "tool_result":
                _append_tool_result_entry(messages, pending_calls, entry)
                pending_calls = []
    return messages
```

### Fact 3: No assistant message entry for tool-calling turns

From `republic/src/republic/tape/manager.py:238-242`:
```python
if response_text is not None:
    await self._tape_store.append(
        tape,
        TapeEntry.message({"role": "assistant", "content": response_text}, **meta),
    )
```

When `_handle_tools_auto_response_async` passes `response_text=None` (because the model returned tool calls, not text), this block is SKIPPED.

### Fact 4: `_append_tool_call_entry` creates assistant message from tool_call entry

From `bub/src/bub/builtin/context.py:48-52`:
```python
def _append_tool_call_entry(messages: list[dict[str, Any]], entry: TapeEntry) -> list[dict[str, Any]]:
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    return calls
```

### Fact 5: `_append_tool_result_entry` creates tool role messages

From `bub/src/bub/builtin/context.py:55-86`:
```python
def _append_tool_result_entry(...):
    results = entry.payload.get("results")
    for index, result in enumerate(results):
        messages.append(_build_tool_result_message(result, pending_calls, index))

# Creates: {"role": "tool", "content": "...", "tool_call_id": "call_123", "name": "echo"}
```

### Fact 6: Agent loop events are separate

From `bub/src/bub/builtin/agent.py`:
```python
# Before LLM call:
await self.tapes.append_event(tape.name, "loop.step.start", {"step": step, "prompt": next_prompt})

# After LLM call:
await self.tapes.append_event(tape.name, "loop.step", {"step": step, "status": "continue", ...})
```

## Claims

### Timeline: User Input with Tool Calls (Two-Step Flow)

**Step 1: Initial LLM Call (User → Assistant with Tool Calls)**

Tape entries appended (in order):

```
# Agent loop events (Bub layer)
event    {"name": "loop.start", "data": {"model": "...", "prompt": "Call echo"}}
event    {"name": "loop.step.start", "data": {"step": 1, "prompt": "Call echo"}}

# LLM call recording (Republic layer)
system   {"content": "You are a helpful assistant..."}
message  {"role": "user", "content": "Call echo"}
tool_call {"calls": [{"id": "call_123", "type": "function", "function": {"name": "echo", "arguments": '{"text":"hello"}'}}]}
tool_result {"results": ["HELLO"]}
event    {"name": "run", "data": {"status": "ok", "usage": {...}}}

# Agent loop event (Bub layer)
event    {"name": "loop.step", "data": {"step": 1, "status": "continue"}}
```

**Critical observation:** There is NO `message` entry with `role="assistant"` for the tool-calling turn. The assistant message is reconstructed from the `tool_call` entry by `_select_messages`.

**Step 2: Continue Prompt (Tool Results → Assistant Final Reply)**

```
# Agent loop event
event    {"name": "loop.step.start", "data": {"step": 2, "prompt": "Continue the task."}}

# LLM call recording
system   {"content": "You are a helpful assistant..."}
message  {"role": "user", "content": "Call echo"}
         # (Note: tool_call and tool_result entries are between these, reconstructed by _select_messages)
message  {"role": "assistant", "content": "HELLO"}
event    {"name": "run", "data": {"status": "ok"}}

# Agent loop event
event    {"name": "loop.step", "data": {"step": 2, "status": "ok"}}
```

### What `_select_messages` produces for Step 2

Given the tape entries from Step 1, `_select_messages` reconstructs:

```python
[
    {"role": "user", "content": "Call echo"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "call_123", ...}]},
    {"role": "tool", "content": "HELLO", "tool_call_id": "call_123", "name": "echo"},
]
```

Then `_prepare_messages_async` adds:
```python
[
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "user", "content": "Call echo"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "call_123", ...}]},
    {"role": "tool", "content": "HELLO", "tool_call_id": "call_123", "name": "echo"},
    {"role": "user", "content": "Continue the task."},
]
```

### Implication for Reasoning Content Storage

**Problem:** For tool-calling turns, there is no assistant `message` entry to store `reasoning_content` on. The assistant message is reconstructed from the `tool_call` entry.

**Options:**

1. **Store reasoning on `tool_call` entry:**
   ```json
   {"calls": [...], "reasoning_content": "I should use the echo tool..."}
   ```
   Then modify `_append_tool_call_entry` to include it:
   ```python
   msg = {"role": "assistant", "content": "", "tool_calls": calls}
   reasoning = entry.payload.get("reasoning_content")
   if reasoning:
       msg["reasoning_content"] = reasoning
   messages.append(msg)
   ```

2. **Create assistant `message` entry even for tool calls:**
   Modify `record_chat` to always create an assistant message, even when `response_text=None`:
   ```python
   if response_text is not None or tool_calls:
       payload = {"role": "assistant", "content": response_text or ""}
       if reasoning:
           payload["reasoning_content"] = reasoning
       if tool_calls:
           payload["tool_calls"] = tool_calls
       self._tape_store.append(tape, TapeEntry.message(payload, **meta))
   ```
   This would change the tape schema significantly.

3. **Store reasoning as separate entry:**
   Add a new entry kind (e.g., `reasoning`) and link it to the turn.

**Recommendation: Option 1** — Store reasoning on the `tool_call` entry payload. This is minimally invasive:
- No new entry kinds
- `_append_tool_call_entry` already reads from the `tool_call` payload
- The reconstructed message can include `reasoning_content`

But wait — for normal text-only turns, reasoning is stored on the `message` entry:
```json
{"role": "assistant", "content": "Hello", "reasoning_content": "..."}
```

For tool-calling turns, reasoning would be on the `tool_call` entry:
```json
{"calls": [...], "reasoning_content": "..."}
```

This asymmetry is confusing but workable.

### DeepSeek Compatibility

For DeepSeek, `reasoning_content` must be preserved for tool-calling turns but stripped for normal turns.

With Option 1:
- Normal turn: `message` entry has `reasoning_content` → included in reconstructed message → DeepSeek sees it
  - But DeepSeek says normal turns should NOT include reasoning_content in history!
  - So we need to strip it during reconstruction for normal turns.

- Tool-call turn: `tool_call` entry has `reasoning_content` → included in reconstructed assistant message → DeepSeek sees it
  - This is correct per DeepSeek docs.

So the rule becomes:
- **Strip** `reasoning_content` from normal assistant `message` entries during reconstruction
- **Preserve** `reasoning_content` from `tool_call` entries during reconstruction

This can be implemented in `_select_messages`:
```python
def _append_message_entry(messages, entry):
    payload = dict(entry.payload)
    if payload.get("role") == "assistant":
        # Normal turn - strip reasoning_content
        payload.pop("reasoning_content", None)
    messages.append(payload)

def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        msg = {"role": "assistant", "content": "", "tool_calls": calls}
        # Tool-call turn - preserve reasoning_content
        reasoning = entry.payload.get("reasoning_content")
        if reasoning:
            msg["reasoning_content"] = reasoning
        messages.append(msg)
    return calls
```

### Open Questions

1. **Streaming path:** Does the same logic apply for `stream_events_async`? Yes — it uses the same `_update_tape_async` path.

2. **Claude compatibility:** Claude uses content blocks array. This would require storing reasoning as a `thinking` block alongside `tool_use` blocks. The `tool_call` entry payload could include a `thinking` field that `_append_tool_call_entry` converts to a content block.

3. **Multiple tool call rounds:** Each round adds another `tool_call` + `tool_result` sequence. Each would have its own `reasoning_content`.
