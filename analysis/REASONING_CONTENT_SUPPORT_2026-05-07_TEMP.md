# Reasoning Content Support Exploration

## Notes

**Goal:** Map the full reasoning content support pipeline across the Bub/Republic stack, from configuration through extraction, transport, storage, and message reconstruction.

**Scope:** This exploration covers the files NOT already detailed in `TAPE_ENTRY_TIMELINE_EXPLORATION.md`. It focuses on extraction (parsers), transport (chat client / execution core), configuration (settings), and the default message reconstruction path.

**Key finding:** As of the current codebase, reasoning content is NOT extracted by either `CompletionTransportParser` or `ResponseTransportParser`. The `reasoning_effort` parameter exists in `TransportCallRequest` and `LLMCore` but is never set by Bub's `AgentSettings`.

## Facts

### Fact 1: AgentSettings has no reasoning_effort field

From `bub/src/bub/builtin/settings.py:34-48`:
```python
@config()
class AgentSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="BUB_", env_parse_none_str="null", extra="ignore")
    model: str = DEFAULT_MODEL
    fallback_models: list[str] | None = None
    api_key: str | dict[str, str] | None = Field(default_factory=provider_specific("api_key"))
    api_base: str | dict[str, str] | None = Field(default_factory=provider_specific("api_base"))
    api_format: Literal["completion", "responses", "messages"] = "completion"
    max_steps: int = 50
    max_tokens: int = DEFAULT_MAX_TOKENS
    model_timeout_seconds: int | None = None
    client_args: dict[str, Any] | None = None
    verbose: int = Field(default=0, description="Verbosity level for logging. Higher means more verbose.", ge=0, le=2)
```

There is no `reasoning_effort` field or environment variable support.

### Fact 2: LLMCore.run_chat_sync/async accepts reasoning_effort

From `republic/src/republic/core/execution.py:58-68`:
```python
@dataclass(frozen=True)
class TransportCallRequest:
    client: AnyLLM
    provider_name: str
    model_id: str
    messages_payload: list[dict[str, Any]]
    tools_payload: list[dict[str, Any]] | None
    max_tokens: int | None
    stream: bool
    reasoning_effort: Any | None
    kwargs: dict[str, Any]
```

From `republic/src/republic/core/execution.py:697-709`:
```python
def run_chat_sync(
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
```

The `reasoning_effort` parameter flows through `_call_client_sync` → `_call_responses_sync` (wrapped via `_with_responses_reasoning`) or `_call_completion_like_sync` (passed as `reasoning_effort=` to `client.completion`).

### Fact 3: LLMCore injects reasoning effort into responses API kwargs

From `republic/src/republic/core/execution.py:411-420`:
```python
@staticmethod
def _with_responses_reasoning(
    kwargs: dict[str, Any],
    reasoning_effort: Any | None,
) -> dict[str, Any]:
    if reasoning_effort is None:
        return kwargs
    if "reasoning" in kwargs:
        return kwargs
    return {**kwargs, "reasoning": {"effort": reasoning_effort}}
```

For the Responses API, reasoning effort becomes `reasoning={"effort": ...}`. For the Completions API, it is passed directly as `reasoning_effort=...`.

### Fact 4: CompletionTransportParser does NOT extract reasoning_content

From `republic/src/republic/clients/parsing/completion.py:33-43`:
```python
def extract_text(self, response: Any) -> str:
    if isinstance(response, str):
        return response

    choices = field(response, "choices")
    if not choices:
        return ""
    message = field(choices[0], "message")
    if message is None:
        return ""
    return field(message, "content", "") or ""
```

There is no extraction of `message.reasoning_content` (DeepSeek format).

### Fact 5: ResponseTransportParser does NOT extract reasoning items

From `republic/src/republic/clients/parsing/responses.py:95-99`:
```python
def extract_text(self, response: Any) -> str:
    output_text = field(response, "output_text")
    if isinstance(output_text, str):
        return output_text
    return self.extract_text_from_output(field(response, "output"))
```

And `extract_text_from_output` only looks for `type: "message"` and `type: "output_text"` items. It skips `type: "reasoning"` items entirely.

### Fact 6: ChatClient response handlers call _update_tape without reasoning

From `republic/src/republic/clients/chat.py:986-1014`:
```python
def _handle_create_response(
    self,
    prepared: PreparedChat,
    response: Any,
    provider_name: str,
    model_id: str,
    attempt: int,
) -> str:
    payload, transport = self._unwrap_response(response)
    text = self._extract_text(payload, transport=transport)
    if text:
        self._update_tape(
            prepared,
            text,
            response=payload,
            provider=provider_name,
            model=model_id,
        )
        return text
    ...
```

No reasoning content is passed to `_update_tape`. The same pattern holds for `_handle_tool_calls_response`, `_handle_tools_auto_response`, and their async variants.

### Fact 7: record_chat stores assistant message only when response_text is not None

From `republic/src/republic/tape/manager.py:112-116` (sync) and `238-242` (async):
```python
if response_text is not None:
    await self._tape_store.append(
        tape,
        TapeEntry.message({"role": "assistant", "content": response_text}, **meta),
    )
```

When `response_text=None` (tool-calling turns), no assistant `message` entry is written. This matches Fact 3 in the master exploration.

### Fact 8: _default_messages only includes "message" kind entries

From `republic/src/republic/tape/context.py:51-60`:
```python
def _default_messages(entries: Iterable[TapeEntry]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in entries:
        if entry.kind != "message":
            continue
        payload = entry.payload
        if not isinstance(payload, dict):
            continue
        messages.append(dict(payload))
    return messages
```

The default message selector ignores `tool_call`, `tool_result`, `event`, and `anchor` entries entirely. This means applications using the default context (not Bub's custom `_select_messages`) would drop tool calls from history.

### Fact 9: Agent loop delegates to tape.run_tools_async / tape.stream_events_async

From `bub/src/bub/builtin/agent.py:530-570`:
```python
async def _run_once(...):
    async with asyncio.timeout(self.settings.model_timeout_seconds):
        if stream_output:
            return await tape.stream_events_async(
                prompt=prompt,
                system_prompt=self._system_prompt(...),
                max_tokens=self.settings.max_tokens,
                tools=model_tools(tools),
                model=model,
            )
        else:
            return await tape.run_tools_async(
                prompt=prompt,
                system_prompt=self._system_prompt(...),
                max_tokens=self.settings.max_tokens,
                tools=model_tools(tools),
                model=model,
            )
```

No `reasoning_effort` is passed because `AgentSettings` lacks the field.

### Fact 10: T3 module defines reasoning trace transformations

From `t3.sf:1-175`:
The T3 (Transformation of Thinking Traces) module defines three ADT transformations:
- `structural_normalize :: Trace -> NormalizedTrace` — step-by-step cheatsheet
- `semantic_distill :: Trace -> DistilledTrace` — progressively abstract representations
- `reflect :: Trace -> ReflectedTrace` — contrastive error-focused form

The module uses SystemF ADT syntax with `data` declarations and `prim_op` annotations (`{-# LLM notools noskills #-}`).

## Claims

### Claim 1: Reasoning content is currently dropped at the parser layer

**Reasoning:** `CompletionTransportParser.extract_text` reads only `message.content`, ignoring `message.reasoning_content` (DeepSeek). `ResponseTransportParser.extract_text` reads only `output_text` and `type: "message"` items, ignoring `type: "reasoning"` items (OpenAI o-series). Since these are the two parsers used for all provider responses, any reasoning content returned by the APIs is discarded before it reaches the tape.

**References:** Fact 4, Fact 5

### Claim 2: The reasoning_effort parameter is a dead parameter in practice

**Reasoning:** `LLMCore` accepts `reasoning_effort` and forwards it to `any-llm`, but Bub's `AgentSettings` does not define the field, and `_build_llm` does not pass it. The `Agent._run_once` method does not forward it to `tape.run_tools_async` or `tape.stream_events_async`. Therefore, even though the transport layer supports it, no caller sets it.

**References:** Fact 1, Fact 2, Fact 9

### Claim 3: Adding reasoning support requires changes across at least 5 layers

**Reasoning:** Based on the call chain:
1. **Config:** `AgentSettings` needs `reasoning_effort` field (Fact 1)
2. **Agent:** `_run_once` needs to pass it to `tape.run_tools_async` / `stream_events_async` (Fact 9)
3. **Execution:** `LLMCore` already supports it (Fact 2) — no change needed here
4. **Parsing:** Both `CompletionTransportParser` and `ResponseTransportParser` need reasoning extraction methods (Fact 4, Fact 5)
5. **Chat client:** `_handle_*_response` methods need to extract reasoning and pass it to `_update_tape` (Fact 6)
6. **Tape storage:** `record_chat` needs to accept and store reasoning content (Fact 7)
7. **Message reconstruction:** `_default_messages` (Fact 8) and `_select_messages` (master exploration) need to include reasoning in reconstructed assistant messages

**References:** Fact 1, Fact 2, Fact 4, Fact 5, Fact 6, Fact 7, Fact 8, Fact 9, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#fact2`

### Claim 4: The T3 module is orthogonal to runtime reasoning content support

**Reasoning:** `t3.sf` defines offline transformations of reasoning traces (normalization, distillation, reflection) as a SystemF library. It operates on `Trace` strings and produces structured ADTs. This is unrelated to the runtime pipeline of extracting `reasoning_content` from LLM API responses and feeding it back into subsequent calls. The T3 module could theoretically consume stored reasoning traces *after* they are persisted, but it is not part of the reasoning content support change plan.

**References:** Fact 10

### Claim 5: Default context consumers would lose tool call history

**Reasoning:** `_default_messages` skips any entry whose `kind != "message"`. Tool calls are stored as `tool_call` entries (master exploration Fact 3), not `message` entries. Therefore, any code path using `_default_messages` (i.e., `TapeContext` without a custom `select`) would reconstruct a message list that omits tool calls entirely. This means reasoning content support must be implemented in both `_default_messages` and `_select_messages` if it is to be universal.

**References:** Fact 8, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#fact3`

### Claim 6: Responses API metadata-only responses are explicitly handled

**Reasoning:** The chat client has a `_is_completed_responses_metadata_only` check in `_handle_create_response`, `_handle_tools_auto_response`, and the finalize methods. `RESPONSES_METADATA_ONLY_ITEM_TYPES = frozenset({"reasoning", "compaction"})` means that a response containing only reasoning items is treated as a valid empty response. However, since `extract_text` ignores reasoning items, the reasoning content is still lost.

**References:** Fact 5, Fact 6, `republic/src/republic/clients/chat.py:32`
