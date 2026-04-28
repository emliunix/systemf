# Type Architecture Review

## Current Type Hierarchy

### Core Types (`core/types.py`)

**Base Type:**
```python
class Type:
    def free_vars(self) -> set[str]
    def substitute(self, subst: dict[str, Type]) -> Type
```

**Type Variants:**
- `TypeVar(name: str)` - Type variable
- `TypeArrow(arg: Type, ret: Type, param_doc: Optional[str])` - Function type with param docs
- `TypeForall(var: str, body: Type)` - Polymorphic type
- `TypeConstructor(name: str, args: list[Type])` - Data type constructor
- `PrimitiveType(name: str)` - Primitive types (Int, String, etc.)

**Issues:**
- ✅ Fixed: Missing `Optional` import
- ❌ `param_doc` in `TypeArrow` - Is this the right place? Consider alternatives:
  - Separate metadata map: `param_docs: dict[TypePath, str]`
  - Keep in type but it complicates equality/substitution

### Core AST (`core/ast.py`)

**Terms (de Bruijn indexed):**
```
Term
├── Var(index: int)                          # Local variable
├── Global(name: str)                        # Top-level reference
├── Abs(var_type: Type, body: Term)          # Lambda
├── App(func: Term, arg: Term)               # Application
├── TAbs(var: str, body: Term)               # Type abstraction
├── TApp(func: Term, type_arg: Type)         # Type application
├── Constructor(name: str, args: list[Term]) # Data constructor
├── Case(scrutinee: Term, branches: list[Branch])
├── Let(name: str, value: Term, body: Term)
├── IntLit(value: int)
├── StringLit(value: str)
├── PrimOp(name: str)
└── ToolCall(tool_name: str, args: list[Term])
```

**Declarations:**
```python
Declaration = DataDeclaration | TermDeclaration

DataDeclaration:
  - name: str                           # Type constructor name
  - params: list[str]                   # Type parameters
  - constructors: list[tuple[str, list[Type]]]  # (name, arg_types)

TermDeclaration:
  - name: str
  - type_annotation: Optional[Type]
  - body: Term
  - pragma: Optional[str]              # LLM config or other
  - docstring: Optional[str]
  - param_docstrings: Optional[list[str]]
```

**Design Notes:**
- ✅ Clean separation between Term and Declaration
- ✅ Primitive operations use `PrimOp` with string name
- ✅ Global vs Var distinction is clear
- ⚠️ `TermDeclaration` stores metadata (docstrings, pragma) - is this right?

### Module (`core/module.py`)

```python
Module:
  - name: str
  - declarations: list[Declaration]
  - constructor_types: dict[str, Type]     # Constructor name -> Type
  - global_types: dict[str, Type]          # Global term name -> Type
  - primitive_types: dict[str, PrimitiveType]
  - docstrings: dict[str, str]             # Redundant with TermDeclaration?
  - llm_functions: dict[str, LLMMetadata]  # Extracted from declarations
  - errors: list[ElaborationError]
  - warnings: list[str]

LLMMetadata:
  - function_name: str
  - function_docstring: Optional[str]
  - arg_types: list[Type]
  - arg_docstrings: list[Optional[str]]
  - pragma_params: Optional[str]
```

**Issues:**
1. **Data Duplication**: `docstrings` in Module vs `docstring` in TermDeclaration
2. **LLMMetadata**: Why separate from TermDeclaration? Answer: Easier lookup at runtime
3. **Error Handling**: Should Module contain errors or should elaboration return `Result[Module, list[Error]]`?

### Context (`core/context.py`)

```python
Context:
  - term_vars: list[Type]      # Index 0 = most recent
  - type_vars: set[str]
```

**Operations:**
- `lookup_type(index: int) -> Type`
- `extend_term(ty: Type) -> Context`
- `extend_type(var: str) -> Context`

**Issues:**
- ✅ Immutable design (returns new Context)
- ⚠️ Missing: Global context for top-level definitions during type checking

### Errors (`core/errors.py`)

**Hierarchy:**
```
TypeError(Exception)
├── UnificationError(t1: Type, t2: Type)
├── TypeMismatch(expected: Type, actual: Type)
├── UndefinedVariable(index: int)
├── UndefinedConstructor(name: str)
└── OccursCheckError(var: str, t: Type)

ElaborationError(Exception)  # Not a TypeError!
```

**Issues:**
1. `ElaborationError` is separate - should it inherit from `TypeError`?
2. `UndefinedVariable` takes `index: int` (for core) but elaborator uses names

---

## Type Flow Through Compilation Pipeline

### Pipeline Overview

```
Source Text
    ↓
Parse → Surface AST (names, sugar)
    ↓
Scope Check → Scoped AST (de Bruijn indices, resolved names)
    ↓
Type Inference → Typed AST + Constraints
    ↓
Elaborate → Core AST + Types
    ↓
Verify → Verified Core AST
    ↓
Module (aggregated declarations + metadata)
```

### Missing: Intermediate AST Types

Currently we have:
- **Surface AST** (`surface/types.py`) - Names, optional types, sugar
- **Core AST** (`core/ast.py`) - de Bruijn, fully typed

**Missing:**
1. **Scoped AST** - After name resolution but before type checking
   - Same structure as Core but without types
   - Or: Core with `Type` being `Type | Unknown`

2. **Typed AST** - During type inference with unification variables
   - Terms annotated with types or metavariables
   - Constraint set alongside

**Recommendation:** For now, the elaborator produces Core directly. As we add more sophisticated inference, we may need intermediate representations.

---

## Issues and Recommendations

### 1. Docstring Duplication

**Current:**
- `TermDeclaration.docstring` - stores docstring
- `Module.docstrings` - same info, different format

**Problem:** Sync issues, duplication

**Options:**
1. **Keep in TermDeclaration only**: Module extracts on demand
2. **Keep in Module only**: TermDeclaration has name, lookup in Module
3. **Keep both**: Accept duplication for convenience

**Recommendation:** Option 1 - Single source of truth in TermDeclaration

### 2. Metadata Placement

**Current:**
```python
TermDeclaration:
  - pragma: Optional[str]              # Opaque config
  - docstring: Optional[str]
  - param_docstrings: Optional[list[str]]
```

**Question:** Should metadata be separate from Core AST?

**Idris 2 approach:**
- Core AST is pure semantics
- Metadata stored separately in interface files

**Recommendation:** Keep in TermDeclaration for now, but consider:
```python
@dataclass
DeclarationMetadata:
    docstring: Optional[str]
    param_docstrings: list[Optional[str]]
    pragma: Optional[str]
    location: Location

# Module stores:
metadata: dict[str, DeclarationMetadata]
```

### 3. Type Variable Representation

**Current:**
```python
TypeVar(name: str)  # Names in both surface and core
```

**Issue:** Name collision in nested scopes
```haskell
(\x:a -> x) (\y:a -> y)  -- Both 'a' are different!
```

**Options:**
1. **Keep names**: Simple, but need to be careful with substitution
2. **de Bruijn for types too**: `TVar(index: int)` like terms
3. **Unique IDs**: Generate fresh names during elaboration

**Recommendation:** Keep names for now (System F style), but:
- Use substitution carefully (avoid capture)
- Add alpha-equivalence check
- Consider switching to de Bruijn for type variables if we add implicits

### 4. Module Error Handling

**Current:**
```python
Module(errors: list[ElaborationError])
```

**Problem:** Caller must check `if module.errors:`

**Alternative:**
```python
from typing import TypeVar, Generic
T = TypeVar('T')

class Result(Generic[T]):
    """Result type like Rust's Result."""
    value: T | None
    errors: list[Error]
    
    @property
    def is_ok(self) -> bool: ...
    
    def unwrap(self) -> T: ...

def elaborate(decls: list[SurfaceDeclaration]) -> Result[Module]:
    ...

# Usage:
result = elaborate(decls)
if result.is_ok:
    module = result.unwrap()
else:
    for error in result.errors:
        print(error)
```

**Recommendation:** Add Result type for cleaner error handling

### 5. Missing: Source Locations in Core AST

**Current:**
- Core AST has no location information
- Errors point to elaborated code, not source

**Problem:** Hard to report good error messages

**Solution:**
```python
@dataclass(frozen=True)
class CoreTerm:
    """Base class for core terms with source mapping."""
    source_loc: Optional[Location]  # Where this term came from
    
@dataclass(frozen=True)
class Var(CoreTerm):
    index: int
```

Or: Keep separate source map:
```python
source_map: dict[CoreTerm, Location]  # Weak references
```

**Recommendation:** Add source_loc to Core AST base class

### 6. Type Annotation Redundancy

**Current:**
```python
# Surface
SurfaceAnn(term: SurfaceTerm, type: SurfaceType)

# Core
Abs(var_type: Type, body: Term)
```

**Issue:** Type annotations exist in both surface and core

**Idris 2 approach:**
- Surface: Optional annotations
- TTImp: May have types or metavariables
- Core: Always fully typed

**Recommendation:** 
- Surface: Keep annotations optional
- Core: Require types (already done)
- Intermediate: Use `Type | MetaVar`

### 7. Constructor Types Storage

**Current:**
```python
Module:
  constructor_types: dict[str, Type]  # "Cons" -> forall a. a -> List a -> List a
```

**Question:** Should this be in Module or separate registry?

**Considerations:**
- Needed for type checking
- Immutable after elaboration
- Could be part of a "Signature" type

**Recommendation:** Keep in Module for now, but consider:
```python
@dataclass(frozen=True)
class Signature:
    """Immutable type signatures for a module."""
    constructors: dict[str, Type]
    globals: dict[str, Type]
    primitives: dict[str, PrimitiveType]
```

---

## Proposed Refactoring

### Immediate Fixes

1. ✅ **Fix Optional import** - Already done
2. **Add Result type for error handling**
3. **Add source locations to Core AST**
4. **Remove redundant docstrings dict from Module**

### Medium-term

1. **Create Signature type**
2. **Separate metadata from Core AST**
3. **Add Scoped AST intermediate**
4. **Consider de Bruijn indices for type variables**

### Long-term

1. **Unification variables / MetaVar type**
2. **Constraint type for type inference**
3. **Case tree representation for pattern matching**

---

## Type Comparison: System F vs Idris 2

| Feature | System F (Current) | Idris 2 | Notes |
|---------|-------------------|---------|-------|
| **Term variables** | de Bruijn indices | de Bruijn indices | ✅ Same |
| **Type variables** | Names | Names | Same, but Idris uses unique IDs internally |
| **Types in AST** | Required | Required | ✅ Same |
| **Source locations** | Missing | Present | ❌ We need this |
| **Metadata** | In declarations | Separate | ❌ Consider separation |
| **Module** | Mutable error list | Interface files | ⚠️ Interface files are the "compiled" form |
| **Error handling** | Accumulate in Module | Fail fast with context | ⚠️ Result type would help |

---

## Conclusion

The type architecture is solid but needs refinement:

**Strengths:**
- Clean separation between Surface and Core
- Good use of dataclasses
- Proper de Bruijn indices in Core

**Weaknesses:**
- Missing source locations in Core AST
- Redundant metadata storage
- Error handling could be cleaner
- No intermediate representations

**Priority Actions:**
1. Add source locations to Core AST
2. Create Result type for error handling
3. Remove docstrings duplication
4. Consider Signature type for type information
