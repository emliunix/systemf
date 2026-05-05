# Change Plan: bub_events Bidirectional Request-Response Channel

## Facts

1. `EventsChannel` (`bub_events/src/bub_events/channel.py:23-96`) currently implements fire-and-forget semantics. `POST /event` calls `on_receive` and returns `{"status": "ok"}` immediately.
2. `Channel.send()` (`bub/src/bub/channels/base.py:34-37`) is a no-op by default. The framework calls it to dispatch outbound messages to the originating channel.
3. `EventsSettings` (`bub_events/src/bub_events/settings.py:7-12`) currently has `host`, `port`, `auth_token`. No timeout configuration exists.
4. `EventsChannel.stop()` (`bub_events/src/bub_events/channel.py:92-96`) shuts down the uvicorn server but does not cancel pending response futures.
5. Exploration `analysis/BUB_EVENTS_LINKING_EXPLORATION.md` establishes that `session_id` is the only field that survives the framework round-trip without modifying `bub/`.

## Design

### Session ID Linking Mechanism

```python
class EventsChannel(Channel):
    def __init__(self, ...):
        ...
        self._pending: dict[str, asyncio.Future[str]] = {}
    
    async def send(self, message: ChannelMessage) -> None:
        request_id = message.session_id
        if request_id in self._pending:
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
            session_id=request_id,  # Unique per request
            channel="bub_events",
            chat_id=msg.chat_id,
            content=msg.content,
            kind=msg.kind,
            context={"sender": msg.sender, **msg.meta},
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
            raise
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

### API Change

Removed `session_id` from `EventMessage`. Users should not pass session IDs — HTTP request-response is naturally paired. State identifiers go in `meta`.

## Why It Works

1. **session_id propagation:** `resolve_session` reads inbound `session_id`. `render_outbound` passes it to outbound. `dispatch_output` copies it to `channel.send()`. No `bub/` modifications needed.
2. **Request isolation:** Each HTTP request gets a unique UUID `session_id`. The framework treats each as a separate session, ensuring no cross-request state pollution.
3. **Timeout prevents leaks:** `asyncio.wait_for` with cleanup in `finally`.
4. **Race safety:** `try/except InvalidStateError` in `send()` handles race between timeout and response.
5. **No hooks needed:** All logic is contained within `EventsChannel`.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/message.py` | Modify | Remove `session_id` field |
| `bub_events/src/bub_events/settings.py` | Modify | Add `response_timeout` field |
| `bub_events/src/bub_events/channel.py` | Modify | Add `_pending` dict, override `send()`, implement linking |
| `bub_events/tests/test_message.py` | Modify | Remove `session_id` tests |
| `bub_events/tests/test_channel.py` | Modify | Add tests for bidirectional response, timeout, shutdown |

## Test Plan

1. **test_post_event_success**: Request with no outbound returns timeout.
2. **test_response_linking**: Mock handler calls `channel.send()` with matching `session_id`. Verify HTTP response contains outbound content.
3. **test_response_timeout**: Mock handler sleeps longer than timeout. Verify HTTP response returns `{"status": "timeout"}`.
4. **test_shutdown_cancels_pending**: Start request, signal stop before response. Verify future is cancelled.
5. **test_send_race_safety**: Verify `send()` handles already-resolved futures gracefully.
6. **test_send_ignores_unknown_session**: Verify `send()` ignores messages with unknown `session_id`.
7. **test_post_event_with_metadata**: Verify `meta` fields end up in `context`.
