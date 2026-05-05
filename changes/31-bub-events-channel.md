# Change Plan: bub_events Channel

## Facts

1. Bub channels implement the `Channel` ABC with `start()`, `stop()`, `send()`, and optional `stream_events()` (`bub/src/bub/channels/base.py:11-40`).
2. Channels are registered via the `provide_channels` hook spec, which returns a list of `Channel` instances (`bub/src/bub/hookspecs.py:101-104`).
3. The builtin `provide_channels` returns `TelegramChannel` and `CliChannel` (`bub/src/bub/builtin/hook_impl.py:260-268`).
4. `ChannelMessage` has fields: `session_id`, `channel`, `content`, `chat_id`, `is_active`, `kind`, `context`, `media`, `lifespan`, `output_channel` (`bub/src/bub/channels/message.py:33-51`).
5. Framework resolves session from `session_id` or falls back to `{channel}:{chat_id}` (`bub/src/bub/builtin/hook_impl.py:106-112`).
6. Pydantic is used for settings (`pydantic_settings.BaseSettings`) and tool inputs (`pydantic.BaseModel`) (`bub/src/bub/channels/telegram.py:25-39`, `bub/src/bub/builtin/tools.py:41-65`).
7. The `gateway` command starts all enabled channels via `ChannelManager` (`bub/src/bub/builtin/cli.py:76-86`).
8. `Channel.needs_debounce` controls whether the channel manager applies debouncing (`bub/src/bub/channels/base.py:25-27`).

## Design

### Subproject: `bub_events/`

New workspace subproject with its own `pyproject.toml`, structured like `bub_sf/`.

```
bub_events/
├── pyproject.toml          # Entry point: [project.entry-points.bub] events = "bub_events.hook:EventsHookImpl"
├── src/bub_events/
│   ├── __init__.py
│   ├── hook.py             # Hook implementation
│   ├── channel.py          # EventsChannel class
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

### Channel Design

**Transport:** TCP socket server. Each connection reads one JSON object (length-prefixed or newline-delimited), validates it, creates a `ChannelMessage`, and dispatches it.

**Length guard:** First 4 bytes = uint32BE payload length, then JSON payload. Max length = 1MB.

**Bidirectional:** The channel implements `send()` to write responses back to the same TCP connection. For request-response, we can use a simple framing protocol. For fire-and-forget, the connection closes after dispatch.

**Session handling:** `session_id` defaults to `f"bub_events:{chat_id}"` if not provided.

**Graceful shutdown:** `start()` creates an asyncio server. `stop()` closes the server and all active connections.

**mDNS:** Advertise `_bub_events._tcp.local` using `zeroconf` library (optional, enabled by config).

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
    max_message_size: int = Field(default=1024*1024, description="Max message size in bytes")
    mdns_enabled: bool = Field(default=False, description="Advertise via mDNS")
```

### CLI Considerations

No new CLI commands needed. The channel is started automatically by `bub gateway` if the plugin is installed.

### Error Handling

- Invalid JSON: close connection, log warning
- Pydantic validation error: send error response (if bidirectional), then close
- Oversized message: close connection immediately

## Why It Works

1. **Follows existing patterns:** `EventsChannel` mirrors `TelegramChannel` and `CliChannel` structure.
2. **Hook integration:** `provide_channels` is the canonical extension point.
3. **Pydantic validation:** Reuses Bub's existing validation infrastructure.
4. **Length guard:** Prevents DoS via oversized payloads.
5. **mDNS optional:** Does not add hard dependency; only activates if configured.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/pyproject.toml` | Create | Subproject config with entry point |
| `bub_events/src/bub_events/__init__.py` | Create | Package init |
| `bub_events/src/bub_events/settings.py` | Create | Pydantic settings |
| `bub_events/src/bub_events/message.py` | Create | Pydantic message model |
| `bub_events/src/bub_events/channel.py` | Create | `EventsChannel` TCP server |
| `bub_events/src/bub_events/hook.py` | Create | Hook implementation |
| `bub_events/tests/test_message.py` | Create | Message validation tests |
| `bub_events/tests/test_channel.py` | Create | Channel protocol tests |

## Open Questions

- Should we use JSON-RPC for bidirectional, or simple request-response framing?
- Should responses be sent synchronously (wait for turn completion) or asynchronously (fire-and-forget)?
- Should the channel support WebSocket as an alternative transport?
