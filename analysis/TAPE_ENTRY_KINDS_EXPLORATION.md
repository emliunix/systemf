# Exploration: Tape Entry Kinds and Markdown/YAML Header Format

## Notes

### Note 1: Goal
Determine how each `TapeEntry.kind` should be rendered into a text format with a YAML header and markdown content body.

### Note 2: Design Constraint
The output should be human-readable in a terminal. Each entry is self-contained: a YAML front-matter block followed by a content body.

## Facts

### Fact 1: TapeEntry Kinds Defined in Republic
`republic/src/republic/tape/entries.py:16-61`
```python
@dataclass(frozen=True)
class TapeEntry:
    id: int
    kind: str
    payload: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    date: str = field(default_factory=utc_now)

    @classmethod
    def message(cls, message: dict[str, Any], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="message", payload=dict(message), meta=dict(meta))

    @classmethod
    def system(cls, content: str, **meta: Any) -> TapeEntry:
        return cls(id=0, kind="system", payload={"content": content}, meta=dict(meta))

    @classmethod
    def anchor(cls, name: str, state: dict[str, Any] | None = None, **meta: Any) -> TapeEntry:
        payload: dict[str, Any] = {"name": name}
        if state is not None:
            payload["state"] = dict(state)
        return cls(id=0, kind="anchor", payload=payload, meta=dict(meta))

    @classmethod
    def tool_call(cls, calls: list[dict[str, Any]], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="tool_call", payload={"calls": calls}, meta=dict(meta))

    @classmethod
    def tool_result(cls, results: list[Any], **meta: Any) -> TapeEntry:
        return cls(id=0, kind="tool_result", payload={"results": results}, meta=dict(meta))

    @classmethod
    def error(cls, error: RepublicError, **meta: Any) -> TapeEntry:
        return cls(id=0, kind="error", payload=error.as_dict(), meta=dict(meta))

    @classmethod
    def event(cls, name: str, data: dict[str, Any] | None = None, **meta: Any) -> TapeEntry:
        payload: dict[str, Any] = {"name": name}
        if data is not None:
            payload["data"] = dict(data)
        return cls(id=0, kind="event", payload=payload, meta=dict(meta))
```

### Fact 2: Schema Stores Payload as JSON
`bub_sf/docs/store/core.md:44-56`
```sql
CREATE TABLE tape_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tape_id INTEGER NOT NULL REFERENCES tapes(id),
    entry_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON
    meta TEXT NOT NULL DEFAULT '{}',-- JSON
    date TEXT NOT NULL              -- ISO timestamp
);
```

### Fact 3: ForkTapeStore Interface Returns `TapeEntry`
`bub_sf/src/bub_sf/store/fork_store.py`
The store's `read()` and `fetch_all()` methods return `list[TapeEntry]` with fields `entry_id`, `kind`, `payload`, `meta`, `date`.

## Claims

### Claim 1: Common YAML Header Fields
Every entry kind should share the same YAML front-matter:
```yaml
---
entry_id: <int>
kind: <str>
date: <ISO timestamp>
---
```
The `meta` dict can be merged into the header as additional keys, or omitted if empty to keep output concise.

**References:** Fact 1, Fact 2

### Claim 2: Per-Kind Content Body Mapping
| Kind | Payload Structure | Body Rendering |
|------|-------------------|----------------|
| `message` | `{"role": ..., "content": ...}` (OpenAI-style) | Print `role:` then `content` as markdown text |
| `system` | `{"content": "..."}` | Print the content string directly |
| `anchor` | `{"name": "...", "state": {...}}` | Print name as heading; optionally pretty-print state as YAML |
| `tool_call` | `{"calls": [{"name", "arguments"}, ...]}` | List each call as `name(args)` or pretty-print JSON |
| `tool_result` | `{"results": [...]}` | Pretty-print each result (JSON for dicts, str for primitives) |
| `error` | ` RepublicError.as_dict()` | Print error fields (kind, message, etc.) |
| `event` | `{"name": "...", "data": {...}}` | Print event name as heading; pretty-print data as YAML/JSON |

**References:** Fact 1

### Claim 3: Message Content May Be Multimodal
`message` entries in practice contain OpenAI-style message dicts with `role` and `content`. The `content` may be a string or a list of content parts. The printer should handle both.

**References:** Fact 1 (payload is `dict[str, Any]`)

### Claim 4: Anchor Entries Are Metadata-Only
`anchor` entries have no natural "body" text — they are bookmarks. The body should display the anchor name and optional state snapshot.

**References:** Fact 1

### Claim 5: JSON Payload Should Be Pretty-Printed for Unknown/Complex Kinds
For `tool_call`, `tool_result`, `error`, and `event`, the payload contains nested structures. Indenting JSON by 2 spaces is the most robust default.

**References:** Fact 1
