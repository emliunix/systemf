---
name: bus-cli
description: WebSocket Message Bus CLI commands for managing the Bub message bus server and sending/receiving messages
---

# Bus CLI Commands

The `bub bus` subcommand provides utilities for interacting with the WebSocket message bus.

## Quick Start

```bash
# Start the bus server (pure message router)
uv run bub bus serve

# Send a message to a topic and wait for responses
uv run bub bus send "hello world" --channel telegram --chat-id 123456

# Subscribe to a topic pattern and print messages (planned)
uv run bub bus recv --topic "telegram:*"
```

## Architecture

All components (agent, telegram-bridge, CLI tools) connect to the bus as JSON-RPC clients. The bus server is a pure message router with no embedded channel logic.

**Telegram Integration**: Telegram is being extracted from the bus server into a standalone bridge process (`bub telegram-bridge` or similar) that connects to wsbus as a proper JSON-RPC client. The bridge handles:
- Telegram Bot API communication
- Message format conversion (Telegram JSON ↔ Bus JSON-RPC)
- Inbound message publishing to the bus
- Outbound message handling from the bus

## Common Commands

| Command | Description |
|---------|-------------|
| `bub bus serve` | Start the WebSocket message bus server |
| `bub bus send <message>` | Send a message to a topic |
| `bub bus recv --topic <pattern>` | Subscribe to topic pattern (planned) |

## Default Configuration

- **Port**: 7892
- **Host**: localhost
- **Protocol**: JSON-RPC 2.0 over WebSocket

## Testing

```bash
# Test bus connectivity
uv run python scripts/test_bus_client.py "test message"
```
