# Change: Events Channel Form-Encoded POST Support

## Status
Proposed

## Description

Extend `POST /event` to accept `Content-Type: application/x-www-form-urlencoded` in addition to `application/json`. This enables simple integrations (curl, webhooks, systemd timers) to send events without constructing JSON payloads.

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

# Webhook-style (no explicit content-type header needed)
curl -X POST http://localhost:8000/event \
  -d "content=disk+full&chat_id=alerts&sender=cron"
```

Form encoding is universally supported by HTTP clients, webhooks, and monitoring tools.

## Design

### Content-Type Handling

The endpoint inspects the `Content-Type` header (case-insensitive):

1. **`application/x-www-form-urlencoded`**: Parse body as form data
2. **`application/json`** (default): Parse body as JSON, validate with `EventMessage`
3. **Missing/unknown**: Attempt JSON first, fall back to form parsing if JSON fails

### Form Data Mapping

Form fields map directly to `EventMessage` fields:
- `content` (required)
- `chat_id` (optional, default "default")
- `sender` (optional, default "unknown")
- `kind` (optional, default "normal")
- `meta[key]` (optional, nested form fields for meta dict)

Example:
```
content=hello&chat_id=room1&meta[source]=cron&meta[job_id]=42
```

### Context Propagation

Form data follows the same context propagation as JSON:
```python
context={"sender": msg.sender, **msg.meta}
```

**Warning:** `context` is LLM-facing. Per `analysis/BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md:216`, custom context keys are visible to the LLM during the turn. Avoid putting sensitive or large metadata in `meta`.

## Implementation

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
        kind=form.get("kind", "normal"),
        meta=meta,
    )
```

### Changes to `bub_events/src/bub_events/message.py`

No changes required. `EventMessage` schema remains the same.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_events/src/bub_events/channel.py` | Modify | Add Content-Type branching and form parsing helper |
| `bub_events/tests/test_channel.py` | Modify | Add tests for form-encoded POSTs |

## Test Plan

1. **test_post_json**: Existing JSON requests still work
2. **test_post_form_urlencoded**: POST with `Content-Type: application/x-www-form-urlencoded`
3. **test_post_form_without_content_type**: POST without content-type header (curl default)
4. **test_post_form_with_meta**: Nested meta fields in form data
5. **test_post_form_missing_content**: Empty content field handled gracefully
6. **test_post_invalid_json**: 400 for malformed JSON when content-type is json
7. **test_post_unknown_content_type**: Falls back to JSON parsing

## Backward Compatibility

- Default behavior unchanged (JSON parsing)
- No API breaking changes
- Existing clients unaffected
- curl without `-H "Content-Type:..."` now works (sends form-encoded by default)
