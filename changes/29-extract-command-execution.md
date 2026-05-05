# Change Plan: Extract Command Execution from Agent

**Status**: Draft
**Author**: opencode
**Date**: 2026-05-04
**Scope**: `bub/src/bub/builtin/agent.py`, `bub/src/bub/builtin/hook_impl.py`
**Refs**: `analysis/COMMAND_FUNCTIONS_EXTRACTION.md`, `analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md`

## Facts

### Fact 1: Command execution is embedded in Agent.run() and Agent.run_stream()
- `bub/src/bub/builtin/agent.py:104-105` — `Agent.run()` checks `prompt.startswith(",")` and calls `_run_command`
- `bub/src/bub/builtin/agent.py:135-150` — `Agent.run_stream()` does the same, wrapping result in `AsyncStreamEvents`
- Both methods conflate tape lifecycle (fork/bootstrap), command dispatch, and agent loop

### Fact 2: _run_command is stateless
- `bub/src/bub/builtin/agent.py:152-190`
- Needs only: `tape: Tape`, `line: str`, plus global `REGISTRY` and `ToolContext`
- No dependency on `self.settings`, `self.framework`, or agent loop internals
- Returns `str`

### Fact 3: hook_impl.py does not handle commands before calling agent
- `bub/src/bub/builtin/hook_impl.py:161-168`
- `run_model()` and `run_model_stream()` directly call `Agent.run()` / `Agent.run_stream()`
- They rely on Agent's internal dispatch, which means commands are only handled when Agent is active

### Fact 4: Multiple layers detect commands independently
- `bub/src/bub/builtin/hook_impl.py:134` — `build_prompt` marks `message.kind = "command"`
- `bub/src/bub/channels/handler.py:42` — `BufferedMessageHandler` bypasses debounce for commands
- `bub/src/bub/channels/cli/__init__.py:133` — CLI shell mode auto-prefixes with `,`
- `bub/src/bub/channels/telegram.py:249` — Telegram passes commands directly
- All these layers agree on `startswith(",")` but none actually execute commands — execution is solely in Agent

## Design

### New Module-Level Functions

Extract `_run_command` logic into two probed functions with `| None` return type:

```python
# agent.py — module-level, no class needed

async def run_command(tape: Tape, prompt: str | list[dict]) -> str | None:
    """Execute command if prompt starts with ','. Return None otherwise."""
    if not isinstance(prompt, str) or not prompt.strip().startswith(","):
        return None
    
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


def _events_from_iterable(iterable: Iterable) -> AsyncStreamEvents:
    """Already exists in Agent; make module-level."""
    ...


async def run_command_stream(tape: Tape, prompt: str | list[dict]) -> AsyncStreamEvents | None:
    """Execute command and wrap result in AsyncStreamEvents. Return None if not a command."""
    result = await run_command(tape, prompt)
    if result is None:
        return None
    
    events = [
        StreamEvent("text", {"delta": result}),
        StreamEvent("final", {"text": result, "ok": True}),
    ]
    return _events_from_iterable(events)
```

### Refactor Agent Facade

```python
class Agent:
    async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
        if not prompt:
            return "error: empty prompt"
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        merge_back = not state.get("session_id", "").startswith("temp/")
        async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
            await self.tapes.ensure_bootstrap_anchor(tape.name)
            if (result := await run_command(tape, prompt)) is not None:
                return result
            return await self._agent_loop(...)
    
    async def run_stream(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> AsyncStreamEvents:
        if not prompt:
            ...
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        merge_back = not state.get("session_id", "").startswith("temp/")
        stack = AsyncExitStack()
        await stack.enter_async_context(self.tapes.fork_tape(tape.name, merge_back=merge_back))
        await self.tapes.ensure_bootstrap_anchor(tape.name)
        
        if (events := await run_command_stream(tape, prompt)) is not None:
            return self._events_with_callback(events, callback=stack.aclose)
        
        events = await self._agent_loop(..., stream_output=True)
        return self._events_with_callback(events, callback=stack.aclose)
```

### Add Command Handling to hook_impl.py

```python
# hook_impl.py

@hookimpl
async def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    tape = agent.tapes.tape(tape_name)
    tape.context = replace(tape.context, state=state)
    
    # Try command first
    if (result := await run_command(tape, prompt)) is not None:
        return result
    
    # Fall through to agent loop
    return await agent.run(tape_name=tape_name, prompt=prompt, state=state)

@hookimpl
async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    tape = agent.tapes.tape(tape_name)
    tape.context = replace(tape.context, state=state)
    
    # Try command first
    if (events := await run_command_stream(tape, prompt)) is not None:
        return events
    
    # Fall through to agent loop
    return await agent.run_stream(tape_name=tape_name, prompt=prompt, state=state)
```

## Validation — Guarded by Exploration

This change is validated by two explorations:

1. **`analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md`** — establishes that:
   - Commands are lost when `bub_sf` intercepts `run_model_stream` (Claim 1)
   - The `build_prompt` hook alone cannot restore command execution (Claim 2)
   - Pre-dispatch check is the minimal fix (Claim 4)

2. **`analysis/COMMAND_FUNCTIONS_EXTRACTION.md`** — establishes that:
   - `_run_command` is stateless and depends only on `tape` + `prompt` + `REGISTRY` (Fact 3)
   - `| None` return type is the correct probe pattern (Claim 2)
   - Functions can be called without `Agent` construction (Claim 3)
   - Return-type asymmetry (command → `str`, agent loop → `AsyncStreamEvents`) is handled by `run_command_stream` (Claim 7)

These facts and claims guard the design: the extraction is justified by the statelessness of command execution, and the probe pattern is justified by the need for explicit dispatch.

## Why It Works

1. **Functions are stateless**: `run_command` and `run_command_stream` take `Tape` + `prompt`, return `| None`. No class construction needed.
2. **Probe pattern**: `| None` return type makes the dispatch explicit at the type level. Callers must handle the `None` case.
3. **Backward compatible**: `Agent.run()` and `Agent.run_stream()` still work exactly the same. The functions are extracted from `_run_command`, not from the public API.
4. **Enables bub_sf interposition**: `bub_sf` hook impl can call `run_command` / `run_command_stream` directly without constructing `Agent`, matching the Layered Turn Architecture.
5. **hook_impl handles commands**: By checking commands before calling `Agent`, `hook_impl` ensures commands are processed even when `bub_sf` intercepts the hook (since `bub_sf` can now call the same functions).

## Files

| File | Action | Description |
|---|---|---|
| `bub/src/bub/builtin/agent.py` | Modify | Extract `_run_command` → `run_command` + `run_command_stream` (module-level). Make `_events_from_iterable` module-level. Refactor `Agent.run()` and `Agent.run_stream()` to use new functions. |
| `bub/src/bub/builtin/hook_impl.py` | Modify | Add command probe before calling `Agent.run()` / `Agent.run_stream()` in `run_model` and `run_model_stream`. |

## Call Sites

- `bub/src/bub/builtin/hook_impl.py:161` — `run_model` calls `self._get_agent().run()`
- `bub/src/bub/builtin/hook_impl.py:166` — `run_model_stream` calls `self._get_agent().run_stream()`
- `bub/src/bub/builtin/tools.py` — `subagent` tool calls `agent.run()` / `agent.run_stream()` (no change needed, still works)
- `bub/src/bub/channels/cli/__init__.py` — `CliChannel` receives `Agent` directly (no change needed)

## Risks

1. **Tape forking in Agent vs hook_impl**: `Agent.run()` forks the tape inside the method. If `hook_impl` probes commands before forking, commands won't be logged to a forked tape. However, `run_command` only needs `tape.context.state` — it doesn't need the fork. The fork is for agent loop isolation.
2. **Import cycles**: `run_command` needs `REGISTRY` from `bub.tools`. Currently `Agent` imports it. Need to ensure module-level import works.
3. **Logging**: `_run_command` logs to `self.tapes.append_event`. If extracted to module-level, logging needs a `tapes` parameter or must be skipped. Recommendation: skip logging for now; it's a side effect, not essential.
