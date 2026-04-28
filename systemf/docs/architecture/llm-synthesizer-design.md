# System F LLM Synthesizer Design

**Last Updated**: 2026-03-09
**Status**: Draft - Pending Review

## Overview

This document specifies the design for synthesizing LLM function bodies that operate on forked REPL sessions. The synthesizer creates `PrimOp` implementations at declaration time that internalize: REPL forking with type constraints, LLM operation via virtual interface, and result retrieval with type validation.

## Key Characteristics

- **Declaration-Time Synthesis**: LLM function body synthesized when pragma is parsed
- **Virtual REPL Forking**: Each call creates isolated REPL session with frozen types
- **Tape Primitive**: First-class `Tape` type for session persistence
- **IORef Integration**: Global mutable state for cross-session data
- **Type Safety**: Return type and dependencies frozen, validated on result retrieval

---

## Architecture Flow

```mermaid
graph TD
    subgraph Declaration["Declaration Phase (REPL Init)"]
        P[Parse {-# LLM ... #-} decl]
        A[Analyze return type]
        F[Collect frozen type deps]
        S[Synthesize PrimOp body]
        P --> A --> F --> S
    end
    
    subgraph Runtime["Runtime (Function Call)"]
        C{Has Tape?}
        FT[Create fresh fork]
        RT[Resume from Tape]
        INJ[Inject arg to env]
        OP[LLM operates via tools]
        GET[Get 'it' value]
        VAL[Validate return type]
        RET[Return to caller]
    end
    
    subgraph Types["Type System"]
        T[Tape a - primitive]
        IO[IORef a - mutable cell]
        FZ[Frozen type constraint]
    end
    
    Declaration -->|Registers PrimOp| Runtime
    C -->|No| FT
    C -->|Yes| RT
    FT --> INJ
    RT --> INJ
    INJ --> OP --> GET --> VAL --> RET
```

---

## Core Components

### 1. Synthesizer (`src/systemf/surface/llm/synthesizer.py`)

| Component | Purpose |
|-----------|---------|
| `LLMSynthesizer` | Analyzes declarations and creates PrimOp bodies |
| `FrozenTypeCollector` | Traverses return type to collect dependencies |
| `PrimOpFactory` | Creates Core AST PrimOp with captured context |

**Synthesis Process:**

```python
def synthesize_llm_function(decl: SurfaceDeclaration) -> core.PrimOp:
    # 1. Extract return type from signature
    return_type = extract_return_type(decl.type_annotation)
    
    # 2. Collect frozen type dependencies
    frozen_types = collect_type_dependencies(return_type)
    
    # 3. Build synthesis context
    context = SynthesisContext(
        function_name=decl.name,
        frozen_types=frozen_types,
        llm_metadata=extract_metadata(decl),
        tape_param=has_tape_parameter(decl),  # Check if takes Tape arg
    )
    
    # 4. Create opaque PrimOp body
    return core.PrimOp(
        name=f"llm.{decl.name}",
        synthesis_context=context,
    )
```

### 2. Virtual REPL (`src/systemf/eval/virtual_repl.py`)

| Method | Purpose |
|--------|---------|
| `fork(frozen_types)` | Create isolated REPL with type constraints |
| `eval(expr)` | Execute expression, returns Value + Type |
| `get_it()` | Retrieve last evaluated result |
| `to_tape()` | Serialize to Tape handle |

**Interface:**

```python
class VirtualREPL:
    def __init__(self, parent_context: REPLContext, frozen_types: set[str]):
        self.global_values = dict(parent_context.global_values)
        self.global_types = dict(parent_context.global_types)
        self.frozen_types = frozen_types  # Cannot redefine these
        
    def eval(self, expr: str) -> tuple[Value, Type]:
        # Parse, elaborate, evaluate in isolation
        pass
        
    def get_it(self) -> Value:
        return self.global_values.get("it")
```

### 3. Tape Primitive Type

**Type Definition:**

```systemf
-- Tape is primitive type representing forked session
prim_type Tape :: * -> *  -- Tape a where a is return type

-- Operations
prim_op fork  :: ∀a. (Unit → a) → Tape a
prim_op resume :: ∀a. Tape a → a
```

**Runtime Representation:**

```python
@dataclass
class VTape(Value):
    """Tape value holding virtual REPL session."""
    session_id: str
    return_type: Type
    frozen_types: set[str]
    repl_state: VirtualREPL  # Or serialized state
```

### 4. IORef for Global Mutable

**Type Definition:**

```systemf
-- IORef for global mutable state
prim_type IORef :: * -> *

prim_op newIORef :: ∀a. a → IORef a
prim_op readIORef :: ∀a. IORef a → a  
prim_op writeIORef :: ∀a. IORef a → a → Unit
```

**Use in LLM Functions:**

```systemf
-- Module-level mutable state
counter :: IORef Int = newIORef 0

-- LLM can access via environment
llm_increment :: Int → Int
{-# LLM model=gpt-4 #-}
llm_increment n = 
  -- LLM operates in fork, can read/write counter
  -- counter accessible via $counter in env
  ...
```

### 5. Evaluator Integration (`src/systemf/eval/machine.py:67-91`)

**Extended `_execute_llm_call`:**

```python
def _execute_llm_call(self, metadata: LLMMetadata, arg: Value) -> Value:
    """Execute LLM call with forking semantics."""
    
    # Check if we have a Tape argument
    if isinstance(arg, VTape):
        # Resume from existing tape
        virtual_repl = arg.repl_state
    else:
        # Create fresh fork with frozen types
        virtual_repl = VirtualREPL(
            parent_context=self.current_repl_context,
            frozen_types=metadata.frozen_types,
        )
        # Inject argument
        virtual_repl.global_values["$arg"] = arg
    
    # LLM operates on virtual REPL via tool interface
    self._llm_operate(virtual_repl, metadata)
    
    # Get result
    result = virtual_repl.get_it()
    
    # Type check against return type
    if not self._check_type(result, metadata.return_type):
        raise TypeError("Return type mismatch")
    
    return result
```

---

## Design Decisions

### Why Synthesize at Declaration Time?

> **Design Note:** "Synthesizing at declaration time ensures the function has a stable, opaque body. The complexity of 'fork with constraints, operate, retrieve' is hidden inside the PrimOp, making the Core AST clean and the runtime straightforward."

**Benefits:**
- Clean separation: elaboration creates body, evaluator executes it
- Type constraints known statically, frozen at synthesis time
- Function value is just a PrimOp reference

### Why Virtual REPL Instead of Direct Fork?

> **Design Note:** "The LLM operates on a virtual interface that mimics REPL interaction. This provides auditability (we log all operations) and safety (constrained environment)."

**Trade-offs:**
- ✅ Audit trail of all LLM operations
- ✅ Can replay/reproduce synthesis sessions
- ✅ Constrained surface area (only `eval`, `get_it`)
- ❌ Slight overhead vs direct execution

### Why Tape as Primitive Type?

> **Design Note:** "Tape captures the session state for resumption. Making it a first-class value enables passing sessions between functions and persisting across calls."

---

## Type Freezing Semantics

**Frozen Type Dependencies:**

```python
def collect_type_dependencies(ty: Type) -> set[str]:
    """Collect all type constructors that must be frozen."""
    deps = set()
    
    def collect(t):
        match t:
            case TypeConstructor(name, args):
                deps.add(name)
                for arg in args:
                    collect(arg)
            case TypeArrow(arg, ret):
                collect(arg)
                collect(ret)
            case TypeForall(_, body):
                collect(body)
                
    collect(ty)
    return deps
```

**Constraint Enforcement:**

```python
class ConstrainedREPL(REPL):
    def define_type(self, name: str, defn: TypeDefinition):
        if name in self.frozen_types:
            raise TypeError(f"Cannot redefine frozen type: {name}")
        super().define_type(name, defn)
```

---

## Open Questions

1. **Tape Serialization**: Should Tape be serializable to disk, or only in-memory?
2. **IORef Scope**: Are IORefs global to all sessions, or scoped per module?
3. **Error Handling**: How do synthesis failures propagate? Exception or Result type?
4. **Progressive Loading**: Should `:load` add to frozen types or treat as separate module?
5. **Tool Interface**: What specific tools does LLM have access to? (eval, typeof, query_docs?)

---

## Implementation Files

| File | Purpose | Lines (est) |
|------|---------|-------------|
| `src/systemf/surface/llm/synthesizer.py` | Declaration analysis & PrimOp synthesis | ~200 |
| `src/systemf/eval/virtual_repl.py` | Virtual REPL session management | ~150 |
| `src/systemf/core/types.py` | Tape and IORef type definitions | ~50 |
| `src/systemf/eval/machine.py` | Extended LLM call execution | ~100 |
| `src/systemf/eval/tape_value.py` | VTape runtime representation | ~50 |

---

## Related Documentation

- **Elaborator Design**: See `docs/architecture/elaborator-design.md` for pipeline structure
- **Type System**: See `docs/architecture/type-system-review.md` for System F types
- **Evaluator**: See `src/systemf/eval/machine.py` for current evaluation logic
- **LLM Pragmas**: See `src/systemf/surface/llm/pragma_pass.py` for existing pragma handling

---

**Next Step**: Review open questions and clarify semantics before implementation.
