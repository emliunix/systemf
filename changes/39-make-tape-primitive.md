# Change Plan: Add `make_tape` Primitive

## Facts

- Tape is a primitive type (`prim_type Tape`) defined in `bub_sf/src/bub_sf/bub.sf`
- Existing tape primitives: `current_tape :: () -> Tape`, `fork_tape :: Tape -> Maybe String -> Tape`
- `BubOps` synthesizer in `bub_sf/src/bub_sf/bub_ext.py` provides tape primitive implementations
- `VPrim` wraps arbitrary runtime values (tape names are strings wrapped in `VPrim`)
- `Maybe` is `VData(0, [])` for `Nothing`, `VData(1, [x])` for `Just x`
- `SQLiteForkTapeStore.create(name)` creates an empty tape (line 168 of `fork_store.py`)
- Tape naming convention: hierarchical paths with `/` separators (e.g., `user/session1`)

## Design

Add `make_tape` primitive:

```systemf
make_tape :: Maybe Tape -> String -> Tape
```

Behavior:
1. Extract optional parent tape name from `Maybe Tape`
2. Extract name string
3. Generate full tape name:
   - With parent: `{parent-tape-name}/{name}-{uuid}`
   - Without parent: `{name}-{uuid}`
4. Call `store.create(tape_name)` to register the tape
5. Return `VPrim(tape_name)`

## Why it works

- Uses existing `Maybe` pattern matching (`_maybe_val` helper)
- Uses existing `VPrim` wrapping for tape values
- Uses existing `store.create()` for tape registration
- Hierarchical naming follows existing tape conventions (seen in `fork_tape`)
- UUID suffix prevents name collisions

## Additional Primitive: `append_message`

```systemf
append_message :: Tape -> String -> ()
```

Appends a user message entry to the given tape. Enables the pattern:

```systemf
let forked_tape = fork_tape tape Nothing
    some_info   = study_with forked_tape "some topic"
in append_message tape some_info
```

Where a sub-computation on a forked tape produces a result, and that result is appended back to the parent tape as a user message.

Behavior:
1. Extract tape name from `VPrim`
2. Extract string message
3. Create `TapeEntry.message({"role": "user", "content": string})`
4. Call `store.append(tape_name, entry)`
5. Return `UNIT_VAL`

## Files

1. `bub_sf/src/bub_sf/bub.sf` — add primitive declarations
2. `bub_sf/src/bub_sf/bub_ext.py` — add implementations in `BubOps.get_primop`
3. `status.md` — add todo items