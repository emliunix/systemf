# Change: Events Channel Form-Encoded POST Support

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
2. **Topic docs layer** (`{workspace}/event_prompts/{topic}.md`): Comprehensive per-topic documentation loaded by hook
3. **Skill layer** (`bub_events/src/skills/bub-events/SKILL.md`): General system documentation about events handling

### Content-Type Handling

The endpoint inspects the `Content-Type` header (case-insensitive):

1. **`application/x-www-form-urlencoded`**: Parse body as form data
2. **`application/json`** (default): Parse body as JSON, validate with `EventMessage`
3. **Missing/unknown**: Attempt JSON first, fall back to form parsing if JSON fails

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
- `content` (required)
- `chat_id` (optional, default "default")
- `sender` (optional, default "unknown")
- `topic` (optional, default "")
- `kind` (optional, default "normal")
- `meta[key]` (optional, nested form fields for meta dict)

Example:
```
content=disk+full&chat_id=alerts&sender=cron&topic=disk-alert
```

### Topic Documentation Reference

The `build_prompt` hook checks for topic documentation and adds a reference instruction:

```python
# Pseudo-code for hook
async def build_prompt(self, message, session_id, state):
    # ... standard prompt formatting (context, date, content) ...
    
    if topic := message.context.get("topic"):
        topic_doc_path = workspace / "event_prompts" / f"{topic}.md"
        if topic_doc_path.exists():
            prompt = f"Topic documentation available at: event_prompts/{topic}.md\n\n{prompt}"
        else:
            prompt = f"No topic documentation found for '{topic}' (event_prompts/{topic}.md does not exist).\n\n{prompt}"
    
    return prompt
```

**Design rationale:** Topic docs may be large. Instead of embedding content, we reference the file path. The agent can use `fs.read` to load it if needed. This is token-efficient and respects progressive disclosure.

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
    topic: str = Field("", description="Topic for convention agreement between tools and agent")
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
        # Default: JSON
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

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/message.py` | Modify | Add `topic` field to `EventMessage` |
| `bub_events/src/bub_events/channel.py` | Modify | Add Content-Type branching, form parsing, topic in context |
| `bub_events/src/bub_events/hook.py` | Modify | Add `build_prompt` hook to load topic docs |
| `bub_events/src/skills/bub-events/SKILL.md` | Create | Skill doc explaining events system |
| `bub_events/tests/test_message.py` | Modify | Update tests for new schema |
| `bub_events/tests/test_channel.py` | Modify | Add tests for form-encoded POSTs and topic |

## Test Plan

1. **test_post_json**: Existing JSON requests still work
2. **test_post_form_urlencoded**: POST with `Content-Type: application/x-www-form-urlencoded`
3. **test_post_form_without_content_type**: POST without content-type header (curl default)
4. **test_post_form_with_topic**: Topic field propagated to context
5. **test_post_form_with_meta**: Nested meta fields in form data
6. **test_post_form_missing_content**: Empty content field handled gracefully
7. **test_post_invalid_json**: 400 for malformed JSON when content-type is json
8. **test_post_unknown_content_type**: Falls back to JSON parsing
9. **test_message_schema_topic**: EventMessage validates with topic field

## Backward Compatibility

- Default behavior unchanged (JSON parsing)
- `topic` has default `""`, so existing clients are unaffected
- `meta` remains optional and backward compatible
- Existing clients unaffected
- curl without `-H "Content-Type:..."` now works (sends form-encoded by default)
