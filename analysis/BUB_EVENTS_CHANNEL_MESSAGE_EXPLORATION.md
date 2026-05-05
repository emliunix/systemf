# Exploration: ChannelMessage Full Definition and Usage

## Notes

### Note 1: Goal
Provide a comprehensive definition of `ChannelMessage` fields based on actual framework usage, covering: field definitions, who reads/writes each field, inbound vs outbound semantics, and propagation through the framework pipeline.

### Note 2: Scope
Covers `bub/src/bub/channels/message.py` definition and all usage sites in `bub/src/bub/builtin/hook_impl.py`, `bub/src/bub/framework.py`, `bub/src/bub/channels/manager.py`, plus channel implementations (Telegram, CLI).

## Facts

### Fact 1: ChannelMessage Dataclass Definition
`bub/src/bub/channels/message.py:33-51`
```python
@dataclass
class ChannelMessage:
    session_id: str
    channel: str
    content: str
    chat_id: str = "default"
    is_active: bool = False
    kind: MessageKind = "normal"
    context: dict[str, Any] = field(default_factory=dict)
    media: list[MediaItem] = field(default_factory=list)
    lifespan: contextlib.AbstractAsyncContextManager | None = None
    output_channel: str = ""
```

### Fact 2: __post_init__ Auto-Populates Context
`bub/src/bub/channels/message.py:48-51`
```python
def __post_init__(self) -> None:
    self.context.update({"channel": "$" + self.channel, "chat_id": self.chat_id})
    if not self.output_channel:
        self.output_channel = self.channel
```

### Fact 3: Framework Pipeline
`bub/src/bub/framework.py:105-144`
```python
async def process_inbound(self, inbound: Envelope, stream_output: bool = False) -> TurnResult:
    session_id = await self._hook_runtime.call_first("resolve_session", message=inbound)
    state = {"_runtime_workspace": str(self.workspace)}
    for hook_state in reversed(await self._hook_runtime.call_many("load_state", ...)):
        state.update(hook_state)
    prompt = await self._hook_runtime.call_first("build_prompt", message=inbound, session_id=session_id, state=state)
    model_output = await self._run_model(inbound, prompt, session_id, state, stream_output)
    await self._hook_runtime.call_many("save_state", session_id=session_id, state=state, message=inbound, model_output=model_output)
    outbounds = await self._collect_outbounds(inbound, session_id, state, model_output)
    for outbound in outbounds:
        await self._hook_runtime.call_many("dispatch_outbound", message=outbound)
```

### Fact 4: resolve_session Hook
`bub/src/bub/builtin/hook_impl.py:106-112`
```python
def resolve_session(self, message: ChannelMessage) -> str:
    session_id = field_of(message, "session_id")
    if session_id is not None and str(session_id).strip():
        return str(session_id)
    channel = str(field_of(message, "channel", "default"))
    chat_id = str(field_of(message, "chat_id", "default"))
    return f"{channel}:{chat_id}"
```

### Fact 5: load_state Hook
`bub/src/bub/builtin/hook_impl.py:115-122`
```python
async def load_state(self, message: ChannelMessage, session_id: str) -> State:
    lifespan = field_of(message, "lifespan")
    if lifespan is not None:
        await lifespan.__aenter__()
    state = {"session_id": session_id, "_runtime_agent": self._get_agent()}
    if context := field_of(message, "context_str"):
        state["context"] = context
    return state
```

### Fact 6: build_prompt Hook
`bub/src/bub/builtin/hook_impl.py:132-158`
```python
async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
    context = field_of(message, "context_str")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
    text = f"{context_prefix}{content}"
    media = field_of(message, "media") or []
    if not media:
        return text
    # ...multimodal handling
```

### Fact 7: save_state Hook
`bub/src/bub/builtin/hook_impl.py:125-129`
```python
async def save_state(self, session_id: str, state: State, message: ChannelMessage, model_output: str) -> None:
    tp, value, traceback = sys.exc_info()
    lifespan = field_of(message, "lifespan")
    if lifespan is not None:
        await lifespan.__aexit__(tp, value, traceback)
```

### Fact 8: render_outbound Hook
`bub/src/bub/builtin/hook_impl.py:290-306`
```python
def render_outbound(self, message, session_id, state, model_output):
    outbound = ChannelMessage(
        session_id=session_id,
        channel=field_of(message, "channel", "default"),
        chat_id=field_of(message, "chat_id", "default"),
        content=model_output,
        output_channel=field_of(message, "output_channel", "default"),
        kind=field_of(message, "kind", "normal"),
    )
    return [outbound]
```

### Fact 9: dispatch_output
`bub/src/bub/channels/manager.py:86-105`
```python
async def dispatch_output(self, message: Envelope) -> bool:
    channel_name = field_of(message, "output_channel", field_of(message, "channel"))
    channel_key = str(channel_name)
    channel = self.get_channel(channel_key)
    outbound = ChannelMessage(
        session_id=str(field_of(message, "session_id", f"{channel_key}:default")),
        channel=channel_key,
        chat_id=str(field_of(message, "chat_id", "default")),
        content=content_of(message),
        context=field_of(message, "context", {}),
        kind=field_of(message, "kind", "normal"),
    )
    await channel.send(outbound)
```

### Fact 10: Telegram Channel lifespan Usage
`bub/src/bub/channels/telegram.py:263-272`
```python
return ChannelMessage(
    session_id=session_id,
    channel=self.name,
    chat_id=chat_id,
    content=content,
    media=media_items,
    is_active=is_active,
    lifespan=self.start_typing(chat_id),
    output_channel="null",
)
```

### Fact 11: CLI Channel lifespan Usage
`bub/src/bub/channels/cli/__init__.py:108-114`
```python
message = ChannelMessage(
    session_id=self._message_template["session_id"],
    channel=self._message_template["channel"],
    chat_id=self._message_template["chat_id"],
    content=request,
    lifespan=self.message_lifespan(request_completed),
)
```

## Field Definitions by Usage

### session_id
**Type:** `str`
**Inbound readers:** `resolve_session` hook (Fact 4), `load_state` hook (Fact 5, via framework)
**Outbound writer:** `render_outbound` hook (Fact 8)
**Outbound reader:** `dispatch_output` (Fact 9)
**Propagation:** ✅ Yes (resolved value passed through)
**Usage:** Session routing identifier. Used for state load/save and outbound routing. Channels may generate UUIDs per request (bub_events) or use `channel:chat_id` format (Telegram).

### channel
**Type:** `str`
**Inbound readers:** `__post_init__` (Fact 2, adds to context), `resolve_session` (Fact 4, fallback)
**Outbound writer:** `render_outbound` hook (Fact 8)
**Outbound reader:** `dispatch_output` (Fact 9, fallback)
**Propagation:** ✅ Yes
**Usage:** Channel identifier. Auto-added to context as `$channel`. Used for routing fallback when `output_channel` is empty.

### content
**Type:** `str`
**Inbound readers:** `build_prompt` hook (Fact 6)
**Outbound writer:** `render_outbound` hook (Fact 8, set to `model_output`)
**Outbound reader:** `dispatch_output` (Fact 9), channel `send()`
**Propagation:** ✅ Yes (semantic change: input → output)
**Usage:** On inbound: user prompt text. On outbound: LLM response. Command detection via `,` prefix.

### chat_id
**Type:** `str`
**Inbound readers:** `__post_init__` (Fact 2, adds to context), `resolve_session` (Fact 4, fallback)
**Outbound writer:** `render_outbound` hook (Fact 8)
**Outbound reader:** `dispatch_output` (Fact 9)
**Propagation:** ✅ Yes
**Usage:** Sub-identifier within channel. Auto-added to context. Used for session fallback.

### kind
**Type:** `MessageKind` ("normal" | "command" | "error")
**Inbound readers:** `build_prompt` hook (Fact 6, modified in place for `,` prefix)
**Outbound writer:** `render_outbound` hook (Fact 8)
**Outbound reader:** `dispatch_output` (Fact 9)
**Propagation:** ✅ Yes
**Usage:** Message type. Commands bypass agent loop. Errors may trigger special handling.

### context
**Type:** `dict[str, Any]`
**Inbound readers:** `build_prompt` hook (Fact 6, via `context_str`), `load_state` hook (Fact 5)
**Outbound writer:** **None** (not copied by `render_outbound`)
**Outbound reader:** `dispatch_output` (Fact 9, reads empty dict)
**Propagation:** ❌ No
**Usage:** Prompt metadata. Auto-populated with `$channel` and `chat_id`. Custom keys visible to LLM during turn. Lost on response path.

### output_channel
**Type:** `str`
**Inbound readers:** `__post_init__` (Fact 2, defaults to `channel`)
**Outbound writer:** `render_outbound` hook (Fact 8)
**Outbound reader:** `dispatch_output` (Fact 9, primary routing key)
**Propagation:** ✅ Yes
**Usage:** Routing override. Defaults to `channel`. Used by `dispatch_output` to select target channel.

### media
**Type:** `list[MediaItem]`
**Inbound readers:** `build_prompt` hook (Fact 6, multimodal handling)
**Outbound writer:** **None**
**Outbound reader:** None
**Propagation:** ❌ No
**Usage:** Attachments for multimodal prompts. Consume-only field.

### lifespan
**Type:** `AbstractAsyncContextManager | None`
**Inbound readers:** `load_state` hook (Fact 5, `__aenter__`), `save_state` hook (Fact 7, `__aexit__`)
**Outbound writer:** **None**
**Outbound reader:** None
**Propagation:** ❌ No
**Usage:** Channel-specific resource lifecycle. Telegram: typing indicator. CLI: request completion signal. Managed by load_state/save_state hooks.

### is_active
**Type:** `bool`
**Inbound readers:** None in framework
**Outbound writer:** None
**Outbound reader:** None
**Propagation:** N/A
**Usage:** Channel-specific field. Not read by framework. Telegram sets it for filtering.

## Claims

### Claim 1: Outbound Is Constructed, Not Derived
**Reasoning:** `render_outbound` (Fact 8) creates a new `ChannelMessage` via constructor. It does not modify the inbound message. Fields not explicitly passed get default values. This is why `context`, `media`, and `lifespan` are lost.
**References:** Fact 8

### Claim 2: session_id Is the Only Framework-Managed Correlation Field
**Reasoning:** Among all fields, only `session_id` is: (a) read by framework hooks for routing, (b) explicitly propagated through `render_outbound` via parameter, (c) available on outbound for channel matching. Other propagated fields (`channel`, `chat_id`, `kind`, `output_channel`) are passively copied without framework semantic management.
**References:** Fact 4, Fact 8, Fact 9

### Claim 3: lifespan Is a Channel-Framework Contract
**Reasoning:** Channels set `lifespan` (Facts 10, 11). Framework hooks manage it via `__aenter__` (Fact 5) and `__aexit__` (Fact 7). This is a contract: channel provides the context manager, framework guarantees cleanup. No other field has this explicit lifecycle management.
**References:** Fact 5, Fact 7, Fact 10, Fact 11

### Claim 4: context Is LLM-Facing Only
**Reasoning:** `context` is read by `build_prompt` (Fact 6) for prompt construction and by `load_state` (Fact 5) for state initialization. It is NOT reproduced on outbound (Fact 8). This means context is visible to the LLM during processing but invisible to the response channel. Any channel-specific metadata should not rely on context propagation.
**References:** Fact 5, Fact 6, Fact 8
