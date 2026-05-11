# Change Plan: Add Role Parameter to `append_message`

## Facts

- `append_message` is declared in `bub_sf/src/bub_sf/bub.sf` as:
  ```systemf
  prim_op append_message :: Tape -> String -> ()
  ```
- Implementation is in `bub_sf/src/bub_sf/bub_ext.py:84-88`:
  ```python
  async def _append_message(args: list[Val]) -> Val:
      tape_name, content = _prim_val(args[0]), _str_val(args[1])
      entry = TapeEntry.message({"role": "user", "content": content})
      await self.store.append(tape_name, entry)
      return bi.UNIT_VAL
  ```
- Role is hardcoded to `"user"` in the `TapeEntry.message()` call
- **No existing SystemF source files call `append_message`** — only the primitive declaration exists
- `TapeEntry.message()` accepts `message: dict[str, Any]` where `"role"` is a string key
- Known roles in the system: `"user"`, `"assistant"`, `"system"`
- `Maybe` is already a defined type in SystemF (`Nothing` / `Just a`)
- `_maybe_val` helper exists in `bub_ext.py:352` for extracting `Maybe` values

## Design

Change `append_message` to accept an optional role parameter:

```systemf
-- | append a message to the tape with optional role
--   role defaults to "user" when Nothing
prim_op append_message :: Tape
  -> String          -- ^ message content
  -> Maybe String    -- ^ role: "user" | "assistant" | "system" (Nothing = "user")
  -> ()
```

### Implementation

1. **Update declaration in `bub.sf`**:
   ```systemf
   -- | append a message to the tape with optional role
   prim_op append_message :: Tape
     -> String          -- ^ message content
     -> Maybe String    -- ^ role (Nothing defaults to "user")
     -> ()
   ```

2. **Update implementation in `bub_ext.py`**:
   ```python
   async def _append_message(args: list[Val]) -> Val:
       tape_name = _prim_val(args[0])
       content = _str_val(args[1])
       role = _maybe_val(_str_val, args[2]) or "user"
       entry = TapeEntry.message({"role": role, "content": content})
       await self.store.append(tape_name, entry)
       return bi.UNIT_VAL
   ```

3. **Update `VPartial` arity**: Change from `len(arg_tys)` (which was 2) to the new arity (3). Since `len(arg_tys)` is computed dynamically from the type signature, this will automatically be 3 after the type declaration is updated.

## Why it works

- **No breaking changes to existing code**: No SystemF files currently call `append_message`
- **Backward-compatible semantics**: `Nothing` defaults to `"user"`, matching current behavior
- **Enables auto-compact**: Compaction summaries can be appended as `"assistant"` messages
- **Follows existing patterns**: Uses `_maybe_val` helper already present in the file
- **Simple and focused**: Minimal change — one parameter added, one line changed in implementation

## Files

1. `bub_sf/src/bub_sf/bub.sf` — update `append_message` declaration signature
2. `bub_sf/src/bub_sf/bub_ext.py` — update `_append_message` implementation to extract role from args

## Notes

- **Role validation**: No validation of role strings — any string is accepted. This is intentional for flexibility; the tape system stores roles opaquely.

## Test Coverage

- `bub_sf/tests/test_bub_ext.py` or equivalent — add tests for `_append_message`:
  - `Nothing` → role defaults to `"user"`
  - `Just "assistant"` → role is `"assistant"`
  - `Just "system"` → role is `"system"`

## Use Case: Auto-Compact

```systemf
-- | Compact a tape by summarizing and replacing history
compact :: Tape -> String -> IO ()
compact tape reason = do
  let branch = fork_tape tape Nothing
  summary  <- summarize branch reason
  tape_handoff tape reason
  -- Append summary as assistant message (not user)
  append_message tape summary (Just "assistant")
```

## Related

- `changes/51-auto-compact-session.md` — Auto-compact at session level (depends on this change)
- `changes/52-tape-handoff-primop-v2.md` — `tape_handoff` primitive (used together in compaction)
- `status.md` — todo #20
