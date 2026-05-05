# Change Plan: bub_events Bidirectional Request-Response Channel (v4)

## Facts

1. `EventsChannel` (`bub_events/src/bub_events/channel.py:23-128`) implements bidirectional request-response using `session_id` as the linking key.
2. `Channel.send()` (`bub/src/bub/channels/base.py:34-37`) receives outbound `ChannelMessage` from the framework.
3. `EventsSettings` (`bub_events/src/bub_events/settings.py:7-15`) has `host`, `port`, `auth_token`, and `response_timeout`.
4. `EventMessage` (`bub_events/src/bub_events/message.py:6-11`) has `content`, `chat_id`, `sender`, `meta`, `kind`. No `session_id` field.
5. Exploration `analysis/BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md` establishes that `session_id` is the only framework-managed field that is both consumed (by `resolve_session`, `load_state`) and reproduced (by `render_outbound`) on the outbound path.
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
            try:
                future.set_result(message.content)
            except asyncio.InvalidStateError:
                pass
```

### Key Design Decisions

**No `done()` check in `send()`:** `set_result()` on an already-resolved future raises `InvalidStateError`. The `try/except` handles this naturally, making an explicit `done()` check redundant.

**No `session_id` in API:** HTTP request-response is naturally paired. Users do not pass correlation IDs. The UUID is an internal implementation detail.

**Context carries metadata:** `sender` and `meta` fields are placed in `context` for LLM visibility during the turn. Context is not propagated to outbound (per framework behavior), but this is acceptable since linking uses `session_id`.

**`send()` is the explicit completion signal:** The framework calls `channel.send()` for each outbound message. This resolves the pending future and completes the HTTP request. We do NOT use `lifespan.__aexit__` or any other mechanism as a fallback completion signal. If `send()` is never called (e.g., agent produces no output), the request times out — this is correct behavior for event processing.

**No `lifespan` on inbound:** The channel does not set `lifespan` on inbound messages. The `lifespan` field is reserved for channel-framework resource contracts (typing indicators, etc.) and is not used for request completion signaling.

### Graceful Shutdown

```python
async def stop(self) -> None:
    for future in list(self._pending.values()):
        if not future.done():
            future.cancel()
    self._pending.clear()
    # ... uvicorn shutdown
```

### Prompt Building Extension: Event Types

**Goal:** Allow contextual prompts based on event type and topic.

**API Extension:** Add optional fields to `EventMessage`:
```python
class EventMessage(BaseModel):
    ...
    event_type: str = Field("default", description="Event type for prompt selection")
    event_topic: str = Field("", description="Event topic or sub-type")
```

**Convention:** `{workspace}/event_prompt/` directory contains `<event_type>.md` files.
- If `event_type="alert"` and `{workspace}/event_prompt/alert.md` exists, its contents are added to context
- If file does not exist, fall back to default prompt building
- `event_topic` is added to `context` for prompt variable substitution

**Note on workspace:** `BubFramework.workspace` is a core bub concept (`bub/src/bub/framework.py:42`). It defaults to `Path.cwd()` but can be overridden via `--workspace` CLI flag. It is passed through `state["_runtime_workspace"]` and used throughout the framework for skill discovery, file resolution, and tape naming. The `event_prompt/` directory follows this same convention.

**Integration:** The channel loads the prompt file in `_handle_request` and injects it into `context`:
```python
context = {"sender": msg.sender, "event_topic": msg.event_topic, **msg.meta}
if prompt_extension := self._load_event_prompt(msg.event_type):
    context["event_prompt"] = prompt_extension
```

`build_prompt` hook (existing) reads `context_str` which includes these keys. The LLM sees the extended context.

### API Format Extension: text/plain

**Goal:** Support simple integrations that send plain text instead of JSON.

**Endpoint:** `POST /event` accepts `Content-Type: text/plain`

**Headers carry metadata:**
```
Content-Type: text/plain
X-Bub-Chat-Id: room1
X-Bub-Sender: cron
X-Bub-Event-Type: alert
X-Bub-Event-Topic: disk-full
```

**Body:** Raw text content (becomes `msg.content`)

**Fallback:** If `Content-Type` is missing or not `application/json`, treat as `text/plain`.

**Why headers:** For simple curl commands and webhook integrations, passing metadata in headers is more ergonomic than constructing JSON.

## Why It Works

1. **session_id propagation:** Per `BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md`, `session_id` is the only framework field that is both consumed by hooks (`resolve_session`, `load_state`) and reproduced on outbound (`render_outbound`). No `bub/` modifications needed.
2. **Request isolation:** Each HTTP request gets a unique UUID. The framework treats each as a separate session (per `session_id` semantics).
3. **Timeout:** `asyncio.wait_for` prevents indefinite hangs.
4. **Race safety:** `try/except InvalidStateError` handles all race conditions between timeout and response.
5. **No hooks:** All logic is self-contained in `EventsChannel`.
6. **Prompt extension uses existing mechanism:** `build_prompt` already reads `context_str`. Adding event metadata to `context` requires no framework changes.
7. **text/plain is additive:** The endpoint checks `Content-Type` and falls back to JSON parsing. Existing JSON clients are unaffected.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/message.py` | Modify | Remove `session_id` field, add `event_type` and `event_topic` |
| `bub_events/src/bub_events/settings.py` | Modify | Add `response_timeout` field |
| `bub_events/src/bub_events/channel.py` | Modify | Implement session_id linking, event prompt loading, text/plain support |
| `bub_events/tests/test_message.py` | Modify | Update tests for new schema |
| `bub_events/tests/test_channel.py` | Modify | Add bidirectional response tests, event type tests, text/plain tests |

## Test Plan

### Core Tests
1. **test_post_event_success**: Request with no outbound returns timeout.
2. **test_response_linking**: Mock handler calls `channel.send()` with matching `session_id`. Verify HTTP response contains content.
3. **test_response_timeout**: Mock handler sleeps longer than timeout. Verify `{"status": "timeout"}`.
4. **test_shutdown_cancels_pending**: Signal stop with pending futures. Verify cancellation.
5. **test_send_race_safety**: Verify `send()` handles already-resolved futures via `InvalidStateError`.
6. **test_send_ignores_unknown_session**: Verify `send()` ignores unknown `session_id`.
7. **test_post_event_with_metadata**: Verify `meta` fields end up in `context`.
8. **test_auth_silent_when_not_configured**: Verify no auth required when `auth_token=None`.
9. **test_auth_token_valid/invalid/missing**: Verify Bearer token enforcement.

### Event Type Tests
10. **test_event_type_prompt_loading**: Verify `event_prompt/alert.md` is loaded and added to context.
11. **test_event_type_prompt_missing**: Verify graceful fallback when prompt file does not exist.
12. **test_event_topic_in_context**: Verify `event_topic` appears in context for LLM.

### Text/Plain Tests
13. **test_post_text_plain**: Verify `POST /event` with `Content-Type: text/plain` and headers works.
14. **test_post_text_plain_no_headers**: Verify default values used when headers are missing.
15. **test_post_fallback_to_json**: Verify JSON requests still work when `Content-Type: application/json`.
