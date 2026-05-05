# Exploration: Session ID Linking Design for Request-Response

## Notes

### Note 1: Scope
Design a request-response linking mechanism using `session_id` as the correlation key, without modifying `bub/`.

### Note 2: Prerequisite
This exploration assumes the findings of `./BUB_EVENTS_FIELD_PROPAGATION_EXPLORATION.md` (context is lost, session_id survives) and `./BUB_EVENTS_HOOK_MECHANISM_EXPLORATION.md` (hooks cannot solve the problem).

## Facts

### Fact 1: session_id Is Resolved from Inbound
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

### Fact 2: session_id Is Written to Outbound
`bub/src/bub/builtin/hook_impl.py:290-306`
```python
def render_outbound(self, message, session_id, state, model_output):
    outbound = ChannelMessage(
        session_id=session_id,  # Parameter from resolve_session
        ...
    )
```

### Fact 3: session_id Is Copied to send() Message
`bub/src/bub/channels/manager.py:96-104`
```python
outbound = ChannelMessage(
    session_id=str(field_of(message, "session_id", f"{channel_key}:default")),
    ...
)
await channel.send(outbound)
```

### Fact 4: ChannelManager.on_receive Creates Handler Per session_id
`bub/src/bub/channels/manager.py:63-81`
```python
async def on_receive(self, message: ChannelMessage) -> None:
    channel = message.channel
    session_id = message.session_id
    if session_id not in self._session_handlers:
        handler = ...
        self._session_handlers[session_id] = handler
    await self._session_handlers[session_id](message)
```

### Fact 5: EventMessage Has session_id Field
`bub_events/src/bub_events/message.py`
```python
class EventMessage(BaseModel):
    content: str
    session_id: str | None = None
    chat_id: str = "default"
    ...
```

### Fact 6: __post_init__ Adds Framework Keys to Context
`bub/src/bub/channels/message.py:48-51`
```python
def __post_init__(self) -> None:
    self.context.update({"channel": "$" + self.channel, "chat_id": self.chat_id})
    if not self.output_channel:
        self.output_channel = self.channel
```

## Claims

### Claim 1: session_id Naturally Survives the Full Round-Trip
**Reasoning:** `resolve_session` (Fact 1) reads `session_id` from inbound. `render_outbound` (Fact 2) receives this as a parameter and writes it to outbound. `dispatch_output` (Fact 3) copies it to the `ChannelMessage` passed to `channel.send()`. No modifications to `bub/` are needed because `session_id` is already fully propagated.
**References:** Fact 1, Fact 2, Fact 3

### Claim 2: Unique session_id Per Request Provides Isolation
**Reasoning:** `ChannelManager.on_receive` (Fact 4) creates a session handler per `session_id`. If each HTTP request uses a unique `session_id` (e.g., UUID), the framework treats each request as a separate session. State is loaded/saved per session, so requests do not interfere with each other. This matches HTTP request-response semantics where each request is independent.
**References:** Fact 4

### Claim 3: User-Provided session_id Should Be Preserved
**Reasoning:** If the user provides a `session_id` in their `EventMessage` (Fact 5), they may expect state persistence across requests. However, for request-response mode, using the user's session_id as the linking key would cause collisions for concurrent requests to the same session. The correct approach is: (1) generate a unique `session_id` for linking, (2) store the user-provided `session_id` in `context` under `user_session_id`, (3) the framework ignores `user_session_id` in context (Fact 6 only adds `channel` and `chat_id`), but it's available for custom hooks that need it.
**References:** Fact 5, Fact 6

### Claim 4: session_id-Based Linking Requires No Hooks
**Reasoning:** The linking mechanism is entirely contained within the `EventsChannel` class: (1) HTTP handler generates UUID, (2) stores `asyncio.Future` keyed by UUID, (3) creates `ChannelMessage` with `session_id=UUID`, (4) `send()` looks up future by `message.session_id`. No hook implementations are needed because `session_id` propagation is already handled by the framework.
**References:** Claim 1

### Claim 5: The Implementation Design
**Reasoning:** Based on Claims 1-4, the concrete implementation is:

```python
class EventsChannel(Channel):
    def __init__(self, ...):
        self._pending: dict[str, asyncio.Future[str]] = {}
    
    async def _handle_request(self, msg: EventMessage) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        
        channel_msg = ChannelMessage(
            session_id=request_id,  # Unique per request
            channel="bub_events",
            chat_id=msg.chat_id,
            content=msg.content,
            kind=msg.kind,
            context={
                "user_session_id": msg.session_id,
                "sender": msg.sender,
                **msg.meta,
            },
        )
        
        try:
            await self._on_receive(channel_msg)
            response = await asyncio.wait_for(
                future, timeout=self._settings.response_timeout
            )
            return {"status": "ok", "response": response}
        except asyncio.TimeoutError:
            return {"status": "timeout"}
        finally:
            self._pending.pop(request_id, None)
    
    async def send(self, message: ChannelMessage) -> None:
        request_id = message.session_id  # UUID from inbound
        if request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                try:
                    future.set_result(message.content)
                except asyncio.InvalidStateError:
                    pass
```

**References:** Claim 1, Claim 2, Claim 3, Claim 4

### Claim 6: Timeout and Shutdown Are Required for Robustness
**Reasoning:** Without timeout, a request would hang indefinitely if the framework never generates an outbound message. Without shutdown cleanup, pending futures would leak during channel stop. Both are standard requirements for request-response systems with async futures.
**References:** Claim 5
