# bub_sf

Extending **Bub** into a powerful agent platform.

**bub_sf** integrates SystemF to provide a scripting layer for organizing async tool calls, and leverages the **tape** primitive to structure agent thinking steps and subagent invocations.

## Architecture

bub_sf is a single-instance system. The core components sit at the same level — the AllInOne channel and the agents are peers. "Agent family" is a classification for the agent components, not a layer above them.

```
External World
       │
       ▼
┌──────────────┐
│ AllInOne     │  ← Sole channel. Receives all external
│   Channel    │    messages and events.
│              │
│ ┌──────────┐ │
│ │ Event    │ │  ← System components (scheduler, mail,
│ │  Queue   │ │    sensors) post events here.
│ └──────────┘ │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Master Agent │  ← Root of the agent family. Owns one
│ (REPLSession)│    REPLSession, maintains focus.
└──────┬───────┘
       │
   ┌───┴───┐
   ▼       ▼
┌─────┐ ┌─────┐
│Sub 1│ │Sub 2│  ← Subagents spawned via SystemF
│ ... │ │ ... │    function calls. Each gets own
└─────┘ └─────┘    REPLSession. No channel access.
```

### Components

- **AllInOne Channel** — The only channel connected to the agent family. Receives all external messages and events. No other channel talks to any agent. Contains an internal event queue where system components post events for delivery to the master agent.

- **Scheduler** — Emits timed events into AllInOne's event queue. Configuration is exposed as SystemF primitives so the master agent can manage its own schedule.

- **SystemF REPL** (`REPLSession`) — The base scripting tool. Each agent (master or subagent) owns one `REPLSession` with its own state and focus. `bub_ext` manages sessions via Bub hooks and shares a single `REPLContext`.

- **Master Agent** — The root of the agent family. Receives all input from AllInOne. Maintains exclusive focus on the current problem and delegates to subagents via SystemF function calls.

- **Subagent Calls** — Spawned via SystemF functions. Each subagent gets its own `REPLSession` and focus. Subagents do not connect to AllInOne or any channel; they communicate strictly through return values. This lets the master define typed, persistent agent tasks with complex control flow.

### Agent Model

The master agent is a single orchestrator. It constructs focused context and workflow (persisted as SystemF code, reusable, and self-evolvable by editing its own thinking code) to solve problems. Subagents are computational children, not independent message receivers. The entire instance operates as one unit.

### Async Pattern

- **Async Primitive (`Async a`)** — A SystemF type that wraps Python async values. `async_get :: Async a -> Maybe a` lets agent code poll async results.

- **Local Notification (`async_notifyme`)** — `async_notifyme :: Async a -> IO ()` registers the async in the agent's local wait list. When the agent is idle, the wait list is checked and the agent is notified to take another turn. This keeps async tracking local to the focal point — a subagent's asyncs stay in the subagent's wait list, not the master's.

Background tasks run in Python, wrapped as `Async a`. The flow:

1. The agent calls `async_notifyme task` before returning to idle.
2. On idle, the `REPLSession` checks its wait list.
3. When the task resolves, the agent is notified to start a new turn.
4. The agent calls `async_get task` to retrieve `Just result`.

## Notification Channel

**NOTE**: this section is old, should be removed, keep it for now cause the code structure can be reused.

bub_sf provides a `notification` channel for async events to communicate with the main agent.

### How it works

The notification channel is an internal async message queue. Background tasks or async events can post messages to the queue, which get delivered as inbound messages to the main agent.

### Usage

```python
from bub_sf.channels.notification import get_notification_channel

# Post a notification from anywhere
channel = get_notification_channel()
if channel:
    await channel.post_notification("Background task completed: 42 items processed")
```

Or if you have access to the channel instance:

```python
from bub_sf.channels.notification import NotificationChannel

# Get the notification channel from the framework
channel = framework.get_channels(...)["notification"]

# Post a notification
await channel.post_notification("Background task completed: 42 items processed")
```

### Characteristics

- **Session ID**: `notification:{chat_id}` (default: `notification:internal`)
- **No debounce**: Notifications are delivered immediately
- **No outbound**: The channel only receives notifications, doesn't send responses
- **Main agent responsibility**: The main agent handles notification messages like any other inbound message

### Example: Tool posting notification

```python
@tool(name="long_task")
async def long_task(*, context: ToolContext) -> str:
    # Start background work
    task = asyncio.create_task(do_work())
    
    # Post notification when done
    async def notify():
        result = await task
        channel = context.state.get("notification_channel")
        if channel:
            await channel.post_notification(f"Task complete: {result}")
    
    asyncio.create_task(notify())
    return "Task started in background"
```

## Running

**NOTE**: this won't work output to cli channel dropped in gateway mode

```bash
# Start with CLI and notification channels
bub-sf gateway --enable-channel cli --enable-channel notification

# Or set via environment
export BUB_ENABLED_CHANNELS=cli,notification
bub-sf gateway
```
