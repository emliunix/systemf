---
name: coop-design
description: Collaborative design workflow for architecture and system design. Use when the user wants to design or redesign a system, component, or feature. Triggers on phrases like "design", "architecture", "how should we", "what's the best way to", or when the user asks for tradeoff analysis. This skill is for exploration and decision-making, not implementation.
---

# Coop Design

**Use this skill when doing architecture or system design work that requires exploration, tradeoff analysis, or collaborative reasoning.**

## Workflow

### Phase 1: Intent

**Human states:**
- The problem or goal
- Constraints and non-negotiables
- Relevant code paths, existing docs, or prior art
- What success looks like

**Assistant does:**
- Reads the codebase to understand current state
- Points to relevant files, hooks, abstractions
- Asks clarifying questions if intent is ambiguous

### Phase 2: Exploration

**Assistant proposes:**
- Design options with concrete pros/cons
- Where each option fits in the architecture
- What existing patterns it follows or breaks

**Human challenges:**
- Edge cases the assistant missed
- Architectural constraints from the codebase
- Incorrect assumptions about how things work
- Preference for simplicity over completeness

**Rule:** The assistant must present multiple options honestly, not just the one it thinks is best. The human decides.

### Phase 3: Convergence

**Human:**
- Chooses a direction or asks for refinement
- May reject all options and restate the problem
- Makes final decisions on tradeoffs

**Assistant:**
- Synthesizes the shared understanding into a structured document
- Documents rejected options and why
- Captures unresolved tensions deliberately

### Phase 4: Documentation

**Assistant writes:**
- Design document with sections: Problem, Constraints, Architecture, Open Questions, Implementation Order
- A "Design Provenance" section capturing raw thoughts, dead-ends, and why decisions were made
- Code sketches where they clarify intent

**Human reviews:**
- Corrects mischaracterizations
- Adds missing constraints
- Approves or requests revision

## Roles

| | Human (User) | Assistant |
|---|---|---|
| **Leads** | Intent and goals | Exploration and documentation |
| **Knows** | Business context, codebase history, constraints | Code structure, patterns, implementation details |
| **Decides** | Which design to pursue | How to present tradeoffs |
| **Responsible for** | Correctness of the design | Accuracy of the documentation |
| **Challenges** | Proposed designs with edge cases | Vague requirements with questions |

## Rules

1. **No premature convergence** — Present at least 2 options before the human decides
2. **Dead-ends are valuable** — Document explored paths that didn't work, with reasons
3. **The human is always right about constraints** — If the human says "X doesn't work," accept it and explore alternatives
4. **The assistant challenges ambiguity** — If the human's intent is unclear, ask before proposing
5. **Design docs are append-only** — Once written, add new insights as new sections; don't erase the thought process
6. **Preserve tension** — If a design has unresolved tradeoffs, say so explicitly

## Design Document Structure

```markdown
# N: Title

**Date:** YYYY-MM-DD
**Status:** Draft / In Progress / Accepted
**Area:** Files and modules affected

## Design Workflow
[How this document was authored — see Coop Design skill]

## Problem
[What we're solving]

## Key Constraints
[Non-negotiables, architectural boundaries]

## Architecture
[The chosen design]

### Options Considered
[Rejected options with reasons]

## Open Questions
[Unresolved tensions, implementation risks]

## Implementation Order
[Phased approach if applicable]

## Design Provenance
[Raw thoughts, dead-ends, iterations]
```

## When to Use

- New features that touch multiple subsystems
- Refactoring that changes architectural boundaries
- Performance or scalability design
- API design or contract changes
- Any change where the "why" matters as much as the "what"

## When NOT to Use

- Bug fixes with obvious solutions
- Adding a new function to an existing module
- Documentation updates
- Any change that fits in a single commit with a clear description

## Related Skills

- `change-plan` — For when the design is done and implementation begins
- `exploration` — For systematic codebase investigation before design
- `code-reading-assistant` — For understanding existing architecture
