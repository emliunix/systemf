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

## Next Steps

1. Analyze `TapeService`, `ForkTapeStore`, and `AgentSettings` to determine if they are core or framework
2. Design the Agent → Framework callback interface (protocol)
3. Decide which of `tools.py` and `skills.py` move with Agent
4. Prototype the adapter layer in `BuiltinImpl`
