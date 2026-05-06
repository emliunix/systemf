# Deployment Guide

## Sub-Projects

This workspace contains the following packages:
- `bub` — Core framework
- `bub_events` — Event-driven HTTP channel
- `bub_sf` — SystemF integration
- `republic` — Shared utilities
- `systemf` — Type system / evaluator

## Build Packages

Build all packages in the workspace:
```bash
uv build --all-packages
```

## Sync Bub Workspace

Navigate to the bub workspace directory and sync dependencies:
```bash
cd ../bub-workspace && uv sync
```

**Note:** If packages were rebuilt, you may need to force reinstall to pick up the latest versions:
```bash
cd ../bub-workspace && uv sync --reinstall-package bub-events --reinstall-package bub-sf --reinstall-package republic --reinstall-package systemf
```

## Restart Service

Restart the bub gateway service:
```bash
systemctl --user restart bub-gateway.service
```

## Check Logs

View service logs:
```bash
journalctl --user -u bub-gateway.service -f
```

## Full Deployment Flow

```bash
# 1. Build
uv build --all-packages

# 2. Sync workspace with force reinstall
cd ../bub-workspace && uv sync --reinstall-package bub-events

# 3. Restart service
systemctl --user restart bub-gateway.service

# 4. Verify logs
journalctl --user -u bub-gateway.service -f
```
