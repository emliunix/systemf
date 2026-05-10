# Change Plan: Ground-Up Redesign of `chat.py`

## Status: Draft

## Problem Statement

`chat.py` must be redesigned as a **consumer** of `LLMCore`'s retry contract. The retry logic is owned entirely by `LLMCore` — `chat.py` does not implement retry, it **participates** in it via the `on_response` CPS callback. This plan documents the retry contract, what guarantees `LLMCore` provides, and what guarantees `ChatClient` must uphold.

---

## 1. The Retry Contract (Owned by LLMCore)

### 1.1 Retry Waterfall

`LLMCore.run_chat_async` implements the following contract:

```
for each (provider, model, client) in fallback chain:
  for attempt in 0..max_attempts-1:
    try:
      response = await _call_client_async(...)
    except Exception as transport_error:
      error = classify_exception(transport_error)
      if should_retry(error) and attempt < max_attempts - 1:
        continue  # RETRY_SAME_MODEL
      else:
        break     # TRY_NEXT_MODEL
    else:
      try:
        result = on_response(response, provider, model, attempt)
      except RepublicError(TEMPORARY):
        if attempt < max_attempts - 1:
          continue  # RETRY_SAME_MODEL (parse-time retry)
        else:
          break     # TRY_NEXT_MODEL
      except RepublicError(other_kind):
        raise       # Abort entire call
      except Exception:
        raise       # Abort entire call
      return result  # Success
```

### 1.2 What LLMCore Guarantees to ChatClient

| Guarantee | Description |
|-----------|-------------|
| **G1** | `on_response` is called with a valid `TransportResponse` (or whatever `_call_client_async` returned) |
| **G2** | `on_response` receives execution metadata: `(provider_name, model_id, attempt_index)` |
| **G3** | If `on_response` raises `RepublicError(TEMPORARY)`, LLMCore retries the **same** model (if attempts remain) |
| **G4** | If `on_response` raises `RepublicError(other)`, the error propagates to the caller |
| **G5** | Transport-level exceptions (network, timeout, rate limit) are classified and retried **before** `on_response` is called |
| **G6** | Fallback chain proceeds linearly: primary → fallback_1 → fallback_2 → ... |
| **G7** | If all models exhausted, the last error is raised |

### 1.3 What ChatClient Must Guarantee to LLMCore

| Guarantee | Description |
|-----------|-------------|
| **C1** | `on_response` must be synchronous (or return an awaitable, which LLMCore will await) |
| **C2** | `on_response` must not hold references that prevent garbage collection across retries |
| **C3** | `on_response` must raise `RepublicError(TEMPORARY)` **only** for transient parse failures (empty response) that might succeed on retry |
| **C4** | `on_response` must raise `RepublicError(INVALID_INPUT)` for unrecoverable parse errors (wrong format) |
| **C5** | For streaming: `on_response` must return the raw response quickly (don't consume the async generator) |
| **C6** | The return value of `on_response` becomes the return value of `run_chat_async` |

---

## 2. Functional Requirements

### 2.1 ChatClient Responsibilities

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Execute non-streaming LLM calls via LLMCore, providing an `on_response` callback | P0 |
| FR-2 | Execute streaming LLM calls via LLMCore, providing an `on_response` callback | P0 |
| FR-3 | Parse transport responses into `LLMResult` | P0 |
| FR-4 | For non-streaming: raise `TEMPORARY` from `on_response` when response is empty (enables retry) | P0 |
| FR-5 | For streaming: validate response is a stream in `on_response`, return raw response | P0 |
| FR-6 | For streaming: consume async generator outside retry loop, yield `StreamEvent` | P0 |
| FR-7 | Accumulate tool call deltas from streaming chunks | P0 |
| FR-8 | Detect metadata-only responses (reasoning-only, no text/tool_calls) | P0 |
| FR-9 | Never execute tools | P0 |
| FR-10 | Never write to tape | P0 |

### 2.2 Event Contracts

**Non-streaming:**
```
chat() -> LLMResult
  ├─ success: LLMResult(text=..., tool_calls=..., usage=...)
  ├─ empty response: on_response raises TEMPORARY -> LLMCore retries (guarantee G3)
  ├─ metadata-only: LLMResult(metadata_only=True, text="")
  └─ unrecoverable: LLMResult(error=RepublicError) or exception propagates
```

**Streaming:**
```
stream() -> AsyncStreamEvents[LLMResult]
  ├─ success: yields TextEvent... FinalEvent(result=LLMResult)
  ├─ non-stream response: on_response raises INVALID_INPUT -> LLMCore tries next model (guarantee G4)
  ├─ stream parse error: yields ErrorEvent(error=...) (no retry possible)
  └─ empty stream: yields FinalEvent(result=LLMResult(error=...)) (no retry possible)
```

---

## 3. Architecture

### 3.1 Design Principle: ChatClient Is a Retry Contract Consumer

`ChatClient` does not implement retry. It provides `on_response` callbacks that LLMCore calls **inside** the retry loop. The callbacks are the only mechanism `ChatClient` has to influence retry behavior.

### 3.2 Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  ChatClient.chat(prepared, messages)                             │
│  ── binds ──> partial(_chat_on_response, prepared)             │
│  ── calls ──> LLMCore.run_chat_async(..., on_response=handler)  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  _chat_on_response(response, prov, mdl, att)               │  │
│  │  ├─ Unwrap TransportResponse                               │  │
│  │  ├─ Extract text, tool_calls, usage                        │  │
│  │  ├─ Check empty response:                                  │  │
│  │  │   ├─ metadata-only? return LLMResult(metadata_only=True)│  │
│  │  │   └─ otherwise raise TEMPORARY (triggers retry, G3)     │  │
│  │  └─ Return LLMResult                                       │  │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  ChatClient.stream(prepared, messages)                           │
│  ── binds ──> partial(_stream_on_response, prepared)            │
│  ── calls ──> LLMCore.run_chat_async(..., on_response=handler)  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  _stream_on_response(response, prov, mdl, att)             │  │
│  │  ├─ Unwrap TransportResponse                               │  │
│  │  ├─ Validate it's a stream (C5)                            │  │
│  │  │   └─ not a stream? raise INVALID_INPUT (try next model) │  │
│  │  └─ Return raw response (identity, C5)                     │  │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  stream() returns AsyncStreamEvents IMMEDIATELY           │  │
│  │  (no post-method call — preserves real-time nature)       │  │
│  │                                                             │  │
│  │  The returned AsyncStreamEvents wraps an async generator   │  │
│  │  that was constructed inline, capturing response + core    │  │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 3.3 Component Contracts

#### Component A: PreparedChat (Existing Type)

**Status:** Already defined in `republic/core/results.py:14-38`. **Not redesigned.**

```python
@dataclass
class PreparedChat:
    """Execution configuration for one LLM API call."""
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    max_tokens: int | None = None
    reasoning_effort: Any | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)
```

**ChatClient uses `PreparedChat` directly.** No duck-typing, no `hasattr()` checks.

#### Component B: _CallParams

**Role:** Extract and normalize `PreparedChat` fields into kwargs for `run_chat_async`. Eliminates duplication.

**Contract:**
```python
@dataclass(frozen=True)
class _CallParams:
    tools: list[dict[str, Any]]
    model: str | None
    provider: str | None
    max_tokens: int | None
    reasoning_effort: Any | None
    kwargs: dict[str, Any]
    
    @classmethod
    def from_prepared(cls, prepared: PreparedChat) -> "_CallParams"
    
    def to_core_kwargs(self) -> dict[str, Any]
    # Returns dict with keys: tools_payload, model, provider, max_tokens, reasoning_effort, kwargs
```

#### Component C: _chat_on_response

**Role:** CPS callback for non-streaming. **Top-level function + functools.partial.** Executes INSIDE LLMCore's retry loop.

**Contract with LLMCore:**
- Called inside retry loop (guarantee G1)
- Receives `(response, provider, model, attempt)` (guarantee G2)
- May raise `RepublicError(TEMPORARY)` to trigger same-model retry (guarantee G3)
- Return value becomes `run_chat_async` return (guarantee C6)

```python
from functools import partial

def _chat_on_response(
    prepared: PreparedChat,
    response: Any,
    provider: str,
    model: str,
    attempt: int,
) -> LLMResult:
    """CPS callback for non-streaming calls.
    
    Passed to LLMCore.run_chat_async as on_response. Executes inside the
    retry loop, so parse errors can trigger retry by raising TEMPORARY.
    
    Use: on_response = partial(_chat_on_response, prepared)
    """
    payload, transport = _unwrap_response(response)
    text = _extract_text(payload, transport=transport)
    tool_calls = _extract_tool_calls(payload, transport=transport)
    usage = _extract_usage(payload, transport=transport)
    
    if not text and not tool_calls:
        if _is_completed_responses_metadata_only(payload, transport=transport):
            return LLMResult(
                request=prepared,
                text="",
                usage=usage,
                metadata_only=True,
            )
        # Parse-time retry: empty response triggers TEMPORARY
        raise RepublicError(
            ErrorKind.TEMPORARY,
            f"{provider}:{model}: empty response (attempt {attempt})",
        )
    
    return LLMResult(
        request=prepared,
        text=text,
        tool_calls=tool_calls,
        usage=usage,
    )
```

**Retry Semantics:**
- `TEMPORARY` from `_on_response` → LLMCore retries same model (guarantee G3)
- This is the **only** mechanism for parse-time retry
- If all attempts exhausted, LLMCore falls back to next model (guarantee G6)

#### Component D: _stream_on_response

**Role:** CPS callback for streaming. **Top-level function.** Only validates, returns identity.

**Contract with LLMCore:**
- Must be fast (don't consume generator) (guarantee C5)
- Validate response is actually a stream
- If not a stream → raise `RepublicError(INVALID_INPUT)` → LLMCore tries next model (guarantee G4)
- Return raw response (identity callback)

```python
def _stream_on_response(
    prepared: PreparedChat,
    response: Any,
    provider: str,
    model: str,
    attempt: int,
) -> Any:
    """CPS callback for streaming calls.
    
    Passed to LLMCore.run_chat_async as on_response. Validates the response
    is a stream and returns it raw. The async generator must NOT be consumed
    here — it escapes the retry loop and is consumed by the caller.
    
    `prepared` is captured via partial even though not used in validation,
    for API symmetry with _chat_on_response and to keep PreparedChat in scope
    for the stream iterator that constructs LLMResult -> ToolCallNeeded.
    
    Use: on_response = partial(_stream_on_response, prepared)
    """
    payload, transport = _unwrap_response(response)
    if _is_non_stream_response(payload, transport=transport):
        raise RepublicError(
            ErrorKind.INVALID_INPUT,
            f"{provider}:{model}: response is not a stream.",
        )
    return response
```

#### Component E: _ParseAccumulator

**Role:** Mutable accumulator for streaming parse state.

**Contract:**
- Append-only state across chunks
- `to_result()` produces final `LLMResult` on stream end
- No retry contract involvement (operates outside retry loop)

```python
@dataclass
class _ParseAccumulator:
    text_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    assembler: ToolCallAssembler = field(default_factory=ToolCallAssembler)
    usage: dict[str, Any] | None = None
    output_item_types: set[str] = field(default_factory=set)
    
    def to_result(self, request: PreparedChat, error: RepublicError | None = None) -> LLMResult
```

**State machine:**
```
Initial: all fields empty/default
Per chunk:
  text chunk -> text_parts.append(text)
  reasoning chunk -> reasoning_parts.append(reasoning)
  tool delta -> assembler.add_deltas(deltas)
  usage -> usage = new_usage (overwrite)
  output_item_type -> output_item_types.add(type)
On finalize:
  metadata_only = output_item_types.issubset({"reasoning", "compaction"})
  return LLMResult(..., metadata_only=metadata_only)
```

#### Component F: ToolCallAssembler

**Status:** **Keep untouched.** Existing code is correct.

**Contract:**
- `add_deltas(tool_calls)` merges partial updates
- `finalize()` returns complete OpenAI-format tool_calls
- No retry contract involvement

---

## 4. Call Convention

### 4.1 Non-Streaming: Full Retry Participation

```python
# ChatClient.chat()
async def chat(self, prepared: PreparedChat, messages: list[dict[str, Any]]) -> LLMResult:
    params = _CallParams.from_prepared(prepared)
    
    try:
        # LLMCore owns retry. We provide on_response callback via partial.
        return await self._core.run_chat_async(
            messages_payload=messages,
            stream=False,
            **params.to_core_kwargs(),
            on_response=partial(_chat_on_response, prepared),
        )
    except RepublicError:
        # This catches errors that propagated through LLMCore's retry loop
        # (all models exhausted, or non-TEMPORARY error from on_response)
        return LLMResult(request=prepared, error=exc)
    except Exception:
        # Unexpected error from LLMCore itself
        error = self._core.wrap_error(exc, params.provider or "", params.model or "")
        return LLMResult(request=prepared, error=error)
```

**What happens with empty response:**
1. LLMCore calls `_call_client_async` → gets `TransportResponse`
2. LLMCore calls `on_response(response, prov, mdl, attempt)`
3. Callback parses → finds empty response → raises `RepublicError(TEMPORARY)`
4. LLMCore catches TEMPORARY → checks `attempt < max_attempts` → retries same model (guarantee G3)
5. If retry succeeds → returns `LLMResult`
6. If all attempts fail → breaks to next model (guarantee G6)
7. If all models fail → raises last error to ChatClient → caught, wrapped in `LLMResult.error`

### 4.2 Streaming: Immediate Return, No Post-Call Build

```python
# ChatClient.stream()
async def stream(
    self,
    prepared: PreparedChat,
    messages: list[dict[str, Any]],
) -> AsyncStreamEvents[LLMResult]:
    params = _CallParams.from_prepared(prepared)
    
    try:
        # Phase 1: Get through retry loop with validation callback
        raw_response = await self._core.run_chat_async(
            messages_payload=messages,
            stream=True,
            **params.to_core_kwargs(),
            on_response=partial(_stream_on_response, prepared),  # Validates, returns identity
        )
    except RepublicError as exc:
        async def _error_iter():
            yield ErrorEvent(exc)
        return AsyncStreamEvents(_error_iter())
    except Exception as exc:
        error = self._core.wrap_error(exc, params.provider or "", params.model or "")
        async def _error_iter():
            yield ErrorEvent(error)
        return AsyncStreamEvents(_error_iter())
    
    # Phase 2: Return stream IMMEDIATELY — no post-method call
    # The async generator is constructed inline and captured in the closure
    payload, transport = _unwrap_response(raw_response)
    accumulator = _ParseAccumulator()
    
    async def _stream_iterator():
        try:
            async for chunk in payload:
                # ... parse chunk ...
                text = _extract_chunk_text(chunk, transport=transport)
                if text:
                    accumulator.text_parts.append(text)
                    yield TextEvent(content=text)
            
            result = accumulator.to_result(prepared, error=None)
            if not result.text and not result.tool_calls and not result.metadata_only:
                result = LLMResult(
                    request=prepared,
                    error=RepublicError(
                        ErrorKind.TEMPORARY,
                        f"{params.provider or 'unknown'}:{params.model or 'unknown'}: empty response",
                    ),
                )
            yield FinalEvent(result=result)
        except Exception as exc:
            error = self._core.wrap_error(exc, params.provider or "", params.model or "")
            yield ErrorEvent(error)
    
    # Return immediately — preserves real-time streaming nature
    return AsyncStreamEvents(_stream_iterator())
```

**What happens with non-stream response:**
1. LLMCore calls `_call_client_async` → gets `TransportResponse` (but payload is not a generator)
2. LLMCore calls `on_response(response, prov, mdl, attempt)`
3. Callback checks `_is_non_stream_response(payload)` → True
4. Callback raises `RepublicError(INVALID_INPUT)`
5. LLMCore catches non-TEMPORARY → re-raises (guarantee G4)
6. LLMCore's outer loop catches it → decision: TRY_NEXT_MODEL (guarantee G6)
7. Falls back to next model in chain

**What happens with stream parse error:**
1. `stream()` returns `AsyncStreamEvents(_stream_iterator())` immediately
2. Caller iterates → `_stream_iterator()` starts consuming payload
3. Chunk parse fails → exception caught
4. Yields `ErrorEvent(error=...)` (no retry possible — stream in progress)

**Why no post-method call:**
- `stream()` must return immediately to preserve real-time nature
- The async generator is constructed inline and returned directly
- No `handler.build_stream()` or similar method call that would delay iteration

---

## 5. Retry Contract Matrix

| Scenario | Where Detected | Error Kind | LLMCore Action | ChatClient Action |
|----------|---------------|------------|----------------|-------------------|
| Network timeout | `_call_client_async` | TEMPORARY/PROVIDER | Retry same model | None (before on_response) |
| Rate limit | `_call_client_async` | TEMPORARY | Retry same model | None (before on_response) |
| Empty response (non-stream) | `on_response` | TEMPORARY (raised) | Retry same model | `_chat_on_response` raises |
| Invalid format (non-stream) | `on_response` | INVALID_INPUT | Abort, try next model | `_chat_on_response` raises |
| Non-stream response | `on_response` | INVALID_INPUT | Abort, try next model | `_stream_on_response` raises |
| Empty stream | `_stream_iterator` | N/A (no retry) | N/A | FinalEvent with error |
| Chunk parse error | `_stream_iterator` | N/A (no retry) | N/A | ErrorEvent |

**Key insight:** Only non-streaming parse errors can trigger retry. This is because `on_response` for non-streaming can safely raise `TEMPORARY` and LLMCore will retry. For streaming, `on_response` returns the raw generator, so parse errors happen outside the retry loop.

---

## 6. Code Style

### 6.1 CPS Callbacks Use functools.partial

```python
from functools import partial

# CORRECT: Top-level function + partial to capture prepared
def _chat_on_response(
    prepared: PreparedChat,
    response: Any,
    provider: str,
    model: str,
    attempt: int,
) -> LLMResult:
    ...

on_response = partial(_chat_on_response, prepared)

# WRONG: Class with method
class _NonStreamingHandler:  # Don't do this
    def on_response(self, ...): ...

# WRONG: Nested closure factory (unnecessary)
def _chat_on_response(prepared):  # Don't do this
    def _on_response(response, provider, model, attempt):
        ...
    return _on_response
```

### 6.2 Immediate Stream Return

```python
# CORRECT: Return AsyncStreamEvents immediately
async def stream(...):
    raw_response = await self._core.run_chat_async(...)
    
    async def _iterator():
        ...
    
    return AsyncStreamEvents(_iterator())  # Immediate, no post-call

# WRONG: Post-method call that delays iteration
async def stream(...):
    raw_response = await self._core.run_chat_async(...)
    handler = _StreamingHandler(...)
    return handler.build_stream(raw_response)  # Delays, breaks real-time
```

### 6.3 Error Wrapping Pattern

```python
try:
    return await self._core.run_chat_async(...)
except RepublicError as exc:
    return LLMResult(request=prepared, error=exc)
except Exception as exc:
    error = self._core.wrap_error(exc, provider or "", model or "")
    return LLMResult(request=prepared, error=error)
```

---

## 7. Files

### Modify

| File | Action |
|------|--------|
| `republic/clients/chat.py` | Complete rewrite per this design |

### No Changes

| File | Reason |
|------|--------|
| `republic/core/execution.py` | LLMCore retry contract is a GIVEN, not redesigned |
| `republic/core/results.py` | PreparedChat and other types unchanged |
| `republic/clients/parsing/` | Parsing helpers unchanged |

---

## 8. Validation Checklist

- [ ] `_chat_on_response` raises TEMPORARY on empty response (triggers LLMCore retry)
- [ ] `_chat_on_response` returns metadata-only result without raising
- [ ] `_stream_on_response` returns raw response without consuming generator
- [ ] `_stream_on_response` raises INVALID_INPUT on non-stream response (LLMCore tries next model)
- [ ] `stream()` returns AsyncStreamEvents immediately (no post-call delay)
- [ ] Empty stream yields FinalEvent with error (no retry — stream already in progress)
- [ ] All transport errors are handled by LLMCore before on_response is called
- [ ] ToolCallAssembler kept untouched
- [ ] PreparedChat used directly (no hasattr checks)
- [ ] All existing tests pass
- [ ] New test: empty non-streaming response triggers retry
- [ ] New test: non-stream response falls back to next model
