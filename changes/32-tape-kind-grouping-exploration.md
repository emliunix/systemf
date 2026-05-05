# Exploration: Tape Entry Kind Sequence Patterns

## Context

The current `TapeEntry.kind` field supports seven distinct kinds (`republic/src/republic/tape/entries.py:30-61`):

| Kind | Purpose | Key Payload Fields |
|------|---------|-------------------|
| `message` | LLM chat messages | `role`, `content` |
| `system` | System prompts | `content` |
| `anchor` | Named checkpoints | `name`, `state` |
| `tool_call` | Function/tool calls | `calls` |
| `tool_result` | Tool execution results | `results` |
| `error` | Error records | arbitrary |
| `event` | Named events | `name`, `data` |

## Observed Patterns in Practice

### Pattern 1: The Request-Response Pair

In LLM tool-use workflows, a common sequence is:

```
message (assistant) → tool_call → tool_result → message (assistant)
```

The `tool_call` and `tool_result` entries are **ancillary** to the assistant message. They represent the "how" of the response, not independent content. Currently they are separate entries with no explicit linkage.

### Pattern 2: System Context Sandwich

```
system → message (user) → message (assistant) → ...
```

System entries often precede user messages but are logically part of the same interaction context. They are rarely queried independently.

### Pattern 3: Error Interruption

```
message (user) → message (assistant) → error → ...
```

Errors break the normal flow but could be viewed as metadata on the preceding turn.

### Pattern 4: Event Bookends

```
event ("start") → ... → event ("end")
```

Events mark boundaries but don't carry primary content.

## Proposed Design: Primary-Secondary Entry Model

Introduce a two-level entry model:

### Primary Kinds (Content-bearing)

These are the "main" entries that users care about when reading a tape:

- **`message`** — The LLM message (user, assistant, system)
- **`anchor`** — Named checkpoints (already acts as a boundary marker)

### Secondary Kinds (Metadata / Context)

These are merged into adjacent primary entries as headers/footers:

- **`tool_call`** → merged as header into the following `message` or `tool_result`
- **`tool_result`** → merged as header into the following `message`
- **`system`** → merged as header into the following `message`
- **`error`** → merged as footer into the preceding primary entry
- **`event`** → merged as header/footer depending on semantic role

### Representation

```python
class TapeEntry:
    id: int
    kind: str  # still the primary kind
    payload: dict  # primary content
    meta: dict  # NEW: merged secondary entries
    date: str
```

The `meta` field (currently underutilized) becomes a list of secondary entries:

```json
{
  "pre": [
    {"kind": "tool_call", "payload": {"calls": [...]}, "date": "..."},
    {"kind": "tool_result", "payload": {"results": [...]}, "date": "..."}
  ],
  "post": [
    {"kind": "error", "payload": {...}, "date": "..."}
  ]
}
```

## Why It Works

1. **Reduced visual noise:** `print-tape` shows one panel per primary entry with secondary info as sub-tables, instead of 4-5 separate panels for a single turn.
2. **Semantic grouping:** Tool calls without a following message are meaningless; this makes the relationship explicit.
3. **Backwards compatibility:** The `kind` field remains the primary kind. Secondary entries are stored in `meta`, which already exists and is JSON.
4. **Query flexibility:** `kinds` filter still works on primary kinds. Secondary kinds can be searched via `meta` if needed.

## Open Questions

1. **Anchor boundaries:** Should `anchor` reset the secondary accumulation? (Probably yes — a checkpoint starts a new logical segment.)
2. **Multi-turn tool chains:** What if there are multiple `tool_call`/`tool_result` pairs before the final message? (Store all in `pre` array.)
3. **Fork semantics:** Do secondary entries fork with their primary? (Yes — they are conceptually part of the same entry.)
4. **Migration:** Existing tapes have flat sequences. A migration would need to scan and group retroactively. Complex and risky.

## Alternative: Keep Flat, Add Grouping View

Instead of changing storage, add a `read_grouped()` method that returns `GroupedEntry` objects:

```python
class GroupedEntry:
    primary: TapeEntry
    pre: list[TapeEntry]  # preceding secondary entries
    post: list[TapeEntry]  # following secondary entries
```

This is **purely a presentation-layer change** — no schema migration, no data rewrite. The `print-tape` CLI and any UI consumers use `read_grouped()` instead of `read()`.

## Recommendation

**Start with the Alternative (Grouping View)** because:
- Zero migration risk
- Can be prototyped and reverted easily
- Doesn't lock in a grouping heuristic prematurely
- Allows iterating on what counts as "primary" vs "secondary"

If the grouping heuristic proves stable and valuable after real-world use, consider migrating storage in a follow-up change.

## Files to Explore

- `republic/src/republic/tape/entries.py` — Entry definitions
- `bub_sf/src/bub_sf/store/fork_store.py` — Storage and query logic
- `bub_sf/src/bub_sf/hook_cli.py` — CLI rendering (consumer of grouping)
- `republic/src/republic/tape/query.py` — Query builder (may need grouping support)
