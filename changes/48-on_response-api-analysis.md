# Change Plan: `LLMCore.run_chat_async` — `on_response` API Reassessment

## Facts

### `LLMCore` public surface

| Member | Role |
|--------|------|
| `resolve_model_provider()` | Static. Splits `provider:model` strings. |
| `classify_exception()` | Maps any `Exception` → `ErrorKind` via three-tier classification. |
| `wrap_error()` | Wraps any exception into `RepublicError`. |
| `run_chat_async()` | **Primary public API.** Full call lifecycle: retry + fallback + response processing. |
| `.provider`, `.model`, `.fallback_models` | Read-only properties. |

**Removed (dead code):** `_call_responses_sync`, `_call_completion_like_sync`. No sync public API exists — all LLM calls are async.

### `run_chat_async` call graph

```
run_chat_async(messages, tools, ..., on_response)
  │
  └─ for provider, model, client in iter_clients(model, provider):
       │
       └─ for attempt in range(max_attempts):
            │
            ├─ _call_client_async()              ← TransportResponse
            │   ├─ _selected_transport()          ← "completion" | "responses" | "messages"
            │   ├─ _call_responses_async()        ← if responses
            │   └─ _call_completion_like_async()  ← if completion/messages
            │
            ├─ on exception → _handle_attempt_error()
            │   └─ RETRY_SAME_MODEL | TRY_NEXT_MODEL
            │
            └─ on success → on_response(response, prov, mdl, attempt)
                ├─ if RepublicError(TEMPORARY) → retry
                └─ else return to caller
```

### The `on_response` contract

```python
on_response: Callable[[Any, str, str, int], Any] | None = None
#                         ↑     ↑     ↑    ↑
#                    TransportResponse payload
#                         provider_name
#                               model_id
#                                     attempt (0-based)
```

The callback receives the raw `TransportResponse` plus execution metadata. Its contract has three facets:

1. **Return value** becomes `run_chat_async`'s return.
2. **Raise `RepublicError(TEMPORARY)`** to trigger an immediate retry of the same model.
3. **Be async** — if the return is awaitable, `run_chat_async` awaits it.

### Invariants

1. `run_chat_async` is the single entry point for LLM calls. `_call_client_async` is private.
2. Transport selection is internal — callers do not choose transport.
3. `TransportResponse(transport=..., payload=...)` is the boundary type between `LLMCore` and callers.
4. Retry decisions are centralized — only `_handle_attempt_error` decides RETRY vs NEXT. `on_response` raising `TEMPORARY` feeds the same path.
5. Fallback chain is linear: primary → fallback_models. Each model gets its own attempt counter.
6. Stream vs non-stream is a boolean flag, determined by the caller.

### Transport dispatch invariants

```
completion → client.acompletion(messages=[...], tools=[...], stream=...)
responses  → client.aresponses(input_data=[...], tools=[...], stream=..., instructions=...)
```

Both return `TransportResponse(transport, payload)`. For streaming, `.payload` is an async generator.

---

## API Use Cases Study

Each use site of `run_chat_async` is enumerated below. For each site: how the site calls it, whether `on_response` is passed, what happens to the return value, and which invariants are exercised.

### Use Site 1: `ChatClient.chat()` — non-streaming

**File:** `republic/clients/chat.py:331`

```python
def _chat_on_response(response: Any, prov: str, mdl: str, _attempt: int) -> LLMResult:
    payload, transport = _unwrap_response(response)
    text = _extract_text(payload, transport=transport)
    tool_calls = _extract_tool_calls(payload, transport=transport)
    usage = _extract_usage(payload, transport=transport)

    if not text and not tool_calls:
        if _is_completed_responses_metadata_only(payload, transport=transport):
            metadata_result = LLMResult(request=prepared, text="", usage=usage, metadata_only=True)
            if metadata_result.metadata_only:
                return metadata_result
        raise RepublicError(ErrorKind.TEMPORARY, f"{prov}:{mdl}: empty response")

    return LLMResult(request=prepared, text=text, tool_calls=tool_calls, usage=usage)

return await self._core.run_chat_async(
    ...,
    on_response=_chat_on_response,
)
```

| Aspect | Value |
|--------|-------|
| `on_response` passed? | **Yes.** Named closure `_chat_on_response`. |
| What it receives | Raw `TransportResponse(transport, payload)` plus execution metadata |
| Continuation flow | 1. `_unwrap_response(response)` extracts `(payload, transport)`<br>2. `_extract_text/tool_calls/usage` → build `LLMResult`<br>3. Empty-response check: metadata_only → return empty result; otherwise **raise** `RepublicError(TEMPORARY)`<br>4. Return `LLMResult` |
| Invariants exercised | 1 (entry point), 2 (transport internal), 3 (boundary type), 4 (retry via TEMPORARY raise), 6 (stream=False) |

### Use Site 2: `ChatClient.stream()` — streaming

**File:** `republic/clients/chat.py:364`

```python
response = await self._core.run_chat_async(
    ...,
    stream=True,
    on_response=lambda response, *_: response,
)
```

| Aspect | Value |
|--------|-------|
| `on_response` passed? | **Yes.** Identity continuation — raw passthrough. |
| What it receives | `TransportResponse(transport, payload)` where `payload` is the async generator from any-llm |
| Post-return flow (lines 386-424) | 1. Catches `RepublicError` → yields `ErrorEvent` via `AsyncStreamEvents`<br>2. Catches `Exception` → yields `ErrorEvent`<br>3. `_unwrap_response(response)` extracts `(payload, transport)`<br>4. Creates `_ParseAccumulator`<br>5. Iterates `async for chunk in payload`<br>6. Per chunk: extracts tool deltas, text, usage → updates accumulator<br>7. Yields `TextEvent(content=...)` per text chunk<br>8. On stream end: `accumulator.to_result()` → `FinalEvent(result=LLMResult)`<br>9. On iteration error: yields `ErrorEvent` |
| Invariants exercised | 1 (entry point), 2 (transport internal), 3 (boundary type), 6 (stream=True) |
| Invariant 4 (retry) | **Not exercised.** Stream iteration happens outside the retry loop; exceptions yield `ErrorEvent`, never trigger retry. |

### Use Site 3: `TapeSession.run()` — indirect via ChatClient

**File:** `republic/tape/session.py:92`

```python
result = await chat.chat(prepared, messages)  # → ChatClient.chat() → run_chat_async()
```

| Aspect | Value |
|--------|-------|
| Chain | `session.run()` → `chat.chat()` → `self._core.run_chat_async()` |
| `on_response` awareness | **None.** TapeSession never sees `LLMCore`, never passes `on_response`. |
| Post-return flow | Receives `LLMResult` from `ChatClient.chat()`. Branches on `result.has_tool_calls` and `result.error` to return `Finished` or `ToolCallNeeded`. |
| Invariant 4 impact | Parse failures arrive as `LLMResult.error` — TapeSession returns `Finished(result=LLMResult(error=...))`. The caller's loop decides whether to retry. |

### Use Site 4: `TapeSession.stream()` — indirect via ChatClient

**File:** `republic/tape/session.py:114`

```python
v2_stream = await chat.stream(prepared, messages)  # → ChatClient.stream() → run_chat_async()
```

| Aspect | Value |
|--------|-------|
| Chain | `session.stream()` → `chat.stream()` → `self._core.run_chat_async()` |
| `on_response` awareness | **None.** |
| Post-return flow | Wraps `AsyncStreamEvents[LLMResult]` into `AsyncIterator` that yields `TextEvent`/`FinalEvent[TurnResult]`/`ErrorEvent`. |

### Use Site 5: `FakeLLMCore.run_chat_async` — test mock

**File:** `republic/tests/test_chat_client_v2.py:30`

```python
async def run_chat_async(self, **kwargs):
    self.calls.append(kwargs)
    response = self.responses.pop(0)
    if isinstance(response, Exception):
        raise response
    return response
```

| Aspect | Value |
|--------|-------|
| `on_response` handling | `**kwargs` swallows it if ever passed (it isn't). |
| Coverage gap | **No test validates `on_response` behavior.** No test passes `on_response`, verifies parse-then-retry, or confirms the callback return becomes `run_chat_async`'s return. |

### Use Site 6: `bub/src/bub/builtin/agent.py` — indirect via deprecated LLM facade

**File:** `bub/src/bub/builtin/agent.py:552,563`

| Aspect | Value |
|--------|-------|
| Chain | `tape.run_tools_async()` / `tape.stream_events_async()` → (deprecated LLM.Tape) → ChatClient methods → `run_chat_async()` |
| `on_response` awareness | **None.** No bub code references `LLMCore`, `run_chat_async`, or `on_response`. |

### Use Site 7: `e2e.py` — end-to-end test

**File:** `e2e.py:115`

| Aspect | Value |
|--------|-------|
| Chain | `session.run(chat, prepared)` → `ChatClient.chat()` → `run_chat_async()` |
| `on_response` awareness | **None.** Writes the tool execution loop directly using TapeSession + ChatClient + ToolExecutor. |

---

## Design

### CPS calling style

`run_chat_async` uses continuation-passing style: every caller must pass an `on_response` callback. There is no optional-None path. The callback is the canonical way to receive the `TransportResponse` after the retry waterfall completes.

```python
on_response: Callable[[Any, str, str, int], Any],
```

When raw-passthrough is desired, the caller passes the identity continuation:

```python
on_response=lambda response, *_: response,
```

### ChatClient adaptation

`ChatClient.chat()` passes a **named continuation** that owns the full non-streaming parse. `ChatClient.stream()` passes the **identity continuation** because the async generator must be consumed outside the retry loop.

| Path | on_response | Post-return |
|------|------------|-------------|
| `chat()` | `_chat_on_response` closure | Extracts text/tool_calls/usage inside the closure; raises `TEMPORARY` on empty response to trigger retry |
| `stream()` | `lambda response, *_: response` | `_unwrap_response()` → `_ParseAccumulator` async iteration → `FinalEvent[LLMResult]` |

---

## Impact Analysis (per use site)

### Site 1: `ChatClient.chat()` — named continuation

`_chat_on_response` closure at `chat.py:316`. Owns the full non-streaming parse inside the continuation. Empty non-metadata responses raise `RepublicError(TEMPORARY)`, which triggers the retry loop in `run_chat_async`. This is the primary user of the CPS contract. The caller (`chat()`) receives `LLMResult` directly — no post-return parsing.

### Site 2: `ChatClient.stream()` — identity continuation

`on_response=lambda response, *_: response` at `chat.py:374`. Raw passthrough because the async generator must be consumed outside the retry loop. Post-return parsing with `_ParseAccumulator` unchanged.

### Site 3: `TapeSession.run()` — indirect, no awareness of on_response

TapeSession receives `LLMResult` via `ChatClient.chat()`. The identity continuation is internal to `ChatClient`. TapeSession never sees or passes `on_response`.

### Site 4: `TapeSession.stream()` — same as site 3

No change. Stream errors arrive as `ErrorEvent`, not retry signals.

### Site 5: `FakeLLMCore.run_chat_async` (test mock)

```python
async def run_chat_async(self, **kwargs):
    ...
```

With `on_response` now required and always called by the real implementation, the mock's `**kwargs` pattern silently discards it. This is a **pre-existing gap** — the mock doesn't exercise the CPS contract. If the real ChatClient ever defines a non-identity `on_response`, the mock would not validate it.

**Action:** No change needed now (identity continuation is trivial). If a future caller passes a non-identity `on_response`, the mock must be updated to match.

### Site 6: bub agent — no impact

Never sees `LLMCore` directly. Identity continuation is internal to `ChatClient`.

### Site 7: e2e.py — no impact

Uses `TapeSession.run()` → `ChatClient.chat()`. Identity continuation is invisible.

---

## Open Questions

1. **Should `on_response` be removed entirely in a future release?** Unlikely — `ChatClient.chat()` now uses it as the primary parse+retry mechanism. Even if no external callers materialize, it serves an internal architectural purpose.
2. ~~Should `ChatClient` use `on_response` to re-enter the retry loop on empty responses?~~ **Done.** `_chat_on_response` raises `RepublicError(TEMPORARY)` on empty non-metadata responses, triggering the retry waterfall. Parse-level retry now lives in the continuation.
3. **Should tests be added for the `on_response` passthrough path?** Yes (see Site 5 in Impact Analysis).
