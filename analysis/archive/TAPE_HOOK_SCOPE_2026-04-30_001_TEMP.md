# Tape Hook Scope Exploration

**Status:** Validated  
**Last Updated:** 2026-04-30  
**Central Question:** How do hook calling scopes affect tape customization, and what's the gap for SystemF extensions?  
**Topics:** hooks, scope, agent, subagent, tape_id, fork, handoff

---

## Notes

### Note 1: Trace Hook Call Paths for Main vs Subagent

We need to trace the exact code paths where hooks are called to determine which hooks fire for main agents vs subagents. The main entry point is `BubFramework.process_inbound()`, but subagents may enter through other paths.

### Note 2: Identify Tape Naming Customization Points

We need to find all places where tape names are determined and check if extensions can inject custom tape IDs. This includes checking `session_tape()`, state keys, and hook return values.

### Note 3: Determine if Store Is Shared or Isolated

We need to understand whether the tape store is created once and shared, or if each agent run gets an isolated store. This affects whether extensions can have private tape storage.

### Note 4: Check if Storage Enforces Boundaries

We need to determine if the `TapeStore` protocol or its implementations enforce session/workspace boundaries, or if isolation is purely a naming convention.

### Note 5: Summarize Findings for SystemF Extension

After validating the claims, we need to synthesize the implications: extensions cannot customize tape names due to hardwired hashing and subagent hook bypass, so they must work within the shared tape using namespacing or request framework changes.

---

## Facts

### Fact 1: Framework Entry Point Orchestrates Full Hook Suite

`BubFramework.process_inbound()` at `bub/src/bub/framework.py:105-144` calls hooks in this sequence:

```python
async def process_inbound(self, inbound: Envelope, stream_output: bool = False) -> TurnResult:
    session_id = await self._hook_runtime.call_first(
        "resolve_session", message=inbound
    ) or self._default_session_id(inbound)
    state = {"_runtime_workspace": str(self.workspace)}
    for hook_state in reversed(
        await self._hook_runtime.call_many("load_state", message=inbound, session_id=session_id)
    ):
        if isinstance(hook_state, dict):
            state.update(hook_state)
    prompt = await self._hook_runtime.call_first(
        "build_prompt", message=inbound, session_id=session_id, state=state
    )
    model_output = await self._run_model(inbound, prompt, session_id, state, stream_output)
    await self._hook_runtime.call_many(
        "save_state", session_id=session_id, state=state, message=inbound, model_output=model_output
    )
    outbounds = await self._collect_outbounds(inbound, session_id, state, model_output)
    for outbound in outbounds:
        await self._hook_runtime.call_many("dispatch_outbound", message=outbound)
```

### Fact 2: Subagent Tool Bypasses Framework Entry Point

`run_subagent` tool at `bub/src/bub/builtin/tools.py:256-277` calls `agent.run_stream()` directly:

```python
async def run_subagent(param: SubAgentInput, *, context: ToolContext) -> str:
    agent = _get_agent(context)
    subagent_session = f"temp/{uuid.uuid4().hex[:8]}"
    state = {**context.state, "session_id": subagent_session}
    async for event in await agent.run_stream(
        session_id=subagent_session,
        prompt=param.prompt,
        state=state,
        ...
    ):
        ...
```

### Fact 3: Agent.run_stream() Skips Framework Hooks

`Agent.run_stream()` at `bub/src/bub/builtin/agent.py:110-150` sets up tape and runs agent loop without framework hooks:

```python
async def run_stream(self, *, session_id: str, prompt: str | list[dict], state: State, ...) -> AsyncStreamEvents:
    tape = self.tapes.session_tape(session_id, workspace_from_state(state))
    tape.context = replace(tape.context, state=state)
    merge_back = not session_id.startswith("temp/")
    await stack.enter_async_context(self.tapes.fork_tape(tape.name, merge_back=merge_back))
    await self.tapes.ensure_bootstrap_anchor(tape.name)
    events = await self._agent_loop(tape=tape, prompt=prompt, ...)
    return self._events_with_callback(events, callback=stack.aclose)
```

### Fact 4: Tape Store Is Cached Singleton

`Agent.tapes` at `bub/src/bub/builtin/agent.py:57-66`:

```python
class Agent:
    @cached_property
    def tapes(self) -> TapeService:
        tape_store = self.framework.get_tape_store()
        if tape_store is None:
            tape_store = InMemoryTapeStore()
        tape_store = ForkTapeStore(tape_store)
        llm = _build_llm(self.settings, tape_store, self.framework.build_tape_context())
        return TapeService(llm, bub.home / "tapes", tape_store)
```

### Fact 5: Tape Store Hook Is App-Level

`BubFramework.get_tape_store()` at `bub/src/bub/framework.py:256-257`:

```python
def get_tape_store(self) -> TapeStore | AsyncTapeStore | None:
    return self._hook_runtime.call_first_sync("provide_tape_store")
```

### Fact 6: Tape Name Is Pure Hash Function

`session_tape()` at `bub/src/bub/builtin/tape.py:120-124`:

```python
def session_tape(self, session_id: str, workspace: Path) -> Tape:
    workspace_hash = hashlib.md5(
        str(workspace.resolve()).encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:16]
    tape_name = (
        workspace_hash + "__" + 
        hashlib.md5(session_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    )
    return self._llm.tape(tape_name)
```

### Fact 7: Storage Protocol Is Flat String Namespace

`TapeStore` protocol at `republic/tape/store.py:21-30`:

```python
class TapeStore(Protocol):
    def list_tapes(self) -> list[str]: ...
    def reset(self, tape: str) -> None: ...
    def fetch_all(self, query: TapeQuery) -> Iterable[TapeEntry]: ...
    def append(self, tape: str, entry: TapeEntry) -> None: ...
```

### Fact 8: System Prompt Hook Called from Agent

`Agent._system_prompt()` at `bub/src/bub/builtin/agent.py:563-566` calls `framework.get_system_prompt()`:

```python
def _system_prompt(self, prompt: str, state: State, ...) -> str:
    if result := self.framework.get_system_prompt(prompt=prompt, state=state):
        blocks.append(result)
```

Which delegates to `framework.get_system_prompt()` at `bub/src/bub/framework.py:259-264`:

```python
def get_system_prompt(self, prompt: str | list[dict], state: dict[str, Any]) -> str:
    return "\n\n".join(
        result for result in reversed(
            self._hook_runtime.call_many_sync("system_prompt", prompt=prompt, state=state)
        ) if result
    )
```

---

## Claims

### Claim 1: Main Agent Is the Only Path That Triggers Full Hook Suite

**Reasoning:** `BubFramework.process_inbound()` (Fact 1) is the exclusive entry point for the full hook sequence: `resolve_session` → `load_state` → `build_prompt` → model execution → `save_state` → `render_outbound` → `dispatch_outbound`. Any code that calls `Agent.run()` or `Agent.run_stream()` directly (Fact 2, Fact 3) bypasses this entire sequence.

**References:** Fact 1, Fact 2, Fact 3

---

### Claim 2: Subagents Bypass All Framework-Level Hooks Except system_prompt

**Reasoning:** The `run_subagent` tool (Fact 2) calls `agent.run_stream()` directly. `Agent.run_stream()` (Fact 3) sets up the tape and runs the agent loop without any framework hook calls. The only hook still triggered is `system_prompt` (Fact 8), which is called from within `Agent._run_once()` during model execution. This means `load_state`/`save_state` hooks never see subagent turns.

**References:** Fact 1, Fact 2, Fact 3, Fact 8

---

### Claim 3: There Is No Customization Point for Tape Names

**Reasoning:** `session_tape()` (Fact 6) is a pure hash function. It accepts only `session_id` and `workspace`, with no state lookup, no hook invocation, and no override parameter. Since subagents bypass `load_state` (Claim 2), even if a hook wanted to inject a `tape_id` into state, the subagent path would never trigger that hook.

**References:** Fact 6, Claim 2

---

### Claim 4: All Agent Runs Share the Same Persistent Storage Backend

**Reasoning:** `Agent.tapes` is a `cached_property` (Fact 4). It calls `framework.get_tape_store()` once, wraps it in `ForkTapeStore`, and caches the result. The `provide_tape_store` hook is app-level (Fact 5). All subsequent calls to `agent.run()` or `agent.run_stream()` reuse this same `TapeService`. The `fork_tape()` context manager provides per-run isolation via an in-memory overlay, but the underlying store is shared application-wide.

**References:** Fact 4, Fact 5

---

### Claim 5: Session/Workspace Isolation Is Pure Naming Convention

**Reasoning:** The `TapeStore` protocol (Fact 7) operates on flat string names with zero awareness of session or workspace. The `FileTapeStore` stores ALL tapes in a single directory (`~/.bub/tapes/`). The only "isolation" comes from `session_tape()` embedding workspace and session hashes into the tape name string (Fact 6). Any code with knowledge of a tape name string can read/write it.

**References:** Fact 7, Fact 6

---

### Claim 6: Hook Scope Is Determined by Call Site, Not Hook Type

**Reasoning:** The same hook mechanism is invoked from different scopes. `provide_tape_store` is called once during framework initialization (Fact 5, via `cached_property`). `system_prompt` is called every time the agent runs a model (Fact 8, from `Agent._run_once()`). `load_state`/`save_state` are called once per inbound message turn (Fact 1, from `Framework.process_inbound()`). This means subagents, which bypass `process_inbound()` (Claim 2), never trigger `load_state`/`save_state` even though they still trigger `system_prompt`.

**References:** Fact 1, Fact 5, Fact 8, Claim 2

---

## Open Questions

- [ ] Can we add `tape_id` override to `Agent.run()` without breaking existing behavior?
- [ ] Should subagents route through `framework.process_inbound()` for hook parity?
- [ ] If an extension provides a custom `TapeStore`, does it replace the shared one or supplement it?

## Related Topics

- `analysis/TAPE_EXPLORATION.md` — Master exploration with primitives and hierarchy
