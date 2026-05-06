---
name: bub-events
description: Event-driven channel for the Bub framework. Use when processing HTTP events from external systems (webhooks, cron jobs, monitoring alerts) via the bub-events channel.
---

# Bub Events Channel

The `bub-events` channel receives HTTP POST events from external systems and converts them into agent messages.

## What It Is

Unlike chat channels (Telegram, CLI), the events channel is designed for **machine-to-machine notifications**:
- Monitoring alerts (disk full, service down)
- Cron job completions
- Webhook callbacks
- Scheduled task reminders

Events arrive at `POST /event` and are processed as a single agent turn with bidirectional response.

## Topic-Based Documentation Convention

Events carry a `topic` field that triggers loading of topic-specific documentation:

**Location:** `{workspace}/event_prompts/{topic}.md`

**Example:** An event with `topic=disk-alert` loads `{workspace}/event_prompts/disk-alert.md`

**Purpose:** Topic docs provide comprehensive handling instructions for specific event types, including:
- What the event means
- Required investigation steps
- Expected response format
- Tool calls to make

**Agent behavior:** When a topic doc exists, follow its instructions precisely. It takes precedence over general event handling guidance.

## Sample Use Case: Cron Jobs

### Systemd Timer Template

Create a systemd timer that calls the events endpoint on schedule:

```ini
# /etc/systemd/system/bub-cron-@NAME@.timer
[Unit]
Description=Bub cron timer for @NAME@

[Timer]
OnCalendar=@SCHEDULE@
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/bub-cron-@NAME@.service
[Unit]
Description=Bub cron job for @NAME@

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -X POST http://localhost:8000/event \
  -d "content=@CONTENT@" \
  -d "sender=cron" \
  -d "topic=@TOPIC@" \
  -d "chat_id=cron-@NAME@"
```

### Example: Daily Backup Check

```bash
# Install timer
sudo systemctl enable bub-cron-backup.timer
sudo systemctl start bub-cron-backup.timer

# Event arrives with:
# content="Daily backup completed"
# sender="cron"
# topic="backup-status"
# chat_id="cron-backup"
```

**Topic doc:** `{workspace}/event_prompts/backup-status.md` would instruct the agent to verify backup integrity and notify on failure.

## Event Message Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `content` | Event payload | "Disk usage 95%" |
| `sender` | Source system | "cron", "monitoring" |
| `topic` | Topic identifier | "disk-alert" |
| `chat_id` | Session grouping | "alerts", "cron-backup" |
| `meta` | Extra key-value pairs | `{"severity": "critical"}` |

## Response Patterns

When handling events:
1. **Acknowledge** if appropriate (especially for webhook expectations)
2. **Investigate** using available tools
3. **Act** on findings (remediate or escalate)
4. **Report** what was done

Events are not conversational—focus on action and resolution.

## References

- [API Reference](references/api-reference.md) — Full API documentation, endpoints, request/response formats, curl examples
