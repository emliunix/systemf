# Agent Class Split — Command Processor vs Agent Loop

## Notes

### Note 1: Goal
Split `Agent` in `bub/src/bub/builtin/agent.py` into two independent tasks with a **structural dispatch** at the entry point:
1. **Command handling** — execute `,`-prefixed commands
2. **Agent loop** — run the LLM agent loop

The dispatcher checks the prompt and routes to exactly one of the two code paths. Tape and session setup (determining `tape_name` and `session_id`) is already handled by `load_state` and `get_tape_name` — it should not be mixed into agent execution code.

### Note 2: Context
The Layered Turn Architecture (see `bub_sf/docs/agent-design.md`) has three conceptual layers:
1. **Setup** — determine tape and session (handled by `load_state` / `get_tape_name`)
2. **Command processing** — execute `,`-prefixed commands
3. **Agent call** — run the LLM agent loop

Currently `Agent.run()` and `Agent.run_stream()` embed the dispatch logic inside the method, conflating layers 2 and 3. This prevents `bub_sf` from executing commands without also invoking the agent loop.

### Note 3: Scope
- Extract `CommandProcessor` from `Agent._run_command`
- Extract `AgentLoop` from `Agent._agent_loop`
- Create a clear **dispatch entry point** that routes to one or the other
- Keep `Agent` as a facade for backward compatibility
- Make it possible to use `CommandProcessor` without `AgentLoop`, and vice versa

## Facts

### Fact 1: Agent.run() Mixes Command and Agent Loop
`bub/src/bub/builtin/agent.py:87-108`
```python
async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
    if not prompt:
        return "error: empty prompt"
    tape = self.tapes.tape(tape_name)
    tape.context = replace(tape.context, state=state)
    merge_back = not state.get("session_id", "").startswith("temp/")
    async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
        await self.tapes.ensure_bootstrap_anchor(tape.name)
        if isinstance(prompt, str) and prompt.strip().startswith(","):
            return await self._run_command(tape=tape, line=prompt.strip())  # command
        return await self._agent_loop(...)                                # agent loop
```

### Fact 2: Agent.run_stream() Also Mixes Both
`bub/src/bub/builtin/agent.py:110-150`
```python
async def run_stream(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> AsyncStreamEvents:
    if not prompt:
        ...
    tape = self.tapes.tape(tape_name)
    tape.context = replace(tape.context, state=state)
    merge_back = not state.get("session_id", "").startswith("temp/")
    stack = AsyncExitStack()
    await stack.enter_async_context(self.tapes.fork_tape(tape.name, merge_back=merge_back))
    await self.tapes.ensure_bootstrap_anchor(tape.name)
    if isinstance(prompt, str) and prompt.strip().startswith(","):
        result = await self._run_command(tape=tape, line=prompt.strip())  # command
        events = self._events_from_iterable([...])
    else:
        events = await self._agent_loop(..., stream_output=True)          # agent loop
    return self._events_with_callback(events, callback=stack.aclose)
```

### Fact 3: _run_command Has No Dependency on _agent_loop
`bub/src/bub/builtin/agent.py:152-190`
```python
async def _run_command(self, tape: Tape, *, line: str) -> str:
    line = line[1:].strip()
    if not line:
        raise ValueError("empty command")
    name, arg_tokens = _parse_internal_command(line)
    start = time.monotonic()
    context = ToolContext(tape=tape.name, run_id="run_command", state=tape.context.state)
    output = ""
    status = "ok"
    try:
        if name not in REGISTRY:
            output = await REGISTRY["bash"].run(context=context, cmd=line)
        else:
            args = _parse_args(arg_tokens)
            if REGISTRY[name].context:
                args.kwargs["context"] = context
            output = REGISTRY[name].run(*args.positional, **args.kwargs)
            if inspect.isawaitable(output):
                output = await output
    except Exception as exc:
        status = "error"
        output = f"{exc!s}"
        raise
    else:
        return output if isinstance(output, str) else str(output)
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        output_text = output if isinstance(output, str) else str(output)
        event_payload = {
            "raw": line, "name": name, "status": status,
            "elapsed_ms": elapsed_ms, "output": output_text,
            "date": datetime.now(UTC).isoformat(),
        }
        await self.tapes.append_event(tape.name, "command", event_payload)
```

### Fact 4: _agent_loop Has No Dependency on _run_command
`bub/src/bub/builtin/agent.py:216-256`
```python
async def _agent_loop(self, *, tape: Tape, prompt: str | list[dict], model: str | None = None,
                     allowed_skills: Collection[str] | None = None,
                     allowed_tools: Collection[str] | None = None,
                     stream_output: bool = False) -> AsyncStreamEvents | str:
    next_prompt: str | list[dict] = prompt
    display_model = model or self.settings.model
    await self.tapes.append_event(tape.name, "loop.start", {...})
    if stream_output:
        state = StreamState()
        iterator = self._stream_events_with_auto_handoff(...)
        return AsyncStreamEvents(iterator, state=state)
    else:
        return await self._run_tools_with_auto_handoff(...)
```

### Fact 5: Callers of Agent
- `bub/src/bub/builtin/hook_impl.py:69-72` — `_get_agent()` creates `Agent(self.framework)`
- `bub/src/bub/builtin/hook_impl.py:161-168` — `run_model` and `run_model_stream` call `Agent.run()` / `Agent.run_stream()`
- `bub/src/bub/builtin/tools.py` — `subagent` tool calls `agent.run()` / `agent.run_stream()`
- `bub/src/bub/channels/cli/__init__.py` — `CliChannel` receives `Agent` directly

## Claims

### Claim 1: CommandProcessor Should Be Independent
**Reasoning:** `_run_command` only needs `tape`, `REGISTRY`, and `ToolContext` (Fact 3). It does not call `_agent_loop` or access `self.settings`. Extracting it as `CommandProcessor` allows `bub_sf` to execute commands without invoking the agent loop.

**References:** Fact 3

### Claim 2: AgentLoop Should Be Independent
**Reasoning:** `_agent_loop` only needs `tape`, `self.settings`, and `self.framework` (Fact 4). It never checks for commands or calls `_run_command`. Extracting it as `AgentLoop` allows `bub_sf` to run the agent loop without command processing overhead.

**References:** Fact 4

### Claim 3: Tape Forking Is Turn Lifecycle, Not Setup
**Reasoning:** The forking and bootstrap in `run()`/`run_stream()` (Fact 1, Fact 2) is part of the turn execution lifecycle, not "setup" in the architectural sense. Setup (determining `tape_name` and `session_id`) is handled by `load_state` and `get_tape_name` before `Agent` is called. Both `CommandProcessor` and `AgentLoop` should receive an already-prepared `Tape` and operate within the fork context managed by the caller.

**References:** Fact 1, Fact 2

### Claim 4: Backward Compatibility Requires a Facade
**Reasoning:** Four distinct call sites instantiate or use `Agent` (Fact 5). A complete API break would require coordinated changes across `bub`. Instead, keep `Agent` as a facade that delegates to `CommandProcessor` and `AgentLoop`. This lets `bub_sf` use the sub-components directly while existing callers continue to work.

**References:** Fact 5

### Claim 5: The Split Enables bub_sf to Interpose Dispatch
**Reasoning:** With the current monolithic `Agent`, `bub_sf` cannot execute commands without also running the agent loop (because its `run_model_stream` bypasses command handling entirely). After the split, `bub_sf` can:
1. Receive `tape_name` from setup layer (already handled)
2. Use the **structural dispatch** to check for `,`-prefix
3. If command: use `CommandProcessor`
4. If not: use its own SystemF evaluation or fall back to `AgentLoop`
The dispatch is a first-class structural element, not an `if` statement buried inside `Agent.run()`.

**References:** Fact 1, `bub_sf/docs/agent-design.md`

### Claim 6: Dispatch Should Be Structural, Not Inline
**Reasoning:** Currently the dispatch `if prompt.startswith(",")` is inline inside `Agent.run()` and `Agent.run_stream()` (Fact 1, Fact 2). This makes it impossible to reuse the dispatch logic or override it. A structural dispatch — either as a separate `TurnDispatcher` class or as explicit `dispatch_command()` / `dispatch_agent()` methods — makes the routing visible and overridable.

**References:** Fact 1, Fact 2, Claim 5

### Claim 7: The Two Tasks Have Different Return Types That Must Be Unified at the Dispatch Boundary
**Reasoning:** `CommandProcessor.execute()` returns `str` (Fact 3). `AgentLoop.run()` returns `str` and `AgentLoop.run_stream()` returns `AsyncStreamEvents` (Fact 4). The current `Agent` has two entry points (`run` → `str`, `run_stream` → `AsyncStreamEvents`) that each do their own dispatch. After splitting, the dispatcher must handle the return type asymmetry:
- In the **non-streaming** path, both return `str` — easy to unify.
- In the **streaming** path, commands return `str` but the agent loop returns `AsyncStreamEvents`. The dispatcher must wrap the command result into `AsyncStreamEvents` (as `Agent.run_stream()` currently does via `_events_from_iterable`).

This suggests the dispatcher should own the return-type normalization, not the individual tasks.

**References:** Fact 3, Fact 4, Fact 1, Fact 2

## Validation

### Validated Claims

| Claim | Status | Notes |
|---|---|---|
| Claim 1: CommandProcessor independent | ✅ Validated | `_run_command` uses only `tape` + `REGISTRY` + `ToolContext` |
| Claim 2: AgentLoop independent | ✅ Validated | `_agent_loop` uses only `tape` + `settings` + `framework` |
| Claim 3: Tape forking is lifecycle | ✅ Validated | Fork/bootstrap happens inside `run()`/`run_stream()`, not in setup layer |
| Claim 4: Backward compat via facade | ✅ Validated | Four callers exist; facade prevents breaking changes |
| Claim 5: Enables bub_sf interposition | ✅ Validated | Dispatcher lets bub_sf route commands independently |
| Claim 6: Structural dispatch | ✅ Validated | Inline `if` in `Agent.run()` is not reusable; `TurnDispatcher` is |
| Claim 7: Return type unification | ✅ Validated | Command → `str`, agent loop → `str` or `AsyncStreamEvents`; dispatcher normalizes |

## Proposed Split

### Task 1: CommandProcessor (returns `str`)

```python
class CommandProcessor:
    """Executes ,-prefixed commands. Returns plain string."""
    
    def __init__(self, tapes: TapeService) -> None:
        self.tapes = tapes
    
    async def execute(self, tape: Tape, line: str) -> str:
        """Execute a command line (including the leading ,). Returns plain text."""
        line = line[1:].strip()
        if not line:
            raise ValueError("empty command")
        name, arg_tokens = _parse_internal_command(line)
        start = time.monotonic()
        context = ToolContext(tape=tape.name, run_id="run_command", state=tape.context.state)
        output = ""
        status = "ok"
        try:
            if name not in REGISTRY:
                output = await REGISTRY["bash"].run(context=context, cmd=line)
            else:
                args = _parse_args(arg_tokens)
                if REGISTRY[name].context:
                    args.kwargs["context"] = context
                output = REGISTRY[name].run(*args.positional, **args.kwargs)
                if inspect.isawaitable(output):
                    output = await output
        except Exception as exc:
            status = "error"
            output = f"{exc!s}"
            raise
        else:
            return output if isinstance(output, str) else str(output)
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            output_text = output if isinstance(output, str) else str(output)
            await self.tapes.append_event(tape.name, "command", {
                "raw": line, "name": name, "status": status,
                "elapsed_ms": elapsed_ms, "output": output_text,
                "date": datetime.now(UTC).isoformat(),
            })
```

### Task 2: AgentLoop (returns `str` or `AsyncStreamEvents`)

```python
class AgentLoop:
    """Runs the LLM agent loop with auto-handoff."""
    
    def __init__(self, tapes: TapeService, settings: AgentSettings, framework: BubFramework) -> None:
        self.tapes = tapes
        self.settings = settings
        self.framework = framework
    
    async def run(self, tape: Tape, prompt: str | list[dict], ...) -> str:
        """Non-streaming agent loop. Returns plain text."""
        ...
    
    async def run_stream(self, tape: Tape, prompt: str | list[dict], ...) -> AsyncStreamEvents:
        """Streaming agent loop. Returns event stream."""
        ...
```

### Structural Dispatch

The dispatcher owns the routing and return-type normalization:

```python
class TurnDispatcher:
    """Dispatches a turn to either command handling or agent loop."""
    
    def __init__(self, commands: CommandProcessor, loop: AgentLoop) -> None:
        self.commands = commands
        self.loop = loop
    
    def is_command(self, prompt: str | list[dict]) -> bool:
        return isinstance(prompt, str) and prompt.strip().startswith(",")
    
    async def run(self, tape: Tape, prompt: str | list[dict], ...) -> str:
        """Non-streaming dispatch. Both paths return str."""
        if self.is_command(prompt):
            return await self.commands.execute(tape, prompt.strip())
        return await self.loop.run(tape, prompt, ...)
    
    async def run_stream(self, tape: Tape, prompt: str | list[dict], ...) -> AsyncStreamEvents:
        """Streaming dispatch. Commands are wrapped into AsyncStreamEvents."""
        if self.is_command(prompt):
            result = await self.commands.execute(tape, prompt.strip())
            # Normalize str -> AsyncStreamEvents
            events = [
                StreamEvent("text", {"delta": result}),
                StreamEvent("final", {"text": result, "ok": True}),
            ]
            return _events_from_iterable(events)
        return await self.loop.run_stream(tape, prompt, ...)
```

### Facade for Backward Compatibility

```python
class Agent:
    """Facade: owns tape lifecycle and delegates to dispatcher."""
    
    def __init__(self, framework: BubFramework) -> None:
        self.settings = load_settings()
        self.framework = framework
        self._commands = CommandProcessor(self.tapes)
        self._loop = AgentLoop(self.tapes, self.settings, self.framework)
        self._dispatcher = TurnDispatcher(self._commands, self._loop)
    
    @cached_property
    def tapes(self) -> TapeService:
        ...
    
    async def run(self, *, tape_name: str, prompt: str | list[dict], state: State, ...) -> str:
        if not prompt:
            return "error: empty prompt"
        tape = self.tapes.tape(tape_name)
        tape.context = replace(tape.context, state=state)
        merge_back = not state.get("session_id", "").startswith("temp/")
        async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
            await self.tapes.ensure_bootstrap_anchor(tape.name)
            return await self._dispatcher.run(tape, prompt, ...)
    
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
        events = await self._dispatcher.run_stream(tape, prompt, ...)
        return _events_with_callback(events, callback=stack.aclose)
```
