# Change: Events Channel Form-Encoded POST Support (v2)

## Status
Proposed

## Description

Extend `POST /event` to accept `Content-Type: application/x-www-form-urlencoded` in addition to `application/json`. Add `topic` field to `EventMessage` for convention-based routing. This enables simple integrations (curl, webhooks, systemd timers) to send events without constructing JSON payloads.

## Motivation

Current API requires JSON:
```bash
curl -X POST http://localhost:8000/event \
  -H "Content-Type: application/json" \
  -d '{"content": "hello", "chat_id": "room1"}'
```

With form-encoded support:
```bash
# Simple form POST
curl -X POST http://localhost:8000/event \
  -d "content=hello&chat_id=room1"

# With topic for routing conventions
curl -X POST http://localhost:8000/event \
  -d "content=disk+full&chat_id=alerts&sender=cron&topic=disk-alert"
```

Form encoding is universally supported by HTTP clients, webhooks, and monitoring tools.

## Design

### Three-Layer Architecture

The events system has three layers of information:

1. **Message layer** (`EventMessage`): Lightweight identifiers (`sender` + `topic`)
2. **Topic docs layer** (`{workspace}/event_prompts/{topic}.md`): Comprehensive per-topic documentation referenced by hook
3. **Skill layer** (`bub_events/src/skills/bub-events/SKILL.md`): General system documentation about events handling

### Content-Type Handling

The endpoint inspects the `Content-Type` header (case-insensitive):

1. **`application/x-www-form-urlencoded`**: Parse body as form data
2. **`application/json`**: Parse body as JSON, validate with `EventMessage`
3. **Missing/unknown**: Parse as JSON. If invalid JSON, return 400. No fallback to form parsing.

**Rationale:** curl without `-H` sends form-encoded by default (with content-type header). Explicit JSON requires the header. Unknown content-types should fail fast rather than guess.

### EventMessage Schema

```python
class EventMessage(BaseModel):
    content: str = Field(..., description="Message content or command")
    chat_id: str = Field("default", description="Chat identifier")
    sender: str = Field("unknown", description="Event sender provenance (acts as event type)")
    topic: str = Field("", description="Topic identifier for loading documentation")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    kind: str = Field("normal", description="Message kind")
```

**Field semantics:**
- `sender`: Identifies the source system (e.g., "cron", "webhook", "monitoring"). Acts as event type.
- `topic`: Identifier for loading topic-specific documentation. Empty string means no topic doc.
- `meta`: Keep mostly empty. Only use for tool-specific key-value pairs that the agent needs to see.

### Form Data Mapping

Form fields map directly to `EventMessage` fields:
- `content` (optional, default "")
- `chat_id` (optional, default "default")
- `sender` (optional, default "unknown")
- `topic` (optional, default "")
- `kind` (optional, default "normal")
- `meta[key]` (optional, nested form fields for meta dict)

**Validation note:** Form parsing allows empty content (defaults to ""), while JSON parsing requires content (422 if missing). This is intentional: form-encoded POSTs from simple curl commands may omit content for ping/heartbeat events.

Example:
```
content=disk+full&chat_id=alerts&sender=cron&topic=disk-alert
```

### Topic Documentation Reference

The `build_prompt` hook checks for topic documentation and adds a reference instruction:

```python
@hookimpl
def build_prompt(self, message, session_id, state):
    # Only handle bub-events messages; return None for everything else
    # so builtin build_prompt handles them
    if message.channel != "bub-events":
        return None
    
    # Replicate builtin prompt construction
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
    context = field_of(message, "context_str")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
    text = f"{context_prefix}{content}"
    
    # Add topic documentation reference
    if topic := message.context.get("topic"):
        safe_topic = re.sub(r'[^a-zA-Z0-9_-]', '', topic)
        if safe_topic:
            topic_doc_path = Path(state.get("_runtime_workspace", ".")) / "event_prompts" / f"{safe_topic}.md"
            if topic_doc_path.exists():
                text = f"Topic documentation available at: event_prompts/{safe_topic}.md\n\n{text}"
            else:
                text = f"No topic documentation found for '{safe_topic}' (event_prompts/{safe_topic}.md does not exist).\n\n{text}"
    
    return text
```

**Design rationale:** Topic docs may be large. Instead of embedding content, we reference the file path. The agent can use `fs.read` to load it if needed. This is token-efficient and respects progressive disclosure.

**Security:** Topic is sanitized with `re.sub(r'[^a-zA-Z0-9_-]', '', topic)` to prevent path traversal. Only alphanumeric, hyphen, and underscore allowed.

**Convention:** Topic docs are comprehensive handling guides stored in `event_prompts/`. They provide background the agent should read when handling that event type.

### Context Propagation

```python
context={"sender": msg.sender, "topic": msg.topic, **msg.meta}
```

**Warning:** `context` is LLM-facing. Per `analysis/BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md:216`, custom context keys are visible to the LLM during the turn. Avoid putting sensitive or large metadata in `meta`.

## Implementation

### Changes to `bub_events/src/bub_events/message.py`

Add `topic` field:

```python
class EventMessage(BaseModel):
    content: str = Field(..., description="Message content or command")
    chat_id: str = Field("default", description="Chat identifier")
    sender: str = Field("unknown", description="Event sender provenance")
    topic: str = Field("", description="Topic identifier for loading documentation")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    kind: str = Field("normal", description="Message kind")
```

### Changes to `bub_events/src/bub_events/channel.py`

Modify `_post_event` handler to branch on `Content-Type`:

```python
async def _post_event(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    
    if "application/x-www-form-urlencoded" in content_type:
        msg = await self._parse_form(request)
    else:
        # Default: JSON (including missing/unknown content-type)
        msg = await self._parse_json(request)
    
    return await self._handle_request(msg)
```

Update `_handle_request` to include `topic` in context:

```python
channel_msg = ChannelMessage(
    session_id=request_id,
    channel="bub-events",
    chat_id=msg.chat_id,
    content=msg.content,
    kind=msg.kind,
    context={"sender": msg.sender, "topic": msg.topic, **msg.meta},
)
```

Add helper methods:

```python
async def _parse_json(self, request: Request) -> EventMessage:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        return EventMessage.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

async def _parse_form(self, request: Request) -> EventMessage:
    form = await request.form()
    meta = {}
    for key, value in form.multi_items():
        if key.startswith("meta[") and key.endswith("]"):
            meta_key = key[5:-1]  # Extract key from meta[key]
            meta[meta_key] = value
    return EventMessage(
        content=form.get("content", ""),
        chat_id=form.get("chat_id", "default"),
        sender=form.get("sender", "unknown"),
        topic=form.get("topic", ""),
        kind=form.get("kind", "normal"),
        meta=meta,
    )
```

### Changes to `bub_events/src/bub_events/hook.py`

Add `build_prompt` hook implementation:

```python
import re
from pathlib import Path

from bub.builtin.hook_impl import content_of, field_of
from bub.channels.message import ChannelMessage
from bub.hookspecs import hookimpl
from bub.types import State

# ... existing provide_channels hook ...

@hookimpl
def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict] | None:
    """Build prompt for bub-events channel messages. Return None for non-events."""
    if message.channel != "bub-events":
        return None
    
    # Replicate builtin prompt construction
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
    
    context = field_of(message, "context_str")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
    text = f"{context_prefix}{content}"
    
    # Add topic documentation reference
    if topic := message.context.get("topic"):
        safe_topic = re.sub(r'[^a-zA-Z0-9_-]', '', topic)
        if safe_topic:
            workspace = state.get("_runtime_workspace", ".")
            topic_doc_path = Path(workspace) / "event_prompts" / f"{safe_topic}.md"
            if topic_doc_path.exists():
                text = f"Topic documentation available at: event_prompts/{safe_topic}.md\n\n{text}"
            else:
                text = f"No topic documentation found for '{safe_topic}' (event_prompts/{safe_topic}.md does not exist).\n\n{text}"
    
    return text
```

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/message.py` | Modify | Add `topic` field to `EventMessage` |
| `bub_events/src/bub_events/channel.py` | Modify | Add Content-Type branching, form parsing, topic in context |
| `bub_events/src/bub_events/hook.py` | Modify | Add `build_prompt` hook with topic doc reference |
| `bub_events/src/skills/bub-events/SKILL.md` | Verify/Update | Skill doc explaining events system |
| `bub_events/tests/test_message.py` | Modify | Update tests for new schema |
| `bub_events/tests/test_channel.py` | Modify | Add tests for form-encoded POSTs and topic |

## Test Plan

### Core Tests
1. **test_post_json**: Existing JSON requests still work
2. **test_post_form_urlencoded**: POST with `Content-Type: application/x-www-form-urlencoded`
3. **test_post_form_without_content_type**: POST without content-type header (curl default)
4. **test_post_form_with_topic**: Topic field propagated to context
5. **test_post_form_with_meta**: Nested meta fields in form data
6. **test_post_form_missing_content**: Empty content field handled gracefully
7. **test_post_invalid_json**: 400 for malformed JSON when content-type is json

### Edge Cases
8. **test_post_unknown_content_type**: Returns 400 for unknown content-type (e.g., `text/plain`)
9. **test_message_schema_topic**: EventMessage validates with topic field
10. **test_topic_sanitization**: Topic with special chars is sanitized (e.g., `../../../etc/passwd` → `etcpasswd`)
11. **test_build_prompt_returns_none_for_non_events**: Hook returns None for telegram/cli messages
12. **test_build_prompt_topic_doc_exists**: Reference added when topic doc exists
13. **test_build_prompt_topic_doc_missing**: Missing doc notice added when topic doc doesn't exist
14. **test_build_prompt_empty_topic**: No reference added when topic is empty string

## Backward Compatibility

- Default behavior unchanged (JSON parsing)
- `topic` has default `""`, so existing clients are unaffected
- `meta` remains optional and backward compatible
- curl without `-H "Content-Type:..."` now works (sends form-encoded by default)
- Non-events channels unaffected (build_prompt returns None for them)
