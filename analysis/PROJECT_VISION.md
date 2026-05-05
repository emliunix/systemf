# Project Vision: Self-Managing Agents with First-Class Context

**Date:** 2026-05-04

## Core Thesis

Instead of treating the agent as a monolithic black box, we decompose it into:

1. **Typed Programs** (SystemF) — Function declarations synthesize LLM calls. LLM calls flow naturally as plain code.
2. **First-Class Context** (Tape) — The LLM context is not hidden state; it's a value you can save, fork, pass around, and capture in closures.
3. **Instance as the Unit** — An instance has a name, goal, and resources. It forks and isolates its own context. The agent manages itself.

## What This Enables

### Dynamic Workflow Construction

Because Tape is a first-class primitive:

```systemf
-- Fork a conversation to explore an idea
let exploration = fork mainTape in
let result = runWith exploration (exploreIdea topic) in
-- Main tape stays clean; exploration is isolated
merge result backInto mainTape
```

### Context as a Value

- **Save**: Persist a conversation state to SQLite
- **Fork**: Split a conversation into parallel explorations
- **Pass**: Hand context between functions
- **Capture**: Close over context in higher-order functions

### Self-Managing Agents

An agent instance:
- Knows its own goal
- Manages its own context (fork when needed, merge when done)
- Allocates its own resources
- Is named and addressable

This is the opposite of "one model, one context" frameworks. Here, context is granular and programmable.

## Why SystemF + Bub

| Primitive | What It Gives Us |
|-----------|-----------------|
| SystemF types | LLM calls are function calls with signatures |
| SystemF evaluation | Programs compose LLM calls deterministically |
| Tape | Context is serializable, forkable, inspectable |
| Bub hooks | Agent loop is interceptable and extensible |

## Demonstration Strategy

The migration of skills to SystemF programs is not just dogfooding — it's proving that real agent workflows can be expressed as typed programs with explicit context management.

### Example: Multi-Step Research

A skill that currently does:
1. Search web
2. Read pages
3. Synthesize

Becomes a SystemF program where:
- Each step is a typed function
- Context forks for parallel page reads
- Results merge back deterministically
- The entire workflow is inspectable and replayable

## Contrasts with Other Approaches

| Approach | Context Management | Agent Unit |
|----------|-------------------|------------|
| Standard LLM APIs | Hidden, monolithic | Single conversation |
| LangChain / etc. | DAG-based, framework-managed | Chain/Graph node |
| **SystemF + Bub** | **First-class, self-managed** | **Named instance with goal** |

## Success Criteria

- [ ] A skill migrated to SystemF runs end-to-end
- [ ] Context forking/merging is visible and debuggable
- [ ] Agent instance declares its own goal and resources
- [ ] Workflow is replayable from Tape records alone
