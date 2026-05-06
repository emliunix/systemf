# Change Plan: Add `tape_handoff` Primitive

## Facts

- Tape is a primitive type (`prim_type Tape`) defined in `bub_sf/src/bub_sf/bub.sf`
- Existing tape primitives: `current_tape :: () -> Tape`, `fork_tape :: Tape -> Maybe String -> Tape`, `make_tape :: Maybe Tape -> String -> Tape`, `append_message :: Tape -> String -> ()`
- `BubOps` synthesizer in `bub_sf/src/bub_sf/bub_ext.py` provides tape primitive implementations
- `VPrim` wraps arbitrary runtime values (tape names are strings wrapped in `VPrim`)
- `UNIT_VAL` is the unit value (`bi.UNIT_VAL`)
- The `tape.handoff` tool in `bub/src/bub/builtin/tools.py:224` calls `agent.tapes.handoff()` which creates an anchor entry + event entry
- Handoff behavior (from `analysis/TAPE_HANDOFF_EXPLORATION.md`):
  - Adds an **anchor** entry (`kind="anchor"`) and an **event** entry (`kind="event"`)
  - Default context truncates at last anchor — entries before anchor are excluded from LLM context
  - Used for compaction, checkpointing, and context management
- `SQLiteForkTapeStore` is the async tape store implementation

## Design

Add `tape_handoff` primitive:

```systemf
-- | Create a handoff anchor on the tape (truncates context)
prim_op tape_handoff :: Tape
  -> String -- ^ handoff name/reason
  -> ()
```

Behavior:
1. Extract tape name from `VPrim`
2. Extract name string from second argument
3. Call `store.handoff(tape_name, name)` to create anchor + event entries
4. Return `UNIT_VAL`

**Implementation:** Access the agent's `TapeService` via session state:
```python
async def _tape_handoff(args: list[Val], session: REPLSessionProto | None) -> Val:
    if session is None:
        raise Exception("tape_handoff must be called with a valid session")
    tape_name = _prim_val(args[0])
    name = _str_val(args[1])
    agent = session.state["bub_state"]["_runtime_agent"]
    await agent.tapes.handoff(tape_name, name=name)
    return bi.UNIT_VAL
```

This delegates to `TapeService.handoff()` (`bub/src/bub/builtin/tape.py:127-130`), which creates the anchor + event entries via the tape manager.

## Why it works

- Uses existing `VPrim` wrapping for tape values
- Uses existing `UNIT_VAL` for unit return
- Follows the same pattern as `append_message` (extract args, call store, return unit)
- Integrates with existing tape entry system
- Enables the compaction pattern: fork tape, summarize, handoff, append summary

## Use Cases

### 1. Compaction Pattern (Primary)

```systemf
-- | Compact a tape by summarizing and replacing history
compact :: Tape -> String -> IO ()
compact tape reason = do
  let branch = fork_tape tape Nothing
  summary  <- summarize branch reason
  tape_handoff tape reason
  append_message tape summary
```

### 2. Checkpointing

```systemf
main prompt = do
  let tape = current_tape ()
  
  -- Normal processing
  let response = process prompt
  
  -- Supervisor check
  let sup_tape = fork_tape tape
  let advice = supervise sup_tape prompt response
  
  case advice of
    Just rethink -> do
      tape_handoff tape "rethink"
      return "Let me reconsider..."
    Nothing -> return response
```

### 3. Phase Transition

```systemf
explore topic = do
  let tape = current_tape ()
  
  -- Mark checkpoint
  tape_checkpoint tape topic "started exploration"
  
  -- Do work...
  
  -- At handoff, use checkpoints for recomposition
  tape_handoff tape "phase2"
```

## Files

1. `bub_sf/src/bub_sf/bub.sf` — add `tape_handoff` primitive declaration
2. `bub_sf/src/bub_sf/bub_ext.py` — add `tape_handoff` implementation in `BubOps.get_primop`
3. `status.md` — update todo #18 to reference this change file

## Open Questions / TODO

- [x] **Entry definition**: Use `agent.tapes.handoff()` via `session.state["bub_state"]["_runtime_agent"]` — delegates to `TapeService.handoff()` which creates anchor + event entries via the tape manager
- [ ] **Error handling**: What if tape doesn't exist? Should match existing behavior of other primitives
- [ ] **Async bridging**: Confirm async/await pattern matches other primitives (`_append_message` uses `VAsync`)

## Related

- `analysis/TAPE_HANDOFF_EXPLORATION.md` — Deep dive into handoff semantics
- `analysis/systemf-orchestrator-spike.md` — Design doc with `tape_handoff` usage examples
- `changes/40-product-demo-prep.md` — Demo preparation (depends on this primop)
- `bub/src/bub/builtin/tools.py:224` — Existing `tape.handoff` tool implementation
