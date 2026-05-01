# SystemF Orchestrator Design

## Overview

This document describes the architecture for making SystemF the primary agent orchestrator by intercepting the Bub framework's `run_model_stream` hook. Instead of the default agent loop (multi-step tool execution), SystemF code controls the entire turn — managing tape, calling LLM primitives, and invoking tools explicitly.

## Architecture

### Before: Bub Agent Loop

```
User Message
    ↓
build_prompt hook → prompt
    ↓
Agent.run_stream(session_id, prompt, state)
    ↓
Agent loop (max 10 steps):
    ├─ LLM call with tools
    ├─ Execute tool calls
    ├─ Continue loop
    ↓
Return final text
```

**Problem:** The agent loop is opaque. Tape is derived from `session_id`. Tool execution is automatic. No way to implement complex patterns (supervision, checkpointing, branching) from within the loop.

### After: SystemF Orchestrator

```
User Message
    ↓
build_prompt hook → prompt
    ↓
SFHookImpl.run_model_stream (firstresult=True)
    ↓
session.eval("main <prompt>")
    ↓
SystemF main function executes:
    ├─ Manage tape (fork, handoff, checkpoint)
    ├─ Call LLM primitives (returns text/tool results)
    ├─ Call tools explicitly via sf.repl
    ├─ Implement supervision patterns
    ↓
Return final result as stream events
```

**Key change:** SystemF code is the agent. The LLM is a primitive function call. Tools are SystemF functions. Tape is explicitly manipulated.

## Hook Interception

### Implementation

```python
# bub_sf/src/bub_sf/hook.py

class SFHookImpl:
    @hookimpl
def load_state(self, message, session_id):
        state = {"sf_ctx": self, "session_id": session_id}
        return state

    @hookimpl
    async def run_model_stream(
        self, 
        prompt: str | list[dict], 
        session_id: str, 
        state: dict
    ) -> AsyncStreamEvents | None:
        # Get or create REPL session for this conversation
        session = self.get_or_create(session_id)
        
        # Inject current prompt into session state
        # so tape_current() can access it
        session.state["current_prompt"] = prompt
        session.state["session_id"] = session_id
        
        # Evaluate main function with the prompt
        # The prompt is passed as a string argument
        prompt_str = prompt if isinstance(prompt, str) else json.dumps(prompt)
        result = await session.eval(f'main ({prompt_str})')
        
        if result is None:
            return AsyncStreamEvents.from_text("Error: no result")
        
        val, ty = result
        text = pp_val(val)
        
        # Convert to stream events
        return AsyncStreamEvents.from_text(text)
```

### Why firstresult=True Works

`run_model_stream` is declared as `@hookspec(firstresult=True)` in `bub/hookspecs.py:44`. This means:
- Pluggy calls the first plugin implementing this hook
- Returns that plugin's result immediately
- Other plugins are skipped

By implementing this hook in `bub_sf`, we take over the entire model execution for all sessions.

### Fallback Behavior

If SystemF evaluation fails, we should return `None` to let the next plugin handle it (though there shouldn't be another `run_model_stream` implementor). Alternatively, return an error stream.

## SystemF Entry Point

### The main Function

```systemf
{-# LLM model=gpt-4 #-}
main :: String -> String
main prompt = do
  -- Get current tape
  let tape = tape_current ()
  
  -- Maybe fork for isolation
  let work_tape = tape_fork tape
  
  -- Do work
  result <- process_message work_tape prompt
  
  -- Maybe checkpoint
  tape_checkpoint tape "turn_complete" result
  
  return result
```

### Tape-Aware LLM Functions

When an LLM function has a `Tape` parameter as its first argument:

```systemf
{-# LLM model=gpt-4 #-}
analyze :: Tape -> Data -> Result
analyze work_tape data = do
  -- LLMOps detects Tape param
  -- Runs agent on work_tape instead of creating temp session
  ...
```

Behind the scenes, `LLMOps`:
1. Checks if `arg_types[0]` is `TyConApp(BUILTIN_TAPE)`
2. Extracts tape name from first argument (`VPrim` value)
3. Calls `tape.run_tools_async()` directly (no agent loop)
4. Captures return value via `set_return`

## Tape Integration

### Tape Primitives in SystemF

```systemf
-- Get current session's tape
prim_op tape_current :: Unit -> Tape

-- Create persistent fork (metadata only, instant)
prim_op tape_fork :: Tape -> Tape

-- Create handoff anchor (truncates context)
prim_op tape_handoff :: Tape -> String -> Unit

-- Add checkpoint (metadata without truncation)
prim_op tape_checkpoint :: Tape -> String -> String -> Unit

-- Append text event
prim_op tape_append :: Tape -> String -> Unit

-- Read entries as strings
prim_op tape_read :: Tape -> [String]
```

### Runtime Implementation

```python
# In BubOps synthesizer
def get_primop(self, name, thing, session):
    match name.surface:
        case "tape_current":
            return VPartial.create("tape_current", 0, 
                lambda _: VPrim(session.state.get("tape_name", "default")))
        
        case "tape_fork":
            return VPartial.create("tape_fork", 1,
                lambda args: VAsync(_tape_fork(args, agent)))
        
        case "tape_handoff":
            return VPartial.create("tape_handoff", 2,
                lambda args: VAsync(_tape_handoff(args, agent)))
        
        # ... etc
```

## Tool Integration

### sf.repl Tool

Already exists in `bub_sf/hook.py`. Allows the LLM to evaluate SystemF expressions:

```systemf
-- In an LLM function, the LLM can call:
sf.repl("tape_current ()")
sf.repl("tape_fork my_tape")
sf.repl("set_return (result)")
```

### Custom Tools as SystemF Functions

Any SystemF function can be exposed as a tool by:
1. Defining it with a pragma
2. Having the LLM call `sf.repl("function_name arg1 arg2")`

The REPL evaluates it and returns the result.

## Patterns Enabled

### Supervision

```systemf
main prompt = do
  let tape = tape_current ()
  
  -- Normal processing
  let response = process prompt
  
  -- Supervisor check
  let sup_tape = tape_fork tape
  let advice = supervise sup_tape prompt response
  
  case advice of
    Just rethink -> do
      tape_handoff tape "rethink"
      return "Let me reconsider..."
    Nothing -> return response
```

### Checkpoint + Recomposition

```systemf
explore topic = do
  let tape = tape_current ()
  
  -- Mark checkpoint
  tape_checkpoint tape topic "started exploration"
  
  -- Do work...
  
  -- At handoff, use checkpoints for recomposition
  tape_handoff tape "phase2" 
    [(topic, "detailed summary")]
```

### Branching (Parallel Exploration)

```systemf
main prompt = do
  let tape = tape_current ()
  
  -- Create two branches
  let branch_a = tape_fork tape
  let branch_b = tape_fork tape
  
  -- Explore different approaches
  let result_a = explore_approach_a branch_a
  let result_b = explore_approach_b branch_b
  
  -- Compare and select
  return (compare_results result_a result_b)
```

## Lifecycle

### Session Initialization

1. `load_state` hook creates `sf_session` in state
2. REPL session imports `builtins` module (includes `Tape` type)
3. User's agent module is loaded with `main` function

### Per-Turn Execution

1. `run_model_stream` receives prompt
2. Evaluates `main(prompt)` in REPL session
3. SystemF code manages tape, calls LLM primitives, tools
4. Return value is streamed back to user

### Session Persistence

- REPL session state persists across turns (bindings, types)
- Tape entries persist in SQLite store
- `sf_session` kept in framework state dictionary

## Error Handling

### SystemF Errors

If `main` throws or returns wrong type:
- Catch exception in `run_model_stream`
- Return error stream with message
- Consider resetting REPL session on persistent errors

### LLM Primitive Errors

If `tape.run_tools_async()` fails:
- `VAsync` coroutine raises exception
- CEK evaluator propagates it
- Can be caught with `try/catch` if SystemF has exception handling

### Tape Errors

If tape operations fail (e.g., fork nonexistent tape):
- Return `VAsync` that raises exception
- SystemF code can use `Maybe` types for error propagation

## Performance Considerations

### Fork Overhead

- Metadata fork: O(1) — single INSERT into `tapes` table
- No data copying
- Read overhead: O(depth) for parent chain resolution

### LLM Primitive Overhead

- Direct `tape.run_tools_async()` call — no agent loop overhead
- Single LLM call per primitive invocation
- Tools executed synchronously within the call

### REPL Session Overhead

- Session state persists across turns
- `main` function lookup is cached
- Module compilation happens once on import

## Open Questions

1. **Tape naming:** How to derive consistent tape names across turns? Use `session_id`? Allow user-defined names?

2. **Multiple LLM calls:** Should `main` be able to make multiple LLM calls in one turn? Yes, each is an independent `run_tools_async()` call.

3. **Streaming:** How to stream partial results from SystemF evaluation? Currently returns final value. May need async generator support.

4. **State persistence:** Should REPL session be saved/restored across process restarts? For now, in-memory only.

## Dependencies

- `bub_sf/store/core.md` — ForkTapeStore design
- `bub_sf/hook.py` — Existing SFHookImpl with sf.repl tool
- `bub_sf/bub_ext.py` — BubOps and LLMOps synthesizers
- `systemf/elab3/repl_session.py` — REPL session with fork and eval

## Next Steps

1. Implement `ForkTapeStore` (see `bub_sf/docs/store/plan.md`)
2. Add `Tape` primitive to `builtins.sf` + runtime
3. Extend `SFHookImpl` with `run_model_stream` hook
4. Update `LLMOps` to detect and route `Tape` parameters
5. Write test SystemF agent module demonstrating patterns
