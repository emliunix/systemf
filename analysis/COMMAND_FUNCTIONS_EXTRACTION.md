# Command Extraction — Probed Functions with `| None` Return

## Notes

### Note 1: Goal
Refactor command execution from `Agent._run_command` into two standalone **probed functions** that return `| None` when the prompt is not a command. This mirrors the `run_model` / `run_model_stream` signatures and makes the dispatch explicit.

### Note 2: Rationale
Extracting a `CommandProcessor` class (see `analysis/AGENT_SPLIT_EXPLORATION.md`) was overkill. Command execution is stateless — it just needs a tape, prompt, and state. Two functions with `| None` return type cleanly express the probe-and-execute pattern.

### Note 3: Design Constraints
- Must work with `Agent` facade for backward compat
- Must be callable from `bub_sf` hook impl without constructing `Agent`
- Return type must be `| None` to signal "not a command, fall through"

## Facts

### Fact 1: Current Command Execution Is Embedded in Agent.run()
`bub/src/bub/builtin/agent.py:87-108`
```python
async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
    ...
    if isinstance(prompt, str) and prompt.strip().startswith(","):
        return await self._run_command(tape=tape, line=prompt.strip())
    return await self._agent_loop(...)
```

### Fact 2: Current Command Execution Is Embedded in Agent.run_stream()
`bub/src/bub/builtin/agent.py:135-150`
```python
if isinstance(prompt, str) and prompt.strip().startswith(","):
    result = await self._run_command(tape=tape, line=prompt.strip())
    events = self._events_from_iterable([
        StreamEvent("text", {"delta": result}),
        StreamEvent("final", {"text": result, "ok": True}),
    ])
else:
    events = await self._agent_loop(..., stream_output=True)
```

### Fact 3: _run_command Signature and Dependencies
`bub/src/bub/builtin/agent.py:152-190`
```python
async def _run_command(self, tape: Tape, *, line: str) -> str:
    context = ToolContext(tape=tape.name, run_id="run_command", state=tape.context.state)
    ...
    if name not in REGISTRY:
        output = await REGISTRY["bash"].run(context=context, cmd=line)
    else:
        args = _parse_args(arg_tokens)
        if REGISTRY[name].context:
            args.kwargs["context"] = context
        output = REGISTRY[name].run(*args.positional, **args.kwargs)
        if inspect.isawaitable(output):
            output = await output
    ...
    await self.tapes.append_event(tape.name, "command", event_payload)
```

Dependencies: `tape`, `REGISTRY`, `ToolContext`, `self.tapes.append_event`

## Claims

### Claim 1: Two Probed Functions Are the Minimal Extraction
**Reasoning:** Instead of a class, two module-level functions suffice:
- `run_command(tape, prompt, state) -> str | None`
- `run_command_stream(tape, prompt, state) -> AsyncStreamEvents | None`

Each probes `prompt.startswith(",")`, parses/executes if matched, returns `None` otherwise. This is the smallest viable extraction.

**References:** Fact 3

### Claim 2: `| None` Return Type Makes the Probe Explicit
**Reasoning:** Returning `None` when the prompt is not a command makes the dispatch visible at the type level. Callers must handle the `None` case, which naturally routes to the agent loop or SystemF evaluation.

**References:** Fact 1, Fact 2

### Claim 3: Functions Can Be Called Without Agent Construction
**Reasoning:** The functions only need `tape` (with `tape.context.state` populated), `prompt`, and `state`. `bub_sf` can call them after setting up the tape via `load_state` / `get_tape_name`, without ever constructing an `Agent` instance.

**References:** Fact 3

### Claim 4: Command Logging Should Be Optional or External
**Reasoning:** `_run_command` calls `self.tapes.append_event` for command logging. If the function is module-level, logging must be injected or made optional. The simplest approach: accept an optional `log_command` callback, or skip logging entirely (it's a side effect, not essential to execution).

**References:** Fact 3

## Proposed Refactor

```python
# agent.py — module-level functions

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
    async def generator() -> AsyncIterator:
        for item in iterable:
            yield item
    return AsyncStreamEvents(generator())


async def run_command_stream(tape: Tape, prompt: str | list[dict]) -> AsyncStreamEvents | None:
    """Execute command in streaming form. Return None if not a command."""
    result = await run_command(tape, prompt)
    if result is None:
        return None
    
    events = [
        StreamEvent("text", {"delta": result}),
        StreamEvent("final", {"text": result, "ok": True}),
    ]
    return _events_from_iterable(events)


# Agent facade uses the probed functions

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
            events = [
                StreamEvent("text", {"delta": "error: empty prompt"}),
                StreamEvent("final", {"text": "error: empty prompt", "ok": False}),
            ]
            return _events_from_iterable(events)
        
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        merge_back = not state.get("session_id", "").startswith("temp/")
        stack = AsyncExitStack()
        await stack.enter_async_context(self.tapes.fork_tape(tape.name, merge_back=merge_back))
        await self.tapes.ensure_bootstrap_anchor(tape.name)
        
        if (events := await run_command_stream(tape, prompt)) is not None:
            return _events_with_callback(events, callback=stack.aclose)
        
        events = await self._agent_loop(..., stream_output=True)
        return _events_with_callback(events, callback=stack.aclose)
```
