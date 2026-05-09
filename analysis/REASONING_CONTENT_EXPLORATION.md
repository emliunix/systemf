# Reasoning Content Exploration

## Notes

### Note 1: Context and Goal
This exploration traces the exact code paths for reasoning content through the Bub/Republic stack. The stack currently does NOT extract, buffer, or store reasoning content from LLM responses. The goal is to identify every point where reasoning content enters, where it is lost, and what changes are needed to enable full reasoning content support.

### Note 2: Scope Boundaries
- In scope: DeepSeek Chat Completions (`reasoning_content` field) and OpenAI Responses API (`reasoning` output item)
- Out of scope: Claude extended thinking, Gemini thinking, reasoning summary extraction, UI display
- Focus on ALL response handling paths in `chat.py` (sync + async, streaming + non-streaming, tool calls + text)

### Note 3: Tape Entry Timeline
`./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` established that Bub uses a custom `_select_messages` message reconstructor and that tool-calling turns have no assistant `message` entry (the assistant message is reconstructed from the `tool_call` entry). This exploration extends that work to cover the full reasoning content pipeline. The timeline-specific facts and claims from that exploration are incorporated below as Facts 1-6 and Claims 1-2.

### Note 4: Entry Points
Reasoning content enters the stack at the transport parser layer (`CompletionTransportParser` for DeepSeek, `ResponseTransportParser` for OpenAI Responses). From there it must flow through:
1. Parser extraction methods
2. ChatClient response handlers (streaming and non-streaming)
3. Tape update methods (`_update_tape`, `_update_tape_async`)
4. `record_chat` storage
5. Message reconstruction (`_default_messages` or `_select_messages`)

### Note 5: Key Finding
Reasoning content is currently lost at EVERY layer. The parsers don't extract it. The streaming buffers don't collect it. The finalization methods don't pass it. `record_chat` doesn't accept it. Message reconstruction doesn't handle it.

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

### Fact 7: AgentSettings has no reasoning_effort field

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

### Fact 8: Agent loop does not pass reasoning_effort

From `bub/src/bub/builtin/agent.py:551-570`:
```python
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
No `reasoning_effort` parameter is passed to either `stream_events_async` or `run_tools_async`.

### Fact 9: Hook implementations call agent.run and agent.run_stream

From `bub/src/bub/builtin/hook_impl.py:160-174`:
```python
@hookimpl
async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    if (result := await agent.run_command(tape_name, prompt, state)) is not None:
        return result
    return await agent.run(tape_name=tape_name, prompt=prompt, state=state)

@hookimpl
async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    if (events := await agent.run_command_stream(tape_name, prompt, state)) is not None:
        return events
    return await agent.run_stream(tape_name=tape_name, prompt=prompt, state=state)
```

### Fact 10: LLM facade passes kwargs through

From `republic/src/republic/llm.py:271-296`:
```python
async def run_tools_async(
    self,
    prompt: str | None = None,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    tape: str | None = None,
    context: TapeContext | None = None,
    tools: ToolInput = None,
    **kwargs: Any,
) -> ToolAutoResult:
    return await self._chat_client.run_tools_async(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        provider=provider,
        messages=messages,
        max_tokens=max_tokens,
        tape=tape,
        context=context,
        tools=tools,
        **kwargs,
    )
```

### Fact 11: ChatClient splits reasoning_effort from kwargs

From `republic/src/republic/clients/chat.py:509-515`:
```python
@staticmethod
def _split_reasoning_effort(kwargs: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
    if "reasoning_effort" not in kwargs:
        return None, kwargs
    request_kwargs = dict(kwargs)
    reasoning_effort = request_kwargs.pop("reasoning_effort", None)
    return reasoning_effort, request_kwargs
```

### Fact 12: reasoning_effort is passed to LLMCore execution

From `republic/src/republic/clients/chat.py:530-543`:
```python
def _execute_sync(self, prepared: PreparedChat, *, tools_payload: list[dict[str, Any]] | None, model: str | None, provider: str | None, max_tokens: int | None, stream: bool, kwargs: dict[str, Any], on_response: Callable[[Any, str, str, int], Any]) -> Any:
    if prepared.context_error is not None:
        raise prepared.context_error
    reasoning_effort, request_kwargs = self._split_reasoning_effort(kwargs)
    try:
        return self._core.run_chat_sync(
            messages_payload=prepared.payload,
            tools_payload=tools_payload,
            model=model,
            provider=provider,
            max_tokens=max_tokens,
            stream=stream,
            reasoning_effort=reasoning_effort,
            kwargs=request_kwargs,
            on_response=on_response,
        )
```

### Fact 13: LLMCore run_chat_sync accepts reasoning_effort

From `republic/src/republic/core/execution.py:697-751`:
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

### Fact 14: Responses API converts reasoning_effort to reasoning dict

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

### Fact 15: Completion API passes reasoning_effort directly

From `republic/src/republic/core/execution.py:519-521`:
```python
payload=request.client.completion(
    ...
    reasoning_effort=request.reasoning_effort,
    **completion_kwargs,
),
```

### Fact 16: BaseTransportParser has no reasoning extraction methods

From `republic/src/republic/clients/parsing/types.py:11-34`:
```python
class BaseTransportParser(ABC):
    @abstractmethod
    def is_non_stream_response(self, response: Any) -> bool: ...
    @abstractmethod
    def extract_chunk_tool_call_deltas(self, chunk: Any) -> list[Any]: ...
    @abstractmethod
    def extract_chunk_text(self, chunk: Any) -> str: ...
    @abstractmethod
    def extract_text(self, response: Any) -> str: ...
    @abstractmethod
    def extract_tool_calls(self, response: Any) -> list[dict[str, Any]]: ...
    @abstractmethod
    def extract_usage(self, response: Any) -> dict[str, Any] | None: ...
```

### Fact 17: CompletionTransportParser does not extract reasoning_content

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

### Fact 18: ResponseTransportParser does not extract reasoning items

From `republic/src/republic/clients/parsing/responses.py:95-99`:
```python
def extract_text(self, response: Any) -> str:
    output_text = field(response, "output_text")
    if isinstance(output_text, str):
        return output_text
    return self.extract_text_from_output(field(response, "output"))
```

### Fact 19: ChatClient _extract_text delegates to parser

From `republic/src/republic/clients/chat.py:2064-2071`:
```python
@staticmethod
def _extract_text(
    response: Any,
    *,
    transport: TransportKind | None = None,
) -> str:
    payload, parser = ChatClient._unwrap_response_with_parser(response, transport=transport)
    return parser.extract_text(payload)
```

### Fact 20: Non-streaming text response handler does not extract reasoning

From `republic/src/republic/clients/chat.py:986-1014`:
```python
def _handle_create_response(self, prepared, response, provider_name, model_id, attempt):
    payload, transport = self._unwrap_response(response)
    text = self._extract_text(payload, transport=transport)
    if text:
        self._update_tape(prepared, text, response=payload, provider=provider_name, model=model_id)
        return text
    if self._is_completed_responses_metadata_only(payload, transport=transport):
        self._update_tape(prepared, None, response=payload, provider=provider_name, model=model_id)
        return ""
    raise RepublicError(ErrorKind.TEMPORARY, f"{provider_name}:{model_id}: empty response")
```

### Fact 21: Tool calls response handler does not extract reasoning

From `republic/src/republic/clients/chat.py:1046-1065`:
```python
def _handle_tool_calls_response(self, prepared, response, provider_name, model_id, attempt):
    payload, transport = self._unwrap_response(response)
    calls = self._extract_tool_calls(payload, transport=transport)
    self._update_tape(prepared, None, tool_calls=calls, tool_results=[], response=payload, provider=provider_name, model=model_id)
    return calls
```

### Fact 22: Tools auto-response handler does not extract reasoning

From `republic/src/republic/clients/chat.py:1088-1135`:
```python
def _handle_tools_auto_response(self, prepared, response, provider_name, model_id, attempt):
    payload, transport = self._unwrap_response(response)
    tool_calls = self._extract_tool_calls(payload, transport=transport)
    if tool_calls:
        execution = self._tool_executor.execute(...)
        self._update_tape(prepared, None, tool_calls=execution.tool_calls, tool_results=execution.tool_results, response=payload, provider=provider_name, model=model_id)
        return ToolAutoResult.tools_result(execution.tool_calls, execution.tool_results)
    text = self._extract_text(payload, transport=transport)
    if text:
        self._update_tape(prepared, text, response=payload, provider=provider_name, model=model_id)
        return ToolAutoResult.text_result(text)
    ...
```

### Fact 23: Streaming text buffer only collects text parts

From `republic/src/republic/clients/chat.py:1554-1625`:
```python
def _build_text_stream(self, prepared, response, provider_name, model_id, attempt):
    ...
    state = StreamState()
    parts: list[str] = []
    assembler = ToolCallAssembler()
    def _iterator():
        nonlocal usage, response_completed
        try:
            for chunk in payload:
                ...
                text = self._extract_chunk_text(chunk, transport=transport)
                if text:
                    parts.append(text)
                    yield text
                usage = self._extract_usage(chunk, transport=transport) or usage
        except Exception as exc:
            state.error = self._core.wrap_error(exc, provider_name, model_id)
        finally:
            tool_calls = assembler.finalize()
            self._finalize_text_stream(prepared, text="".join(parts) if parts else None, tool_calls=tool_calls, state=state, provider_name=provider_name, model_id=model_id, attempt=attempt, usage=usage, log_empty=True, ...)
```

### Fact 24: Streaming event buffer only collects text parts

From `republic/src/republic/clients/chat.py:1722-1802`:
```python
def _build_event_stream(self, prepared, response, provider_name, model_id, attempt):
    ...
    state = StreamState()
    usage: dict[str, Any] | None = None
    parts: list[str] = []
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[Any] = []
    assembler = ToolCallAssembler()
    def _iterator():
        nonlocal usage, tool_calls, tool_results, response_completed
        try:
            for chunk in payload:
                ...
                text = self._extract_chunk_text(chunk, transport=transport)
                if text:
                    parts.append(text)
                    yield StreamEvent("text", {"delta": text})
            tool_calls = assembler.finalize()
            events, tool_results = self._finalize_event_stream(prepared, parts=parts, tool_calls=tool_calls, state=state, provider_name=provider_name, model_id=model_id, attempt=attempt, usage=usage, ...)
            yield from events
        ...
        finally:
            tool_calls = self._finalize_event_stream_state(prepared, parts=parts, tool_calls=tool_calls, tool_results=tool_results, state=state, provider_name=provider_name, model_id=model_id, usage=usage, assembler=assembler)
```

### Fact 25: Event stream from response does not extract reasoning

From `republic/src/republic/clients/chat.py:1890-1951`:
```python
def _build_event_stream_from_response(self, prepared, response, provider_name, model_id, *, transport=None):
    text = self._extract_text(response, transport=transport)
    tool_calls = self._extract_tool_calls(response, transport=transport)
    usage = self._extract_usage(response, transport=transport)
    ...
    self._update_tape(prepared, text or None, tool_calls=tool_calls or None, tool_results=tool_results or None, error=state.error, response=response, provider=provider_name, model=model_id, usage=usage)
    return StreamEvents(iter(events), state=state)
```

### Fact 26: _update_tape does not accept reasoning parameter

From `republic/src/republic/clients/chat.py:583-614`:
```python
def _update_tape(self, prepared, response_text, *, tool_calls=None, tool_results=None, error=None, response=None, provider=None, model=None, usage=None):
    if not prepared.should_update:
        return
    if prepared.tape is None:
        return
    self._tape.record_chat(
        tape=prepared.tape,
        run_id=prepared.run_id,
        system_prompt=prepared.system_prompt,
        context_error=prepared.context_error,
        new_messages=prepared.new_messages,
        response_text=response_text,
        tool_calls=tool_calls,
        tool_results=tool_results,
        error=error,
        response=response,
        provider=provider,
        model=model,
        usage=usage,
    )
```

### Fact 27: record_chat does not accept reasoning parameter

From `republic/src/republic/tape/manager.py:78-126`:
```python
def record_chat(self, *, tape, run_id, system_prompt, context_error, new_messages, response_text, tool_calls=None, tool_results=None, error=None, response=None, provider=None, model=None, usage=None):
    meta = {"run_id": run_id}
    if system_prompt:
        self._tape_store.append(tape, TapeEntry.system(system_prompt, **meta))
    ...
    if response_text is not None:
        self._tape_store.append(tape, TapeEntry.message({"role": "assistant", "content": response_text}, **meta))
    data = {"status": "error" if error is not None else "ok"}
    resolved_usage = usage or self._extract_usage(response)
    ...
```

### Fact 28: _default_messages copies message payloads verbatim without transformation

From `republic/src/republic/tape/context.py:51-59`:
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

### Fact 29: _select_messages does not handle reasoning_content on message or tool_call entries

From `bub/src/bub/builtin/context.py:42-52`:
```python
def _append_message_entry(messages, entry):
    payload = entry.payload
    if isinstance(payload, dict):
        messages.append(dict(payload))

def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    return calls
```

### Fact 30: TapeEntry kinds do not include a reasoning kind

From `republic/src/republic/tape/entries.py:16-61`:
```python
@dataclass(frozen=True)
class TapeEntry:
    id: int
    kind: str
    payload: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    date: str = field(default_factory=utc_now)

    @classmethod
    def message(cls, message, **meta): ...
    @classmethod
    def system(cls, content, **meta): ...
    @classmethod
    def anchor(cls, name, state=None, **meta): ...
    @classmethod
    def tool_call(cls, calls, **meta): ...
    @classmethod
    def tool_result(cls, results, **meta): ...
    @classmethod
    def error(cls, error, **meta): ...
    @classmethod
    def event(cls, name, data=None, **meta): ...
```

### Fact 31: _prepare_messages copies user-provided messages verbatim

From `republic/src/republic/clients/chat.py:346-348`:
```python
if messages is not None:
    payload = [dict(message) for message in messages]
    return payload, []
```

### Fact 32: RESPONSES_METADATA_ONLY_ITEM_TYPES includes reasoning

From `republic/src/republic/clients/chat.py:32`:
```python
RESPONSES_METADATA_ONLY_ITEM_TYPES = frozenset({"reasoning", "compaction"})
```

### Fact 33: T3 module is a Haskell-like ADT specification for reasoning trace transformations

From `t3.sf:1-5`:
```
-- t3.sf
-- Transformation of Thinking Traces (T3)
-- Based on: "RAG over Thinking Traces Can Improve Reasoning Tasks"
-- arXiv-2605.03344v1
```

## Claims

### Claim 1: Tape entry timeline for tool-calling turns lacks an assistant message entry

**Reasoning:** For tool-calling turns, `record_chat` only creates an assistant `message` entry when `response_text is not None` (Fact 3). Since tool-calling turns pass `response_text=None`, no assistant message is stored. The assistant message is instead reconstructed from the `tool_call` entry by `_select_messages` (Fact 4). This means reasoning content for tool-calling turns must be stored on the `tool_call` entry, not on an assistant message.

**References:** Fact 3, Fact 4

### Claim 2: DeepSeek compatibility requires conditional reasoning stripping

**Reasoning:** DeepSeek requires `reasoning_content` to be preserved for tool-calling turns but stripped for normal turns. Currently, `_default_messages` (Fact 28) copies payloads verbatim, so if `reasoning_content` were stored on a message entry, it would be included in reconstructed messages for all turns. Bub's `_select_messages` (Fact 29) reconstructs `tool_call` entries into assistant messages without including any reasoning fields. Neither strips reasoning from normal turns, which would cause DeepSeek 400 errors.

**References:** Fact 28, Fact 29

### Claim 3: Reasoning content is lost at the parser layer

**Reasoning:** The `BaseTransportParser` abstract class (Fact 16) defines no `extract_reasoning()` or `extract_chunk_reasoning()` methods. `CompletionTransportParser.extract_text` (Fact 17) reads `message.content` but not `message.reasoning_content`. `ResponseTransportParser.extract_text` (Fact 18) filters `output` items to `type == "message"`, skipping `type == "reasoning"` items entirely. Therefore, reasoning content is never extracted from responses or streaming chunks at the parser layer.

**References:** Fact 16, Fact 17, Fact 18

### Claim 4: Reasoning content is lost in all non-streaming response handlers

**Reasoning:** All non-streaming handlers (`_handle_create_response`, `_handle_tool_calls_response`, `_handle_tools_auto_response`, and their async variants) call `_extract_text` and `_extract_tool_calls` (Facts 20, 21, 22). Since there is no `_extract_reasoning` method (Fact 19), and the handlers don't call any reasoning extraction, reasoning content is completely ignored in non-streaming paths.

**References:** Fact 19, Fact 20, Fact 21, Fact 22

### Claim 5: Reasoning content is lost in all streaming response handlers

**Reasoning:** The streaming handlers (`_build_text_stream`, `_build_async_text_stream`, `_build_event_stream`, `_build_async_event_stream`) buffer text deltas in `parts: list[str]` (Facts 23, 24). There is no `reasoning_parts` buffer. They call `_extract_chunk_text` but not any chunk reasoning extraction. In the `finally` block, only `parts` is passed to finalization. The event stream from response handlers (Fact 25) also don't extract reasoning. Therefore, streaming reasoning deltas are lost.

**References:** Fact 23, Fact 24, Fact 25

### Claim 6: Reasoning content cannot be stored because _update_tape and record_chat lack the parameter

**Reasoning:** `_update_tape` (Fact 26) and `_update_tape_async` have no `reasoning` parameter. They call `record_chat` which also has no `reasoning` parameter (Fact 27). Even if reasoning were extracted upstream, there is no mechanism to pass it through to tape storage.

**References:** Fact 26, Fact 27

### Claim 7: Message reconstruction does not handle reasoning fields

**Reasoning:** Republic's `_default_messages` (Fact 28) copies `message` entry payloads verbatim, so if `reasoning_content` were stored on a message entry, it would be included in reconstructed messages. However, Bub's `_select_messages` (Fact 29) reconstructs `tool_call` entries into assistant messages without including any reasoning fields. Neither `_default_messages` nor `_select_messages` strips reasoning fields from normal turns, which would cause DeepSeek 400 errors on subsequent calls.

**References:** Fact 28, Fact 29, Claim 2

### Claim 8: User-provided messages may contain reasoning_content from prior calls

**Reasoning:** `_prepare_messages` and `_prepare_messages_async` (Fact 31) copy user-provided message arrays verbatim. If a user passes messages that include `reasoning_content` from a previous DeepSeek response, those fields are sent to the API. This could cause 400 errors on providers that don't expect `reasoning_content` in the message history.

**References:** Fact 31

### Claim 9: The reasoning_effort parameter is wired through the execution layer but never set at the top

**Reasoning:** `AgentSettings` has no `reasoning_effort` field (Fact 7). The agent loop doesn't pass it (Fact 8). However, if it were passed as a kwarg, `LLM.run_tools_async` would forward it (Fact 10), `ChatClient._split_reasoning_effort` would extract it (Fact 11), and `LLMCore.run_chat_sync/async` would receive it (Fact 13). For Responses API, `_with_responses_reasoning` converts it (Fact 14). For Completion API, it's passed directly (Fact 15). The parameter chain is complete from `ChatClient` down to `any-llm`; only the top of the stack (Bub settings and agent loop) is missing.

**References:** Fact 7, Fact 8, Fact 10, Fact 11, Fact 13, Fact 14, Fact 15

### Claim 10: The two API formats require different reasoning extraction strategies

**Reasoning:** DeepSeek Chat Completions places reasoning in `message.reasoning_content` (a string) and streams it as `delta.reasoning_content` deltas. OpenAI Responses API places reasoning as a separate `output` item with `type: "reasoning"` (a dict). The Responses API does not stream reasoning as text deltas; it returns complete reasoning items in the final response. This means:
1. `CompletionTransportParser` needs `extract_reasoning` to read `message.reasoning_content` and `extract_chunk_reasoning` to read `delta.reasoning_content`
2. `ResponseTransportParser` needs `extract_reasoning` to scan `output` items for `type == "reasoning"`, but `extract_chunk_reasoning` can return `""` since reasoning is not streamed as text deltas

**References:** Fact 17, Fact 18, Fact 32

### Claim 11: Changes are needed in six layers to enable full reasoning support

**Reasoning:** Based on the facts above, reasoning content is lost at every layer. To enable full support, changes are needed in:
1. **Settings:** Add `reasoning_effort` to `AgentSettings` (Fact 7)
2. **Agent loop:** Pass `reasoning_effort` to LLM calls (Fact 8)
3. **Parsers:** Add `extract_reasoning()` and `extract_chunk_reasoning()` to `BaseTransportParser` with implementations in `CompletionTransportParser` and `ResponseTransportParser` (Facts 16, 17, 18)
4. **ChatClient response handlers:** Extract/buffer reasoning in all 12+ response paths and pass it to finalization (Facts 20-25)
5. **Tape storage:** Add `reasoning` parameter to `_update_tape`, `record_chat`, and store it in message/tool_call payloads (Facts 26, 27, 3)
6. **Message reconstruction:** Update `_default_messages` and/or `_select_messages` to conditionally preserve/strip reasoning based on tool_calls presence (Facts 28, 29)

**References:** Fact 7, Fact 8, Fact 16, Fact 17, Fact 18, Facts 20-27, Facts 28, 29, 3

### Claim 12: The T3 module is orthogonal to runtime reasoning content support

**Reasoning:** `t3.sf` defines offline transformations of reasoning traces (normalization, distillation, reflection) as a SystemF library. It operates on `Trace` strings and produces structured ADTs. This is unrelated to the runtime pipeline of extracting `reasoning_content` from LLM API responses and feeding it back into subsequent calls. The T3 module could theoretically consume stored reasoning traces *after* they are persisted, but it is not part of the reasoning content support change plan.

**References:** Fact 33
