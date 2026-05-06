# Bub Events Channel API Reference

## Endpoints

### POST /event

Receives event notifications and processes them through the agent framework.

**Authentication:** Bearer token (optional, configured via `EventsSettings`)

**Request Headers:**
- `Content-Type`: `application/json` or `application/x-www-form-urlencoded`
- `Authorization`: `Bearer <token>` (if auth is configured)

**Request Body (JSON):**
```json
{
  "content": "Disk usage 95% on /data",
  "chat_id": "alerts",
  "sender": "monitoring",
  "topic": "disk-alert",
  "kind": "normal",
  "meta": {
    "severity": "critical",
    "host": "server-01"
  }
}
```

**Request Body (Form-Encoded):**
```
content=Disk+usage+95%25+on+%2Fdata
&chat_id=alerts
&sender=monitoring
&topic=disk-alert
&meta[severity]=critical
&meta[host]=server-01
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "response": "Agent response text here"
}
```

**Response (Timeout):**
```json
{
  "status": "timeout"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid JSON (when Content-Type is JSON)
- `401 Unauthorized`: Invalid or missing Bearer token
- `422 Unprocessable Entity`: Validation error (e.g., missing required field, invalid topic)

### GET /health

Health check endpoint.

**Response (200 OK):**
```json
{
  "status": "healthy"
}
```

## EventMessage Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `content` | string | Yes | - | Event payload text |
| `chat_id` | string | No | `"default"` | Session identifier for grouping related events |
| `sender` | string | No | `"unknown"` | Source system identifier (e.g., "cron", "monitoring") |
| `topic` | string | No | `""` | Topic identifier for documentation loading |
| `kind` | string | No | `"normal"` | Message kind: `"normal"`, `"command"`, or `"error"` |
| `meta` | object | No | `{}` | Extra key-value pairs for tool-specific data |

**Topic Validation:**
- Must contain only alphanumeric characters, hyphens (`-`), and underscores (`_`)
- Empty string is allowed (no topic)
- Invalid topics return `422 Unprocessable Entity`

## Topic Documentation Convention

Topic documentation files provide comprehensive handling instructions for specific event types.

**Location:** `{workspace}/event_prompts/{topic}.md`

**Example file:** `{workspace}/event_prompts/disk-alert.md`

**Content structure:**
```markdown
# Disk Alert Handling

## Trigger Conditions
- Disk usage > 90%
- inode usage > 85%

## Investigation Steps
1. Check which filesystem is affected
2. Identify largest directories
3. Check for log rotation issues

## Actions
- Clean temporary files
- Rotate logs if needed
- Alert on-call if > 95%

## Response Format
Report: filesystem, current usage, action taken, recommendation
```

## Configuration

EventsSettings (environment variables or config):

| Setting | Env Variable | Default | Description |
|---------|--------------|---------|-------------|
| `host` | `BUB_EVENTS_HOST` | `"127.0.0.1"` | Server bind address |
| `port` | `BUB_EVENTS_PORT` | `8000` | Server port |
| `auth_token` | `BUB_EVENTS_AUTH_TOKEN` | `None` | Bearer token (optional) |
| `response_timeout` | `BUB_EVENTS_RESPONSE_TIMEOUT` | `30` | Request timeout in seconds |

## Curl Examples

### Basic event
```bash
curl -X POST http://localhost:8000/event \
  -H "Content-Type: application/json" \
  -d '{"content": "hello"}'
```

### Form-encoded event
```bash
curl -X POST http://localhost:8000/event \
  -d "content=disk+full&topic=disk-alert"
```

### With authentication
```bash
curl -X POST http://localhost:8000/event \
  -H "Authorization: Bearer secret123" \
  -H "Content-Type: application/json" \
  -d '{"content": "alert"}'
```

### Cron job event
```bash
curl -X POST http://localhost:8000/event \
  -d "content=Daily+backup+completed" \
  -d "sender=cron" \
  -d "topic=backup-status" \
  -d "chat_id=cron-backup"
```
