# Exploration: LLMCore CPS Contract, Retry Semantics, and Exception Classification

## Notes

### Note 1: Context and Motivation

Change Plan 44 (ChatClient Architectural Refactor) proposes a layered architecture separating ChatClient, TapeSession, and AgentRunner. The refactor document shows `ChatClient.chat(prepared, messages) -> LLMResult` as a direct method with no mention of `on_response`. However, the current `LLMCore.run_chat_async` uses CPS (Continuation Passing Style) where the caller must provide an `on_response` callback that executes **inside** the retry loop. This exploration investigates why the CPS contract exists, what would be lost by breaking it, and how exception classification drives retry decisions.

### Note 2: Investigation Scope

**IN scope:**
- `LLMCore.run_chat_async` retry waterfall
- Exception classification pipeline (3-tier + custom)
- `on_response` callback contract and semantics
- How `ChatClient` currently uses `on_response`
- What happens if response handling moves outside the retry loop

**OUT of scope:**
- Transport-specific parsing details
- Tool execution logic
- Tape entry serialization

### Note 3: Key Questions

1. What are the exact retry semantics? (Same-model vs next-model, max attempts)
2. How does exception classification decide RETRY_SAME_MODEL vs TRY_NEXT_MODEL?
3. What does `on_response` receive, and what can it do?
4. Why must parsing happen inside `on_response` rather than after `run_chat_async` returns?
5. What would break if Change 44's API (direct return) replaces the CPS contract?

---

## Facts

### Fact 1: Retry Waterfall Structure

`republic/src/republic/core/execution.py:645-701`

```python
async def run_chat_async(  # noqa: C901
    self,
    *,
    messages_payload: list[dict[str, Any]],
    tools_payload: list[dict[str, Any]] | None,
    model: str | None,
    provider: str | None,
    max_tokens: int | None,
    stream: bool,
    reasoning_effort: Any | None,
    kwargs: dict[str, Any],
    on_response: Callable[[Any, str, str, int], Any],
) -> Any:
    last_provider: str | None = None
    last_model: str | None = None
    last_error: RepublicError | None = None
    for provider_name, model_id, client in self.iter_clients(model, provider):
        last_provider, last_model = provider_name, model_id
        for attempt in range(self.max_attempts()):
            try:
                response = await self._call_client_async(...)
            except Exception as exc:
                outcome = self._handle_attempt_error(exc, provider_name, model_id, attempt)
                last_error = outcome.error
                if outcome.decision is AttemptDecision.RETRY_SAME_MODEL:
                    continue
                break
            else:
                try:
                    result = on_response(response, provider_name, model_id, attempt)
                    if inspect.isawaitable(result):
                        result = await result
                except RepublicError as exc:
                    self.log_error(exc, provider_name, model_id, attempt)
                    if exc.kind == ErrorKind.TEMPORARY:
                        continue
                    raise
                return result

    if last_error is not None:
        raise last_error
    if last_provider and last_model:
        raise RepublicError(
            ErrorKind.TEMPORARY,
            f"{last_provider}:{last_model}: LLM call failed after retries",
        )
    raise RepublicError(ErrorKind.TEMPORARY, "LLM call failed after retries")
```

### Fact 2: Exception Classification Pipeline

`republic/src/republic/core/execution.py:345-374`

```python
def classify_exception(self, exc: Exception) -> ErrorKind:
    if isinstance(exc, RepublicError):
        return exc.kind
    if self._error_classifier is not None:
        try:
            kind = self._error_classifier(exc)
        except Exception as classifier_exc:
            logger.warning("error_classifier failed: %r", classifier_exc)
        else:
            if isinstance(kind, ErrorKind):
                return kind
    try:
        from pydantic import ValidationError as PydanticValidationError
        validation_error_type: type[Exception] | None = PydanticValidationError
    except ImportError:
        validation_error_type = None
    if validation_error_type is not None and isinstance(exc, validation_error_type):
        return ErrorKind.INVALID_INPUT

    for classifier in (
        self._classify_anyllm_exception,
        self._classify_by_http_status,
        self._classify_by_text_signature,
    ):
        mapped = classifier(exc)
        if mapped is not None:
            return mapped

    return ErrorKind.UNKNOWN
```

### Fact 3: Retry Decision Logic

`republic/src/republic/core/execution.py:376-394`

```python
def should_retry(self, kind: ErrorKind) -> bool:
    return kind in {ErrorKind.TEMPORARY, ErrorKind.PROVIDER}

def _handle_attempt_error(self, exc: Exception, provider_name: str, model_id: str, attempt: int) -> AttemptOutcome:
    wrapped = exc if isinstance(exc, RepublicError) else self.wrap_error(exc, provider_name, model_id)
    kind = wrapped.kind
    self.log_error(wrapped, provider_name, model_id, attempt)
    can_retry_same_model = self.should_retry(kind) and attempt + 1 < self.max_attempts()
    if can_retry_same_model:
        return AttemptOutcome(error=wrapped, decision=AttemptDecision.RETRY_SAME_MODEL)
    return AttemptOutcome(error=wrapped, decision=AttemptDecision.TRY_NEXT_MODEL)
```

### Fact 4: Three-Tier Classifier Details

Tier 1 — any-llm exception types (`execution.py:268-287`):
```python
def _classify_anyllm_exception(self, exc: Exception) -> ErrorKind | None:
    error_map = [
        ((MissingApiKeyError, AuthenticationError), ErrorKind.CONFIG),
        ((UnsupportedProviderError, UnsupportedParameterError, InvalidRequestError, ModelNotFoundError, ContextLengthExceededError), ErrorKind.INVALID_INPUT),
        ((RateLimitError, ContentFilterError), ErrorKind.TEMPORARY),
        ((ProviderError, AnyLLMError), ErrorKind.PROVIDER),
    ]
    for types, kind in error_map:
        if isinstance(exc, types):
            return kind
    return None
```

Tier 2 — HTTP status codes (`execution.py:289-300`):
```python
def _classify_by_http_status(self, exc: Exception) -> ErrorKind | None:
    status = self._extract_status_code(exc)
    if status in {401, 403}:
        return ErrorKind.CONFIG
    if status in {400, 404, 413, 422}:
        return ErrorKind.INVALID_INPUT
    if status in {408, 409, 425, 429}:
        return ErrorKind.TEMPORARY
    if status is not None and 500 <= status < 600:
        return ErrorKind.PROVIDER
    return None
```

Tier 3 — Text signature matching (`execution.py:302-343`):
```python
def _classify_by_text_signature(self, exc: Exception) -> ErrorKind | None:
    name = type(exc).__name__.lower()
    text = f"{name} {exc!s}".lower()
    if self._text_matches(text, (r"auth|authentication|unauthorized|forbidden|permission denied|access denied", r"invalid[_\s-]?api[_\s-]?key|incorrect api key|api key.*not valid")):
        return ErrorKind.CONFIG
    if self._text_matches(text, (r"ratelimit|rate[_\s-]?limit|too many requests|quota exceeded", r"\b429\b")):
        return ErrorKind.TEMPORARY
    if self._text_matches(text, (r"invalid request|bad request|validation|unprocessable", r"model.*not.*found|does not exist", r"context.*length|maximum.*context|token limit", r"unsupported parameter")):
        return ErrorKind.INVALID_INPUT
    if self._text_matches(text, (r"timeout|timed out|connection error|network error", r"internal server|service unavailable|gateway timeout")):
        return ErrorKind.PROVIDER
    return None
```

### Fact 5: ChatClient.chat() on_response Usage

`republic/src/republic/clients/chat.py:292-305`

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
```

### Fact 6: ChatClient.stream() on_response Usage

`republic/src/republic/clients/chat.py:334-338`

```python
def _stream_on_response(response: Any, prov: str, mdl: str, _attempt: int) -> Any:
    payload, transport = _unwrap_response(response)
    if _is_non_stream_response(payload, transport=transport):
        raise RepublicError(ErrorKind.INVALID_INPUT, f"{prov}:{mdl}: response is not a stream.")
    return response
```

### Fact 7: max_attempts() Calculation

`republic/src/republic/core/execution.py:146-147`

```python
def max_attempts(self) -> int:
    return max(1, 1 + self._max_retries)
```

### Fact 8: Fallback Chain Structure

`republic/src/republic/core/execution.py:180-188`

```python
def model_candidates(self, override_model: str | None, override_provider: str | None) -> list[tuple[str, str]]:
    if override_model:
        provider, model = self.resolve_model_provider(override_model, override_provider)
        return [(provider, model)]

    candidates = [(self._provider, self._model)]
    for model in self._fallback_models:
        candidates.append(self.resolve_fallback(model))
    return candidates
```

### Fact 9: Change 44 Proposed API (No on_response)

`changes/44-chatclient-architectural-refactor.md:220-246`

```python
class ChatClient:
    def __init__(self, core: LLMCore) -> None:
        self._core = core
    
    async def chat(
        self,
        prepared: PreparedChat,
        messages: list[dict[str, Any]],
    ) -> LLMResult:
        """Execute single turn with given messages. Returns complete result."""
    
    async def stream(
        self,
        prepared: PreparedChat,
        messages: list[dict[str, Any]],
    ) -> AsyncStreamEvents[LLMResult]:
        """Execute single turn with streaming. Returns wrapper over async generator."""
```

**No mention of `on_response` in the entire document.**

### Fact 10: Change 44 Call Site Analysis (Omitting on_response)

`changes/48-on_response-api-analysis.md:85-94`

```python
response = await self._core.run_chat_async(
    messages_payload=messages,
    tools_payload=tools_payload or None,
    model=model, provider=provider,
    max_tokens=max_tokens, stream=False,
    reasoning_effort=reasoning_effort,
    kwargs=request_kwargs,
    # on_response omitted
)
```

This was the state **before** the on_response reassessment (change 48). The refactor initially proposed omitting `on_response` entirely.

---

## Claims

### Claim 1: The CPS Contract Is Not Optional — It Is the Retry Boundary

**Reasoning:** `run_chat_async` implements a retry waterfall with two nested loops: outer for fallback models, inner for attempts per model. Transport-level exceptions (network, rate limit, 5xx) are caught and classified. But **parse-time errors** (empty response, invalid format) can only trigger retries if they occur inside the retry loop. The `on_response` callback is the only code that executes inside the success branch of the inner loop. If parsing happens after `run_chat_async` returns, a parse error cannot trigger retry — the retry context is lost. `ChatClient.chat()` leverages this by raising `RepublicError(TEMPORARY)` from `_chat_on_response` when the response is empty, which causes `run_chat_async` to `continue` the attempt loop.

**References:** Fact 1, Fact 5

### Claim 2: Exception Classification Has Four Layers with Fallback

**Reasoning:** `classify_exception` checks: (1) if already a RepublicError, use its kind; (2) custom error classifier (user-provided); (3) Pydantic validation errors; (4) three-tier built-in classifiers in order: any-llm exception types → HTTP status codes → text signature regex matching. Each tier returns `ErrorKind | None`; if all return None, defaults to `UNKNOWN`. This layered design means new exception types are handled gracefully without code changes (text signature catches them).

**References:** Fact 2, Fact 4

### Claim 3: Retry vs Fallback Decisions Are Centralized and Deterministic

**Reasoning:** `_handle_attempt_error` is the single decision point. It wraps the exception, classifies it, logs it, then decides: retry same model if `should_retry(kind) and attempt + 1 < max_attempts()`. `should_retry` returns True only for `TEMPORARY` and `PROVIDER`. If same-model retry is exhausted, it returns `TRY_NEXT_MODEL`, which causes the inner loop to `break` and the outer loop to advance to the next fallback model. No other code makes retry decisions.

**References:** Fact 3, Fact 7

### Claim 4: on_response Receives Execution Metadata Unavailable to Post-Return Handlers

**Reasoning:** The callback receives `(response, provider_name, model_id, attempt)`. The actual provider/model used may differ from the requested one (fallbacks, resolution). The attempt counter is per-model. Post-return code would need to receive this metadata separately, or lose visibility into which model actually produced the response and on which attempt. `ChatClient.chat()` uses `prov` and `mdl` in error messages and empty-response checks.

**References:** Fact 1, Fact 5

### Claim 5: on_response Errors Are Also Subject to Retry Classification

**Reasoning:** When `on_response` raises `RepublicError`, the catch block at lines 687-691 checks `exc.kind == ErrorKind.TEMPORARY`. If true, it retries the same model. If false, it re-raises. This means parse errors classified as temporary (empty response) get retried, while parse errors classified as invalid input (schema mismatch) abort immediately. Moving parsing outside `run_chat_async` would require duplicating this logic.

**References:** Fact 1

### Claim 6: Change 44's Proposed API Silently Breaks Parse-Time Retry

**Reasoning:** Change 44 shows `ChatClient.chat()` returning `LLMResult` directly. The document never mentions how the retry loop integrates with parsing. If `ChatClient.chat()` were implemented as `response = await self._core.run_chat_async(...)` followed by post-return parsing, empty responses would return `LLMResult(error=...)` instead of triggering retry. The `_chat_on_response` pattern in current code exists precisely to avoid this. The refactor document's silence on `on_response` indicates a design gap.

**References:** Fact 9, Fact 5, Claim 1

### Claim 7: Streaming Has Different Retry Semantics by Necessity

**Reasoning:** `ChatClient.stream()` passes the identity continuation because the payload is an async generator that must be consumed outside the retry loop. Stream iteration errors (malformed chunks) are caught in the iterator and yield `ErrorEvent` — they do NOT trigger retry. This is a fundamental constraint: streaming cannot retry mid-stream because chunks are already yielded to the caller. Non-streaming has no such constraint, so it should use the full CPS retry contract.

**References:** Fact 6, Fact 1

### Claim 8: The Fallback Chain Is Linear and Exhaustive

**Reasoning:** `model_candidates` returns `[(primary_provider, primary_model)] + [fallbacks...]`. `iter_clients` yields them in order. The outer loop continues until a successful `on_response` returns or all candidates are exhausted. There is no early exit except success. `last_error` tracks the most recent error from the final candidate; if all fail, it is re-raised.

**References:** Fact 8, Fact 1

### Claim 9: Breaking CPS Would Require Duplicating Retry Logic in ChatClient

**Reasoning:** If `run_chat_async` were changed to return `TransportResponse` directly (no CPS), and `ChatClient.chat()` parsed it afterward, parse errors would need their own retry loop. This would duplicate: (a) exception classification, (b) fallback chain iteration, (c) attempt counting, (d) error logging. Alternatively, parsing errors would simply not be retried, degrading reliability. The current design centralizes all retry logic in `LLMCore`.

**References:** Claim 1, Claim 6, Fact 3

### Claim 10: Custom Error Classifiers Extend the Pipeline Without Modification

**Reasoning:** The `error_classifier` constructor parameter is checked before the three built-in tiers. This allows users to override classification for domain-specific errors without modifying `execution.py`. The classifier is wrapped in try/except to prevent user bugs from crashing the retry loop.

**References:** Fact 2
