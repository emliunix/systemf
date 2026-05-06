# Change Plan: bub_jobs — SystemD Cron Jobs Integration

## Status

**ON HOLD.** Tracked as a follow-up to `bub_events` channel. Do not implement until `bub_events` is stable.

## Goal

Create a `bub_jobs` subproject that leverages systemd timers/cron to trigger Bub agents on schedules. Uses the `bub_events` channel to inject scheduled events.

## Design Sketch

### Subproject: `bub_jobs/`

```
bub_jobs/
├── pyproject.toml
├── src/bub_jobs/
│   ├── __init__.py
│   ├── scheduler.py      # SystemD timer management
│   ├── cli.py            # `bub jobs add/list/remove` commands
│   └── templates/
│       └── timer.unit     # SystemD timer template
└── tests/
```

### Use Cases

1. **Periodic agent tasks:** "Every hour, run the health-check agent and report results"
2. **Scheduled reminders:** "Tomorrow at 9am, remind me about the meeting"
3. **Event-driven cron:** "When disk usage > 90%, trigger cleanup agent"

### Integration

- `bub_jobs` installs systemd user service/timer units
- On trigger, the timer unit calls `bub run --channel bub_events --content '{"content": "..."}'`
- Or directly opens a TCP socket to the `bub_events` channel

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_jobs/pyproject.toml` | Create | Subproject config |
| `bub_jobs/src/bub_jobs/scheduler.py` | Create | SystemD integration |
| `bub_jobs/src/bub_jobs/cli.py` | Create | CLI commands |

## Dependencies

- `bub_events` channel must be implemented first
- SystemD user session support
