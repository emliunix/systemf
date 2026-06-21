# Tape Store (`SQLiteForkTapeStore`)

Reference for the SQLite-backed fork tape store: `bub_sf/src/bub_sf/store/fork_store.py`.
Query builder: `bub_sf/src/bub_sf/store/query.py`.

The store supports **tape forking**: a child tape shares its parent's entries up to
a fork point and diverges afterwards. Reads transparently merge the ancestor chain
via SQL views; writes only ever touch the leaf tape.

## Schema

Tables (`SCHEMA_SQL` in `fork_store.py`):

| Table | Purpose |
|---|---|
| `tapes` | One row per tape. `parent_id` + `parent_entry_id` define the fork point; `next_entry_id` is the monotonic append cursor. |
| `tape_entries` | Append-only entries, keyed by `(tape_id, entry_id)`. `kind` ∈ `message`, `assistant`, `tool_call`, `tool_result`, `anchor`, `event`. |
| `anchors` | Named bookmarks. `UNIQUE(tape_id, anchor_name)` and `UNIQUE(tape_id, entry_id)`. |

Views (drive the merged read model):

- `tape_ancestors` — recursive CTE from each leaf tape up through its ancestors,
  carrying `fork_point` (the parent's `parent_entry_id`) and `depth` (0 = leaf).
- `merged_entries` — all entries visible from a leaf: own entries at `depth 0`,
  plus ancestor entries with `entry_id <= fork_point`.
- `merged_anchors` — all anchors visible from a leaf, across the ancestor chain.

## Error vs. silent-empty

The most important behavioral distinction. Operations are grouped by what they do
when a tape or anchor is missing.

### Silent empty (no error)

| Operation | Behavior on missing tape | Location |
|---|---|---|
| `read(name)` | Returns `None` | `fork_store.py:414` |
| `fetch_all(TapeQuery{tape})` | `tape_id` is set to `-1` (a dummy id that cannot match), query returns `[]` | `query.py:137-140` |
| `list_tapes()` / `list_tapes_ext()` | Just return what exists | `fork_store.py:459-467` |

The dummy `-1` id in `BuildQuery.build` is deliberate: a `TapeQuery` against a
non-existent tape is treated as "empty result," **not** an error. The commented-out
`raise RepublicError(...)` shows this was a conscious choice.

### Anchor resolution errors

`BuildQuery.build` raises `RepublicError(NOT_FOUND)` when an anchor filter is
requested but the anchor cannot be resolved:

| Filter | Failure mode | Location |
|---|---|---|
| `after_anchor(name)` | name not found → error | `query.py:149-154` |
| `after_last` | no anchors in tape → error | `query.py:157-162` |
| `between_anchors(start, end)` | per-anchor errors distinguishing which side is missing (both / start / end) | `query.py:165-175` |

### Write errors

| Operation | Failure mode | Location |
|---|---|---|
| `fork(src, entry_id, tgt)` | source missing → error; target exists → error; `entry_id` out of range → error | `fork_store.py:211-239` |
| `rename(old, new)` | `old` missing → error; `new` already exists → error | `fork_store.py:197-209` |
| `reset(tape)` | `tape` missing → error | `fork_store.py:352-361` |
| `fork_tape(src, tgt)` | source missing → error; source has no entries → error; last entry is `tool_call` without a preceding assistant → error | `fork_store.py:367-409` |
| `append(tape, entry)` where `entry.kind == "anchor"` | anchor name already exists in the merged view → `INVALID_INPUT` error | `fork_store.py:156-170` |

## Auto-creation behavior

Whether a tape is implicitly created on first touch depends on the operation:

| Operation | Auto-creates? | Mechanism |
|---|---|---|
| `append` | **Yes** | goes through `_get_or_create_tape` (`fork_store.py:124-139`) |
| `create` | n/a — idempotent | `INSERT OR IGNORE`, no-op if the tape exists (`fork_store.py:141-147`) |
| `fork` / `fork_tape` | **No** | requires source to exist; explicitly errors otherwise |
| `rename` / `reset` | **No** | require the target tape to exist; explicitly errors otherwise |

Rule of thumb: only `append` will silently bring a tape into existence. Everything
else assumes the tape already exists and errors if it does not.

## `fork_tape` and the tool_call special case

`fork_tape(src, tgt)` forks at the last entry, with one special case
(`fork_store.py:367-409`):

1. Find the last entry of `src` (across the merged view).
2. If the last entry is **not** a `tool_call`, fork at its `entry_id`.
3. If the last entry **is** a `tool_call`:
   - look back for the most recent assistant message,
   - fork at the entry *before* that assistant message,
   - re-append the assistant message **with `tool_calls` stripped**.

This prevents a forked tape from starting with an assistant message that references
`tool_call_id`s whose `tool_call` entries were left behind at the fork point. If
the `tool_call` has no preceding assistant entry, the tape is rejected as invalid.

## Anchor resolution semantics

`BuildQueryImpl.anchors` (`fork_store.py:253-283`) resolves names against
`merged_anchors` and returns the **shallowest** (lowest `depth`) match. This means
a child tape can shadow a parent's anchor name; queries against the child resolve
to the child's anchor.

`last_anchor` (`fork_store.py:285-302`) returns the highest `entry_id` among
merged anchors, regardless of which ancestor defined it.

## Transaction model

- `CoreOps` performs raw SQL and **never commits**.
- `SQLiteForkTapeStore` wraps each public mutation in `_tranx()` (`fork_store.py:469-478`),
  which issues `BEGIN`, commits on success, rolls back on exception.
- Reads (`read`, `fetch_all`, `list_tapes*`) do not open a transaction, except
  `fetch_all`, which uses `_tranx` for consistency with the query builder.

## Read ordering

Merged reads order by `depth DESC, entry_id`. This yields ancestor entries first
(oldest ancestor at the greatest depth), then the leaf's own entries in append
order — i.e. a natural chronological replay of the conversation.
