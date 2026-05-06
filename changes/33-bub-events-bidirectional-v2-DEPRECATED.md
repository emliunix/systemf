# Change Plan: bub_events Bidirectional Request-Response Channel (v2)

## Facts

1. `EventsChannel` (`bub_events/src/bub_events/channel.py:23-96`) currently implements fire-and-forget semantics. `POST /event` calls `on_receive` and returns `{"status": "ok"}` immediately.
2. `Channel.send()` (`bub/src/bub/channels/base.py:34-37`) is a no-op by default. The framework calls it to dispatch outbound messages to the originating channel.
3. `ChannelMessage.context` (`bub/src/bub/channels/message.py:43`) is a `dict[str, Any]`.
4. `EventsSettings` (`bub_events/src/bub_events/settings.py:7-12`) currently has `host`, `port`, `auth_token`. No timeout configuration exists.
5. `EventsChannel.stop()` (`bub_events/src/bub_events/channel.py:92-96`) shuts down the uvicorn server but does not cancel pending response futures.
6. **Critical finding from review:** The builtin `render_outbound` (`bub/src/bub/builtin/hook_impl.py:290-306`) creates outbound `ChannelMessage` **without copying `context`** from the inbound message. This breaks request-response linking unless fixed.
7. The existing `test_render_outbound_preserves_message_metadata` (`bub/tests/test_builtin_hook_impl.py:253-270`) tests that channel/chat_id/output_channel/kind are preserved, but does not test context.

## Design

### Framework Fix: Propagate Context in render_outbound

```python
# bub/src/bub/builtin/hook_impl.py:290-306
@hookimpl
def render_outbound(
    self,
    message: Envelope,
    session_id: str,
    state: State,
    model_output: str,
) -> list[ChannelMessage]:
    outbound = ChannelMessage(
        session_id=session_id,
        channel=field_of(message, "channel", "default"),
        chat_id=field_of(message, "chat_id", "default"),
        content=model_output,
        output_channel=field_of(message, "output_channel", "default"),
        kind=field_of(message, "kind", "normal"),
        context=field_of(message, "context", {}) or {},  # <-- propagate context
    )
    return [outbound]
```

### Request-Response Linking Mechanism

```python
class EventsChannel(Channel):
    def __init__(self, ...):
        ...
        self._pending: dict[str, asyncio.Future[str]] = {}
    
    async def send(self, message: ChannelMessage) -> None:
        request_id = message.context.get("request_id")
        if request_id and request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                try:
                    future.set_result(message.content)
                except asyncio.InvalidStateError:
                    pass
    
    async def _handle_request(self, msg: EventMessage) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        
        channel_msg = ChannelMessage(
            ...
            context={"request_id": request_id, "sender": msg.sender, **msg.meta},
        )
        
        try:
            await self._on_receive(channel_msg)
            response = await asyncio.wait_for(
                future, timeout=self._settings.response_timeout
            )
            return {"status": "ok", "response": response}
        except asyncio.TimeoutError:
            return {"status": "timeout"}
        except asyncio.CancelledError:
            raise  # Let FastAPI handle cancellation during shutdown
        finally:
            self._pending.pop(request_id, None)
```

### Settings Addition

```python
class EventsSettings(Settings):
    ...
    response_timeout: float = Field(
        default=30.0, gt=0, description="Seconds to wait for outbound response"
    )
```

### Graceful Shutdown

```python
async def stop(self) -> None:
    for future in list(self._pending.values()):
        if not future.done():
            future.cancel()
    self._pending.clear()
    if self._server is not None:
        logger.info("EventsChannel stopping")
        await self._server.shutdown()
        self._server = None
```

## Why It Works

1. **Context propagation**: By adding `context=field_of(message, "context", {})` to `render_outbound`, the framework preserves channel-specific metadata from inbound to outbound.
2. **Request ID linking**: `request_id` placed in inbound context flows through to outbound, allowing `send()` to match and resolve the waiting future.
3. **Single-process**: `asyncio.Future` can be resolved directly from `send()` without IPC.
4. **Timeout prevents leaks**: `asyncio.wait_for` with cleanup in `finally`.
5. **Race safety**: `try/except InvalidStateError` in `send()` handles race between timeout and response.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub/src/bub/builtin/hook_impl.py` | Modify | Add `context=...` to `render_outbound` |
| `bub/tests/test_builtin_hook_impl.py` | Modify | Add context preservation assertion |
| `bub_events/src/bub_events/settings.py` | Modify | Add `response_timeout` field |
| `bub_events/src/bub_events/channel.py` | Modify | Add `_pending` dict, override `send()`, implement linking |
| `bub_events/tests/test_channel.py` | Modify | Add tests for bidirectional response, timeout, shutdown |

## Test Plan

1. **test_render_outbound_propagates_context**: Verify inbound context is copied to outbound.
2. **test_response_linking**: Mock handler that calls `channel.send()` with matching request_id. Verify HTTP response contains outbound content.
3. **test_response_timeout**: Mock handler that does nothing. Verify HTTP response returns `{"status": "timeout"}`.
4. **test_shutdown_cancels_pending**: Start request, signal stop before response. Verify future is cancelled.
5. **test_meta_request_id_collision**: Verify user-provided `meta["request_id"]` does not overwrite the generated UUID.
