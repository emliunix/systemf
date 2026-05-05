# Demo Plan

**Date:** 2026-05-04
**Status:** Draft

## Goal

Demonstrate the core insight: **Context is a first-class value**. Show how SystemF programs with Bub's Tape primitive enable self-managing agents that fork, pass, and merge their own LLM context.

## The Pitch (30 seconds)

> "Every other framework hides the LLM context. We make it a first-class value — save it, fork it, pass it to functions, capture it in closures. The agent manages its own context."

## Storyline

### 1. Introduction (2 min)
- **SystemF**: Typed lambda calculus where LLM calls are function declarations
- **Bub**: Agent runtime with Tape as the context primitive
- **The integration**: Programs orchestrate LLM calls; context is explicit and manipulable
- **Key principle**: The instance is the ultimate unit — named, goal-driven, self-managing

### 2. Live Demo: Context as a Value (5 min)

**Setup:**
```bash
cd bub && uv run bub chat
```

**Scenario:** "Analyze this codebase, but explore two approaches in parallel"

**Steps:**
1. Start with a single agent instance (named "code-analyzer")
2. Show the Tape (context) being passed around
3. Fork the Tape into two branches:
   - Branch A: "Analyze architecture"
   - Branch B: "Find security issues"
4. Run both in parallel (simulated)
5. Merge results back
6. Show that the main context stayed clean

**Key Points:**
- Tape is serializable and inspectable
- Forking creates isolated exploration spaces
- Merging brings results back deterministically
- The agent manages its own context lifecycle

### 3. Live Demo: Typed LLM Calls (5 min)

**Scenario:** "Write a skill that searches the web and synthesizes findings"

**Show the SystemF program:**
```systemf
{-# LLM #-}
searchWeb : String -> List SearchResult
synthesize : List SearchResult -> Report

research : String -> Report
research topic =
  let results = searchWeb topic in
  let report = synthesize results in
  report
```

**Key Points:**
- LLM calls are just function applications
- Types enforce the contract
- The program composes LLM calls deterministically
- No hidden state — everything is explicit

### 4. Architecture Deep Dive (3 min)

Show the mechanics:
- `bub_sf/src/bub_sf/hook.py:153` — Interception: SystemF's `main.main` runs instead of standard LLM loop
- `bub_sf/src/bub_sf/bub_ext.py:83` — `{-# LLM #-}` pragma: function body triggers LLM call
- `bub_sf/src/bub_sf/store/fork_store.py` — SQLite-backed Tape fork/merge
- `systemf/` — The language: type checker, REPL, evaluator

### 5. Vision: Dogfooding (2 min)

- Migrating real skills to SystemF programs
- Each skill becomes a typed, inspectable, replayable program
- Agent instances declare their own goals and manage their own context
- The framework fades into the background; the program is the agent

## Technical Requirements

- [ ] Working Bub CLI with SystemF integration
- [ ] Sample SystemF program demonstrating Tape fork/merge
- [ ] Sample SystemF program with `{-# LLM #-}` calls
- [ ] SQLite fork store populated with demo data
- [ ] Backup plan if LLM API is slow/unavailable

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM API latency | Pre-run the demo, have cached responses ready |
| Tool errors | Test all file paths beforehand |
| SystemF compilation errors | Have a fallback to plain Bub mode |
| Concept too abstract | Lead with the concrete demo, explain theory after |

## Preparation Checklist

- [ ] Rehearse the demo 2-3 times
- [ ] Prepare slide deck (5-10 slides) — one slide per storyline section
- [ ] Set up clean terminal with large font
- [ ] Have `status.md` and `analysis/PROJECT_VISION.md` ready for reference
- [ ] Prepare one "surprise" question with answer (e.g., "How does this compare to LangGraph?")

## Success Criteria

- Audience understands: **Context is a first-class value**
- Audience sees Tape fork/merge in action
- Audience sees a typed LLM call (`{-# LLM #-}`)
- Audience grasps the "instance as ultimate unit" principle
- No crashes or major errors during demo
