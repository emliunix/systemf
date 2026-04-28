# Update systemf/README.md

## Facts

- The current `systemf/README.md` was written for an older architecture (elab2/core/eval/llm/desugar/inference/scoped directories) that no longer exists.
- The current codebase is organized around `elab3/` — a unified elaborator with Parse → Rename → Typecheck → Eval pipeline.
- The README incorrectly lists project structure with `core/`, `eval/`, `inference/`, `scoped/`, `llm/` directories that have been removed.
- The README contains duplicated REPL commands that will quickly go out of date (REPL already has `:help`).
- The README uses implementation jargon (`CEK evaluator`, `Synthesizer protocol`, `System F core`) that is not user-facing.
- Current test count: 366 elab3 tests + 304 surface tests = 670 total.
- Entry points: `systemf.elab3.repl_main` (REPL), `systemf.elab3_demo` (demo), `bub_sf` (bub integration).
- The README should reflect the current architecture but remain focused on user-facing features and project organization, not implementation details.

## Design

Replace the README with a compact, accurate document organized as:

1. **About** — What the project is, design goals (module system, bidirectional type inference, pluggable primitives)
2. **Features** — User-facing capabilities only (ADTs, pattern matching, wildcard types, unicode syntax, interactive REPL, primitive operations)
3. **Quick Start** — Run REPL, run demo, run tests (with correct current commands)
4. **Project Structure** — Actual directory layout (`elab3/`, `surface/`, `tests/test_elab3/`, `bub_sf/`) with one-line pipeline mention
5. **Extension** — How to extend with custom primitives, bub integration overview
6. **License**

Remove:
- Detailed REPL commands table (duplicates `:help`, goes stale)
- `CEK evaluator` / `Synthesizer protocol` / `System F core` jargon
- Old architecture sections (scope checker, elaborator as separate passes)
- `core/`, `eval/`, `inference/`, `scoped/`, `llm/` directory listings
- Development section (lint/format commands) — keep in internal docs

## Why it works

- The README is now a landing page for users and contributors, not an architecture document.
- By removing duplicated REPL commands, we eliminate a source of staleness.
- By removing implementation jargon, we lower the barrier to entry.
- By keeping the project structure accurate, we help newcomers navigate the codebase.
- The Extension section highlights the unique value prop (pluggable primitives, bub integration) without diving into protocol details.

## Files

| File | Action |
|------|--------|
| `systemf/README.md` | Replace with new content |
| `changes/25-update-readme.md` | Create (this file) |

## Rationale (guiding principles for README)

1. **README is for users, not implementers** — Implementation details belong in internal docs or code comments.
2. **Don't duplicate machine-readable info** — REPL commands are already available via `:help`; duplicating them guarantees staleness.
3. **Be honest about architecture** — Don't pretend old directories still exist. Accurate structure reduces confusion.
4. **Show, don't tell** — Quick start with working commands is more valuable than paragraphs of explanation.
5. **Extension is a feature** — The Synthesizer protocol and bub integration are selling points, but should be described at the capability level, not the protocol level.
