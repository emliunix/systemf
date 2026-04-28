# Elaboration Architecture Comparison

## Overview

This document compares the elaboration architectures of four major dependently-typed / advanced type system languages:
- **Lean 4** (Theorem prover + programming language)
- **GHC Haskell** (Industrial strength, lazy, type classes)
- **Agda** (Dependently typed, proof assistant)
- **Idris 2** (Dependently typed, practical programming)

## Key Concepts

### What is Elaboration?

**Elaboration** is the process of translating surface syntax (what users write) into a core language (what the machine checks/executes). It involves:

1. **Name resolution** (scope checking)
2. **Type inference** (figuring out missing types)
3. **Implicit argument synthesis** (filling in `_` holes)
4. **Desugaring** (removing syntactic sugar)
5. **Translation** to core language

### The Core Question

**Is elaboration a single pass or multiple passes?**

Answer: All these languages use **multiple passes**, but they organize them differently.

---

## Language-by-Language Analysis

### 1. Lean 4

**Architecture: Command vs Term Elaboration**

Lean 4 distinguishes between:

```
Syntax (surface) → CommandElabM Unit  (commands: def, inductive, etc.)
                → TermElabM Expr    (terms: expressions)
```

**Pipeline:**
```
1. Parse → Syntax (concrete syntax tree)
2. Macro Expansion → Expanded Syntax
3. Command Elaboration → Environment changes
4. Term Elaboration → Expr (core language)
5. Kernel Check → Verified Expr
```

**Key Design Decisions:**

1. **Command vs Term Distinction**
   - Commands (`def`, `inductive`, `theorem`) modify the environment
   - Terms (`2 + 2`, `λx => x`) elaborate to expressions
   - **Why?** Commands have side effects on the global state

2. **Elaborator Monad (`TermElabM`)**
   ```lean
   TermElabM = StateT TermElabState (ExceptT Exception MetaM)
   ```
   - Carries: local context, expected type, metavariables, info trees
   - Supports: backtracking, metavariables, constraint solving

3. **Info Trees**
   - Metadata associating core terms with source positions
   - Used for: IDE features, hover info, go-to-definition

4. **Kernel Separation**
   - Elaborator produces `Expr` (core language)
   - Kernel independently verifies `Expr`
   - **Critical:** Kernel is small, trusted, pure

**Top-level vs Local:**
- Commands are elaborated at the top level
- Terms can appear in commands (e.g., `def f := term`)
- Local `let` bindings are elaborated as part of the enclosing term

**Metavariables:**
- Unified during elaboration
- Constraint queue in the monad state
- Dynamic pattern unification

**Pros:**
- Clean separation of concerns
- Extensible via elaborator reflection
- Strong IDE support via info trees

**Cons:**
- Complex monad stack
- Elaborator is large and complex

---

### 2. GHC Haskell

**Architecture: The Five-Stage Pipeline**

```
Source Text
    ↓
Parser → HsSyn (Haskell Abstract Syntax)
    ↓
Renamer → Resolved HsSyn
    ↓
Typechecker → Type-annotated HsSyn
    ↓
Desugarer → Core
    ↓
Core-to-Core Optimizations
    ↓
Code Generation
```

**Stage 1: Parser**
- Produces `HsSyn` (concrete syntax with sugar)
- Handles layout, indentation
- No name resolution yet

**Stage 2: Renamer**
- **Scope checking:** Resolves names to unique identifiers
- **Dependency analysis:** Finds groups of mutually recursive bindings
- **Operator resolution:** Fixes precedences
- **Produces:** `HsSyn` with `Name` (not `RdrName`)

**Stage 3: Type Checker**
- Bidirectional type checking
- Constraint generation and solving
- Type class dictionary elaboration
- Produces: Type-annotated `HsSyn` with `Id`

**Stage 4: Desugarer**
- Remove all syntactic sugar:
  - Pattern matching → case expressions
  - List comprehensions → monadic operations
  - Do notation → `>>=` and `>>`
  - Type classes → dictionary passing
- Produces: Core (System FC)

**Stage 5: Core-to-Core**
- Optimizations on Core
- Simplifier, specializer, etc.

**Top-level vs Local:**

**Top-level declarations:**
- Collected in the renamer
- Dependency-sorted into strongly-connected components (SCCs)
- Type checked together if mutually recursive
- **Generalization:** Top-level bindings get polymorphic types (via let-generalization)

**Local bindings:**
- Monomorphic by default (with `-XMonoLocalBinds`)
- Can be recursive via `let rec` (in GHC's core)

**Key Insight:**
GHC keeps source syntax (`HsSyn`) through most of the pipeline, only converting to Core at the end. This preserves source location information for error messages.

**Pros:**
- Clear pipeline stages
- Excellent error messages (preserve source info)
- Separate desugaring phase is clean

**Cons:**
- Multiple AST representations (memory overhead)
- Type class elaboration is complex

---

### 3. Agda

**Architecture: Concrete → Abstract → Internal**

```
Concrete Syntax (what user writes)
    ↓
Scope Checking (ConcreteToAbstract)
    ↓
Abstract Syntax (scope-resolved, still surface-ish)
    ↓
Type Checking
    ↓
Internal Syntax (core language)
```

**Key Design Decisions:**

1. **Concrete vs Abstract**
   - **Concrete:** Exact user syntax (with ranges for error locations)
   - **Abstract:** Names resolved, operators fixed, but still surface-like

2. **Scope Checking (`concreteToAbstract`)**
   - Resolves names in scope
   - Handles `open import` and module parameters
   - Produces: Abstract syntax with resolved identifiers

3. **Type Checking**
   - Elaborates abstract syntax to internal syntax
   - Unification for metavariables
   - Constraint solving
   - Produces: `Term` (de Bruijn indices)

4. **No Separate Renamer**
   - Scope checking is the renaming phase
   - Unlike GHC, no separate "renamer" pass

**Top-level vs Local:**

**Top-level:**
- Declarations are scope-checked one by one
- Mutual recursion: All declarations in a mutual block are scope-checked together
- **Forwarding references:** Allowed within a mutual block

**Local `let`:**
- Scope-checked in context
- Can refer to outer scope
- Type checking can generalize (monomorphic by default in recent Agda)

**Metavariables:**
- Created during type checking
- Solved by unification
- Can be postponed (constraint queue)

**Pros:**
- Clean distinction between concrete and abstract
- Good source location preservation
- Module system is sophisticated

**Cons:**
- Module system complexity
- Performance issues with large modules

---

### 4. Idris 2

**Architecture: Explicit Multi-Pass (TTImp → TT)**

Idris 2 has the **clearest separation** of phases:

```
Source Text
    ↓
Parser → RawImp (surface AST with names)
    ↓
Scope Checker → TTImp (de Bruijn indices, well-scoped)
    ↓
Elaborator → TT (core language with type annotations)
    ↓
Totality Checker → Verified TT
    ↓
Code Generation
```

**Key Data Types:**

```idris
-- RawImp: Surface syntax (names)
RawImp : Type

-- TTImp: Scope-checked, de Bruijn indices
TTImp : Type

-- TT: Core language (fully elaborated)
TT : Type
```

**Pass 1: Parsing → RawImp**
- Standard parsing
- Produces surface AST with names

**Pass 2: Scope Checking → TTImp**
- **Name resolution** to de Bruijn indices
- **Import handling**
- **Operator resolution**
- **Produces:** `TTImp` - well-scoped but not yet type-checked

**Pass 3: Elaboration → TT**
- **Type inference** with unification
- **Implicit argument synthesis**
- **Translation to core language**
- Uses: **Elaborator monad** with metavariable state

**Key Design Decisions:**

1. **Explicit Intermediate (`TTImp`)**
   - Makes the scope-checking/type-checking boundary explicit
   - Enables separate testing of each phase
   - Improves error reporting

2. **Elaborator Monad**
   ```idris
   Elab : Type -> Type
   -- State: proof state with metavariables
   -- Supports: unification, backtracking, hole manipulation
   ```

3. **Metavariables in Global State**
   - Stored in a mutable array (following Norell's thesis)
   - O(1) access during unification
   - Constraint queue for postponed problems

4. **Totality Checking (Separate Pass)**
   - After elaboration, check termination
   - Pattern coverage checking
   - Produces: Verified core terms

**Top-level vs Local:**

**Top-level declarations:**
1. Collect all names first
2. Elaborate type signatures
3. Elaborate definitions (with names in scope)
4. **Mutual recursion:** All definitions see each other

**Local `let`:**
- Elaborated immediately in context
- Monomorphic (no let-generalization)
- Can be recursive with explicit `let rec`

**Lazy Import Loading:**
- Definitions loaded only when referenced
- Major performance improvement over Idris 1

**Pros:**
- Cleanest separation of phases
- Excellent for understanding compiler architecture
- Fast unification with global metavariable state

**Cons:**
- Multiple AST types to maintain
- Two passes over the tree

---

## Comparative Summary

| Aspect | Lean 4 | GHC | Agda | Idris 2 |
|--------|--------|-----|------|---------|
| **Surface AST** | `Syntax` | `HsSyn` | `Concrete` | `RawImp` |
| **Intermediate** | `Syntax` (expanded) | `HsSyn` (renamed) | `Abstract` | `TTImp` (scoped) |
| **Core Language** | `Expr` | `Core` | `Internal` | `TT` |
| **Passes** | Parse→Macro→Elab | Parse→Rename→Type→Desugar | Parse→Scope→Type | Parse→Scope→Elab |
| **Scope Check** | During elaboration | Renamer pass | `concreteToAbstract` | Separate pass |
| **Type Check** | `TermElabM` | Bidirectional | Constraint-based | `Elab` monad |
| **Metavariables** | Yes (elaborator state) | Yes (constraints) | Yes (constraint queue) | Yes (global array) |
| **Command/Term Split** | Yes (CommandElabM/TermElabM) | No (all via HsSyn) | No | No (but declarations separate) |
| **Kernel Check** | Yes (separate) | No (trust type checker) | No | No (trust elaborator) |

## Top-Level vs Local Handling

### Common Patterns

| Feature | Top-Level | Local |
|---------|-----------|-------|
| **Scope** | Global/module | Expression-bound |
| **Recursion** | Mutual, forward refs | Sequential (unless `let rec`) |
| **Type Generalization** | Yes (polymorphism) | No (monomorphic by default) |
| **Ordering** | SCC/dependency-sorted | Sequential |
| **REPL Support** | Incremental additions | Ephemeral |

### Why Top-Level is Special

1. **Forward References**
   ```idris
   even : Nat -> Bool  -- Can reference odd before it's defined
   even Z = True
   even (S n) = odd n
   
   odd : Nat -> Bool
   odd Z = False
   odd (S n) = even n
   ```

2. **REPL Workflow**
   ```idris
   > x = 5      -- Added to environment
   > y = x + 1  -- Can reference x
   ```

3. **Let-Generalization** (Hindley-Milner style)
   ```haskell
   id x = x           -- id :: forall a. a -> a (polymorphic)
   
   f = let id = \x -> x  -- Without generalization: id :: t -> t
       in (id 5, id True)  -- Would fail!
   ```

### How Each Language Handles It

**Lean 4:**
- Top-level: Commands add to environment
- Local: Part of term elaboration, no generalization
- REPL: Same command elaboration

**GHC:**
- Top-level: Dependency-sorted SCCs, generalization
- Local: Monomorphic (by default), can be recursive
- REPL: GHCi uses same pipeline

**Agda:**
- Top-level: Mutual blocks for mutual recursion
- Local: Monomorphic
- REPL: Limited REPL support

**Idris 2:**
- Top-level: Collect names → elaborate types → elaborate bodies
- Local: Monomorphic (no let-generalization by design)
- REPL: Incremental elaboration

## Recommendations for System F

Based on this analysis:

### 1. Adopt Idris 2's Explicit Multi-Pass Approach

**Why:**
- Cleanest separation of concerns
- Easier to test each phase
- Good error reporting at each stage

**Pipeline:**
```
Surface AST (names)
    ↓
Scope Checker → Scoped AST (de Bruijn indices)
    ↓
Type Elaborator → Core AST + Types
    ↓
Verifier → Verified Core
```

### 2. Separate Scoped AST

Create `ScopedTerm` as an explicit intermediate:

```python
# Surface: names, optional types, sugar
@dataclass
class SurfaceTerm:
    pass

# Scoped: de Bruijn indices, resolved names
@dataclass  
class ScopedTerm:
    pass

# Core: fully typed, minimal
@dataclass
class CoreTerm:
    pass
```

### 3. Elaborator Monad

Create an elaboration monad similar to Idris 2:

```python
@dataclass
class ElabState:
    metavariables: dict[MetaVarId, MetaVar]
    constraints: list[Constraint]
    context: Context
    source_map: dict[int, Location]  # For error messages

ElabM = State[ElabState, Result[T, ElabError]]
```

### 4. Top-Level Collection Strategy

Follow the Idris 2 approach for top-level:

```python
def elaborate_module(decls: list[SurfaceDeclaration]) -> Module:
    # Pass 1: Collect all names
    names = collect_names(decls)
    
    # Pass 2: Elaborate type signatures
    signatures = {name: elaborate_type_sig(decl) for name, decl in names.items()}
    
    # Pass 3: Elaborate bodies (with all signatures in scope)
    definitions = {name: elaborate_body(decl, signatures) for name, decl in decls.items()}
    
    return Module(signatures, definitions)
```

### 5. Type Generalization

**Decision:** Start without let-generalization (like Idris 2)

**Rationale:**
- Simpler to implement
- Dependent types make generalization more complex
- Can add later if needed

### 6. Kernel Separation

**Decision:** Eventually add a separate verification pass

**Current:** Elaborator produces Core directly  
**Future:** Kernel checks Core independently

**Why:**
- Trustworthiness
- Can prove soundness of kernel separately
- Matches Lean 4's approach

## Conclusion

The key insight from all four languages:

> **Elaboration is not a single pass but a pipeline of increasingly refined representations.**

- **Lean 4** emphasizes extensibility and IDE support
- **GHC** emphasizes optimization and industrial strength
- **Agda** emphasizes proof assistant features
- **Idris 2** emphasizes clean architecture and performance

For System F, **Idris 2's approach** is the best model because:
1. Clean separation enables understanding
2. Explicit intermediate representations help debugging
3. It scales well as we add features
4. It matches academic literature on elaboration
