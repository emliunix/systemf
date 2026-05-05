# Exploration: Channel Message Fields and Framework Usage

## Notes

### Note 1: Goal
Understand the `ChannelMessage` fields and which ones have special meaning in the framework.

## Facts

### Fact 1: ChannelMessage Dataclass
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

    def __post_init__(self) -> None:
        self.context.update({"channel": "$" + self.channel, "chat_id": self.chat_id})
        if not self.output_channel:
            self.output_channel = self.channel
```

### Fact 2: Framework Uses These Fields
`bub/src/bub/builtin/hook_impl.py:106-112`
```python
@hookimpl
def resolve_session(self, message: ChannelMessage) -> str:
    session_id = field_of(message, "session_id")
    if session_id is not None and str(session_id).strip():
        return str(session_id)
    channel = str(field_of(message, "channel", "default"))
    chat_id = str(field_of(message, "chat_id", "default"))
    return f"{channel}:{chat_id}"
```

### Fact 3: Context is Used in Prompt Building
`bub/src/bub/builtin/hook_impl.py:132-140`
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
```

### Fact 4: Special Field Meanings
- `session_id`: Identifies the conversation session. Framework resolves session from this.
- `channel`: Channel name (e.g., "telegram", "cli"). Used for routing and context.
- `chat_id`: Sub-identifier within a channel (e.g., Telegram chat ID). Used with channel for session resolution.
- `content`: The actual message text. Framework uses this as the prompt.
- `kind`: "normal", "command", or "error". Framework treats "command" specially (`,`-prefixed).
- `context`: Extra metadata passed through. `context_str` property formats it for prompts.
- `output_channel`: Where to send replies. Defaults to same channel.
- `lifespan`: Async context manager for resource cleanup (e.g., typing indicators).
- `is_active`: Whether the message should trigger active processing.

**References:** Fact 1, Fact 2, Fact 3

## Claims

### Claim 1: Minimal Required Fields for Inbound Messages
For a socket channel, the minimal required fields are:
- `session_id` (or let framework resolve from channel+chat_id)
- `channel` (fixed to "bub_events")
- `content` (the event payload)
- `chat_id` (optional, default "default")

**References:** Fact 1, Fact 2

### Claim 2: Provenance Should Go in `context`
Sender information, timestamps, and event provenance should be placed in the `context` dict, which the framework passes through to state and prompt building.

**References:** Fact 1, Fact 3

### Claim 3: `kind="command"` Has Special Framework Behavior
If `content` starts with `,`, the framework sets `kind="command"` and routes it through command handling instead of the agent loop.

**References:** Fact 3
