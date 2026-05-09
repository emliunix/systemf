# Change Plan: Reasoning Content Support (v8)

**Reviewed by:** Reading `REASONING_VALIDATION_MODEL.md` and `test_state_machine_validation.py`
**Key Finding:** ALL tool-call assistant messages after the last user message need reasoning_content

---

## Facts

### From Analysis

**Test 3:** Tool-call message after user message WITHOUT reasoning → 400 Error
**Test 5 (R2):** Historical tool-call message (before last user message) without reasoning → 200 OK
**Example 2:** ALL tool-call messages after user message need reasoning — dropping any causes 400

### Correct Rule

```
Last user message in array
    ↓
All assistant messages AFTER it with tool_calls → MUST have reasoning_content
All assistant messages BEFORE it → reasoning_content optional (can strip)
```

### Storage Format (Do Not Discard)

```python
# Text turn
TapeEntry.message({
    "role": "assistant",
    "content": "Hello",
    "reasoning_content": "Let me greet..."  # stored
})

# Tool-call turn
TapeEntry.message({
    "role": "assistant",
    "content": "",
    "reasoning_content": "I need to calculate...",  # stored
})
TapeEntry.tool_call({"calls": [...]})
```

### Reconstruction Format

```python
# Messages before last user: strip reasoning
{"role": "assistant", "content": "4"}  # no reasoning

# Messages after last user with tool_calls: add reasoning
{"role": "assistant", "content": "", "tool_calls": [...], "reasoning_content": "..."}
```

---

## Design

### 1. Storage: Keep All Reasoning

**File:** `republic/src/republic/tape/manager.py`

```python
# Store reasoning on assistant message ALWAYS
if response_text is not None or reasoning:
    payload = {"role": "assistant", "content": response_text or ""}
    if reasoning:
        payload["reasoning_content"] = reasoning
    TapeEntry.message(payload, **meta)
```

### 2. Reconstruction: Add Reasoning Only to Active Batch

**File:** `republic/src/republic/tape/context.py`

```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    entry_list = list(entries)
    
    # First pass: build all messages, merge tool_calls
    i = 0
    while i < len(entry_list):
        entry = entry_list[i]
        
        if entry.kind == "message":
            payload = dict(entry.payload) if isinstance(entry.payload, dict) else {}
            
            # Check if next entry is tool_call (belongs to this assistant)
            if (payload.get("role") == "assistant"
                    and i + 1 < len(entry_list)
                    and entry_list[i + 1].kind == "tool_call"):
                tool_calls = entry_list[i + 1].payload.get("calls", []) if isinstance(entry_list[i + 1].payload, dict) else []
                payload["tool_calls"] = tool_calls
                messages.append(payload)
                i += 2
                continue
            else:
                messages.append(payload)
        
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
    
    # Second pass: strip reasoning from all assistant messages before last user
    last_user_index = -1
    for idx, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user_index = idx
    
    if last_user_index >= 0:
        for idx, msg in enumerate(messages):
            if msg.get("role") == "assistant" and idx < last_user_index:
                # Historical assistant message: strip reasoning
                msg.pop("reasoning_content", None)
                msg.pop("reasoning", None)
    
    return messages
```

### 3. TapeEntry Constructor

Keep `TapeEntry.tool_call` simple (no reasoning param):
```python
@classmethod
def tool_call(cls, calls: list[dict[str, Any]], **meta: Any) -> TapeEntry:
    return cls(id=0, kind="tool_call", payload={"calls": calls}, meta=dict(meta))
```

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `republic/src/republic/tape/manager.py` | Modify | Store reasoning on assistant message always |
| `republic/src/republic/tape/context.py` | Modify | Strip reasoning from historical assistant messages |
| `republic/src/republic/tape/entries.py` | Revert | Remove reasoning param from tool_call |
| `changes/43-reasoning-content-support-v8.md` | Create | This change plan |

---

## Why It Works

1. **Store all reasoning:** Never lose reasoning on receive side
2. **Reconstruction adds reasoning:** Only active batch (after last user) gets reasoning
3. **Historical messages clean:** Old assistant messages have reasoning stripped
4. **API correctness:** All tool-call messages after last user have reasoning (I1)

(End of file)
