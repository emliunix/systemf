# Change Plan: Reasoning Content Support (v6)

**Reviewed by:** Code review of tape entry format against `TapeEntry` constructor design
**Changes from v5:** Fixes `TapeEntry.tool_call` constructor signature; corrects reasoning storage format

---

## Facts

### Tape Entry Design

Tape entries are **simple, append-only records** with a `kind` and `payload`. The design principle is:

- **One entry per semantic unit** (message, tool call, tool result)
- **Payload is self-contained** — no cross-references between entries
- **Reconstruction is the reader's job** — `_default_messages` merges entries into API format

### Current `TapeEntry.tool_call` Constructor

From `republic/src/republic/tape/entries.py:45`:
```python
@classmethod
def tool_call(cls, calls: list[dict[str, Any]], **meta: Any) -> TapeEntry:
    return cls(id=0, kind="tool_call", payload={"calls": calls}, meta=dict(meta))
```

The constructor accepts `calls` (a list) and stores it in `payload["calls"]`. It does **not** accept reasoning.

### Current `record_chat` Usage

From `republic/src/republic/tape/manager.py:105`:
```python
if tool_calls:
    self._tape_store.append(tape, TapeEntry.tool_call(tool_calls, **meta))
```

`tool_calls` is passed directly as the `calls` argument. No reasoning is passed.

### Tool-Calling Turn Storage Gap

For tool-calling turns:
- `response_text=None` (no text content)
- `tool_calls=[...]` (tool calls present)
- `reasoning="..."` (reasoning present, from v3+ parsers)

**Problem:** `record_chat` stores `tool_calls` via `TapeEntry.tool_call()`, but reasoning has nowhere to go. The constructor doesn't accept it, and the `message` entry is skipped because `response_text is None`.

### v5 Implementation Bug

The v5 implementation attempted:
```python
# BROKEN — passes dict where list is expected
tool_call_payload = {"calls": tool_calls, "reasoning_content": reasoning}
TapeEntry.tool_call(tool_call_payload, **meta)
# Creates: payload = {"calls": {"calls": [...], "reasoning_content": "..."}}
```

This violates the constructor contract and creates a nested, malformed payload.

### Message Reconstruction Gap

From `republic/src/republic/tape/context.py:51`:
```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in entries:
        if entry.kind != "message":
            continue
        # ... copies message payloads
    # tool_call and tool_result entries are SKIPPED
```

`_default_messages` only handles `message` entries. `tool_call` entries are silently dropped. This means:
1. Tool calls are never reconstructed into assistant messages
2. Reasoning on tool_call entries is never read
3. The API message array is incomplete

---

## Design

### 1. Extend `TapeEntry.tool_call` Constructor

**File:** `republic/src/republic/tape/entries.py`

Add optional `reasoning` parameter:
```python
@classmethod
def tool_call(
    cls,
    calls: list[dict[str, Any]],
    reasoning: str | dict | None = None,
    **meta: Any,
) -> TapeEntry:
    payload: dict[str, Any] = {"calls": calls}
    if reasoning:
        if isinstance(reasoning, dict):
            payload["reasoning"] = reasoning
        else:
            payload["reasoning_content"] = reasoning
    return cls(id=0, kind="tool_call", payload=payload, meta=dict(meta))
```

The payload format becomes:
```json
{"calls": [{"id": "call_1", "type": "function", ...}], "reasoning_content": "Let me think..."}
```

### 2. Update `record_chat` to Pass Reasoning

**Files:** `republic/src/republic/tape/manager.py` (sync + async)

```python
if tool_calls:
    self._tape_store.append(
        tape,
        TapeEntry.tool_call(tool_calls, reasoning=reasoning, **meta),
    )
```

When `tool_calls` is present, reasoning is stored on the `tool_call` entry. When `response_text` is present, reasoning is stored on the `message` entry (already implemented in v3).

### 3. Update `_default_messages` to Handle `tool_call` Entries

**File:** `republic/src/republic/tape/context.py`

Replace the current `message`-only logic with a multi-kind handler:

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
                # Strip reasoning fields from text-only assistant messages (R1)
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

### 4. Remove Duplicate Assistant Message Creation

With `tool_call` entries now being reconstructed as assistant messages, we must **not** create an additional `message` entry for tool-call turns. The current `record_chat` logic is correct:

```python
if response_text is not None:
    # Only create message entry when there is actual text
    self._tape_store.append(tape, TapeEntry.message({...}, **meta))
```

For tool-call turns, `response_text=None`, so no `message` entry is created. The `tool_call` entry is the sole record of the assistant's turn.

---

## Why It Works

1. **Simple entries preserved:** Each turn produces exactly one entry — `message` for text, `tool_call` for tool calls, `tool_result` for results.

2. **Self-contained payloads:** The `tool_call` entry carries both the calls and the reasoning that produced them. No cross-referencing needed.

3. **Reconstruction is complete:** `_default_messages` now handles all three relevant entry kinds (`message`, `tool_call`, `tool_result`), producing a complete API message array.

4. **No duplication:** Tool-call turns produce one `tool_call` entry. Text turns produce one `message` entry. Never both.

5. **DeepSeek invariant I1 satisfied:** When reconstructing messages for API calls, tool-call assistant messages include `reasoning_content` from the `tool_call` entry payload.

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `republic/src/republic/tape/entries.py` | Modify | Add `reasoning` parameter to `TapeEntry.tool_call` |
| `republic/src/republic/tape/manager.py` | Modify | Pass `reasoning` to `TapeEntry.tool_call` in `record_chat` (sync + async) |
| `republic/src/republic/tape/context.py` | Modify | Handle `tool_call` entries in `_default_messages` |
| `changes/43-reasoning-content-support-v6.md` | Create | This change plan |

---

## Testing Plan

1. **Unit test:** `TapeEntry.tool_call` creates payload with `reasoning_content`
2. **Unit test:** `TapeEntry.tool_call` creates payload with `reasoning` dict
3. **Unit test:** `record_chat` stores reasoning on `tool_call` entry when `response_text=None`
4. **Integration test:** `_default_messages` reconstructs `tool_call` as assistant message with `tool_calls` and `reasoning_content`
5. **Integration test:** `_default_messages` strips reasoning from text-only assistant messages
6. **Regression test:** All 127 existing tests pass
7. **End-to-end test:** Full round-trip — tool-call turn with reasoning is stored and reconstructed correctly

---

## Out of Scope

- OpenAI Responses API streaming reasoning
- Reasoning summary extraction
- CLI display of reasoning
- Support for other reasoning providers

(End of file)
