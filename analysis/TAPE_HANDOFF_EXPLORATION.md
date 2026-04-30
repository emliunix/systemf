# Tape Handoff Exploration

## Notes

### Note 1: Investigation Context
Understanding how `handoff` works in the Bub tape system — its mechanism, semantics, and limitations for context management.

### Note 2: Scope
- IN: How handoff creates anchors, how context is truncated, what metadata is stored
- OUT: Implementation details of republic tape manager, agent loop internals beyond handoff

### Note 3: Central Questions
1. What entries does handoff add to the tape?
2. How does the anchor affect context building for subsequent LLM calls?
3. What state/metadata can be stored in a handoff?
4. How does auto-handoff recover from context length errors?
5. What are the limitations of handoff for branching/snapshot patterns?

---

## Facts

### Fact 1: Handoff Adds Two Entries
`republic/tape/manager.py:72-76`
```python
def handoff(self, tape, name, state=None, **meta):
    entry = TapeEntry.anchor(name, state=state, **meta)
    event = TapeEntry.event("handoff", {"name": name, "state": state or {}}, **meta)
    self._tape_store.append(tape, entry)
    self._tape_store.append(tape, event)
```

Handoff adds:
1. An **anchor** entry (`kind="anchor"`) with the handoff name and state
2. An **event** entry (`kind="event"`) recording the handoff occurrence

### Fact 2: Default Context Truncates at Last Anchor
`republic/tape/context.py:33-42`
```python
@dataclass(frozen=True)
class TapeContext:
    anchor: AnchorSelector = LAST_ANCHOR
    
    def build_query(self, query):
        if self.anchor is None:
            return query
        if isinstance(self.anchor, _LastAnchor):
            return query.last_anchor()
        return query.after_anchor(self.anchor)
```

By default, `TapeContext.anchor = LAST_ANCHOR`, which builds a query with `query.last_anchor()`.

### Fact 3: Last Anchor Query Filters Out Anchor and All Before
`republic/tape/store.py:132-136`
```python
def _anchor_index(entries, name, default, forward, start):
    # Find last anchor matching criteria
    ...

# In fetch_all:
elif query._after_last:
    anchor_index = _anchor_index(entries, None, default=-1, forward=False)
    if anchor_index < 0:
        raise RepublicError(NOT_FOUND, "No anchors found in tape.")
    start_index = min(anchor_index + 1, len(entries))
```

The `_after_last` flag causes `fetch_all` to skip the anchor entry itself and all entries before it. Only entries **after** the last anchor are returned.

### Fact 4: ForkTapeStore Also Clears Parent Entries on Anchor
`bub/builtin/store.py:72-76`
```python
for entry in this_entries:
    if entry.kind == "anchor":
        if query._after_last or (query._after_anchor and entry.name == query._after_anchor):
            this_entries.clear()
            parent_entries = []
            continue
    this_entries.append(entry)
```

Inside a fork context, encountering an anchor entry with `_after_last` clears **both** the in-memory buffer (`this_entries`) and the parent store entries (`parent_entries`). The merged view starts fresh after the anchor.

### Fact 5: Handoff State is Stored but Not Injected
`republic/tape/entries.py:38-42`
```python
@classmethod
def anchor(cls, name, state=None, **meta):
    payload = {"name": name}
    if state is not None:
        payload["state"] = dict(state)
    return cls(id=0, kind="anchor", payload=payload, meta=dict(meta))
```

The `state` parameter is stored in the anchor entry's payload, but the default context builder (`build_messages`) only includes entries with `kind="message"`. Anchors are not automatically included in the LLM prompt.

### Fact 6: Auto-Handoff Recovers from Context Length Errors
`bub/builtin/agent.py:327-353`
```python
if auto_handoff_remaining > 0 and _is_context_length_error(outcome.error):
    auto_handoff_remaining -= 1
    await self.tapes.handoff(
        tape.name,
        name="auto_handoff/context_overflow",
        state={"reason": "context_length_exceeded", "error": outcome.error},
    )
    # Retry with original prompt — the handoff anchor will truncate history
    next_prompt = prompt
    continue
```

When context length is exceeded:
1. A handoff anchor is created to truncate history
2. The agent retries with the **original prompt**
3. Because of the anchor, the retry only sees entries after the handoff

### Fact 7: Tape.handoff_async Returns the Added Entries
`republic/tape/session.py:207-208`
```python
async def handoff_async(self, name, state=None, **meta):
    return await self._client._async_tape.handoff(self._name, name, state=state, **meta)
```

`Tape.handoff_async` delegates to `AsyncTapeManager.handoff`, which returns `[anchor_entry, event_entry]`.

### Fact 8: Handoff is NOT a Snapshot/Branch
Handoff creates a **checkpoint** in a linear tape:
- Entries before the anchor are excluded from context
- But they still exist in the tape store
- Appending after handoff continues on the same tape
- No new tape is created

This is fundamentally different from forking (creating a divergent branch).

### Fact 9: Between-Anchors Query Can Access Truncated History
`republic/tape/query.py:39-40`
```python
def between_anchors(self, start, end):
    return replace(self, _between_anchors=(start, end))
```

Entries before the last anchor are still accessible via:
- `query.between_anchors("start", "end")`
- `query.after_anchor("specific_anchor_name")`
- `query.anchor = None` (full tape)

### Fact 10: Agent Always Ensures Bootstrap Anchor
`bub/builtin/tape.py:69-74`
```python
async def ensure_bootstrap_anchor(self, tape_name):
    tape = self._llm.tape(tape_name)
    anchors = list(await tape.query_async.kinds("anchor").all())
    if not anchors:
        await tape.handoff_async("session/start", state={"owner": "human"})
```

If a tape has no anchors, a bootstrap anchor `"session/start"` is created. This ensures there's always a truncation point.

---

## Claims

### Claim 1: Handoff is a Context Truncation Mechanism, Not a Branch
**Status:** VALIDATED
**Reasoning:** Handoff adds an anchor entry that causes `fetch_all` with `last_anchor()` to skip the anchor and all preceding entries. No new tape is created. Entries are still in storage but excluded from the default prompt context.

**References:** Fact 1, Fact 2, Fact 3, Fact 8

### Claim 2: Handoff State is Invisible to the LLM by Default
**Status:** VALIDATED
**Reasoning:** The anchor entry's `state` payload is stored but the default `build_messages` only includes `kind="message"` entries. Anchors are not converted to prompt messages unless a custom `TapeContext.select` is used.

**References:** Fact 5

### Claim 3: Auto-Handoff Works by Truncating and Retrying
**Status:** VALIDATED
**Reasoning:** When context length error occurs, the agent creates a handoff anchor (which drops previous entries from context) and retries the same prompt. The LLM sees a fresh context with only the anchor and the retry prompt.

**References:** Fact 6

### Claim 4: Handoff Does Not Enable True Branching/Snapshotting
**Status:** VALIDATED
**Reasoning:** Because handoff operates on a single tape with linear history, there's no way to explore divergent paths from a handoff point. ForkTapeStore's `fork()` creates a temporary buffer, not a persistent branch. For true branching, a separate tape with copied entries is needed.

**References:** Fact 8

---

## Summary

**Handoff is a compaction primitive:** It marks a point in a linear tape where context should be truncated for subsequent reads. Entries before the anchor are still in storage but excluded from the default prompt.

**Key limitation:** Handoff doesn't create branches or snapshots. For divergent exploration (e.g., trying multiple approaches from a checkpoint), a separate mechanism (like ForkTapeStore with persistent snapshot semantics) is needed.

**For context recomposition:** Handoff state can store topic summaries, but they're not automatically injected. A custom `TapeContext.select` function would be needed to rebuild context with selective retention.

---

## Related Documents

- `bub_sf/docs/store/core.md` — ForkTapeStore design with true branching
- `bub_sf/docs/design_notes.md` — Checkpoint vs Handoff comparison
- `bub_sf/docs/systemf-orchestrator.md` — Using handoff in SystemF agent pattern
