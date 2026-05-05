# Change Plan: bub_events Channel (v2 — HTTP)

## Facts

1. Bub channels implement the `Channel` ABC with `start()`, `stop()`, `send()`, and optional `stream_events()` (`bub/src/bub/channels/base.py:11-40`).
2. Channels are registered via the `provide_channels` hook spec, which returns a list of `Channel` instances (`bub/src/bub/hookspecs.py:101-104`).
3. The builtin `provide_channels` returns `TelegramChannel` and `CliChannel` (`bub/src/bub/builtin/hook_impl.py:260-268`).
4. `ChannelMessage` has fields: `session_id`, `channel`, `content`, `chat_id`, `is_active`, `kind`, `context`, `media`, `lifespan`, `output_channel` (`bub/src/bub/channels/message.py:33-51`).
5. Framework resolves session from `session_id` or falls back to `{channel}:{chat_id}` (`bub/src/bub/builtin/hook_impl.py:106-112`).
6. Pydantic is used for settings (`pydantic_settings.BaseSettings`) and tool inputs (`pydantic.BaseModel`) (`bub/src/bub/channels/telegram.py:25-39`, `bub/src/bub/builtin/tools.py:41-65`).
7. The `gateway` command starts all enabled channels via `ChannelManager` (`bub/src/bub/builtin/cli.py:76-86`).
8. `Channel.needs_debounce` controls whether the channel manager applies debouncing (`bub/src/bub/channels/base.py:25-27`).
9. Telegram and CLI channels already mix sync/async — Telegram uses `python-telegram-bot` (sync in async context), CLI uses `prompt_toolkit`.

## Design

### Subproject: `bub_events/`

```
bub_events/
├── pyproject.toml          # Entry point: [project.entry-points.bub] events = "bub_events.hook:EventsHookImpl"
├── src/bub_events/
│   ├── __init__.py
│   ├── hook.py             # Hook implementation
│   ├── channel.py          # EventsChannel (Flask + threading)
│   ├── message.py          # Pydantic models for JSON validation
│   └── settings.py         # Pydantic settings
└── tests/
```

### Pydantic Message Model

```python
class EventMessage(BaseModel):
    content: str = Field(..., description="Message content or command")
    session_id: str | None = Field(None, description="Optional session override")
    chat_id: str = Field("default", description="Chat identifier")
    sender: str = Field("unknown", description="Event sender provenance")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    kind: Literal["normal", "command"] = Field("normal", description="Message kind")
```

### Channel Design (HTTP)

**Transport:** Flask app running in a background thread. Single endpoint:

```python
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1MB — Flask/Werkzeug enforces this automatically

@app.route("/event", methods=["POST"])
def post_event():
    payload = request.get_json()
    msg = EventMessage.model_validate(payload)
    channel_msg = ChannelMessage(
        session_id=msg.session_id or f"bub_events:{msg.chat_id}",
        channel="bub_events",
        chat_id=msg.chat_id,
        content=msg.content,
        kind=msg.kind,
        context={"sender": msg.sender, **msg.meta},
    )
    # Bridge sync Flask to async handler
    asyncio.run_coroutine_threadsafe(
        self._on_receive(channel_msg), self._loop
    )
    return {"status": "ok"}
```

**Threading model:** `start()` spawns a daemon thread running `app.run()`. `stop()` sets a shutdown flag and joins the thread.

**Session handling:** `session_id` defaults to `f"bub_events:{chat_id}"` if not provided.

**Graceful shutdown:** `stop()` calls `werkzeug.server.shutdown` or simply stops the thread.

**Authentication (optional):** `Authorization: Bearer <token>` header, validated in a `before_request` handler against a configured secret.

### Hook Implementation

```python
class EventsHookImpl:
    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework
        self._settings = ensure_config(EventsSettings)

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
        from bub_events.channel import EventsChannel
        return [EventsChannel(on_receive=message_handler, settings=self._settings)]
```

### Settings

```python
class EventsSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="BUB_EVENTS_", extra="ignore")

    host: str = Field(default="127.0.0.1", description="Bind address")
    port: int = Field(default=9123, description="Listen port")
    auth_token: str | None = Field(default=None, description="Optional Bearer token for authentication")
```

### CLI Considerations

No new CLI commands needed. The channel is started automatically by `bub gateway` if the plugin is installed.

### Error Handling

- Payload too large (> MAX_CONTENT_LENGTH): Werkzeug automatically returns **HTTP 413** — no code needed
- Invalid JSON: return HTTP 400 with error details
- Pydantic validation error: return HTTP 422 with validation errors
- Missing auth: return HTTP 401
- Framework dispatch failure: return HTTP 500

## Why It Works

1. **Follows existing patterns:** `EventsChannel` mirrors `TelegramChannel` structure.
2. **Hook integration:** `provide_channels` is the canonical extension point.
3. **Pydantic validation:** Reuses Bub's existing validation infrastructure.
4. **Standard HTTP:** No custom protocol. Test with `curl`. Deploy behind nginx.
5. **Threading is OK:** Telegram channel already runs sync code in async context.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/pyproject.toml` | Create | Subproject config with entry point |
| `bub_events/src/bub_events/__init__.py` | Create | Package init |
| `bub_events/src/bub_events/settings.py` | Create | Pydantic settings |
| `bub_events/src/bub_events/message.py` | Create | Pydantic message model |
| `bub_events/src/bub_events/channel.py` | Create | `EventsChannel` Flask app |
| `bub_events/src/bub_events/hook.py` | Create | Hook implementation |
| `bub_events/tests/test_message.py` | Create | Message validation tests |
| `bub_events/tests/test_channel.py` | Create | Channel endpoint tests |

## Open Questions

- Should responses be synchronous (wait for turn completion) or fire-and-forget?
- Should we support WebSocket for streaming responses?
- Should there be a `GET /health` endpoint for monitoring?
