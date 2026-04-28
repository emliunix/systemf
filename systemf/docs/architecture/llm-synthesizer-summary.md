# System F LLM Synthesizer Design - Final Summary

**Status**: Ready for Implementation Planning
**Date**: 2026-03-09

---

## Design Documents

1. **`llm-synthesizer-design.md`** - Main design specification
2. **`llm-synthesizer-qa.md`** - First round Q&A (10 categories)
3. **`llm-synthesizer-qa2.md`** - Second round Q&A (31 follow-up questions)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DECLARATION PHASE                        │
│  (REPL Init / Module Load)                                  │
│                                                             │
│  Parse {-# LLM ... #-} decl                                 │
│         ↓                                                   │
│  Synthesizer.analyze(return_type)                           │
│         ↓                                                   │
│  Collect frozen type dependencies                           │
│         ↓                                                   │
│  Create SynthesisContext                                    │
│         ↓                                                   │
│  Register in Evaluator.synthesis_registry                   │
│         ↓                                                   │
│  Return PrimOp(name="llm.func_name")  ← Opaque marker       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME PHASE                           │
│  (Function Call)                                            │
│                                                             │
│  User: analyze myData                                       │
│         ↓                                                   │
│  Evaluator sees PrimOp("llm.analyze")                       │
│         ↓                                                   │
│  Lookup SynthesisContext in registry                        │
│         ↓                                                   │
│  {Has Tape param?}                                          │
│    ↓ YES                           ↓ NO                     │
│  Use existing Tape            Create fresh fork             │
│    ↓                               ↓                        │
│  Resume from Tape state       Copy parent context           │
│                               Apply frozen_types            │
│         ↓                                                   │
│  Inject $arg into fork environment                          │
│         ↓                                                   │
│  LLM operates via tool interface                            │
│    - eval(expr) → {value, type, it_updated}                 │
│    - typeof(expr) → type string                             │
│    - browse() → available values/types                      │
│         ↓                                                   │
│  LLM produces "it" binding                                  │
│         ↓                                                   │
│  Get result = fork.get_it()                                 │
│         ↓                                                   │
│  Validate type against return_type                          │
│    ↓ Match                       ↓ Mismatch                 │
│  Return value                 raise TypeError               │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

| Component | Decision | Rationale |
|-----------|----------|-----------|
| **Core AST** | Opaque `PrimOp` with registry | Minimal AST, redefinition support |
| **Synthesis** | Hardcoded template | No per-function code generation |
| **Tape** | Phantom type `Tape a` | Type-safe resumption |
| **Fresh fork** | Auto-created, auto-discarded | Simple default case |
| **IORef** | Session-scoped, shared across forks | Cross-fork mutable state |
| **Frozen types** | Return type + dependencies only | Minimal constraints |
| **Tool interface** | 3 tools (eval, typeof, browse) | Minimal viable surface |
| **Error handling** | Exceptions | Simple failure mode |
| **Timeout** | 5min default, configurable | Prevents infinite hangs |
| **Concurrency** | Cooperative (async) | Simpler than true parallelism |

---

## Type System Integration

### New Primitive Types

```systemf
-- Tape for session persistence
prim_type Tape :: * → *           -- Phantom type parameter

-- IORef for mutable state  
prim_type IORef :: * → *

-- Primitive operations
prim_op spawn :: ∀a. (Unit → a) → Tape a
prim_op resume :: ∀a. Tape a → a
prim_op newIORef :: ∀a. a → IORef a
prim_op readIORef :: ∀a. IORef a → a
prim_op writeIORef :: ∀a. IORef a → a → Unit
```

### LLM Function Declaration

```systemf
-- Fresh fork (default)
analyze :: Data → Result
{-# LLM model=gpt-4 timeout=600 #-}
analyze data = ...

-- With Tape parameter (resumption)
analyzeWithContext :: Tape Result → Data → Result
{-# LLM model=gpt-4 #-}
analyzeWithContext tape data = ...

-- With IORef for mutable state
counter :: IORef Int = newIORef 0

increment :: Int → Int
{-# LLM model=gpt-4 #-}
increment n = ...  -- Can access counter via environment
```

---

## Implementation Files (Estimated)

| File | Lines | Purpose |
|------|-------|---------|
| `src/systemf/surface/llm/synthesizer.py` | ~250 | Declaration analysis, context creation |
| `src/systemf/eval/virtual_repl.py` | ~200 | Forked REPL with constraints |
| `src/systemf/eval/synthesis_registry.py` | ~100 | Registry management |
| `src/systemf/eval/llm_tools.py` | ~150 | Tool interface for LLM |
| `src/systemf/core/types.py` (extend) | ~50 | Tape, IORef type definitions |
| `src/systemf/eval/value.py` (extend) | ~50 | VTape, VIORef runtime values |
| `src/systemf/eval/machine.py` (extend) | ~100 | Integration with evaluator |
| `tests/test_llm_synthesizer/` | ~300 | Comprehensive tests |
| **Total** | **~1200** | |

---

## Critical Unknowns (Before Implementation)

### None identified

After two rounds of Q&A (41 total questions), all major design questions have been answered:

- ✅ Core AST structure (opaque PrimOp)
- ✅ Registry lifecycle (session-scoped)
- ✅ Tape semantics (fresh vs resume)
- ✅ IORef behavior (shared across forks)
- ✅ Tool interface (3 tools, JSON-RPC)
- ✅ Error handling (exceptions)
- ✅ Concurrency model (cooperative)
- ✅ Type validation (runtime check)
- ✅ Synthesis mechanism (hardcoded template)

---

## Next Steps

### Option 1: Third Review Round
Launch another subagent to review `llm-synthesizer-qa2.md` and check for:
- Inconsistencies between answers
- Missing edge cases
- Implementation gotchas

### Option 2: Implementation Planning
Create detailed implementation plan with:
- Component dependency graph
- Implementation order (bottom-up)
- Test strategy
- Milestone breakdown

### Option 3: Start Implementation
Begin coding with:
1. Core types (Tape, IORef)
2. VirtualREPL scaffolding
3. Synthesis registry
4. Tool interface
5. Integration

---

## Recommendation

**Proceed to Implementation Planning (Option 2)**

The design is sufficiently detailed. A structured implementation plan will help identify any remaining gaps during the planning phase.

---

## Quick Reference

### SynthesisContext Structure
```python
@dataclass
class SynthesisContext:
    function_name: str
    frozen_types: set[str]          # Type names that cannot be redefined
    return_type: Type               # For validation
    llm_config: dict                # model, temperature, timeout, etc.
    has_tape_param: bool            # Whether to expect Tape argument
```

### VirtualREPL API
```python
class VirtualREPL:
    def __init__(self, parent: REPLContext, frozen_types: set[str])
    def eval(self, expr: str) -> dict  # {value, type, it_updated}
    def typeof(self, expr: str) -> str
    def browse(self) -> dict           # {values, types, frozen_types}
    def get_it(self) -> Value
```

### Evaluator Integration
```python
class Evaluator:
    synthesis_registry: dict[str, SynthesisContext]
    
    def register_llm_function(self, name: str, context: SynthesisContext)
    def _execute_llm_call(self, context: SynthesisContext, arg: Value) -> Value
```

---

**Documents Location**: `systemf/docs/architecture/llm-synthesizer-*.md`
