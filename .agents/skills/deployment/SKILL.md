---
name: deployment
description: Production deployment commands for managing Bub components as systemd user services
---

# Production Deployment

Systemd-based production deployment script for managing Bub components as user services.

## Quick Start

```bash
# Check what's running
./scripts/deploy-production.sh list

# View logs
./scripts/deploy-production.sh logs agent  # or bus, tape

# Start components
./scripts/deploy-production.sh start bus      # Start message bus
./scripts/deploy-production.sh start agent    # Start agent worker
./scripts/deploy-production.sh start tape     # Start tape service
```

## Components

| Component | Description | Port |
|-----------|-------------|------|
| `bus` | WebSocket message bus server - routes messages between all components | 7892 |
| `agent` | Agent worker process - handles LLM interactions and tool execution | - |
| `tape` | Tape store REST API - persistent append-only conversation storage | 7890 |
| `telegram-bridge` | Telegram Bot API bridge - connects Telegram to the bus as JSON-RPC client | - |

See `docs/components.md` for detailed component documentation.

## Commands

Pattern: `./scripts/deploy-production.sh <action> <component>`

**Actions:** `start`, `stop`, `logs`, `status`
**Components:** `bus`, `agent`, `tape`, `telegram-bridge`, `all` (virtual - logs/stop only)

```bash
# Examples
./scripts/deploy-production.sh start bus              # Start message bus
./scripts/deploy-production.sh logs agent             # Follow agent logs
./scripts/deploy-production.sh logs all               # Follow logs from ALL components
./scripts/deploy-production.sh stop tape              # Stop tape service
./scripts/deploy-production.sh stop all               # Stop ALL running components
./scripts/deploy-production.sh status telegram-bridge # Check bridge status
./scripts/deploy-production.sh list                   # List all running components
```

### Virtual Component: `all`

Use `all` as a virtual component to operate on all running components at once:

```bash
# View logs from all components (merged chronologically)
./scripts/deploy-production.sh logs all
./scripts/deploy-production.sh logs all --since "10 minutes ago"

# Stop all running components
./scripts/deploy-production.sh stop all
```

## Features

- Uses `systemd-run` for process management with automatic cleanup
- **Auto-restart on failure** (`Restart=always`) with 5-second delay
- **Rate limiting**: Max 3 restarts per minute to prevent restart loops
- Persists unit names in `run/` directory for lifecycle management
- Integrates with `journalctl` for centralized logging
- Sets proper working directory and environment variables

## Restart Behavior

- Services automatically restart if they crash or exit with error
- 5-second delay between restart attempts
- After 3 failed restarts within 1 minute, systemd stops trying
- Check restart count: `systemctl --user show <unit> | grep NRestarts`

## Documentation Server

MkDocs documentation server with live reload via systemd.

```bash
./scripts/docs-server.sh start [port]   # Start on port (default: 8000)
./scripts/docs-server.sh stop           # Stop server
./scripts/docs-server.sh status         # Check status
./scripts/docs-server.sh logs           # View logs
```
