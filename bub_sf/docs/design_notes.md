# Design Notes

## Tape Parameter Routing (Short Facts)

- **Type detection**: `LLMOps.get_primop` checks `thing.id.ty` for `TyConApp(BUILTIN_TAPE)` as first argument
- **Runtime value**: `Tape` primitive represented as `VPrim(TapeHandle(name))` containing tape name string
- **Agent access**: `session.state["_runtime_agent"]` → `agent.tapes._llm.tape(name)` gives `Tape` object
- **Async boundary**: Tape operations return `VAsync` values, CEK evaluator calls `unasync()` which awaits coroutine
- **Session derivation**: When tape param detected, derive `session_id` from tape name instead of `uuid4()`
- **No agent loop for LLM primitives**: Internal LLM calls go directly to `tape.run_tools_async()` / `tape.stream_events_async()`, bypassing Agent's multi-step loop

Full design to be revisited after systemf-orchestrator and fork-store are ready.

## Supervision Pattern

Supervision is function composition in SystemF — the main agent calls a supervisor function with a tape snapshot before responding.

```systemf
-- Supervisor with its own tape for context
{-# LLM model=gpt-4 #-}
supervise :: Tape -> String -> Maybe String
supervise supervisor_tape message = do
  tape_append supervisor_tape ("Checking: " ++ message)
  -- LLM decides if intervention needed
  if is_distracted message then
    return (Just "rethink")
  else
    return Nothing

-- Main agent uses supervisor  
{-# LLM model=gpt-4 #-}
process :: Tape -> String -> String
process main_tape message = do
  let result = normal_processing message
  
  -- Fork snapshot for supervisor
  let sup_tape = tape_fork main_tape
  let advice = supervise sup_tape message
  
  case advice of
    Just "rethink" -> do
      tape_handoff main_tape "rethink"
      return "I need to reconsider my approach..."
    Nothing -> return result
```

Key insight: Supervisor is just another LLM function call with its own tape. No framework hooks needed.

## Checkpoint vs Handoff

See `analysis/TAPE_HANDOFF_EXPLORATION.md` for full handoff analysis.

### Handoff (Current Behavior)
- Adds anchor entry to tape
- Default `TapeContext.anchor = LAST_ANCHOR` truncates context at handoff
- Previous entries excluded from prompt
- Used for: context length management, phase boundaries

### Checkpoint (Proposed Enhancement)
- Adds metadata entry WITHOUT truncating context
- Marks topic/phase boundary but keeps full history visible
- Stores: topic name, summary, relevance score
- Queryable via `tape_checkpoints :: Tape -> [(String, String)]`
- Used for: topic tracking, provenance, recomposition planning

```systemf
-- Mark checkpoint during exploration
tape_checkpoint tape "approach_a" "tried solution X, found issue Y"

-- Later, use checkpoints to build recomposition plan
checkpoints = tape_checkpoints tape
-- [("approach_a", "tried solution X..."), ...]
```

Checkpoints enable selective context recomposition at handoff time — rerank topics, keep relevant ones, drop distractions.

## Design Decisions Log

### 1. SystemF as Agent (Not Agent as SystemF)
- **Decision**: Hook intercepts `run_model_stream`, delegates to SystemF `main()` evaluation
- **Result**: SystemF controls the turn, calls LLM as primitive, manages tape explicitly
- **Implication**: Default agent loop is bypassed; SystemF is the orchestrator

### 2. Fork Semantics
- **Decision**: Metadata-only fork with lazy parent resolution
- **Result**: Instant fork (O(1)), shared storage, transparent merged view
- **Implication**: Entries physically exist in one tape, read via union query across parent chain

### 3. Snapshot vs Fork
- **Decision**: `tape_fork` = metadata fork (shared parent); `tape_snapshot` = physical copy (independent)
- **Result**: Fork for branching exploration, snapshot for long-lived independent copies
- **Implication**: Two distinct operations with different lifecycle guarantees
