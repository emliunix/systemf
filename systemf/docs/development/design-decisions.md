# Design Decision Log

**Project**: System F Elaborator Refactor  
**Date Range**: 2026-03-02  
**Status**: Planning Phase

---

## Decision 1: Multi-Pass Architecture

**Decision**: Implement explicit multi-pass elaboration following Idris 2 design.

**Rationale**:
- Single-pass mixes concerns (name resolution + type checking)
- Hard to debug when everything is interleaved
- Can't test scope checking independently
- Foundation for future features (implicits, type classes)

**Passes**:
1. Scope checking (names → de Bruijn indices)
2. Type elaboration (indices → typed Core)
3. LLM pragma processing (optional)

**Consequence**: ~2-3 weeks implementation time, but cleaner architecture.

**Date**: 2026-03-02

---

## Decision 2: All-or-Nothing Implementation

**Decision**: No gradual migration. System works when complete, not before.

**Rationale**:
- Gradual migration adds complexity
- Need to maintain compatibility with old code
- Harder to reason about intermediate states
- "All at once" is actually simpler

**Consequence**: 
- System will be broken during refactor
- Can't ship partial implementation
- Need feature branch or freeze

**Date**: 2026-03-02

---

## Decision 3: Extend Surface AST (Don't Duplicate)

**Decision**: Add scoped variants to Surface AST instead of creating separate Scoped AST hierarchy.

**Options Considered**:
1. Separate `ScopedTerm` hierarchy (rejected - too much duplication)
2. Extend Surface AST with `ScopedVar`, `ScopedAbs` (chosen)

**Rationale**:
- Avoid duplicating ~15 AST types (App, Constructor, Case, etc.)
- Can mix scoped/unscoped during transformation
- Pattern matching logic reused
- Less code to maintain

**Implementation**:
```python
# Before
SurfaceVar(name="x")
SurfaceAbs(var="x", body=...)

# After scope checking
ScopedVar(index=1, debug_name="x")
ScopedAbs(var_name="x", body=...)
# SurfaceApp, SurfaceConstructor unchanged!
```

**Consequence**: Need to be careful about pattern matching - must handle both variants.

**Date**: 2026-03-02

---

## Decision 4: Core AST Keeps Names

**Decision**: Add `debug_name` to `Var` and `var_name` to `Abs` in Core AST.

**Rationale**:
- Source location alone isn't enough
- Want to show actual variable names in errors
- Makes REPL output readable
- Debugging is easier

**Previous State**: Core AST had indices only (`x0`, `x1`)
**New State**: Core AST has names (`x`, `y`, `counter`)

**Consequence**:
- Slightly larger Core AST
- Names must flow through entire pipeline
- Better user experience

**Date**: 2026-03-02

---

## Decision 5: Source Locations Mandatory

**Decision**: `source_loc` is required field in Core AST base class.

**Rationale**:
- Every error needs location info
- No such thing as "location unknown"
- Forces all code to track positions

**Implementation**:
```python
@dataclass
class Term:
    source_loc: Optional[Location] = None  # Has default but shouldn't be None
```

**Consequence**: All Core term constructors must pass location.

**Date**: 2026-03-02

---

## Decision 6: Elaborate Directly to Typed Core

**Decision**: No untyped Core intermediate. Scope-checked → Typed Core directly.

**Options Considered**:
1. Untyped Core then type inference (rejected - extra step)
2. Direct to typed Core (chosen)

**Rationale**:
- Core AST requires types anyway (Abs needs var_type)
- Cleaner pipeline
- Matches Idris 2 approach
- Less memory overhead

**Pipeline**:
```
Surface ──► Scoped ──► Core (typed)
```

**Consequence**: Elaborator must synthesize types during translation.

**Date**: 2026-03-02

---

## Decision 7: No Verification Pass

**Decision**: Remove separate verification/kernel pass. Trust elaborator.

**Rationale**:
- Adds complexity for small benefit
- We're not formally verifying anyway
- Can add later if needed
- Faster compilation

**Note**: May revisit if we add proof-carrying code or formal verification.

**Date**: 2026-03-02

---

## Decision 8: LLM Pragma as Separate Pass

**Decision**: Dedicated pass for LLM pragma processing.

**Rationale**:
- LLM functions are special case (no real body)
- Keeps main elaborator clean
- Easy to disable LLM support
- Can add more pragma types later

**What it does**:
- Extract pragma parameters
- Replace function body with PrimOp
- Build LLM metadata

**Date**: 2026-03-02

---

## Decision 9: Top-Level Collection Strategy

**Decision**: Collect all signatures first, then elaborate bodies (for mutual recursion).

**Algorithm**:
1. Scope check all declarations
2. Collect all type signatures
3. Elaborate type signatures to Core types
4. Elaborate all bodies (with all signatures in scope)
5. Process LLM pragmas

**Why**: Enables mutual recursion and forward references.

```python
# Both can reference each other
even n = if n == 0 then True else odd (n - 1)
odd n = if n == 0 then False else even (n - 1)
```

**Date**: 2026-03-02

---

## Decision 10: Scoped AST Stores Indices + Names

**Decision**: `ScopedVar` has both `index: int` AND `original_name: str`.

**Rationale**:
- Index for computation (substitution, lookup)
- Name for error messages
- Can't reconstruct name from index alone

**Implementation**:
```python
@dataclass
class ScopedVar:
    index: int           # For type checking
    original_name: str   # For error reporting
```

**Date**: 2026-03-02

---

## Decision 11: Error Hierarchy

**Decision**: Unified error hierarchy with source location.

**Structure**:
```
SystemFError (abstract)
├── ScopeError
├── TypeError
│   ├── UnificationError
│   ├── TypeMismatch
│   └── ...
├── ElaborationError
└── ParseError
```

**Features**:
- All errors have `location`, `message`
- Optional `term` (problematic term)
- Optional `diagnostic` (helpful suggestion)

**Date**: 2026-03-02

---

## Open Questions

**Q1**: How to handle type variables in scope checking?
- Option A: Same as term variables (list with indices)
- Option B: Set (order doesn't matter for types)

**Q2**: Should we keep old elaborator during transition?
- Leaning toward: No (all at once)

**Q3**: How to test partially scoped terms?
- Need `is_fully_scoped()` detection function

---

## Decisions Pending

None currently. All major architectural decisions made.

---

## Implementation Status

**Completed**:
- ✅ Research on elaborator architectures
- ✅ Core AST with source locations
- ✅ Core AST with debug names
- ✅ Error hierarchy
- ✅ Documentation

**Not Started**:
- ❌ Scope checker
- ❌ Scoped AST extensions
- ❌ Type elaborator (refactored)
- ❌ Pipeline orchestration
- ❌ LLM pragma pass

**Estimated Timeline**: 3 weeks

---

## References

- `docs/elaboration-comparison.md` - Language comparison
- `docs/elaborator-architecture-analysis.md` - Architecture analysis
- `docs/elaborator-implementation-plan.md` - Implementation plan
- `docs/scoped-ast-design.md` - Scoped AST design
- `docs/scoped-extended-ast-design.md` - Extended Surface AST design
- `docs/type-architecture-review.md` - Type system review

---

**Last Updated**: 2026-03-02
**Next Review**: When implementation begins
