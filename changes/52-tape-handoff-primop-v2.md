# Change Plan: Add `tape_handoff` Primitive (v2)

## Facts

- Tape is a primitive type (`prim_type Tape`) defined in `bub_sf/src/bub_sf/bub.sf`
- Existing tape primitives: `current_tape`, `fork_tape`, `make_tape`, `append_message`
- `BubOps` synthesizer in `bub_sf/src/bub_sf/bub_ext.py` provides tape primitive implementations
- All existing primitives use `self.store` (`SQLiteForkTapeStore`) directly — no dependency on agent runtime
- `SQLiteForkTapeStore.append()` already handles `kind="anchor"` specially, creating records in both `tape_entries` and `anchors` tables
- `AsyncTapeManager.handoff()` creates two entries: `TapeEntry.anchor()` and `TapeEntry.event("handoff", ...)`
- `SQLiteForkTapeStore` does **not** currently have a `handoff()` method
- The previous plan (`changes/41-tape-handoff-primop.md`) proposed accessing `agent.tapes.handoff()` via session state, which introduces an unnecessary dependency on the agent runtime
- `VPrim` wraps tape names (strings), `UNIT_VAL` is the unit value

## Design

Add `tape_handoff` primitive with direct store implementation (no agent dependency):

```systemf
-- | Create a handoff anchor on the tape (truncates context)
prim_op tape_handoff :: Tape
  -> String -- ^ handoff name/reason
  -> ()
```

### Implementation

1. **Add `handoff` method to `CoreOps`** (`bub_sf/src/bub_sf/store/fork_store.py`):
   ```python
   async def handoff(self, tape_name: str, name: str) -> None:
       """Create anchor + event entries for context handoff within a single transaction."""
       entry = TapeEntry.anchor(name)
       event = TapeEntry.event("handoff", {"name": name})
       await self.append(tape_name, entry)
       await self.append(tape_name, event)
   ```
   - Reuses existing `append()` which already handles anchor entries correctly
   - Runs within a single transaction (caller wraps in `_tranx()`)

2. **Add `handoff` wrapper to `SQLiteForkTapeStore`**:
   ```python
   async def handoff(self, tape_name: str, name: str) -> None:
       @_unwrap_e
       async def _go():
           async with self._tranx() as _:
               await self._core.handoff(tape_name, name)
       return await _go()
   ```
   - Follows same transaction wrapper pattern as `reset()` and other compound operations
   - Returns `None` (primop returns `UNIT_VAL`)

2. **Add primop implementation in `BubOps.get_primop`** (`bub_sf/src/bub_sf/bub_ext.py`):
   ```python
   async def _tape_handoff(args: list[Val]) -> Val:
       tape_name = _prim_val(args[0])
       name = _str_val(args[1])
       await self.store.handoff(tape_name, name)
       return bi.UNIT_VAL
   ```
   - Same pattern as `_append_message`: extract args, call store, return unit
   - Uses `VAsync` wrapper like other async primitives

3. **Register in `BubOps.get_primop` match**:
   ```python
   case "tape_handoff":
       return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_tape_handoff(vals)))
   ```

4. **Add declaration in `bub.sf`**:
   ```systemf
   -- | Create a handoff anchor on the tape (truncates context at this point)
   prim_op tape_handoff :: Tape
     -> String -- ^ handoff name/reason
     -> ()
   ```

## Why it works

- **Consistent with existing primitives**: Uses `self.store` directly, same as `append_message`, `fork_tape`, etc.
- **No agent runtime dependency**: Works in any context where `BubOps` synthesizer is available
- **Reuses existing infrastructure**: `SQLiteForkTapeStore.append()` already handles anchor entries specially
- **Simple and focused**: Single responsibility — create anchor + event entries
- **Enables compaction pattern**: `fork_tape` → summarize → `tape_handoff` → `append_message`

## Files

1. `bub_sf/src/bub_sf/store/fork_store.py` — add `handoff()` method to `SQLiteForkTapeStore`
2. `bub_sf/src/bub_sf/bub_ext.py` — add `_tape_handoff` implementation and register in match
3. `bub_sf/src/bub_sf/bub.sf` — add `tape_handoff` primitive declaration
4. `status.md` — update todo #18 to reference this change file

## Open Questions

- [x] **Store vs Agent approach**: Using direct store method (consistent with other primitives) rather than agent runtime
- [x] **Return value**: Returns `()` — primop doesn't need entry IDs
- [ ] **Error handling**: What if tape doesn't exist? `append()` auto-creates tape, which may or may not be desired for handoff

## Test Coverage

- `bub_sf/tests/test_fork_store.py` — add tests for `handoff()`:
  - Creates anchor + event entries in single transaction
  - Anchor is queryable via `merged_anchors` view
  - Duplicate anchor names raise `RepublicError`
  - Failed second append rolls back both entries (atomic)

## Related

- `changes/41-tape-handoff-primop.md` — Previous plan (uses agent runtime approach)
- `changes/40-product-demo-prep.md` — Demo preparation (depends on this primop)
- `changes/51-auto-compact-session.md` — Auto-compact at session level (uses this primop)
- `analysis/TAPE_HANDOFF_EXPLORATION.md` — Deep dive into handoff semantics
