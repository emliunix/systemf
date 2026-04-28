# Tiered Analysis Framework

**Status:** Validated  
**Last Updated:** 2026-04-10  
**Purpose:** A systematic approach to understanding complex codebases through layered abstraction

---

## Overview

This framework provides a structured methodology for analyzing software systems. It separates concerns into three tiers, enabling both bottom-up discovery and top-down validation.

**Use when:**
- Exploring unfamiliar codebases
- Documenting architectural decisions
- Validating understanding across team members
- Tracing data flow through multiple components

---

## The Three Tiers

### 1. Base Theme (Analytical Dimensions)

**The lens through which we view all code.**

Define 3-5 core dimensions that capture the essence of the system. These are your analytical primitives.

**Examples by domain:**

| Domain | Base Dimensions |
|--------|----------------|
| Type Inference | LEVELS, EXPECT, CLOSURE, META/SKOLEM |
| Compiler Frontend | SCOPE, PHASE, REPRESENTATION, ERROR-KIND |
| Runtime System | LIFETIME, OWNERSHIP, THREADING, SCHEDULING |
| Build System | TARGET, DEPENDENCY, ARTIFACT, INVALIDATION |

**Characteristics of good base dimensions:**
- **Universally applicable** across the codebase
- **Mutually exclusive** (minimize overlap)
- **Exhaustive** (cover all important aspects)
- **Stable** (don't change frequently)

---

### 2. Main Theme (Architecture)

**How components compose functional systems.**

The call hierarchies, data flows, and architectural patterns. This tier answers "how do the pieces fit together?"

**Elements:**
- Call graphs / hierarchies
- Data flow diagrams
- State machines
- Module boundaries
- Interface contracts

**Key question:** How do base dimensions propagate through the architecture?

---

### 3. Detailed Facts (Implementation)

**Concrete evidence about specific functions/components.**

Every function analyzed through the base theme dimensions.

**Structure per function:**
```
Function: name
├── Base Analysis:
│   ├── Dimension 1: value/behavior
│   ├── Dimension 2: value/behavior
│   └── ...
├── Main Theme Position:
│   └── How it fits in call hierarchy
└── Detailed Facts:
    ├── Location: file.hs:line
    ├── Signature: type
    └── Key invariants
```

---

## Application Workflow

### Phase 1: Establish Base Theme

1. Identify 3-5 core dimensions that capture the system's essence
2. Define each dimension precisely
3. Ensure dimensions are mutually exclusive

**Warning:** Getting this wrong pollutes all downstream analysis.

### Phase 2: Analyze Detailed Facts

For each key function:
1. Determine value for each base dimension
2. Note main theme relationships (calls/called by)
3. Record specific implementation details

**Validation:** Does this function make sense through the base theme lens?

### Phase 3: Synthesize Main Theme

Build call hierarchies showing:
- How data flows through the system
- How dimensions transform between functions
- Where architectural boundaries exist

**Validation:** Does the main theme preserve base dimension invariants?

---

## Iterative Refinement

The framework is not static. As you explore:

**Base theme refinement →**
- New pattern discovered in detailed facts
- Refine dimension definition
- Re-validate affected detailed facts

**Detailed facts discovery →**
- Inconsistency with base theme
- Either: incorrect analysis OR base theme incomplete
- Investigate and resolve

**Main theme revision →**
- Connection doesn't make sense
- Check underlying detailed facts
- May reveal missing base dimension

---

## Cross-Tier Validation Rules

| Check | Rule |
|-------|------|
| Base ↔ Detailed | Every detailed fact must reference all base dimensions |
| Detailed ↔ Main | Main theme edges must preserve dimension invariants |
| Main ↔ Base | Architecture must respect base dimension boundaries |

---

## Example Application: GHC Type Inference

### Base Dimensions

**LEVELS**: TcLevel tracking (N, N+1, N+2)
- Invariant: Metas only unify at their creation level

**EXPECT**: Check vs Infer mode
- Check: Top-down with expected type
- Infer: Bottom-up synthesis

**CLOSURE**: CPS pattern with thing_inside callbacks
- Environment extension brackets
- Results flow back through closures

**META/SKOLEM**: Variable classification
- Metas: Mutable, unifyable (TauTv, TyVarTv)
- Skolems: Immutable, rigid (SkolemTv)

### Application Pattern

```
Analyzing tcPolyInfer:
├── LEVELS: N → N+1 → N (push/pop)
├── EXPECT: INFER (bottom-up)
├── CLOSURE: Bracket pattern
└── META/SKOLEM: Creates metas, quantifies to skolems

Main Theme Position:
└── Called by decideGeneralisationPlan
    └── Part of let-binding typechecking flow
```

---

## Anti-Patterns to Avoid

### 1. Mixing Tiers
- **Bad:** Putting implementation details in base theme
- **Bad:** Using base theme dimensions without analyzing detailed facts
- **Good:** Clear separation of concerns

### 2. Wrong Abstraction Level
- **Bad:** Base dimensions too specific (change frequently)
- **Bad:** Base dimensions too vague (don't help analysis)
- **Good:** Stable, domain-appropriate dimensions

### 3. One-Way Analysis
- **Bad:** Only bottom-up or only top-down
- **Good:** Iterative refinement across all tiers

### 4. Ignoring Cross-Tier Validation
- **Bad:** Inconsistent analysis between tiers
- **Good:** Explicit validation rules, fix inconsistencies

---

## Comparison to Other Approaches

| Approach | Focus | When to Use |
|----------|-------|-------------|
| **This Framework** | Multi-tier, bidirectional | Complex systems, deep analysis |
| Top-Down Only | Architecture first | Greenfield design, known requirements |
| Bottom-Up Only | Implementation first | Debugging, incremental understanding |
| Flat Documentation | Equal detail everywhere | Simple systems, reference docs |

---

## Integration with Exploration Skill

This framework extends the **exploration skill** by providing:

1. **Structured analysis template** (the 3 tiers)
2. **Validation methodology** (cross-tier checks)
3. **Documentation format** (consistent structure)

**When exploring a new codebase:**
1. First establish base theme (1-2 iterations)
2. Then analyze key functions (detailed facts)
3. Finally synthesize main theme
4. Iterate as needed

---

## Files Using This Framework

- `upstream/ghc/analysis/LET_BINDING_ARCHITECTURE_EXPLORATION.md` - GHC let binding analysis
- `docs/elab3-typecheck-notes.md` - Application to elab3 design

---

*This is a living document. Refine the framework based on usage experience.*
