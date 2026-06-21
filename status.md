# Project Status

**Last Updated:** 2026-06-21

## Conventions

- Concise entries only. Heavy analysis goes to `./analysis/*_EXPLORATION.md` and is referenced here.
- Tags: `#issue`, `#feature`, `#exploration`.
- File paths relative to workspace root.
- **Sequence numbers are permanent across Issues, Todo, and Completed.** When an item is completed, move it to the Completed section but keep its original number. Do not renumber remaining items. Pick the next unused number when adding a new item.
- **Add new items to Todo.** Use tags to indicate kind: `#bug`, `#feature`, `#issue`, `#design`, `#exploration`, `#dogfooding`, `#documentation`. The existing Issues section is legacy and is being merged into Todo over time.

## Vision

See [`analysis/PROJECT_VISION.md`](analysis/PROJECT_VISION.md) for the core thesis: **Context is a first-class value**. Agents manage their own Tape (LLM context) via fork, pass, and merge. LLM calls are typed function declarations in SystemF programs.

## Architecture

- **bub** (`bub/`): Framework, agent loop, channels, builtin tools.
- **systemf** (`systemf/`): Typed lambda calculus, REPL, evaluator.
- **bub_sf** (`bub_sf/`): Integration plugin connecting SystemF to Bub via hooks.

## Completed

- SystemF Orchestrator: `bub_sf` intercepts `run_model_stream` to evaluate `main.main` (`bub_sf/src/bub_sf/hook.py:153`).
- Tape Integration: SQLite fork store and tape primitives (`bub_sf/src/bub_sf/store/fork_store.py`).
- LLM Synthesizer: `{-# LLM #-}` pragma triggers agent calls (`bub_sf/src/bub_sf/bub_ext.py:83`).
- **LLM pragma options** (`bub_sf/src/bub_sf/bub_ext.py`):
  - `notools` — restricts tools to only `sf.repl` for lightweight text generation
  - `noskills` — disables markdown skill injections for cleaner context
- **Funcall prompt instruction** (`bub_sf/src/bub_sf/bub_ext.py:211`):
  - Injects `<rules>Strictly follow the instructions funcall doc to complete the funcall</rules>` at the top of every funcall prompt
  - Leverages docstrings as the actual instruction content
- **Tape primitives** (`bub_sf/src/bub_sf/bub_ext.py`):
  - `data Role = User | Assistant` — type-safe role definition
  - `tape_handoff :: Tape -> String -> ()` — creates handoff anchor via `AsyncTapeManager`
  - `append_message :: Tape -> String -> Role -> ()` — appends message with type-safe role
  - Assistant messages include `reasoning_content: ""` for tape system convention
  - **Change:** [`changes/54-tape-primitives-handoff-and-role.md`](changes/54-tape-primitives-handoff-and-role.md)
- **Fork store refactoring** (`bub_sf/src/bub_sf/store/fork_store.py`):
  - Removed `_E` and `_unwrap_e` indirection, simplified transaction handling
  - **Change:** [`changes/55-remove-e-unwrap-e.md`](changes/55-remove-e-unwrap-e.md)
- **#16 Channel manager session serialization** `#feature` (Won't do — covered by #19 Per-session message serialization and #20 Idle-triggered auto-compaction)
  - **Rationale:** Session serialization and idle detection are now split into two focused changes. Channel-level serialization was rejected in favor of message-processor-level queues.
  - **References:** [`changes/35-channel-manager-session-serialization.md`](changes/35-channel-manager-session-serialization.md), [`changes/36-session-tape-sync.md`](changes/36-session-tape-sync.md)
- **#18 Add `tape_handoff` primop** `#feature`
  - Completed
- **#20 tape_append should support role parameter** `#feature`
  - Completed
- **#2 Dogfooding: migrate some skills to SystemF programs** `#dogfooding`
  - Completed initial tape primitives for SystemF programs
  - `append_message :: Tape -> String -> Role -> ()` — append message with type-safe role
  - `tape_handoff :: Tape -> String -> ()` — create handoff anchor
  - **Completed:** [`changes/54-tape-primitives-handoff-and-role.md`](changes/54-tape-primitives-handoff-and-role.md)
- **#34 Bub gateway Telegram polling stall + lock cascade** `#bug`
  - Fixed by wrapping `Bot.get_updates()` in `asyncio.wait_for(..., timeout=60.0)` (`bub/src/bub/channels/telegram.py`).
  - Secondary `ensure_task()` lock cascade fixed by wrapping the event iterator in `try/finally: out_q.shutdown()`.
  - **Change:** `bub/src/bub/channels/telegram.py`
- **#35 Inflight steering messages not inserted at the right granularity** `#issue`
  - Steering messages are now consumed between agent inner-loop turns via the steering queue.
- **#24 Steering message** `#feature`
  - Per-session steering queue (`asyncio.Queue[str]`) passed into the active agent loop and consumed between steps via `PreparedChat.additional_messages` (ephemeral, not persisted to tape).
  - Session singleton (`TaskBase.ensure_task` + per-session `asyncio.Lock`) guarantees one agent loop per session; new messages during an active loop become steering instead of spawning competing loops.
  - System F bridge: `bub.Steering` prim_type; `main :: String -> Steering -> LLM ()` receives `VPrim(session.queue)` (`bub_sf/src/bub_sf/hook.py:244`); `checked_run` declares a `Steering` arg picked up by `MatchLLMResult.steering_idx` and forwarded to `run_agent_with_repl[_and_stream]`.
  - **Root-cause fix for inflight not working:** `main.sf` was not threading `Steering` into the LLM func (`checked_run`). Now passes `st` through.
  - **Design:** [`changes/59-steering-message-support.md`](changes/59-steering-message-support.md)
  - **Supersedes:** [`changes/56-per-session-message-serialization.md`](changes/56-per-session-message-serialization.md)
- **#25 Document `fork_store.py` query behavior** `#documentation`
  - Documented in [`docs/tape.md`](docs/tape.md): error-vs-silent-empty matrix, auto-creation rules, schema/views, `fork_tape` tool_call special case, anchor resolution, transaction model, read ordering.
- **#21 Implement `make_tape` primitive for SystemF programs** `#dogfooding`
  - Implemented `make_tape :: Maybe Tape -> String -> Tape` in `bub_sf/src/bub_sf/bub_ext.py`.
  - Creates a new tape with optional parent; child tapes are named `{parent}/{name}-{suffix}`.
  - Repaired broken test fixture (`MockSession.state` nesting) and stale `_make_tape`/`_fork_tape` references in `bub_sf/tests/test_bub_ext.py`.
  - **Change:** [`changes/39-make-tape-primitive.md`](changes/39-make-tape-primitive.md), test repairs in [`changes/61-tape-primitives-needs-compact-and-inferior-tape.md`](changes/61-tape-primitives-needs-compact-and-inferior-tape.md)
- **#36 Idle-triggered auto-compaction** `#feature` (channel-side done; compaction delegated to SF `main`)
  - `IdleTracker` integrated into `TelegramChannel`: registered on first message (30-min timeout), `heartbeat()` resets via message lifespan, `_on_session_idle` emits the idle signal through the normal `_on_receive` pipeline (`bub/src/bub/channels/telegram.py:160,250-275,325-332`).
  - **Design pivot from change 57:** the `kind="idle"` `MessageKind` / `BuiltinImpl` hook handling (steps 3-5) were dropped; the idle signal is now a regular content message (`<context type="idle_event">`), and compaction is delegated to the SF `main` program (`main.sf` `with_compact`).
  - **Design:** [`changes/57-idle-triggered-auto-compaction.md`](changes/57-idle-triggered-auto-compaction.md)
  - **Supersedes:** [`changes/51-auto-compact-session.md`](changes/51-auto-compact-session.md)
- **#37 Inferior tape** `#feature`
  - Implemented `inferior_tape :: String -> Tape -> Tape` as a stable `{parent}/{tag}` named child tape.
  - Get-or-create semantics: creates the tape only when `info().anchors == 0` (no bootstrap anchor), otherwise returns the existing tape.
  - **Change:** [`changes/61-tape-primitives-needs-compact-and-inferior-tape.md`](changes/61-tape-primitives-needs-compact-and-inferior-tape.md)
- **#38 Implement missing SF primitives for `main.sf` compaction path** `#bug` `#dogfooding`
  - Implemented `needs_compact :: Tape -> Bool` and `inferior_tape :: String -> Tape -> Tape`.
  - `needs_compact` returns `TRUE` when `entries_since_last_anchor > COMPACT_THRESHOLD_ENTRIES` (threshold = 40).
  - `inferior_tape` provides stable named child tapes for intent tracking.
  - Fixed sibling primitive arg extractors: `_tape_append` uses `_role_val`, `_tape_make` and `_tape_handoff` use `str_val`.
  - Repaired `MockSession` fixture and stale `_make_tape`/`_fork_tape` test references; all 11 `test_bub_ext.py` tests pass.
  - Added `test.sf` regression guard; `uv run bub sf-check test -L .` → `OK: test`.
  - **Change:** [`changes/61-tape-primitives-needs-compact-and-inferior-tape.md`](changes/61-tape-primitives-needs-compact-and-inferior-tape.md)
- 30. **`,command` execution blocked by tape lock / agent session** `#issue`
    - User-issued `,`-prefixed commands should execute **immediately** without waiting for the current agent loop to finish.
    - Current behavior: commands queue up behind `ensure_task()` just like regular messages, because `run_model_stream()` takes the session lock and all inbound messages are funneled through the same serialization path.
    - **Related:** #4 (steering granularity) — commands are a special case of steering that need bypass logic.
    - dup of **28**

## Todo

1. Add workspace folder to systemf search path in bub_sf, and reconsider priority handling per search path
3. Improve fs.read tool error message when file does not exist
4. Audit and improve error reporting: friendly messages for common errors (e.g., file not found), detailed stack traces for internal errors only
5. Fix sqlite tape store search
6. Investigate context entry types and tape configurability for event-driven agent reactions
    - What entries are used to build up LLM context? Could tape config make this configurable?
    - Direct use case: should user command execution (`,`-prefixed) be visible to the LLM? Should command completion trigger events that the agent reacts to?
    - Broader goal: make agents react to events in general, not just user messages
7. Treat return string specially for synthesized LLM functions `#feature`
    - When a `{-# LLM #-}` function returns `String`, use the LLM response message directly as the return value instead of requiring `set_return` tool call
    - **Exploration:** [`analysis/LLM_STRING_RETURN_EXPLORATION.md`](analysis/LLM_STRING_RETURN_EXPLORATION.md)
8. Bub standalone CLI to validate sf programs `#feature`
    - Add a command to `bub` CLI that validates SystemF source files (typecheck, parse, etc.) without running them
    - Useful for CI and pre-commit checks
9. LLM pragma to support temporary flag, allowed tools config, model config `#feature`
    - Extend `{-# LLM #-}` pragma to accept optional per-call configuration: temporary flag (don't persist tool defs), allowed tools list, and model override
10. Hook system prompt or bub framework logic to be able to skip something `#feature`
    - Add a mechanism (hook or config) to selectively skip parts of the system prompt or framework logic during a turn
11. **bub_events channel** `#feature`
    - TCP/JSON socket channel for event-driven agent reactions. Accepts JSON messages, validates with Pydantic, dispatches to framework.
    - See `analysis/BUB_EVENTS_CHANNEL_EXPLORATION.md`
12. **Tape provenance for tape fork**
    - Track provenance information when forking tapes to understand lineage and relationships between tape versions
13. **REPL LLM value agent call** `#feature`
    - If user `.sf.repl` evaluates to an LLM value, it should be further executed as an agent call
    - See [`changes/33-repl-llm-agent-call.md`](changes/33-repl-llm-agent-call.md)
14. **my_skills system prompt injection** `#feature`
    - Enhance `my_skills/` sub-project to inject system prompts that guide the agent on how to use available skills effectively
    - Skills should declare their purpose, parameters, and usage patterns so the agent can discover and invoke them contextually
15. **Channel events design** `#feature`
    - Extend channel to support events: channel owns session/session_id, knows when session is idle, and should compact context to prepare for later messages
    - See [`changes/34-channel-events-design.md`](changes/34-channel-events-design.md)
17. **Product demo preparation** `#feature`
    - Prepare demo covering: model ordinary agents, assisted recall pattern, explore ask pattern
    - Architecture: REPL as language primitive, tools + skills framework, tape, extensibility
    - Special features: events channel, systemd cron jobs, people skill
    - **Change:** [`changes/40-product-demo-prep.md`](changes/40-product-demo-prep.md)
19. **Per-session message serialization** `#feature`
     - Serialize per-session messages in the message processor (hook impl), not at channel level
     - Uses per-session queue + `_ensure_agent()` worker pattern to maintain single-agent-per-session invariant
     - Works for all entry points (gateway, CLI, tests)
     - **Change:** [`changes/56-per-session-message-serialization.md`](changes/56-per-session-message-serialization.md)
22. **Continue dogfooding: migrate additional skills to SystemF programs** `#dogfooding`
     - Migrate other bub tools and framework components to SystemF programs beyond tape primitives
23. **sf-check bub missing** `#bug`
     - sf-check doesn't include bub.sf to search paths by default.
     - the problem is BubExt requires TapeStore and BubFrameworkd for actually calling, though for check purpose it's not needed.
     - I'm not sure, maybe we can make search path a static field of Ext.
26. **SF tools feature: typed todo items** `#feature`
    - Leverage SystemF's type system to give structure to the todo list itself
    - Instead of free-form markdown todos, define typed todo items as SystemF data types (e.g., `data TodoStatus = Todo | InProgress | Done`, `data Todo = MkTodo Int String TodoStatus (Maybe String)`)
    - Benefits: type-checked status transitions, typed metadata fields, REPL-queryable todo state, composable with tape/LLM primitives
    - Enables: `todo_add`, `todo_update`, `todo_query` as typed prim_ops returning structured data instead of raw strings
27. **Remove `LLM` type; move streaming marker to pragma** `#issue` `#design`
    - `LLM a` was overloaded to mean both "LLM-synthesized value" and "stream through the agent loop", making it uncomposable.
    - Sequencing two LLM calls needs a monad that SystemF does not have.
    - **Decision:** drop `LLM a`. Carry intent via the `{-# LLM #-}` pragma and attributes (e.g. `stream`, `notools`). Functions return ordinary types; the pragma controls synthesis and streaming.

28. **Command execution lost after SystemF takes control of `run_model_stream`** `#issue`
    - When `SFHookImpl.run_model_stream` intercepts the hook, it evaluates `main.main` directly, bypassing the agent loop's `,`-prefixed command handling (`bub/src/bub/builtin/agent.py:135`).
    - **Exploration:** [`analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md`](analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md)

29. **Agent class mixes command handling and agent loop** `#issue`
    - `Agent.run()` and `Agent.run_stream()` embed command dispatch inline, preventing `bub_sf` from executing commands without invoking the agent loop.
    - **Exploration:** [`analysis/AGENT_SPLIT_EXPLORATION.md`](analysis/AGENT_SPLIT_EXPLORATION.md) — proposes `CommandProcessor` + `AgentLoop` + `TurnDispatcher` split.
    - **Refined proposal:** [`analysis/COMMAND_FUNCTIONS_EXTRACTION.md`](analysis/COMMAND_FUNCTIONS_EXTRACTION.md) — two probed functions `run_command` and `run_command_stream` returning `| None`, no class needed.

31. **`summarize` prompt needs improvement** `#bug`
    - The `{-# LLM notools #-}` prim_op spawns a sub-agent, but the sub-agent still needs explicit instructions to output the summarization directly without attempting tool calls or `set_return`.
    - Current prompt steering is insufficient.

32. **Delegate tape to subagent** `#issue`
    - When a sub-agent (e.g., from `summarize`) is running, the parent agent is inherently inactive/blocked. The current tape is locked as "in use", so the sub-agent cannot operate on the same tape.
    - `summarize` should internally fork the tape and spawn the sub-agent on the fork.
    - Manual fork + summarize currently hits `max_steps_reached=50`.
    - design: maybe we can lock session at run_model_stream level, instead of current subagent call level. The real concern we try to solve with session lock is to prevent concurrent modification to tape.

33. **Experiment seuqence LLM calls** `#feature`
    - It's often the case the workflow has steps, each has it's goal. Yet we'd like them to share a tape so it has accumulated global view, but with different focuses.
    - example: `do_a ; do_b ; do_c`, each with its own Prompt.
    - realized it's just plain function calls, but maybe we can sequence `Maybe` as a good helper

39. **`bub sf-check --help` hangs / requires terminal input** `#bug`
    - Running `uv run bub sf-check --help` opens an interactive pager/editor and does not return when stdout is not a terminal.
    - Expected: print usage and exit immediately, like other CLI commands.

40. **comment macros `@include`**, `#feature`
    - to make prompt in its own .md file and included into the comment in the .sf file.

## Entry Points

- **Bub CLI**: `uv run bub chat`
- **Bub Gateway**: `uv run bub gateway`
- **SystemF REPL**: `uv run python -m systemf.elab3.repl_main`