# Change Plan v2: Extract Command Execution as Agent Methods

**Status**: Draft
**Author**: opencode
**Date**: 2026-05-04
**Scope**: `bub/src/bub/builtin/agent.py`, `bub/src/bub/builtin/hook_impl.py`
**Replaces**: `changes/29-extract-command-execution.md`
**Refs**: `analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md`, `analysis/COMMAND_FUNCTIONS_EXTRACTION.md`

## Problem

The previous change plan extracted `run_command` and `run_command_stream` as module-level functions. This makes the call site in `hook_impl.py` complicated because callers must:
1. Get an Agent instance
2. Extract a Tape from `agent.tapes.tape(tape_name)`
3. Set `tape.context.state`
4. Pass the Tape to the module-level function
5. Fall through to `agent.run()` if the function returns None

This is unreasonably complex. The command execution should be encapsulated within Agent.

## Design

### New Agent Methods

Extract `_run_command` logic into two **Agent methods** with `| None` return type:

```python
class Agent:
    async def run_command(self, tape_name: str, prompt: str | list[dict], state: State) -> str | None:
        """Execute command if prompt starts with ','. Return None otherwise."""
        if not isinstance(prompt, str) or not prompt.strip().startswith(","):
            return None
        
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        line = prompt.strip()[1:].strip()
        if not line:
            raise ValueError("empty command")
        
        name, arg_tokens = _parse_internal_command(line)
        context = ToolContext(tape=tape.name, run_id="run_command", state=tape.context.state)
        
        if name not in REGISTRY:
            output = await REGISTRY["bash"].run(context=context, cmd=line)
        else:
            args = _parse_args(arg_tokens)
            if REGISTRY[name].context:
                args.kwargs["context"] = context
            output = REGISTRY[name].run(*args.positional, **args.kwargs)
            if inspect.isawaitable(output):
                output = await output
        
        return output if isinstance(output, str) else str(output)
    
    async def run_command_stream(self, tape_name: str, prompt: str | list[dict], state: State) -> AsyncStreamEvents | None:
        """Execute command and wrap result in AsyncStreamEvents. Return None if not a command."""
        result = await self.run_command(tape_name, prompt, state)
        if result is None:
            return None
        
        events = [
            StreamEvent("text", {"delta": result}),
            StreamEvent("final", {"text": result, "ok": True}),
        ]
        return self._events_from_iterable(events)
```

### Clean Agent.run() and Agent.run_stream()

```python
class Agent:
    async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
        if not prompt:
            return "error: empty prompt"
        if (result := await self.run_command(tape_name, prompt, state)) is not None:
            return result
        # ... rest of agent loop setup
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        merge_back = not state.get("session_id", "").startswith("temp/")
        async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
            await self.tapes.ensure_bootstrap_anchor(tape.name)
            return await self._agent_loop(...)
    
    async def run_stream(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> AsyncStreamEvents:
        if not prompt:
            events = [
                StreamEvent("text", {"delta": "error: empty prompt"}),
                StreamEvent("final", {"text": "error: empty prompt", "ok": False}),
            ]
            return self._events_from_iterable(events)
        if (events := await self.run_command_stream(tape_name, prompt, state)) is not None:
            return events
        # ... rest of agent loop setup
```

### Update hook_impl.py

```python
@hookimpl
async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    if (result := await agent.run_command(tape_name, prompt, state)) is not None:
        return result
    return await agent.run(tape_name=tape_name, prompt=prompt, state=state)

@hookimpl
async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    if (events := await agent.run_command_stream(tape_name, prompt, state)) is not None:
        return events
    return await agent.run_stream(tape_name=tape_name, prompt=prompt, state=state)
```

## Why This Is Better

1. **Simpler call sites**: `hook_impl.py` just calls `agent.run_command(...)` — no manual Tape construction
2. **Tape lifecycle stays in Agent**: Tape lookup and context setup remains encapsulated
3. **No duplication**: `Agent.run()` and `Agent.run_stream()` reuse `run_command`/`run_command_stream`
4. **Backward compatible**: Existing callers of `Agent.run()`/`run_stream()` see no change in behavior
5. **bub_sf can use it**: `bub_sf` can call `agent.run_command()` directly without dealing with Tape objects

## Files

| File | Action | Description |
|---|---|---|
| `bub/src/bub/builtin/agent.py` | Modify | Add `run_command` and `run_command_stream` methods. Refactor `run()` and `run_stream()` to use them. Remove module-level functions from v1. |
| `bub/src/bub/builtin/hook_impl.py` | Modify | Simplify: call `agent.run_command()`/`run_command_stream()` instead of manual Tape setup. |

## Validation

- 152 bub tests should pass
- Command execution should work in both streaming and non-streaming paths
- `bub_sf` can call `agent.run_command()` directly
