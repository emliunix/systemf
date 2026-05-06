# Project Status

**Last Updated:** 2026-05-06

## Conventions

- Concise entries only. Heavy analysis goes to `./analysis/*_EXPLORATION.md` and is referenced here.
- Tags: `#issue`, `#feature`, `#exploration`.
- File paths relative to workspace root.

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

## Issues

1. **Command execution lost after SystemF takes control of `run_model_stream`** `#issue`
   - When `SFHookImpl.run_model_stream` intercepts the hook, it evaluates `main.main` directly, bypassing the agent loop's `,`-prefixed command handling (`bub/src/bub/builtin/agent.py:135`).
   - **Exploration:** [`analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md`](analysis/COMMAND_EXECUTION_LOST_EXPLORATION.md)

2. **Agent class mixes command handling and agent loop** `#issue`
   - `Agent.run()` and `Agent.run_stream()` embed command dispatch inline, preventing `bub_sf` from executing commands without invoking the agent loop.
   - **Exploration:** [`analysis/AGENT_SPLIT_EXPLORATION.md`](analysis/AGENT_SPLIT_EXPLORATION.md) — proposes `CommandProcessor` + `AgentLoop` + `TurnDispatcher` split.
   - **Refined proposal:** [`analysis/COMMAND_FUNCTIONS_EXTRACTION.md`](analysis/COMMAND_FUNCTIONS_EXTRACTION.md) — two probed functions `run_command` and `run_command_stream` returning `| None`, no class needed.

## Todo

1. Add workspace folder to systemf search path in bub_sf, and reconsider priority handling per search path
2. Dogfooding: migrate some skills to SystemF programs
   - **In progress:** Add tape primitives for SystemF programs
     - `make_tape :: Maybe Tape -> String -> Tape` — create new tape with optional parent
     - `append_message :: Tape -> String -> ()` — append user message to tape
     - **Change:** [`changes/39-make-tape-primitive.md`](changes/39-make-tape-primitive.md)
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
16. **Channel manager session serialization** `#feature`
    - **Problem:** Tape is append-only. If multiple agent calls use the same tape in parallel, they see each other's progress — "brain interleaving"
    - **Fact:** Session ID determines tape → same session = same tape
    - **Solution:** Enforce per-session serialization in `ChannelManager` — at most one `process_inbound` per session at a time
    - Prevents interleaved agent turns, race conditions on tape fork/merge, and duplicate outbound messages
    - **Design:** [`changes/35-channel-manager-session-serialization.md`](changes/35-channel-manager-session-serialization.md) (implementation options)
    - **Problem statement:** [`changes/36-session-tape-sync.md`](changes/36-session-tape-sync.md) (why this is needed)
17. **Product demo preparation** `#feature`
    - Prepare demo covering: model ordinary agents, assisted recall pattern, explore ask pattern
    - Architecture: REPL as language primitive, tools + skills framework, tape, extensibility
    - Special features: events channel, systemd cron jobs, people skill
    - **Change:** [`changes/40-product-demo-prep.md`](changes/40-product-demo-prep.md)
18. **Add `tape_handoff` primop** `#feature`
    - SystemF primitive for tape handoff: `tape_handoff :: Tape -> String -> Unit`
    - Enables the compaction pattern: fork tape, summarize, handoff, append summary
    - Required for demo of context compaction as first-class operation
    - **Change:** [`changes/40-product-demo-prep.md`](changes/40-product-demo-prep.md)

## Entry Points

- **Bub CLI**: `cd bub && uv run bub chat`
- **Bub Gateway**: `cd bub && uv run bub gateway`
- **SystemF REPL**: `cd systemf && uv run python -m systemf.elab3.repl_main`