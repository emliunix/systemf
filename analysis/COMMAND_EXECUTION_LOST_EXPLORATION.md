# Command Execution Lost After SystemF Takes Control of run_model_stream

## Notes

### Note 1: Context
When `bub_sf` plugin is active, it intercepts the `run_model_stream` hook and evaluates the SystemF `main.main` function instead of running the default Bub agent loop. The normal agent loop handles `,`-prefixed commands (e.g., `,sf.repl`) via `Agent._run_command`. When SystemF takes control, this command path is bypassed entirely.

### Note 2: Scope
This exploration covers:
- How commands are handled in the default Bub agent loop
- How `SFHookImpl.run_model_stream` bypasses command handling
- What options exist to restore command execution

Out of scope:
- General SystemF REPL behavior (covered in `ELAB3_PROJECT_STATUS.md`)
- Tape management details (covered in `TAPE_EXPLORATION.md`)

### Note 3: Entry Points
- `bub/src/bub/builtin/agent.py:104-105` — command check in `Agent.run()`
- `bub/src/bub/builtin/agent.py:135-136` — command check in `Agent.run_stream()`
- `bub_sf/src/bub_sf/hook.py:153-170` — `SFHookImpl.run_model_stream()`

## Facts

### Fact 1: Default Agent Loop Checks for Commands
`bub/src/bub/builtin/agent.py:104-105`
```python
if isinstance(prompt, str) and prompt.strip().startswith(","):
    return await self._run_command(tape=tape, line=prompt.strip())
```

### Fact 2: Streaming Path Also Checks for Commands
`bub/src/bub/builtin/agent.py:135-136`
```python
if isinstance(prompt, str) and prompt.strip().startswith(","):
    result = await self._run_command(tape=tape, line=prompt.strip())
```

### Fact 3: SystemF Hook Does Not Check for Commands
`bub_sf/src/bub_sf/hook.py:153-170`
```python
async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
    if not isinstance(prompt, str):
        raise Exception("Only string prompt is supported for now")

    repl = await self.get_or_create(session_id)
    repl.state["bub_state"] = state
    # eval: main prompt
    main = repl.lookup(repl.resolve_name(QualName("main", "main")))
    if not isinstance(main, AnId):
        raise Exception("main.main is not an Id")
    res = await repl.unsafe_eval(C.app(C.var(main.id), C.lit(LitString(prompt))))
    match res:
        case VPrim([AsyncStreamEvents() as events, _]):
            return events
        case _:
            raise Exception(f"Expected AsyncStreamEvents from main.main, got {res}")
```

### Fact 4: Hook Precedence Puts bub_sf First
`bub/src/bub/hook_runtime.py:178-192`
`HookRuntime.run_model_stream()` checks plugins in reverse registration order. Since `BuiltinImpl` is loaded first and `bub_sf` is discovered later, `reversed()` puts `bub_sf` first. If `bub_sf` implements `run_model_stream`, it shadows `BuiltinImpl`'s implementation.

### Fact 5: Commands Are Routed via build_prompt Hook
`bub/src/bub/builtin/hook_impl.py:132-136`
```python
async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
```
The `build_prompt` hook marks messages starting with `,` as commands, but this only sets `message.kind = "command"` and returns the content. The actual command execution happens in `Agent._run_command`.

## Claims

### Claim 1: Command Execution Is Lost Because SystemF Hook Bypasses Agent Loop
**Reasoning:** The default agent loop (`Agent.run` and `Agent.run_stream`) explicitly checks if the prompt starts with `,` and routes it to `_run_command` (Fact 1, Fact 2). When `bub_sf` intercepts `run_model_stream`, it directly evaluates `main.main` without any command check (Fact 3). Because `bub_sf` has higher hook precedence (Fact 4), the default agent loop never runs. Therefore, any `,`-prefixed command sent while `bub_sf` is active will be passed to `main.main` as a regular prompt instead of being executed as a command.
**References:** Fact 1, Fact 2, Fact 3, Fact 4

### Claim 2: build_prompt Hook Alone Cannot Restore Command Execution
**Reasoning:** The `build_prompt` hook marks commands but does not execute them (Fact 5). Command execution is the responsibility of the agent loop, which is bypassed when `bub_sf` takes control. Even if `build_prompt` identifies a command, `SFHookImpl.run_model_stream` would still receive the prompt and attempt to evaluate it via SystemF.
**References:** Fact 3, Fact 5

### Claim 3: The Correct Architecture Is Layered — Setup, Commands, Then Agent
**Reasoning:** The `run_model_stream` hook should follow a strict three-layer sequence: (1) determine tape and setup state, (2) check for and process commands, (3) only if not a command, invoke the agent (SystemF `main` or default Bub agent). Currently, `SFHookImpl` conflates steps 1 and 3 by skipping step 2 (Fact 3). The default agent loop correctly does all three (Fact 1, Fact 2). Command processing must happen **before** the agent call because commands are meta-level operations (e.g., `,sf.repl` evaluates SystemF expressions directly, `,tape.handoff` manipulates tape state) that should not be interpreted as user prompts.
**References:** Fact 1, Fact 2, Fact 3, Claim 1

### Claim 4: Pre-Dispatch Check Is the Minimal Fix
**Reasoning:** The simplest way to align with the layered architecture (Claim 3) is to add a command check at the top of `SFHookImpl.run_model_stream` before evaluating `main.main`. If `prompt.startswith(",")`, route to `Agent._run_command` or equivalent. This preserves the existing agent loop's command handling without requiring new SystemF primitives or hook fallback gymnastics. The `bub_sf` plugin already has access to the agent via `state["_runtime_agent"]` (used by `bub_ext.py` for LLM calls).
**References:** Fact 3, Claim 3
