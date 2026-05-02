# Agent Vendoring Design

## Goal

Extract `bub.builtin.agent.Agent` from the bub framework so it can be vendored into `bub_sf`, then hook it back into bub via the `run_model_stream` (and `run_model`) hook specs.

## Style

- **Provenance**: Facts must be annotated with provenance — file path, line number, and class/function name. This applies to code snippets, behavioral claims, and architectural observations.
  - Preferred inline form: `# file.py:123-145` or `# file.py:123` for code block headers
  - Preferred prose form: `` `ClassName.method_name()` in `path/to/file.py:123` ``

## Current Architecture

### Agent Class Location

- **File**: `bub/src/bub/builtin/agent.py` (657 lines)
- **Class**: `Agent` — "Republic-driven runtime engine to process prompts"

### Agent Public API

| Method | Returns | Description |
|--------|---------|-------------|
| `Agent(framework: BubFramework)` | `Agent` | Constructor; caches settings, framework reference |
| `run(session_id, prompt, state, ...)` | `str` | Synchronous-style turn execution |
| `run_stream(session_id, prompt, state, ...)` | `AsyncStreamEvents` | Streaming turn execution |

### Internal Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `_run_command(tape, line)` | `str` | Handles `,`-prefixed internal commands |
| `_agent_loop(tape, prompt, ..., stream_output)` | `str` or `AsyncStreamEvents` | Main loop with auto-handoff, max_steps, tool execution |
| `_run_tools_with_auto_handoff(...)` | `str` | Non-streaming agent loop |
| `_stream_events_with_auto_handoff(...)` | `AsyncGenerator[StreamEvent]` | Streaming agent loop |
| `_run_once(tape, prompt, ..., stream_output)` | `ToolAutoResult` or `AsyncStreamEvents` | Single LLM call + tool execution |
| `_system_prompt(prompt, state, allowed_skills)` | `str` | Builds system prompt from framework hooks + tools + skills |
| `_load_skills_prompt(prompt, workspace, allowed_skills)` | `str` | Discovers and renders skills prompt |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `tapes` | `TapeService` | Lazily initialized; builds `LLM` + `ForkTapeStore` + tape context |
| `settings` | `AgentSettings` | Loaded at construction time |
| `framework` | `BubFramework` | Injected reference |

## Hook Wiring (Current)

The `BuiltinImpl` class in `bub/src/bub/builtin/hook_impl.py` implements the model hooks:

```python
# hook_impl.py:159-165
@hookimpl
async def run_model(self, prompt, session_id, state) -> str:
    return await self._get_agent().run(session_id=session_id, prompt=prompt, state=state)

@hookimpl
async def run_model_stream(self, prompt, session_id, state) -> AsyncStreamEvents:
    return await self._get_agent().run_stream(session_id=session_id, prompt=prompt, state=state)
```

`BuiltinImpl._get_agent()` lazily creates and caches `Agent(self.framework)`.

## Agent Dependencies

### Direct imports in `agent.py`

| Import | Source | Used For |
|--------|--------|----------|
| `LLM`, `AsyncStreamEvents`, `AsyncTapeStore`, `RepublicError`, `StreamEvent`, `StreamState`, `TapeContext`, `ToolAutoResult`, `ToolContext` | `republic` | Core LLM runtime |
| `InMemoryTapeStore`, `Tape` | `republic.tape` | Tape storage fallback |
| `AgentSettings`, `load_settings` | `bub.builtin.settings` | Configuration |
| `ForkTapeStore` | `bub.builtin.store` | Tape forking |
| `TapeService` | `bub.builtin.tape` | Tape lifecycle management |
| `BubFramework` | `bub.framework` | Framework reference (tape store, tape context, system prompt) |
| `discover_skills`, `render_skills_prompt` | `bub.skills` | Skill discovery |
| `REGISTRY`, `model_tools`, `render_tools_prompt` | `bub.tools` | Tool registry |
| `State` | `bub.types` | Type alias |
| `workspace_from_state` | `bub.utils` | Workspace extraction |

### Framework interactions

The Agent calls back into `BubFramework` via:

1. `framework.get_tape_store()` → `TapeStore | AsyncTapeStore | None`
2. `framework.build_tape_context()` → `TapeContext`
3. `framework.get_system_prompt(prompt, state)` → `str`

## Reverse Dependencies (Who Uses Agent)

### 1. `builtin/hook_impl.py`

- **Imports**: `from bub.builtin.agent import Agent`
- **Usage**: Creates `Agent(self.framework)` in `_get_agent()`
- **Wires**: `run_model` and `run_model_stream` hooks
- **State injection**: `load_state` puts agent into `state["_runtime_agent"]`

### 2. `builtin/tools.py`

- **Imports**: `from bub.builtin.agent import Agent` (TYPE_CHECKING guarded)
- **Usage**: `_get_agent(context: ToolContext)` extracts agent from `context.state["_runtime_agent"]`
- **Consumer**: `subagent` tool calls `agent.run()` / `agent.run_stream()` to spawn sub-agents

### 3. `channels/cli/__init__.py`

- **Imports**: `from bub.builtin.agent import Agent`
- **Usage**: `CliChannel.__init__(on_receive, agent)` takes Agent directly
- **Accesses**: `agent.tapes`, `agent.framework.workspace`

## Design Thoughts / Change Bits

### Fork Tape as Leaf Scope

The Agent already uses `fork_tape` internally for short-scoped contextual thinking — usually no more than a single turn of the agent loop. This is good: the fork pattern is exactly what we want for isolated, branchable reasoning.

### Session Coupling Problem

The current logic couples tape identity with session management via `session_tape(session_id, workspace)`. This makes true branching hard because the tape name is derived from session + workspace hashes, not from an explicit tape identity.

```python
# builtin/tape.py:120-125 — session_tape is bub-specific
class TapeService:
    def session_tape(self, session_id: str, workspace: Path) -> Tape:
        workspace_hash = hashlib.md5(str(workspace.resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        tape_name = workspace_hash + "__" + hashlib.md5(session_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        return self._llm.tape(tape_name)
```

`session_tape` is **bub-specific** (defined in `bub.builtin.tape.TapeService`, not in republic). The lower-level primitive is `self._llm.tape(tape_name)` which returns a `republic.tape.Tape`.

**Idea**: Refactor Agent to accept a `tape_id` (or `Tape` directly) instead of `session_id`. The caller (framework adapter) maps session → tape, but the Agent itself operates on an explicit tape identity. This decouples branching logic from session management.

### TapeService is a Tool Frontend to the Tape

`TapeService` sits between Agent and the underlying `Tape`/`LLM`. It handles rendering concerns (event logging schema, archive paths, reset) and session name encoding. Key observations:

- `reset()` and `archive_path` suggest it was originally designed around file-based tape persistence
- `_archive()` is explicitly file-based: it dumps the entire tape as JSON Lines to `{tape_name}.jsonl.{timestamp}.bak` under the configured archive directory (`bub.home / "tapes"`)
- `session_tape()` mixes the concept of session into tape identity by encoding `session_id` into the tape name
- `append_event()` provides a structured logging schema on top of raw tape entries
- `handoff()` wraps `tape.handoff_async()` with no added behavior

**Design note:** The underlying SQLite store is append-only, and `reset()` performs an implicit archive before clearing the tape. The archive file path is currently stored in the new session anchor's state (`state={"archived": str(archive_path)}`). With a database-backed store, consider storing the archive name/identifier in the anchor state as well, so the archive reference travels with the tape rather than living only in the filesystem.

### Tape vs tape.name Usage Pattern

Agent receives a `Tape` object from `session_tape()`, but the usage is split:

- **Uses `tape.name` (string)** to call back into `TapeService` for:
  - `fork_tape(tape.name, ...)`
  - `ensure_bootstrap_anchor(tape.name)`
  - `append_event(tape.name, ...)`
  - `handoff(tape.name, ...)`

- **Uses `tape` object directly** for:
  - `tape.context.state` — read/write agent state
  - `tape.stream_events_async(...)` — actual LLM streaming call
  - `tape.run_tools_async(...)` — actual LLM + tools call

So `TapeService` is the "frontend" for logging/forking/management, but the `Tape` itself (from republic) is the "backend" for model execution.

### Builtin Plugin Tool Coupling

Tape manipulation tools (`tape.handoff`, `tape.info`, `tape.reset`, etc.) are exposed from the **builtin plugin** (`bub/src/bub/builtin/tools.py`), which is loaded automatically and difficult to disable. This creates a coupling problem:

- The `tape.handoff` tool calls `_get_agent(context)` and invokes `agent.tapes.handoff(...)` directly (`tools.py:222-227`)
- `tape.info` similarly reaches into `agent.tapes.info(...)` (`tools.py:190-197`)
- These tools assume the agent exposes a `TapeService` with specific methods

**Concern**: If `bub_sf` vendors its own `Agent` with a different tape lifecycle model, the builtin tools will either break or force `bub_sf` to replicate the exact `TapeService` API surface. The tools are not injected — they are hardcoded against the bub builtin agent implementation.

**Implication**: Any agent vendoring effort must either:
1. Re-implement the tape tools in `bub_sf` and suppress the builtin ones
2. Keep `TapeService` as a stable interface that both bub and `bub_sf` implement
3. Push tape tools into a separate, optional plugin rather than the mandatory builtin

### Preferred Architecture: LLM owns Tape, not the other way around

The current republic structure where `Tape.run_tools_async()` and `Tape.stream_events_async()` exist is backwards. A `Tape` should not know how to call tools or stream events — that's an LLM concern.

**Preferred model**: `LLM` has a `tape` field. For zero-state or ephemeral operations, create `LLM(tape=...)` on demand and call `llm.run_tools_async(...)` / `llm.stream_events_async(...)`. The `Tape` is just state/storage; the `LLM` is the executor.

This aligns better with the fork pattern: fork the tape, create an LLM backed by that tape, run the turn, then discard the LLM. The tape persists the state, the LLM is transient.

**Constraint**: `republic` is a low-level library and should not be modified. Any architectural changes must happen at the bub/bub_sf layer.

## Vendoring Strategy Options

### Option A: Extract Agent to `bub_sf` as standalone module

Move `Agent` class and its direct dependencies into `bub_sf`. Agent becomes a library that bub depends on.

**Pros:**
- Clean separation of concerns
- Agent can be tested independently
- bub framework becomes thinner

**Cons:**
- Agent still needs `BubFramework` for callbacks (tape store, system prompt, skills, tools)
- Creates a circular dependency or requires interface extraction
- `CliChannel` and `subagent` tool need refactoring

### Option B: Extract Agent core, keep framework adapter in bub

Split Agent into:
1. **Core engine** (in `bub_sf`): Pure republic-based runtime, no bub framework dependencies
2. **Framework adapter** (in `bub`): Hook implementations that create the core engine and bridge framework callbacks

**Pros:**
- Core engine is truly independent
- Adapter pattern keeps framework integration clean

**Cons:**
- More files to manage
- Need to define clean interface for callbacks (system prompt, skills, tools)

### Option C: Keep Agent in bub, expose via `run_model_stream` contract

Don't move Agent at all. Instead, ensure `bub_sf` can consume the `run_model_stream` hook as a client.

**Pros:**
- Minimal code movement
- Hooks are already the abstraction boundary

**Cons:**
- Doesn't achieve "vendoring" goal
- `bub_sf` would depend on full bub runtime

## Open Questions

1. **Framework callback interface**: If we extract Agent, what interface replaces `BubFramework`? Options:
   - Protocol/class with `get_tape_store()`, `build_tape_context()`, `get_system_prompt()`
   - Pass these as constructor arguments / callbacks
   - Make Agent unaware of framework, push all framework calls into the adapter

2. **Tool registry coupling**: Agent imports `REGISTRY` from `bub.tools`. If vendored, how does Agent know about tools?
   - Option: Inject tool registry at construction
   - Option: Tool registry also moves to `bub_sf`

3. **Skills coupling**: Agent imports `discover_skills` and `render_skills_prompt` from `bub.skills`.
   - Similar to tools: inject or co-vendor

4. **TapeService / ForkTapeStore**: These are in `bub.builtin.*`. Are they part of the agent core or framework infrastructure?

5. **subagent tool**: Lives in `bub.builtin.tools` and calls Agent directly. If Agent moves, this tool must either:
   - Stay in bub and import from `bub_sf`
   - Move to `bub_sf` as well

6. **CLI channel**: Takes `Agent` in constructor. Should it instead get agent from framework/hooks?

7. **Tape identity vs session identity**: Should Agent work with explicit `tape_id`/`Tape` instead of `session_id`? This would let callers manage their own branching/forking logic outside the Agent.

8. **LLM/Tape inversion**: Should we push to invert the LLM/Tape relationship so `LLM(tape=...)` is the primary interface, rather than `Tape.run_tools_async()`?

## Agent Functions

### Input Model

The agent's entry points (`run()` and `run_stream()` at `agent.py:87-151`) take:

| Parameter | Role |
|---|---|
| `session_id` | Used with `workspace` to derive a tape name via `session_tape()` (`builtin/tape.py:120-125`) |
| `prompt` | The user message for this turn |
| `state` | A mutable `dict[str, Any]` that becomes `tape.context.state`; consumed by tools, framework hooks, and the agent loop |
| `model` | Optional model override |
| `allowed_skills` | Case-folded skill whitelist; stored into `tape.context.state["allowed_skills"]` (`agent.py:536`) |
| `allowed_tools` | Case-folded tool whitelist; filters `REGISTRY.values()` before passing to LLM (`agent.py:538-540`) |

**Desired change**: Replace `session_id + workspace` with an explicit `tape_id` (or `Tape` object) so callers manage tape identity directly.

### tape.context.state

`tape.context.state` is the agent's mutable scratchpad. It flows through the system as follows:

1. **Set at entry**: `tape.context = replace(tape.context, state=state)` (`agent.py:100/128`)
2. **Mutated by `_run_once`**: `allowed_skills` is written back into state (`agent.py:536`)
3. **Read by the loop**: `state["context"]` is appended to `CONTINUE_PROMPT` on continuation (`agent.py:311-314`, `429-432`)
4. **Passed to framework hooks**: `framework.get_system_prompt(prompt=prompt, state=state)` (`agent.py:565`)
5. **Accessed by tools**: Tools receive `ToolContext.state` which is the same dict

The state dict is **not frozen** and is the primary mechanism for cross-turn and tool-to-agent communication.

### Agent Loop

The bulk of `agent.py` is the agent loop (`_run_tools_with_auto_handoff` and `_stream_events_with_auto_handoff`). The loop:

1. Calls `_run_once()` to execute a single LLM turn
2. Handles `"text"` (done), `"continue"` (loop with `CONTINUE_PROMPT`), or `"error"` (auto-handoff or raise)
3. Repeats up to `max_steps` (default 50)

This loop is where auto-handoff, tool execution, and streaming all live.

### System Prompt Construction

`_system_prompt()` (`agent.py:563-573`) is called **on every turn** with no caching. It concatenates:

1. Framework hook system prompt (`framework.get_system_prompt(prompt, state)`)
2. Tools prompt (`render_tools_prompt(REGISTRY.values())`)
3. Skills prompt (`_load_skills_prompt(prompt, workspace, allowed_skills)`)

The resulting string is passed as `system_prompt` to `tape.run_tools_async()` / `tape.stream_events_async()` on every loop iteration (`agent.py:545-546`, `555-556`).

**Concern**: `allowed_skills` and `allowed_tools` are passed fresh each turn, but they effectively form part of the system prompt (skills are rendered into the prompt; tools are passed via the LLM API which typically prepends tool descriptions). Passing them as mutable arguments on every turn means the system prompt can change between turns, potentially causing prefix invalidation in APIs that support prompt caching.

### LLM Call Structure

`_run_once()` calls the LLM via republic's `Tape` methods:

```python
# agent.py:545-561
system_prompt = self._system_prompt(prompt_text, state=tape.context.state, allowed_skills=allowed_skills)
if stream_output:
    return await tape.stream_events_async(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=self.settings.max_tokens,
        tools=model_tools(tools),
        model=model,
    )
else:
    return await tape.run_tools_async(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=self.settings.max_tokens,
        tools=model_tools(tools),
        model=model,
    )
```

The system prompt is **not** stored as a persistent tape entry. It is constructed and passed as a parameter on every call. Whether the LLM runtime prepends it to the message list internally is an implementation detail of republic.

## System F Modeling

**Design note**: We are exploring how to model agent calls in System F. The agent is essentially an LLM call with tool execution in a forked context. We need a type that denotes "this is an LLM agent call" rather than a plain function.

### Why `String -> String` Is Insufficient

A naive model of the agent as `main :: String -> String` has two problems:

1. **Tool call leakage**: The agent loop generates a `set_return :: String -> ()` tool that the LLM can call. In a plain `String -> String` model, the LLM would communicate its result back through a tool call (`sf.eval`), which is awkward — you generally don't want the LLM to "chat" with the runtime via tool calls just to return a value.

2. **No streaming representation**: `String` is synchronous and total. It cannot represent `AsyncStreamEvents` or partial outputs.

### Proposed Model: `main :: String -> LLM ()`

Introduce a primitive type `LLM a` that denotes an LLM agent computation:

```haskell
prim_type LLM a

{-# LLM #-}
prim_op llm :: Tape -> String -> LLM ()
current_tape :: () -> Tape
```

**Semantics:**
- `String` is the **last user input** (not the full history). This models the common case where programmatic preprocessing happens on the fresh input before sending it to the LLM.
- Historical context lives in the **internal tape** during execution. It is accessible if needed via `current_tape :: () -> Tape`.
- `LLM ()` is a **special primitive type** that no ordinary System F function can inspect or manipulate. It denotes "execute this as an LLM agent call" and is handled by the runtime.

**Leveraging currying**: Because System F supports currying, `{-# LLM #-}` functions can take multiple arguments naturally. The only constraint is that `main` must have type `String -> LLM ()`. Intermediate `{-# LLM #-}` functions may return `LLM a` or other types, but **at most one `LLM a` value** may be used as the ultimate return value of `main`.

**Argument-level prompt pragma**: Consider `{-# PROMPT #-}` to mark arguments that should be inlined into the LLM prompt:

```haskell
{-# LLM #-}
prim_op ask :: String -> LLM ()

{-# LLM #-}
prim_op ask_with_context :: {-# PROMPT #-} String -> String -> LLM ()
```

Here `{-# PROMPT #-}` tells the runtime to concatenate the marked arguments into the user prompt for the LLM call. Unmarked arguments are passed through as positional values (`arg0`, `arg1`, `arg2`, etc.) in the REPL context — they carry no special meaning, and it is up to the program (or the LLM) to decide how to use them.

**Simple case:**
```haskell
main :: String -> LLM ()
main = \s -> llm (current_tape ()) s
```

**Workflow with recall:**
```haskell
recall_tape :: Tape = mk_tape "recall"

{-# LLM #-}
prim_op recall :: String -> Maybe String

main :: String -> LLM ()
main = \user_input ->
  case recall user_input of
    Just ctnt -> llm (current_tape ()) (ctnt ++ "\n" ++ user_input)
    Nothing   -> llm (current_tape ()) user_input
```

Here `recall` is a System F primitive backed by the agent's tool-calling capability, but the top-level `main` is explicitly typed as returning `LLM ()` so the runtime knows to enter the agent loop rather than treating it as a pure function.

### System F to Python Correspondence

| System F | Python | Notes |
|---|---|---|
| `Tape` | `str` (tape name) | The runtime passes the tape name string; the agent resolves it via `session_tape()` or `llm.tape()` |
| `LLM a` | `AsyncStreamEvents` | Represents the streaming agent computation; for non-streaming cases the runtime awaits the full result |
| `String` | `str` | The last user input, not the full message history |

### Tape Naming and Linking

For now, tapes are identified by strings with naming conventions rather than explicit dependency links:

```haskell
tape_name :: Tape -> String
mk_tape   :: String -> Tape
```

**Example**: Deriving a dependent tape name from the current tape:

```haskell
recall_tape :: Tape = mk_tape ((tape_name (current_tape ())) ++ "_recall_ctx")
```

**Future work**: We may add explicit tape dependency links (e.g., `parent_tape`, `derived_from`) so the runtime can track provenance chains rather than relying on string conventions.

**Design note on `set_return`**: When synthesizing the agent's tool interface, the runtime generates a `set_return` tool so the LLM can communicate its result back. For return type `()` (unit), the result cell can be **pre-filled with unit** before the LLM call — the LLM does not need to invoke `set_return` at all. This eliminates the awkward "chat via tool call" pattern for void-returning agent functions.

## Integration Plan

### Hook Override

Override `run_model_stream` in the `bub_sf` hook implementation to:

1. **Evaluate** the user's System F program to obtain a synthesized function of type `String -> LLM ()`
2. **Apply** the user prompt to this function
3. **Dispatch** based on the return type:
   - If the result is **not** `LLM ()`, treat it as a pure computation and return the result directly (via `run_model`)
   - If the result **is** `LLM ()`, enter the agent loop via `run_model_stream` and wrap the `AsyncStreamEvents` in a `VPrim`

### REPL Extension: `unsafe_eval`

The Python `REPLSession` needs an `unsafe_eval` method that calls the underlying evaluator with a raw core expression. This allows the runtime to evaluate the synthesized `main` function with a `StringLit` value directly:

```python
# Python extension on REPLSession
class REPLSession:
    def unsafe_eval(self, expr: CoreExpr) -> Value:
        """Evaluate a raw core expression bypassing the parser."""
        return self._evaluator.eval(expr)
```

**Use case**: When `run_model_stream` receives a user prompt, the hook implementation synthesizes a core expression representing `main "user prompt"`, then calls `repl.unsafe_eval(expr)` to reduce it. If the result is `LLM ()`, the runtime enters the agent loop; otherwise it returns the pure value.

### LLM Synthesizer

The synthesizer is the heaviest component. For each `{-# LLM #-}` function call site, it must:

1. **Render the prompt**: Concatenate all `{-# PROMPT #-}`-marked arguments into the user message
2. **Fork the REPL**: Create a fresh evaluation context for the LLM to execute tool calls
3. **Pass state**: Thread the current `tape.context.state` into the forked REPL so tools can access it
4. **Call the agent**:
   - If the function returns a non-`LLM` type, call `run_model` (single-turn, synchronous)
   - If the function returns `LLM ()`, call `run_model_stream` and wrap the resulting `AsyncStreamEvents` in a `VPrim` so the System F runtime can stream it back to the caller

The synthesizer bridges the gap between System F's pure functional semantics and the bub agent's imperative, streaming, stateful execution model.

## Context and Handoff Behavior

### Auto-Handoff Mechanism

The agent loop (`_run_tools_with_auto_handoff` and `_stream_events_with_auto_handoff`) implements a **reactive** recovery mechanism for context-length errors. When the LLM API returns a context-overflow error (detected via regex), the agent:

1. Creates a `handoff` anchor on the tape
2. Retries with the original prompt, relying on `TapeContext(anchor=LAST_ANCHOR)` to slice away all history before the new anchor

```python
# agent.py:327-353
if auto_handoff_remaining > 0 and _is_context_length_error(outcome.error):
    auto_handoff_remaining -= 1
    await self.tapes.handoff(
        tape.name,
        name="auto_handoff/context_overflow",
        state={"reason": "context_length_exceeded", "error": outcome.error},
    )
    # Retry with original prompt — the handoff anchor will truncate history
    next_prompt = prompt
    continue
```

`MAX_AUTO_HANDOFF_RETRIES = 1`, so this recovery happens at most once per turn. After the handoff, the LLM sees only the **system prompt + original prompt** — no prior conversation survives.

### No Proactive Context Budget Management

The system **does not** track token usage proactively or trigger handoff/compaction before hitting the context limit:

| Capability | Status |
|---|---|
| Token counting before API call | ❌ Not implemented |
| Budget threshold (e.g., 80% handoff) | ❌ Not implemented |
| Per-model context window registry | ❌ Not implemented |
| `max_tokens` as context budget | ❌ It is an **output** token limit per response (default 16,384) |

Usage is only recorded **after** each API call (from the response's `usage` field). The only automatic handling is the reactive auto-handoff described above. The system prompt explicitly tells the LLM to use `tape.handoff` manually if context gets too long.

### Handoff Content Passing

The `handoff` mechanism does **not** support passing content to the next stage through the anchor's `state` in the default configuration:

- `handoff()` writes an `anchor` entry with a `state` payload and a `handoff` event
- The `tape.handoff` tool accepts a `summary` parameter that gets stored in `state={"summary": summary}`
- However, the default `TapeContext(anchor=LAST_ANCHOR)` slices history to **entries after the most recent anchor**, **excluding the anchor itself**
- Therefore the anchor's `state` (including any summary) is **never rendered into the LLM's message context**

**What does work:** Because `last_anchor()` includes everything **after** the anchor, you can seed the next stage by appending a `message` entry after the handoff:

```python
await tape.append_async(TapeEntry.message({
    "role": "assistant",
    "content": "Summary of work so far: ..."
}))
```

This message would be included in the sliced history and visible to the LLM on the next turn.

**Implication:** Today there is no built-in way to pass a summary through auto-handoff or manual handoff. Any summarization/compaction logic must either append a message entry after the anchor, or change the `TapeContext` to not use `LAST_ANCHOR`.

## Design Decision: Agent Stays in `bub`

### What We Tried

We vendored `Agent`, `TapeService`, and `ForkTapeStore` into `bub_sf/src/bub_sf/agent/` and `bub_sf/src/bub_sf/store/`. The key refactoring was changing `Agent.run()` and `Agent.run_stream()` to accept `tape_name: str` instead of `session_id: str`, with the caller responsible for mapping session → tape. This decoupling is correct.

### Why Vendoring Failed

The vendored classes in `bub_sf` are **incompatible with bub's builtin tools**:

- `bub/src/bub/builtin/tools.py` imports `Agent` from `bub.builtin.agent` (`tools.py:1`)
- The `subagent` tool extracts the agent from `context.state["_runtime_agent"]` and calls `agent.run()` / `agent.run_stream()` (`tools.py:198-210`)
- Tape manipulation tools (`tape.handoff`, `tape.info`, `tape.reset`) reach into `agent.tapes` and call `TapeService`-specific methods (`tools.py:190-197`, `tools.py:222-227`)
- `bub/src/bub/channels/cli/__init__.py` takes `Agent` in its constructor and accesses `agent.tapes` and `agent.framework.workspace`

If `bub_sf` has its own `Agent` class, these tools break because they expect the bub `Agent` with its `TapeService` API surface. Maintaining two `Agent` implementations or forking the tools is more complexity than the problem warrants.

### The Correct Boundary

**Agent stays in `bub`.** The tape-name refactoring stays. `bub_sf` imports `Agent` from `bub` and uses it directly.

The boundary is not "which package owns Agent" — it is "what parameters does Agent accept":

| Before (session-coupled) | After (tape-decoupled) |
|---|---|
| `Agent.run(session_id=..., prompt=..., state=...)` | `Agent.run(tape_name=..., prompt=..., state=...)` |
| `TapeService.session_tape(session_id, workspace)` → `Tape` | `TapeService.tape(tape_name)` → `Tape` |
| Session management is baked into Agent | Session management lives in the caller (framework adapter or `bub_sf` hook impl) |

The `Agent` class still constructs its own `LLM` via `_build_llm()` — there is no benefit to pushing this out. Someone must own the LLM construction, and Agent is the natural place. The `TapeService` still manages archive paths and fork stores — this is fine because `TapeService` stays in `bub` alongside `Agent`.

### What `bub_sf` Actually Needs

`bub_sf` does not need to vendor `Agent`. It needs:

1. **A way to create tapes with stable names** — so it can call `Agent.run(tape_name=...)` predictably
2. **Its own tape store** — `SQLiteForkTapeStore` in `bub_sf/store/fork_store.py` is a legitimate `bub_sf`-specific implementation of `AsyncTapeStore` with fork support. This can be injected into `Agent` via the framework's `get_tape_store()` hook
3. **Hook integration** — `bub_sf`'s hook impl calls `Agent.run()` / `Agent.run_stream()` after mapping its own session concept to a tape name

### Revised Vendoring Strategy

This is a refinement of **Option C** from the original design:

> **Option C: Keep Agent in bub, expose via `run_model_stream` contract**

With one amendment: Agent's contract changes from `session_id` to `tape_name`. This is a breaking change to `Agent`'s public API, but it is the right change because it decouples session semantics from tape identity.

The vendored code in `bub_sf/src/bub_sf/agent/` and `bub_sf/src/bub_sf/store/fork_store.py` should be:
- **`bub_sf/agent/`** — removed entirely. The refactored `Agent` (with `tape_name`) moves back to `bub/src/bub/builtin/agent.py`
- **`bub_sf/store/fork_store.py`** — kept. This is `bub_sf`'s custom `AsyncTapeStore` implementation (`SQLiteForkTapeStore`). It is not a fork of bub code; it is new code that implements the republic `AsyncTapeStore` protocol

### Impact on Tools

Moving `Agent` back to `bub` restores compatibility:

- `builtin/tools.py` continues to import `Agent` from `bub.builtin.agent`
- `channels/cli/__init__.py` continues to receive `Agent` directly
- `hook_impl.py` continues to create `Agent(self.framework)` and cache it

The only change to the tools is that `Agent.run()` now takes `tape_name=` instead of `session_id=`. The `subagent` tool already calls `agent.run()` with keyword arguments, so this is a straightforward update.

### Impact on `bub_sf` Hook Implementation

`bub_sf`'s hook implementation (`bub_sf/hook.py`) currently needs to:
1. Map its session concept to a tape name
2. Obtain or create an `Agent` instance (from `bub.builtin.agent`)
3. Call `agent.run(tape_name=mapped_name, prompt=..., state=...)`

The `Agent` instance can be shared or cached as before. The session → tape mapping is `bub_sf`'s policy decision.

## Architectural Principle: Channel Owns the Session ID

### Provenance

The `session_id` is **not** synthesized by the framework. It originates at the **channel** and flows through the system untouched.

**`bub/src/bub/channels/message.py:33-51`** — `ChannelMessage` requires `session_id`:
```python
@dataclass
class ChannelMessage:
    session_id: str
    channel: str
    content: str
    chat_id: str = "default"
    ...
```

**`bub/src/bub/channels/telegram.py:243`** — Telegram derives it:
```python
session_id = f"{self.name}:{chat_id}"   # "telegram:123456789"
```

**`bub/src/bub/channels/cli/__init__.py:38-46`** — CLI hard-codes it:
```python
_session_id = "cli_session"
```

**`bub_sf/src/bub_sf/channels/notification.py:47-54`** — Notification channel:
```python
session_id = f"{self.SESSION_PREFIX}:{chat_id}"  # "notification:<chat_id>"
```

### Framework's Role: Passive Transport

**`bub/src/bub/framework.py:105-114`** — The framework resolves `session_id` via the `resolve_session` hook, but the default resolver just echoes back what the channel already put on the message:
```python
session_id = await self._hook_runtime.call_first(
    "resolve_session", message=inbound
) or self._default_session_id(inbound)
```

**`bub/src/bub/builtin/hook_impl.py:104-111`** — `BuiltinImpl.resolve_session` returns `message.session_id` verbatim:
```python
@hookimpl
def resolve_session(self, message: ChannelMessage) -> str:
    session_id = field_of(message, "session_id")
    if session_id is not None and str(session_id).strip():
        return str(session_id)
    ...
```

**`bub/src/bub/framework.py:114-119`** — The framework injects `_runtime_workspace` into state, but does **not** store, index, or route by `session_id`:
```python
state = {"_runtime_workspace": str(self.workspace)}
```

**`bub/src/bub/framework.py:146-188`** — `_run_model` merely forwards `session_id` to the hook runtime:
```python
async def _run_model(..., session_id: str, ...):
    ...
    stream = await self._hook_runtime.run_model_stream(
        prompt=prompt, session_id=session_id, state=state
    )
```

### Implication: Session is Channel Policy, Not Framework Policy

Because the channel originates `session_id`, different channels can have different session scoping policies:
- **Telegram**: one session per chat (`telegram:<chat_id>`)
- **CLI**: one global session (`cli_session`) regardless of who is typing
- **Notification**: one session per notification target (`notification:<chat_id>`)
- **Future channels**: could use user ID, thread ID, or anything else

The framework **cannot** assume a universal session semantics because it does not control session creation. It can only guarantee that every inbound message has a non-empty `session_id` string by the time it reaches hooks.

### Implication for Tape Naming

Since `session_id` is channel policy, and `workspace` is framework boot-time policy (`Path.cwd()`), the combination `session_id + workspace` is a **concern of the application layer** (the builtin implementation or a plugin), not the framework.

This reinforces the decision to:
1. Keep `session_id` in the framework hook contract
2. Let `BuiltinImpl` (or `bub_sf`'s hook impl) map `session_id + workspace → tape_name`
3. Pass `tape_name` to `Agent`, which remains session-agnostic

The framework stays ignorant of both sessions and tapes. The channel owns the session. The builtin/plugin owns the mapping. The agent owns the loop.

## Plugin Precedence: `bub_sf` Can Override `BuiltinImpl`

### Critical Correction

`bub_sf` is **not** a passive state-injecting plugin riding on top of `BuiltinImpl`. It is a **full plugin** that can override any hook, including `run_model_stream`.

**`bub/src/bub/hook_runtime.py:178-192`** — `HookRuntime.run_model_stream()` checks plugins in **reverse registration order**:
```python
async def run_model_stream(
    self, prompt: str | list[dict], session_id: str, state: dict[str, Any]
) -> AsyncStreamEvents | None:
    for _, plugin in reversed(self._plugin_manager.list_name_plugin()):
        if hasattr(plugin, "run_model_stream"):
            return await self.call_first("run_model_stream", prompt=prompt, session_id=session_id, state=state)
        elif hasattr(plugin, "run_model"):
            async def iterator() -> AsyncGenerator[StreamEvent, None]:
                result = await self.call_first("run_model", prompt=prompt, session_id=session_id, state=state)
                yield StreamEvent("text", {"delta": result})
            return AsyncStreamEvents(iterator(), state=StreamState())
    return None
```

Since `BuiltinImpl` is loaded first (`framework.py:45` calls `_load_builtin_hooks`) and `bub_sf` is discovered later, **`reversed()` puts `bub_sf` first.** If `bub_sf` implements `run_model_stream`, it **shadows** `BuiltinImpl`'s implementation.

### What This Means for Streaming

**`bub_sf` receives the live `AsyncStreamEvents` at the hook level**, not just at the channel level. The full flow is:

```
[Channel] → ChannelMessage(session_id=...)
    ↓
[Framework] process_inbound() → _run_model(stream_output=True)
    ↓
[HookRuntime] run_model_stream() → finds bub_sf first
    ↓
[bub_sf SFHookImpl.run_model_stream()]
    ├── Maps session_id → tape_name
    ├── Calls Agent.run_stream(tape_name=...) → AsyncStreamEvents
    └── Returns AsyncStreamEvents to framework
    ↓
[Framework._run_model()] wraps via OutboundRouter → channel.stream_events()
    ↓
[Channel] renders live stream (CLI) or consumes silently (Telegram)
    ↓
[Framework] assembles final str → process_inbound returns TurnResult
```

`bub_sf` has full control over:
1. **Session→tape mapping policy** — how `session_id` becomes `tape_name`
2. **Whether to call the agent at all** — for pure System F computations, return a synthetic stream without touching Agent
3. **Stream transformation** — filter, buffer, or augment events before returning
4. **Fallback to `run_model`** — if `bub_sf` only implements `run_model`, `HookRuntime.run_model_stream` will wrap the string result in a synthetic `AsyncStreamEvents`

### Channel's Role in Streaming

The channel does **not** receive `AsyncStreamEvents` as a return value. It receives it via `stream_events()` as an **observer wrapper** (`channels/base.py:39-41`):

```python
def stream_events(self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]) -> AsyncIterable[StreamEvent]:
    """Optionally wrap the output stream for this channel."""
    return stream
```

**CLI** (`cli/__init__.py:141-160`) uses this to render live text via Rich's `Live` display. **Telegram** does not override it, so Telegram gets no live rendering — only the final message via `send()`.

The channel's `stream_events()` is a **display concern**. `bub_sf`'s `run_model_stream()` is a **semantic concern**. They are orthogonal layers.

## ChannelManager and Async Event Stream Mechanics

### What `ChannelManager` Is

`ChannelManager` (`bub/src/bub/channels/manager.py:44`) is **not** a hook or plugin. It is a concrete runtime class instantiated by CLI entry points (`bub chat`, `bub gateway` in `builtin/cli.py:86-105`). It acts as the **bridge** between channels and the framework.

### Four Responsibilities

| Responsibility | Location | Description |
|---|---|---|
| **Inbound queue + session routing** | `manager.py:63` | Receives `ChannelMessage` from channels, routes per `session_id` |
| **Outbound router** | `manager.py:86, 107, 119` | Implements `OutboundChannelRouter`; binds to framework via `bind_outbound_router(self)` |
| **Task lifecycle tracking** | `manager.py:150-153` | Tracks `asyncio.Task` objects per `session_id`; `quit()` cancels them |
| **Channel lifecycle** | `manager.py:145-146` | Starts/stops channels; discovers them via `framework.get_channels()` |

### Inbound Flow

```
[CLI Channel] ──on_receive──► [ChannelManager.on_receive()] ──queue──► [ChannelManager.listen_and_run()] ──► [Framework.process_inbound()]
```

`on_receive()` (`manager.py:63`) selects a **per-session handler**:

```python
# manager.py:69-81
if session_id not in self._session_handlers:
    if self._channels[channel].needs_debounce:
        handler = BufferedMessageHandler(self._messages.put, ...)   # Telegram
    else:
        handler = self._messages.put                                 # CLI
    self._session_handlers[session_id] = handler
await self._session_handlers[session_id](message)
```

**Decision rule**: `Channel.needs_debounce` is a property declared by the channel class. `TelegramChannel` overrides it to `True` (`telegram.py:165-166`); `CliChannel` inherits `False` from `Channel` base (`channels/base.py:25-27`). The manager **interprets** the flag but does not override it.

`BufferedMessageHandler` (`channels/handler.py:9`) batches messages with debounce (`debounce_seconds=1.0`), max wait (`max_wait_seconds=10.0`), and active time window (`active_time_window=60.0`). Commands starting with `,` bypass buffering.

### Outbound Flow

`ChannelManager` binds itself as the framework's outbound router:

```python
# manager.py:144
self.framework.bind_outbound_router(self)
```

This gives the framework three callback points:

| Callback | Method | Role |
|---|---|---|
| `dispatch_output()` | `manager.py:86` | Receives final `Envelope` → wraps in `ChannelMessage` → calls `channel.send()` |
| `wrap_stream()` | `manager.py:107` | Receives `AsyncStreamEvents` → delegates to `channel.stream_events()` |
| `quit()` | `manager.py:119` | Cancels all in-flight tasks for a session |

### How the Async Event Stream Is Driven

The stream is **cold** (lazy) until the framework starts iterating. Here is the full mechanical flow:

**1. Agent produces a cold stream**

`Agent.run_stream()` (`builtin/agent.py:110`) returns `AsyncStreamEvents` wrapping an async generator. **No LLM call has happened yet.**

**2. HookRuntime passes the cold stream up**

`HookRuntime.run_model_stream()` → `BuiltinImpl.run_model_stream()` → returns the same cold `AsyncStreamEvents` to `Framework._run_model()`.

**3. Framework wraps with channel observer**

`Framework._run_model()` (`framework.py:164-188`):

```python
stream = await self._hook_runtime.run_model_stream(...)
if self._outbound_router is not None:
    stream = self._outbound_router.wrap_stream(inbound, stream)
    # └─► ChannelManager.wrap_stream() → channel.stream_events(message, stream)
async for event in stream:
    # As we iterate, CLI.stream_events() renders via Rich Live
    if event.kind == "text":
        parts.append(str(event.data.get("delta", "")))
return "".join(parts)
```

**4. Channel wrapper is an async generator decorator**

`CLI.stream_events()` (`cli/__init__.py:141-160`):

```python
async def stream_events(self, message, stream):
    live = None
    text = ""
    try:
        async for event in stream:          # ← pulls from AGENT (triggers LLM)
            if event.kind == "text":
                text += str(event.data.get("delta", ""))
                if live is None:
                    live = self._renderer.start_stream(...)
                else:
                    self._renderer.update_stream(live, ...)
            yield event                      # ← pushes to FRAMEWORK
    finally:
        if live is not None:
            self._renderer.finish_stream(live, ...)
```

**Key mechanics:**
- The wrapper **pulls** from the agent stream, **side-effects** (renders), then **yields** the same event forward.
- The framework is the **sole consumer**. The channel cannot pause, filter, or short-circuit the stream — it only observes.
- The `finally` block ensures display cleanup even if the framework stops iterating mid-stream.

**5. Framework assembles final string**

After consuming all events, `Framework._run_model()` returns the assembled string to `process_inbound()`, which builds outbounds via `render_outbound` hook → `dispatch_output` → `channel.send()`.

For CLI, `send()` (`cli/__init__.py:80`) is a no-op for `kind != "error"` because output was already rendered live during stream consumption.

### Design Principles

1. **Channel declares transport policy; manager interprets it.** Channels control `needs_debounce`, `enabled`, and `stream_events`. `ChannelManager` reads these flags but does not override them.

2. **Framework owns stream consumption.** The channel gets an observer wrapper, not the stream itself. This keeps the framework in control of the turn lifecycle.

3. **Stream is cold until framework iterates.** The agent loop, LLM calls, and tool execution only begin when `async for event in stream:` starts. This laziness is essential because `wrap_stream()` must attach before any events fire.

4. **Display and semantics are orthogonal.** `channel.stream_events()` is a display concern (Rich Live). `bub_sf`'s `run_model_stream()` is a semantic concern (System F evaluation). They compose via wrapper chaining.

## Updated Next Steps

1. ✅ **Analyze `TapeService`, `ForkTapeStore`, and `AgentSettings`** — Decision: all stay in `bub`; `Agent` stays in `bub` with `tape_name` API
2. ✅ **Determine session ownership** — Decision: channel owns `session_id`; framework transports it; builtin/plugin maps it to `tape_name`
3. **Move refactored `Agent` from `bub_sf` back to `bub`** — port the `tape_name` refactoring to `bub/src/bub/builtin/agent.py`
4. **Delete `bub_sf/src/bub_sf/agent/`** — remove the vendored agent code
5. **Update `bub`'s `TapeService`** — change `session_tape()` to `tape()` (or keep both for backward compat during transition)
6. **Update callers in `bub`** — `hook_impl.py`, `tools.py`, `channels/cli/` to use `tape_name=` instead of `session_id=`
7. **Extract session→tape mapping utility** — create a stable `_make_tape_name(session_id, workspace)` in `bub.builtin` for reuse by `BuiltinImpl` and future `bub_sf` interceptors
8. **Verify `bub_sf` hook impl** — ensure it can construct/pass tape names and call `Agent.run()` correctly
9. **Update System F modeling section** — `Tape` in System F corresponds to `tape_name: str` that bub_sf manages, then passes to bub's Agent
