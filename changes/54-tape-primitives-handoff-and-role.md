# Change Plan: Tape Primitives — `tape_handoff` and `append_message` Role

## Facts

- Tape is a primitive type (`prim_type Tape`) defined in `bub_sf/src/bub_sf/bub.sf`
- Existing tape primitives: `current_tape :: () -> Tape`, `fork_tape :: Tape -> Maybe String -> Tape`, `make_tape :: Maybe Tape -> String -> Tape`, `append_message :: Tape -> String -> ()`
- `BubOps` synthesizer in `bub_sf/src/bub_sf/bub_ext.py` provides tape primitive implementations
- All existing primitives use `self.store` (`SQLiteForkTapeStore`) directly — no dependency on agent runtime
- `SQLiteForkTapeStore.append()` already handles `kind="anchor"` specially, creating records in both `tape_entries` and `anchors` tables
- `AsyncTapeManager.handoff()` creates two entries: `TapeEntry.anchor()` and `TapeEntry.event("handoff", ...)`
- `AsyncTapeManager` accepts `AsyncTapeStore` protocol — `SQLiteForkTapeStore` satisfies this
- `append_message` hardcodes role to `"user"` in `bub_ext.py:86`
- **No existing SystemF source files call `append_message`** — only the primitive declaration exists
- `VPrim` wraps tape names (strings), `UNIT_VAL` is the unit value
- `VData` represents data constructors: `VData(0, [])` for `User`, `VData(1, [])` for `Assistant`

## Design

### Part 1: Add `tape_handoff` Primitive

```systemf
-- | Create a handoff anchor on the tape (truncates context at this point)
prim_op tape_handoff :: Tape
  -> String -- ^ handoff name/reason
  -> ()
```

**Implementation:**

1. **Add `AsyncTapeManager` to `BubOps`** (`bub_sf/src/bub_sf/bub_ext.py`):
   ```python
   from republic.tape.manager import AsyncTapeManager

   class BubOps(Synthesizer):
       store: SQLiteForkTapeStore
       
       def __init__(self, store: SQLiteForkTapeStore) -> None:
           self.store = store
           self.mgr = AsyncTapeManager(store=store)
   ```

2. **Add primop implementation in `BubOps`**:
   ```python
   async def _tape_handoff(self, args: list[Val]) -> Val:
       tape_name = _prim_val(args[0])
       name = _str_val(args[1])
       await self.mgr.handoff(tape_name, name)
       return bi.UNIT_VAL
   ```

3. **Register in `BubOps.get_primop` match**:
   ```python
   case "tape_handoff":
       return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(self._tape_handoff(vals)))
   ```

4. **Add declaration in `bub.sf`**:
   ```systemf
   -- | Create a handoff anchor on the tape (truncates context at this point)
   prim_op tape_handoff :: Tape
     -> String -- ^ handoff name/reason
     -> ()
   ```

### Part 2: Add Role Data Type and Update `append_message`

Define `Role` as a SystemF data type for type-safe role handling:

```systemf
-- | Message role for tape entries
data Role = User | Assistant

-- | append a message to the tape
prim_op append_message :: Tape
  -> String  -- ^ message content
  -> Role    -- ^ role: User or Assistant
  -> ()
```

**Implementation:**

1. **Add `Role` data type and update `append_message` declaration in `bub.sf`**:
   ```systemf
   data Role = User | Assistant
   
   prim_op append_message :: Tape
     -> String  -- ^ message content
     -> Role    -- ^ role
     -> ()
   ```

2. **Add `_role_val` helper and update implementation in `bub_ext.py`**:
   ```python
   def _role_val(val: Val) -> str:
       """Extract role string from Role data constructor.
       
       data Role = User | Assistant
       User      -> VData(0, []) -> "user"
       Assistant -> VData(1, []) -> "assistant"
       """
       match val:
           case VData(0, []):
               return "user"
           case VData(1, []):
               return "assistant"
           case v:
               raise Exception(f"Expected Role value, got: {v}")

   async def _append_message(self, args: list[Val]) -> Val:
       tape_name = _prim_val(args[0])
       content = _str_val(args[1])
       role_tag = _role_val(args[2])
       message = {"role": role_tag, "content": content}
       if role_tag == "assistant":
           message["reasoning_content"] = ""
       entry = TapeEntry.message(message)
       await self.store.append(tape_name, entry)
       return bi.UNIT_VAL
   ```

3. **Update `VPartial` arity**: `len(arg_tys)` is computed dynamically from the type signature, so it automatically becomes 3 after the type declaration is updated.

## Why it works

- **Type-safe roles**: `Role` is a proper data type, not raw strings. SystemF typechecker ensures only `User` or `Assistant` can be passed
- **Consistent with existing primitives**: `append_message` uses `self.store` directly; `tape_handoff` uses `AsyncTapeManager` which is the canonical handoff implementation
- **No agent runtime dependency**: Works in any context where `BubOps` synthesizer is available
- **Reuses existing infrastructure**: `AsyncTapeManager.handoff()` already creates anchor + event entries correctly
- **No breaking changes**: No SystemF files currently call `append_message`
- **Enables compaction pattern**: `fork_tape` → summarize → `tape_handoff` → `append_message` with `Assistant`

## Files

1. `bub_sf/src/bub_sf/bub_ext.py` — add `AsyncTapeManager` to `BubOps`, add `_tape_handoff` implementation, add `_role_val` helper, update `_append_message` implementation
2. `bub_sf/src/bub_sf/bub.sf` — add `Role` data type, add `tape_handoff` declaration, update `append_message` signature
3. `status.md` — update todos #18 and #20 to reference this change file

## Notes

- **Role handling**: `User` and `Assistant` are the only valid roles. For `Assistant` messages, `reasoning_content` is set to `""` in the payload as a tape system convention
- **Handoff return value**: Returns `()` — primop doesn't need entry IDs
- **Handoff atomicity (known limitation)**: `AsyncTapeManager.handoff()` calls `store.append()` twice (anchor + event). Each append is its own transaction in `SQLiteForkTapeStore`. If the system crashes between the two appends, the tape may have an anchor without a matching handoff event. This is accepted for now — fixing it would require either adding a `handoff` method to `AsyncTapeStore` protocol or exposing transaction control, both of which complicate the design. Not addressed in this change.

## Test Coverage

- `bub_sf/tests/test_bub_ext.py` — tests for tape primitives:
  - `append_message` with `User` role → `"user"`, no `reasoning_content`
  - `append_message` with `Assistant` role → `"assistant"`, `reasoning_content=""`
  - `tape_handoff` delegates to `AsyncTapeManager.handoff()`
  - `make_tape` with/without parent
  - `fork_tape` with/without explicit name

## Use Case: Auto-Compact

```systemf
-- | Compact a tape by summarizing and replacing history
compact :: Tape -> String -> IO ()
compact tape reason = do
  let branch = fork_tape tape Nothing
  summary  <- summarize branch reason
  tape_handoff tape reason
  -- Append summary as assistant message
  append_message tape summary Assistant
```

## Related

- `changes/41-tape-handoff-primop.md` — Previous plan (uses agent runtime approach)
- `changes/52-tape-handoff-primop-v2.md` — Superseded by this plan
- `changes/53-append-message-role.md` — Superseded by this plan
- `changes/40-product-demo-prep.md` — Demo preparation (depends on these primops)
- `changes/51-auto-compact-session.md` — Auto-compact at session level (uses these primops)
- `analysis/TAPE_HANDOFF_EXPLORATION.md` — Deep dive into handoff semantics
