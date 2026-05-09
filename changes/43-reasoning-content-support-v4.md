# Change Plan: Reasoning Content Support (v4)

**Reviewed by:** Code review of v3 implementation against plan `changes/43-reasoning-content-support-v3.md`
**Changes from v3:** Completes event-stream reasoning paths; fixes `_final_event_data`; updates event-stream finalization

---

## Facts

### What v3 Implemented

The v3 plan was partially implemented:

- **Parsers** (`types.py`, `completion.py`, `responses.py`): `extract_reasoning()` and `extract_chunk_reasoning()` implemented correctly.
- **Tape manager** (`manager.py`): Both sync/async `record_chat` accept `reasoning` and store it in the assistant message payload.
- **Tape context** (`context.py`): `_default_messages` reconstructs `tool_calls` and conditionally preserves/strips reasoning per I1/R1.
- **Message preparation** (`chat.py:331-394`): `_prepare_messages` strips `reasoning_content`/`reasoning` from user-provided messages.
- **Text streams** (`chat.py:1621-1671`): Reasoning deltas are buffered and passed to `_finalize_text_stream`.
- **Non-streaming response paths** (`_handle_create_response`, `_handle_tool_calls_response`, `_handle_tools_auto_response` and async variants): Reasoning is extracted via `_extract_reasoning()` and passed through to `_update_tape`.

### What's Missing

| Gap | Location | Plan Section |
|---|---|---|
| Event streams do not buffer or yield reasoning deltas | `_build_event_stream`, `_build_async_event_stream` | §4 |
| Event streams from response do not extract reasoning | `_build_event_stream_from_response`, `_build_async_event_stream_from_response` | §4 |
| Event-stream finalization lacks `reasoning` parameter | `_finalize_event_stream`, `_finalize_event_stream_async`, `_finalize_event_stream_state`, `_finalize_event_stream_state_async` | §7 |
| `_final_event_data` omits reasoning | `chat.py:718-732` | §7 |
| Event-stream `_update_tape` call lacks reasoning | `_finalize_event_stream_state`, `_finalize_event_stream_state_async` | §7 |

### Call Site Inventory (Event-Stream Paths)

```
republic/src/republic/clients/chat.py:1768     _build_event_stream
republic/src/republic/clients/chat.py:1851     _build_async_event_stream
republic/src/republic/clients/chat.py:1936     _build_event_stream_from_response
republic/src/republic/clients/chat.py:1999     _build_async_event_stream_from_response
republic/src/republic/clients/chat.py:816      _finalize_event_stream
republic/src/republic/clients/chat.py:871      _finalize_event_stream_async
republic/src/republic/clients/chat.py:927      _finalize_event_stream_state
republic/src/republic/clients/chat.py:954      _finalize_event_stream_state_async
republic/src/republic/clients/chat.py:718      _final_event_data
```

---

## Design

### 1. Buffer Reasoning in Event Streams

**Files:** `republic/src/republic/clients/chat.py`

**Sync event stream** (`_build_event_stream`):
- Add `reasoning_parts: list[str] = []` alongside `parts`
- Extract reasoning deltas: `reasoning_delta = self._extract_chunk_reasoning(chunk, transport=transport)`
- Yield `StreamEvent("reasoning", {"delta": reasoning_delta})` when non-empty
- In the `finally` block, compute `reasoning = "".join(reasoning_parts) if reasoning_parts else None`
- Pass `reasoning` to `_finalize_event_stream_state`

**Async event stream** (`_build_async_event_stream`):
- Same changes as sync variant.

### 2. Extract Reasoning in Event Stream from Response

**Files:** `republic/src/republic/clients/chat.py`

**Sync** (`_build_event_stream_from_response`):
- Add: `reasoning = self._extract_reasoning(response, transport=transport)`
- Include `reasoning` in `_final_event_data` call
- Pass `reasoning` to `_update_tape`

**Async** (`_build_async_event_stream_from_response`):
- Same changes as sync variant.

### 3. Update Event Stream Finalization

**Files:** `republic/src/republic/clients/chat.py`

**`_finalize_event_stream`** (line 816):
- Add `reasoning: str | dict | None = None` parameter
- Include `reasoning` in the `_final_event_data` call
- Return `reasoning` as an additional tuple element (or pass to `_finalize_event_stream_state`)

**`_finalize_event_stream_async`** (line 871):
- Same changes as sync variant.

**`_finalize_event_stream_state`** (line 927):
- Add `reasoning: str | dict | None = None` parameter
- Pass `reasoning` to `_update_tape`

**`_finalize_event_stream_state_async`** (line 954):
- Same changes as sync variant.

### 4. Update `_final_event_data`

**File:** `republic/src/republic/clients/chat.py`

```python
def _final_event_data(
    *,
    text: str | None,
    tool_calls: list[dict[str, Any]],
    tool_results: list[Any],
    usage: dict[str, Any] | None,
    error: RepublicError | None,
    reasoning: str | dict | None = None,
) -> dict[str, Any]:
    data = {
        "text": text,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "usage": usage,
        "ok": error is None,
    }
    if reasoning is not None:
        data["reasoning"] = reasoning
    return data
```

### 5. Update Event Stream Callers

**File:** `republic/src/republic/clients/chat.py`

Update the call sites in `_build_event_stream` and `_build_async_event_stream`:
- Pass `reasoning` to `_finalize_event_stream` / `_finalize_event_stream_async`
- Pass `reasoning` to `_finalize_event_stream_state` / `_finalize_event_stream_state_async`

---

## Why It Works

1. **Event streams get reasoning**: Users consuming the event stream API will now receive `StreamEvent("reasoning", ...)` deltas in real time, matching the behavior described in the v3 plan.
2. **Final events are complete**: `_final_event_data` now includes reasoning, so downstream consumers (UI, logging) can access it without making a separate tape query.
3. **Tape is consistent**: All streaming and non-streaming paths now pass reasoning through to `_update_tape`, so the tape always contains reasoning when available.
4. **Backward compatible**: Default `reasoning=None` in all updated signatures. Existing callers and tests continue to work.

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `republic/src/republic/clients/chat.py` | Modify | Buffer/yield reasoning in event streams; extract reasoning in response-to-event paths; add reasoning param to all event-stream finalization methods; update `_final_event_data` |
| `changes/43-reasoning-content-support-v4.md` | Create | This change plan |

---

## Testing Plan

1. **Unit test:** `_build_event_stream` yields `StreamEvent("reasoning")` when reasoning deltas are present
2. **Unit test:** `_build_event_stream_from_response` includes reasoning in `StreamEvent("final")` data
3. **Unit test:** `_final_event_data` includes `reasoning` key when provided
4. **Integration test:** Async variants mirror sync behavior
5. **Regression test:** Event streams without reasoning continue to work (reasoning=None default)

---

## Out of Scope

- OpenAI Responses API stateless mode (ZDR / `store=false`) with encrypted reasoning items
- Reasoning summary extraction (`reasoning.summary` field)
- Displaying reasoning in CLI output (UI layer)
- Support for other reasoning providers (Gemini thinking, Claude extended thinking)
- Anthropic endpoint (`thinking` blocks vs `reasoning_content`)

---

## References

- `changes/43-reasoning-content-support-v3.md` — Previous change plan
- `analysis/REASONING_VALIDATION_MODEL.md` — Consolidated empirical findings
- `analysis/test_state_machine_validation.py` — Formal state machine tests

(End of file)
