# Change Plan: Reasoning Content Support (v5)

**Reviewed by:** Code style and dataflow architecture review of v4 implementation
**Changes from v4:** Fixes async text stream; fixes reasoning storage for tool-call-only responses; fixes message reconstruction for tool-call entries

---

## Facts

### Critical Bugs Found in v4 Review

**Bug 1: Async text stream lacks reasoning support**
- `_build_async_text_stream` has no `reasoning_parts` buffer
- No `_extract_chunk_reasoning()` calls in the streaming loop
- Does not pass `reasoning` to `_finalize_text_stream_async`
- Impact: All async streaming text responses silently lose reasoning

**Bug 2: Reasoning lost when `response_text is None`**
- `record_chat` only stores reasoning inside `if response_text is not None:` (manager.py:113)
- Tool-call-only responses pass `response_text=None` → reasoning is never stored
- Impact: DeepSeek v4-pro invariant I1 is violated (tool calls require reasoning_content)

**Bug 3: `_default_messages` never reconstructs tool_call entries**
- The function handles `message` and `tool_result` kinds, but silently skips `tool_call` entries
- Even if it did handle them, the forward-looking adjacency check (`i + 1`) never matches because `tool_call` entries are appended BEFORE assistant `message` entries in `record_chat`
- Impact: Tool calls are never reconstructed into assistant messages; reasoning preservation logic is dead code

---

## Design

### 1. Fix Async Text Stream Reasoning

**File:** `republic/src/republic/clients/chat.py`

**Non-stream branch** (`_build_async_text_stream`, line 1694):
- Add: `reasoning = self._extract_reasoning(payload, transport=transport)`
- Pass `reasoning=reasoning` to `_finalize_text_stream_async`

**Streaming branch** (`_build_async_text_stream`, line 1717):
- Add: `reasoning_parts: list[str] = []`
- Inside the async for loop: extract reasoning deltas, append to `reasoning_parts`
- In `finally` block: compute `reasoning = "".join(reasoning_parts) if reasoning_parts else None`
- Pass `reasoning` to `_finalize_text_stream_async`

### 2. Fix Reasoning Storage When response_text is None

**File:** `republic/src/republic/tape/manager.py`

Change the storage condition from:
```python
if response_text is not None:
```
to:
```python
if response_text is not None or reasoning:
```

When `response_text is None` but `reasoning` is present:
```python
payload = {"role": "assistant", "content": response_text or ""}
if reasoning:
    if isinstance(reasoning, dict):
        payload["reasoning"] = reasoning
    else:
        payload["reasoning_content"] = reasoning
self._tape_store.append(tape, TapeEntry.message(payload, **meta))
```

This ensures an assistant message is always created when reasoning is present, even for tool-call-only turns.

### 3. Fix Message Reconstruction for Tool-Call Entries

**File:** `republic/src/republic/tape/context.py`

Add handling for `tool_call` entries in `_default_messages`:

```python
elif entry.kind == "tool_call":
    payload = dict(entry.payload) if isinstance(entry.payload, dict) else {}
    calls = payload.get("calls", [])
    if calls:
        msg = {"role": "assistant", "content": "", "tool_calls": calls}
        # Preserve reasoning if present on tool_call entry (for API correctness)
        reasoning = payload.get("reasoning_content") or payload.get("reasoning")
        if reasoning:
            if isinstance(reasoning, dict):
                msg["reasoning"] = reasoning
            else:
                msg["reasoning_content"] = reasoning
        messages.append(msg)
```

Remove the broken forward-looking adjacency logic for assistant messages. Instead:
- For text-only assistant messages (no associated tool_call): strip reasoning fields
- For tool-call turns: reasoning is handled when processing the `tool_call` entry itself

Updated flow:
```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    entry_list = list(entries)
    
    i = 0
    while i < len(entry_list):
        entry = entry_list[i]
        
        if entry.kind == "message":
            payload = dict(entry.payload) if isinstance(entry.payload, dict) else {}
            if payload.get("role") == "assistant":
                # Strip reasoning from text-only assistant messages (R1)
                payload.pop("reasoning_content", None)
                payload.pop("reasoning", None)
            messages.append(payload)
        
        elif entry.kind == "tool_call":
            payload = dict(entry.payload) if isinstance(entry.payload, dict) else {}
            calls = payload.get("calls", [])
            if calls:
                msg = {"role": "assistant", "content": "", "tool_calls": calls}
                # Preserve reasoning for tool-call messages (I1)
                reasoning = payload.get("reasoning_content") or payload.get("reasoning")
                if reasoning:
                    if isinstance(reasoning, dict):
                        msg["reasoning"] = reasoning
                    else:
                        msg["reasoning_content"] = reasoning
                messages.append(msg)
        
        elif entry.kind == "tool_result":
            results = entry.payload.get("results", []) if isinstance(entry.payload, dict) else []
            for result in results:
                if isinstance(result, dict):
                    messages.append({
                        "role": "tool",
                        "content": str(result.get("content", result)),
                        "tool_call_id": result.get("tool_call_id", ""),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                        "tool_call_id": "",
                    })
        
        i += 1
    
    return messages
```

### 4. Remove Duplicate Reasoning Computation

**File:** `republic/src/republic/clients/chat.py`

In `_build_event_stream` and `_build_async_event_stream`, reasoning is computed twice (in `try` block for `_finalize_event_stream`, then again in `finally` block for `_finalize_event_stream_state`).

Simplify by computing once in `finally` and passing to both finalization methods. Since `_finalize_event_stream_state` is called in `finally` after `_finalize_event_stream`, we can compute reasoning once before `_finalize_event_stream` and reuse it.

Actually, looking at the control flow more carefully:
- `_finalize_event_stream` is called in the `try` block (after the loop completes normally)
- `_finalize_event_stream_state` is called in the `finally` block
- If an exception occurs, the `try` block's `_finalize_event_stream` is skipped, but `finally` still runs

So we need reasoning in both places. But we can compute it once using `nonlocal`:

```python
def _iterator() -> Iterator[StreamEvent]:
    nonlocal usage, tool_calls, tool_results, response_completed, reasoning
    reasoning = None
    try:
        for chunk in payload:
            # ... extract deltas, text, reasoning ...
            reasoning_delta = self._extract_chunk_reasoning(chunk, transport=transport)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                yield StreamEvent("reasoning", {"delta": reasoning_delta})
        
        tool_calls = assembler.finalize()
        reasoning = "".join(reasoning_parts) if reasoning_parts else None
        events, tool_results = self._finalize_event_stream(
            prepared,
            parts=parts,
            reasoning=reasoning,
            # ...
        )
        yield from events
    except Exception as exc:
        # ... error handling ...
    finally:
        if reasoning is None:
            reasoning = "".join(reasoning_parts) if reasoning_parts else None
        tool_calls = self._finalize_event_stream_state(
            prepared,
            parts=parts,
            reasoning=reasoning,
            # ...
        )
```

This avoids recomputing when the `try` block succeeded, while still computing it in `finally` when an exception occurred.

---

## Why It Works

1. **Async parity:** Sync and async text streams now both extract and buffer reasoning, maintaining the sync/async parity expected by consumers.

2. **Tool-call reasoning preserved:** By storing an assistant message with empty content when reasoning is present, we ensure reasoning is captured even for tool-call-only turns.

3. **Message reconstruction fixed:** By handling `tool_call` entries directly and converting them to assistant messages with `tool_calls`, we ensure the reconstructed message array includes all necessary fields for API correctness.

4. **Efficiency:** Removing duplicate computation avoids redundant string joins in the hot path.

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `republic/src/republic/clients/chat.py` | Modify | Add reasoning to async text stream; optimize duplicate computation |
| `republic/src/republic/tape/manager.py` | Modify | Store reasoning even when response_text is None |
| `republic/src/republic/tape/context.py` | Modify | Handle tool_call entries; fix reasoning preservation |
| `changes/43-reasoning-content-support-v5.md` | Create | This change plan |

---

## Testing Plan

1. **Unit test:** `_build_async_text_stream` extracts and passes reasoning
2. **Unit test:** `record_chat` stores assistant message with empty content when reasoning is present but text is None
3. **Unit test:** `_default_messages` reconstructs tool_call entries as assistant messages with tool_calls
4. **Integration test:** Async text stream round-trip (extract → buffer → store → retrieve)
5. **Regression test:** All existing tests pass (127/127)

---

## Out of Scope

- OpenAI Responses API streaming reasoning extraction
- Reasoning summary extraction
- CLI display of reasoning
- Support for other reasoning providers

(End of file)
