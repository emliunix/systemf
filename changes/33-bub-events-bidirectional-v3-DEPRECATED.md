# Change Plan: bub_events Bidirectional Request-Response Channel (v3)

## Facts

1. `EventsChannel` (`bub_events/src/bub_events/channel.py:23-128`) implements bidirectional request-response using `session_id` as the linking key.
2. `Channel.send()` (`bub/src/bub/channels/base.py:34-37`) receives outbound `ChannelMessage` from the framework.
3. `EventsSettings` (`bub_events/src/bub_events/settings.py:7-15`) has `host`, `port`, `auth_token`, and `response_timeout`.
4. `EventMessage` (`bub_events/src/bub_events/message.py:6-11`) has `content`, `chat_id`, `sender`, `meta`, `kind`. No `session_id` field.
5. Exploration `analysis/BUB_EVENTS_LINKING_EXPLORATION.md` establishes that `session_id` is the only field that survives the framework round-trip without modifying `bub/`.
6. The channel uses FastAPI + uvicorn for the HTTP server, with `POST /event` and `GET /health` endpoints.
7. Auth is optional via Bearer token; when `auth_token` is `None`, no auth is enforced.
8. 19/19 tests pass covering: auth, validation, response linking, timeout, shutdown, race safety.

## Design

### Core Mechanism: session_id Linking

Each HTTP request generates a UUID `session_id`. This UUID is:
- Set as `session_id` on the inbound `ChannelMessage`
- Propagated by the framework through `render_outbound` to the outbound message
- Received by `channel.send()` as `message.session_id`
- Used to look up and resolve the pending `asyncio.Future`

```python
class EventsChannel(Channel):
    def __init__(self, ...):
        self._pending: dict[str, asyncio.Future[str]] = {}
    
    async def _handle_request(self, msg: EventMessage) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        
        channel_msg = ChannelMessage(
            session_id=request_id,  # Internal linking key
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
        finally:
            self._pending.pop(request_id, None)
    
    async def send(self, message: ChannelMessage) -> None:
        request_id = message.session_id
        if request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                try:
                    future.set_result(message.content)
                except asyncio.InvalidStateError:
                    pass
```

### Graceful Shutdown

```python
async def stop(self) -> None:
    for future in list(self._pending.values()):
        if not future.done():
            future.cancel()
    self._pending.clear()
    # ... uvicorn shutdown
```

## Why It Works

1. **session_id propagation:** The framework reads `session_id` from inbound, passes it through `render_outbound`, and delivers it to `send()`. No `bub/` modifications needed.
2. **Request isolation:** Each HTTP request gets a unique UUID. The framework treats each as a separate session.
3. **Timeout:** `asyncio.wait_for` prevents indefinite hangs.
4. **Race safety:** `try/except InvalidStateError` handles races between timeout and response.
5. **No hooks:** All logic is self-contained in `EventsChannel`.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/message.py` | Modify | Remove `session_id` field |
| `bub_events/src/bub_events/settings.py` | Modify | Add `response_timeout` field |
| `bub_events/src/bub_events/channel.py` | Modify | Implement session_id linking |
| `bub_events/tests/test_message.py` | Modify | Update tests for new schema |
| `bub_events/tests/test_channel.py` | Modify | Add bidirectional response tests |

## Test Plan

1. **test_post_event_success**: Request with no outbound returns timeout.
2. **test_response_linking**: Mock handler calls `channel.send()` with matching `session_id`. Verify HTTP response contains content.
3. **test_response_timeout**: Mock handler sleeps longer than timeout. Verify `{"status": "timeout"}`.
4. **test_shutdown_cancels_pending**: Signal stop with pending futures. Verify cancellation.
5. **test_send_race_safety**: Verify `send()` handles already-resolved futures.
6. **test_send_ignores_unknown_session**: Verify `send()` ignores unknown `session_id`.
7. **test_post_event_with_metadata**: Verify `meta` fields end up in `context`.
8. **test_auth_silent_when_not_configured**: Verify no auth required when `auth_token=None`.
9. **test_auth_token_valid/invalid/missing**: Verify Bearer token enforcement.
