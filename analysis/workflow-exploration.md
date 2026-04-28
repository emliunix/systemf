# Model-Validation Workflow Pattern

## Overview

A systematic approach to understanding complex systems through building simplified mental models and validating them against source code implementation.

## Core Pattern: Model-Validation Loop

```
┌─────────────────────────────────────┐
│  SIMPLIFIED MODEL                   │
│  (mental abstraction of mechanism)  │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  BEHAVIOUR VALIDATION               │
│  • Trace data flow                  │
│  • Check source at boundaries       │
│  • Verify transformations           │
└────────────┬────────────────────────┘
             ↓
       ┌─────┴─────┐
    Confirm    Contradiction
       ↓           ↓
    Document   Update Model
       ↓           ↓
       └─────┬─────┘
             ↓
       Refined Model
```

## Build Sub-Patterns

### 1. Boundary Isolation

Identify the specific slice of the system to understand:
- **Entry point**: Where does the mechanism start? (e.g., `tcCaseMatches` for pattern matching)
- **Exit point**: Where does it end? (e.g., Core generation in `HsToCore`)
- **Scope**: Ignore everything outside this slice

### 2. State Tracking

Follow what metadata travels through the pipeline:
- **What metadata?** (e.g., `HsWrapper`, `ExpPatType` with mode)
- **What transforms?** (e.g., `Check` mode → `Scaled ExpSigmaTypeFRR`)
- **Origin point**: Where does it come from? (e.g., `mkCheckExpType` at entry)

### 3. Mechanism Separation

Divide the flow into distinct phases:
- **Generation**: Where is evidence created? (e.g., `tcDataConPat`, `matchExpectedConTy`)
- **Transport**: How is it carried forward? (e.g., `ConPatTc`, `CoPat`)
- **Consumption**: How is it interpreted at the end? (e.g., `dsHsWrapper`, `matchCoercion`)

### 4. Happy Path Focus

Start with the normal case before considering exceptions:
- Regular data constructors (ignore type families initially)
- Check mode only (defer Infer mode analysis)
- Identity wrapper (`WpHole`) as baseline

## Validate Sub-Patterns

### 1. Signature Verification

Verify interfaces match the mental model:
```
grep type signatures at each function boundary
Verify parameter types match expectations
Confirm return types are as predicted
```

### 2. Call Chain Tracing

Follow the data through the call graph:
- Follow data parameter through calls
- Verify no unintended transformations (e.g., Check stays Check)
- Check for explicit conversions (e.g., `mkCheckExpType`, `expTypeToType`)

### 3. Consumption Point Check

Verify how evidence is ultimately used:
- Where is the evidence consumed? (e.g., `dsHsWrapper`)
- What structure is produced? (e.g., `let`-binding, `Cast`)
- Verify placement (e.g., wraps match result, not individual branches)

### 4. Exception Identification

Document edge cases separately from primary mechanism:
- When is evidence non-identity? (e.g., data families, pattern synonyms)
- Document as edge case, not primary mechanism
- Exclude from initial model, add in refinement phase

## Application Example: HsWrapper in Pattern Matching

### Build Phase

| Step | Application |
|------|-------------|
| Boundary Isolation | `tcCaseMatches` → `tc_pat` → `HsToCore` |
| State Tracking | `HsWrapper` from `mkWpCastN`/`idHsWrapper` through `ConPatTc`/`CoPat` |
| Mechanism Separation | Gen: `tcDataConPat` → Transport: `ConPatTc` → Consume: `matchCoercion` |
| Happy Path | Regular constructors, `idHsWrapper` baseline |

### Validate Phase

| Step | Application |
|------|-------------|
| Signature Verification | All use `Scaled ExpSigmaTypeFRR` consistently |
| Call Chain Tracing | Check mode throughout, no switches |
| Consumption Check | `let`-binding wrapping match result |
| Exception ID | `cpt_wrap` non-identity only for pattern synonyms |

### Model Refinement

**Initial model:** HsWrapper guides all pattern matching transformations
**Contradiction:** `ConPatTc.cpt_wrap` is `idHsWrapper` for regular constructors
**Refined model:** HsWrapper primarily via `CoPat` for type mismatches (data families), pattern signatures

## Key Principles

1. **Source is ground truth** — Documentation describes intent, code reveals mechanism
2. **Trace data transformation** — What goes in, what comes out, how it changes
3. **Distinguish primary from edge cases** — Happy path first, exceptions documented separately
4. **Validate at component boundaries** — Interface contracts, type signatures, data structures

## When to Apply

This workflow applies to understanding:
- Compiler pipelines (type checking → code generation)
- Distributed system message flows
- Framework request handling
- Protocol implementations
- Any system with explicit data transformation pipelines

## Anti-Patterns

- **Premature generalization** — Trying to understand edge cases before primary path
- **Documentation worship** — Treating docs as authoritative without source validation
- **Control flow tracing** — Following "function A calls B" instead of "data X becomes Y"
- **Scope creep** — Including tangential mechanisms (type families when studying regular constructors)
