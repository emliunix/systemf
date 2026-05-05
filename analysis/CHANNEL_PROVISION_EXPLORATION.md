# Exploration: How to Provide a Channel in Bub

## Notes

### Note 1: Goal
Understand the channel registration mechanism to implement a new `bub_events` channel.

## Facts

### Fact 1: Channel Base Class
`bub/src/bub/channels/base.py:11-40`
```python
class Channel(ABC):
    name: ClassVar[str] = "base"

    @abstractmethod
    async def start(self, stop_event: asyncio.Event) -> None:
        """Start listening for events and dispatching to handlers."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""

    @property
    def needs_debounce(self) -> bool:
        return False

    @property
    def enabled(self) -> bool:
        return True

    async def send(self, message: ChannelMessage) -> None:
        return

    def stream_events(self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]) -> AsyncIterable[StreamEvent]:
        return stream
```

### Fact 2: Channel Registration via Hook
`bub/src/bub/hookspecs.py:101-104`
```python
@hookspec
def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
    """Provide a list of channels for receiving messages."""
```

### Fact 3: Builtin Implementation Provides Channels
`bub/src/bub/builtin/hook_impl.py:260-268`
```python
@hookimpl
def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
    from bub.channels.cli import CliChannel
    from bub.channels.telegram import TelegramChannel

    return [
        TelegramChannel(on_receive=message_handler),
        CliChannel(on_receive=message_handler, agent=self._get_agent()),
    ]
```

### Fact 4: Channel Manager Starts Channels
`bub/src/bub/channels/manager.py:142-162`
```python
async def listen_and_run(self) -> None:
    stop_event = asyncio.Event()
    self.framework.bind_outbound_router(self)
    for channel in self.enabled_channels():
        await channel.start(stop_event)
    ...
    finally:
        self.framework.bind_outbound_router(None)
        await self.shutdown()
```

### Fact 5: Gateway Command Starts Channel Manager
`bub/src/bub/builtin/cli.py:76-86`
```python
def gateway(ctx: typer.Context, enable_channels: list[str] = typer.Option([], "--enable-channel", ...)) -> None:
    from bub.channels.manager import ChannelManager
    framework = ctx.ensure_object(BubFramework)
    manager = ChannelManager(framework, enabled_channels=enable_channels or None)
    asyncio.run(manager.listen_and_run())
```

## Claims

### Claim 1: New Channel Requires Three Components
1. **Channel class**: Implements `Channel` base class
2. **Hook implementation**: `provide_channels` returns the channel instance
3. **Settings** (optional): Pydantic `Settings` subclass for configuration

**References:** Fact 1, Fact 2, Fact 3

### Claim 2: Channel is Started by `bub gateway`
The `gateway` command creates a `ChannelManager` which calls `channel.start(stop_event)` for all enabled channels.

**References:** Fact 4, Fact 5

### Claim 3: `stop_event` is Used for Graceful Shutdown
Channels should listen to the `stop_event` asyncio.Event to know when to stop polling/accepting connections.

**References:** Fact 4

### Claim 4: `enabled` Property Controls Channel Activation
If `enabled` returns `False`, the channel manager skips starting it. This is useful for disabling when configuration is missing.

**References:** Fact 1, Fact 4
