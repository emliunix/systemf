# System FC Elaborator Design (elab2)

**Status**: Design Phase  
**Goal**: System FC-style elaborator with impredicative polymorphism, coercion axioms, and ADTs  
**Priority**: Expressiveness with practical inference

---

## Context

### Type Theory Background

We are implementing a **System FC-style** elaboration system with:
- **Impredicative Polymorphism**: First-class polymorphic types
- **Coercion Axioms**: Type equality witnesses for newtypes and mutual recursion
- **Algebraic Data Types (ADTs)**: Sum and product types via `data` declarations  
- **Type Inference**: HM-style inference where possible, annotations where needed

System FC (used in GHC) provides the theoretical foundation: explicit type abstractions/applications, coercions for type equality, and nominal type distinctions. Our elaborator bridges user-friendly surface syntax to this explicit core.

### Design Philosophy

**Reference-Based Implementation**: We choose System FC not because it's simple, but because it's *documented*. GHC's implementation provides battle-tested algorithms and extensive literature (papers, theses, blog posts) we can reference when stuck. Rolling our own type system would be simpler initially but risk subtle bugs with no external reference.

**Practical Expressiveness**: Support advanced type system features (higher-rank types, first-class polymorphism) that appear in real-world functional programming, with reasonable inference.

**Clear Core Semantics**: Core language is fully explicit (no inference needed), making evaluation and optimization straightforward.

**User-Friendly Surface**: Surface syntax can use type inference and leave details implicit, elaborated to explicit Core.

### The Complexity Tradeoff

| Approach | Complexity | Reference Material | Risk |
|----------|-----------|-------------------|------|
| **Pure HM** | Low | Standard, well-understood | Low - but limited expressiveness |
| **Custom ADT + Recursion** | Medium | Fragmented literature | Medium - edge cases in mutual recursion |
| **System FC (chosen)** | High | Extensive (GHC papers, FC papers, SPJ's blog) | Medium - complex but well-documented |

**Why System FC despite complexity:**
1. **Papers exist**: SPJ's "System F with Type Equality Coercions" (2007), "OutsideIn(X)" (2011), etc.
2. **Real implementation**: GHC is open source, we can inspect actual code
3. **Community knowledge**: Haskell communities understand these concepts deeply
4. **Extensibility**: Once coercion system works, adding features (GADTs, type families) is incremental

**The risk of simpler approaches:**
- Mutual recursion handling is subtle - easy to get wrong without reference
- Type equality for optimization is hard to retrofit later
- When stuck on a bug, no external resources to consult

---

## Decisions

### 1. Type System

| Aspect | Decision | Rationale | Error to Avoid |
|--------|----------|-----------|----------------|
| **Base System** | **System FC** | GHC-style core with explicit types and coercions. Complex but well-documented in papers | **DON'T** roll our own - use proven design even if complex |
| **Polymorphism** | **Impredicative** | Support `(∀a.a→a) → Int`, higher-rank types | **DON'T** limit to predicative only - DSLs need first-class polymorphism |
| **Recursion** | **Coercion Axioms** | Use nominal types with coercions for mutual recursion, not structural μ | **DON'T** use explicit fold/unfold - coercions are zero-cost and cleaner |
| **User Syntax** | **Implicit where possible** | Type applications inferred, coercions implicit in surface | **DON'T** require full System F annotations everywhere |
| **Inference** | **Partial + Bidirectional** | Infer where possible, check against annotations | **DON'T** expect complete inference - impredicativity requires hints |

### 2. Architecture

| Aspect | Decision | Rationale | Error to Avoid |
|--------|----------|-----------|----------------|
| **Elaborator Strategy** | **Refine existing** | Build on current bidirectional elaborator, add coercion support | **DON'T** start from scratch - existing infrastructure is solid |
| **Core AST** | **Add coercions** | `Coercion` type, `Coerce` term constructor, `Axiom` declarations | **DON'T** skip coercions - they're essential for impredicativity and optimization |
| **Type Equality** | **Coercion-based** | Types equal only if coercible, nominal for ADTs | **DON'T** use pure structural equality - loses optimization opportunities |
| **Pipeline** | **Multi-pass** | Collect types → SCC analysis → Generate axioms → Elaborate terms | **DON'T** mix phases - order matters (axioms before elaboration) |

### 3. Coercion Axioms for Mutual Recursion

| Aspect | Decision | Rationale | Error to Avoid |
|--------|----------|-----------|----------------|
| **Representation** | **Tagged sum in single μ** | Mutually recursive types share one underlying μ-type with constructor tags | **DON'T** create separate μ types - they can't reference each other |
| **Coercions** | **Axioms witness isomorphism** | `ax_A : A ~ μR.C_A(...)`, `ax_B : B ~ μR.C_B(...)` | **DON'T** make users write coercions - elaborator inserts them |
| **Pattern Matching** | **Coerce then deconstruct** | `case e of C x → ...` becomes `case coerce⁻¹(e) of injᵢ(y) → let x = coerce(y) in ...` | **DON'T** expose internal representation to users |

### 4. ADT & Pattern Matching

| Aspect | Decision | Rationale | Error to Avoid |
|--------|----------|-----------|----------------|
| **Constructor Application** | **Fully applied** | Saturated constructors, currying desugared | **DON'T** allow partial application in elaboration - desugar to λ first |
| **Pattern Support** | **Nested patterns** | `case xs of Cons (Pair a b) Nil → ...`, practical for DSLs | **DON'T** reject nested patterns - desugar to nested case expressions |
| **Exhaustiveness** | **Check coverage** | Ensure pattern matching is complete | **DON'T** skip exhaustiveness checking - source of runtime errors |
| **Partial Application** | **Desugar to λ** | `map Succ nums` becomes `map (λx. Succ x) nums` | **DON'T** complicate elaborator with partial applications - desugar early |

---

## Formal Algorithm Specification

See [Bidirectional Type Inference Algorithm](./bidirectional-algorithm.md) for the complete formal specification including:

- **Core typing rules** (from Jones et al. 2007, extended for System FC)
- **ADT and pattern matching rules**
- **Constructor application and case analysis**
- **Coercion axiom generation for mutual recursion**

The algorithm uses bidirectional type checking with:
- **Checking mode** ($Γ ⊢_↓ e : σ$): verify term has expected type
- **Synthesis mode** ($Γ ⊢_↑ e : ρ$): infer type from term
- **Coercion insertion**: Elaborator generates coercions where needed

---

## Critical Design Decisions

### Decision 1: From HM to System FC

**OLD (HM-only)**:
- Predicative polymorphism only
- No explicit type abstractions
- Limited expressiveness

**NEW (System FC)**:
- Impredicative polymorphism
- Explicit Λ/∀ in Core, implicit in surface
- Higher-rank types: `(∀a.a→a) → Int`

**Why the change**: HM is too limiting for expressive DSLs. First-class polymorphism (passing polymorphic functions as arguments) is essential for many functional programming patterns.

### Decision 2: Coercion Axioms Instead of Explicit Fold/Unfold

**OLD (Iso-recursive with fold/unfold)**:
- `fold`/`unfold` as explicit Core term constructors
- Simple theory but verbose Core AST
- Runtime overhead (though optimizable)

**NEW (Coercion axioms)**:
- Coercions witness type equality: `ax : A ~ Repr(A)`
- Zero-cost at runtime (erasable)
- Cleaner Core AST
- Supports both ADTs and newtypes uniformly

**Example elaboration**:

User writes:
```systemf
data Nat = Zero | Succ Nat

let one = Succ Zero
```

Core becomes:
```
ax_Nat : Nat ~ μR. Unit + Nat  -- coercion axiom

one : Nat = coerce(ax_Nat)(fold(inj₂(coerce(sym(ax_Nat))(Zero))))
```

Pattern matching:
```systemf
case n of
  Succ m → m
```

Becomes:
```
case unfold(coerce(sym(ax_Nat))(n)) of
  inj₂(m') → let m = coerce(ax_Nat)(m') in m
```

### Decision 3: Pipeline Order

**CORRECT**:
```
Source Code
    ↓
[Parse]
    ↓
Surface AST
    ↓
[Desugar]
    ↓
Desugared Surface AST
    ↓
[Separate Declarations]
    ↓
Type Decls + Term Decls
    ↓
[SCC Analysis]
    ↓
Recursion Groups
    ↓
[Generate Coercion Axioms]
    ↓
Type Signatures + Axioms
    ↓
[Scope Check]
    ↓
Scoped AST
    ↓
[Type Elaboration]
    ↓
Typed AST with constraints
    ↓
[Constraint Solving]
    ↓
Substitution + Resolved Types
    ↓
[Apply Substitution]
    ↓
Fully Typed AST
    ↓
[Finalize Core AST]
    ↓
Core AST (with coercions)
```

**Key difference**: Generate coercion axioms early (after SCC analysis), before elaboration. Elaborator uses these axioms when processing constructors and pattern matches.

---

## Elaboration Pipeline

### Phase 1: Parse
**Input**: Source code (text)  
**Output**: Surface AST  
**Guarantees**: Syntax is valid

### Phase 2: Desugar
**Input**: Surface AST  
**Output**: Desugared Surface AST  
**Actions**:
- Expand operators (`+`, `-`, etc.) to primitive applications
- Expand nested patterns to nested case expressions
- Desugar if-then-else to case
- Expand multi-param lambdas to nested single-param

### Phase 3: Separate Declarations
**Input**: Desugared declarations  
**Output**: `(type_decls, term_decls)`  
**Purpose**: Route type and term declarations down different paths

### Phase 4: SCC Analysis
**Input**: Type declarations  
**Output**: List of SCCs (strongly connected components)  
**Algorithm**: Tarjan's algorithm  
**Purpose**: Detect mutually recursive type groups

Example:
```
data Expr = Num Int | Add Expr Expr
data Stmt = ExprStmt Expr | Seq Stmt Stmt
```
Dependency graph: `Expr → Stmt → Expr` (cycle)  
SCCs: `[{Expr, Stmt}]` (one SCC containing both)

### Phase 5: Generate Coercion Axioms
**Input**: Type declarations + SCCs  
**Output**: Type signatures + coercion axioms  
**Actions**:
- For each SCC, build single μ-type representation
- Generate constructor tags for each type in the group
- Create coercion axioms: `ax_T : T ~ μR.C_T(...)`

**Example**:

Input:
```systemf
data Nat = Zero | Succ Nat
```

Output:
```
Nat : Type
ax_Nat : Nat ~ μR. Unit + Nat

Zero : Nat = coerce(ax_Nat)(fold(inj₁(())))
Succ : Nat → Nat = λn. coerce(ax_Nat)(fold(inj₂(coerce(sym(ax_Nat))(n))))
```

### Phase 6: Scope Check
**Input**: Term declarations + type signatures  
**Output**: Scoped AST  
**Actions**:
- Resolve variable names to de Bruijn indices
- Resolve constructor names using type signatures
- Build ScopeContext with all globals (for mutual recursion)

### Phase 7: Type Elaboration
**Input**: Scoped AST + type signatures  
**Output**: Typed AST + constraints  
**Actions**:
- Walk AST, assign types or fresh meta-variables
- Insert coercions at constructor applications
- Insert coercions at pattern matches
- Generate equality constraints
- Handle let-generalization

### Phase 8: Constraint Solving
**Input**: Constraints  
**Output**: Substitution  
**Algorithm**: Unification with coercion-aware equality

### Phase 9: Apply Substitution
**Input**: Typed AST + substitution  
**Output**: Fully resolved typed AST

### Phase 10: Generalization
**Input**: Resolved typed AST  
**Output**: Polymorphic types at let-bindings

### Phase 11: Finalize Core AST
**Input**: Fully elaborated terms  
**Output**: Core AST  
**Actions**:
- Ensure all coercions are well-formed
- Verify coercion axioms are used correctly
- Attach source locations

---

## Module Structure

```
src/systemf/surface/elaborator/
├── __init__.py              # Public API
├── pipeline.py              # Phase orchestration
├── scc.py                   # SCC analysis
├── coercion_axioms.py       # Generate axioms for mutual recursion
├── elaborator.py            # Type elaboration (constraint gen)
├── constraint_solver.py     # Unification with coercions
├── context.py               # Type context with coercion support
├── types.py                 # Surface types + coercion types
└── errors.py                # Error hierarchy
```

---

## Key Design Principles

1. **Explicit Core**: Core language is fully explicit - no inference, all coercions explicit
2. **Zero-Cost Coercions**: Coercion axioms are erasable, no runtime overhead
3. **Impredicativity**: Support first-class polymorphism where practically inferable
4. **Nominal Types**: ADTs are nominal (distinct even if structurally equal), coercions witness representation
5. **Testability**: Each phase independently testable
6. **Error Quality**: Clear error messages at each phase

---

## Comparison: Old vs New

| Aspect | Old (HM + μ) | New (System FC + Coercions) |
|--------|--------------|---------------------------|
| **Polymorphism** | Predicative only | Impredicative |
| **First-class ∀** | No | Yes |
| **Recursion** | Explicit fold/unfold | Coercion axioms |
| **Core overhead** | fold/unfold terms | Zero (coercions erased) |
| **Inference** | Complete | Partial (needs hints) |
| **Complexity** | Simpler | Higher but manageable |

---

## Notation Style Guide

### LaTeX Conventions

| Concept | Notation | Example |
|---------|----------|---------|
| **Type variables** | $α$, $β$, $γ$ | $∀α. τ$ |
| **Term variables** | $x$, $y$, $z$ | $λx. e$ |
| **Type constructors** | $\mathsf{Name}$ | $\mathsf{List}$, $\mathsf{Maybe}$ |
| **Data constructors** | $\mathsf{Name}$ | $\mathsf{Cons}$, $\mathsf{Nil}$ |
| **Coercions** | $γ$, $δ$ | $γ : τ₁ ~ τ₂$ |
| **Coercion axioms** | $\mathsf{ax}_T$ | $\mathsf{ax}_\mathsf{Nat} : \mathsf{Nat} ~ μR.\ldots$ |
| **Meta-variables** | $τ$, $σ$, $ρ$ for types; $e$ for terms | $Γ ⊢ e : τ$ |
| **Sequences** | $\overline{x}$ | $\overline{α}$, $\overline{e}$ |
| **Judgments** | $Γ ⊢ e : τ$ | typing judgment |
| **Substitution** | $τ[σ/α]$ | substitute $σ$ for $α$ in $τ$ |
| **Products** | $τ₁ × τ₂$ | $\mathsf{Int} × \mathsf{Bool}$ |
| **Sums** | $τ₁ + τ₂$ | $\mathsf{Unit} + \mathsf{Nat}$ |
| **Function types** | $τ₁ → τ₂$ | $α → α$ |
| **Forall** | $∀α. τ$ | $∀α. α → α$ |
| **Mu types** | $μX. τ$ | $μN. \mathsf{Unit} + N$ |

---

## Implementation Style

**Simple recursive pattern matching.** Each pass is a single function with a big `match` statement:

```python
def elaborate_term(term: SurfaceTerm, ctx: Context) -> CoreTerm:
    match term:
        case Var(name):
            return core.Var(name)
        case App(e1, e2):
            c1 = elaborate_term(e1, ctx)
            c2 = elaborate_term(e2, ctx)
            return core.App(c1, c2)
        case Let(x, e1, e2):
            c1 = elaborate_term(e1, ctx)
            c2 = elaborate_term(e2, ctx.extend(x, c1.type))
            return core.Let(x, c1, c2)
        # ... one case per constructor
```

**Why this style:**
- **Clear**: Each pass does one thing, easy to understand
- **Composable**: Passes chain together naturally
- **Debuggable**: Can print intermediate ASTs easily
- **Maintainable**: No fancy traversal combinators to learn

**Tradeoff:** Multiple traversals (O(k*n) where k=6-10). Acceptable for DSL-sized inputs.

---

## AST Extension for Coercions

### Required Extensions

**Core AST needs:**
1. **`Coercion` type** - witnesses τ ~ σ
2. **`Cast` term** - `e |> γ` (term e with coercion γ applied)
3. **`Axiom` declarations** - named coercion axioms like `ax_Nat : Nat ~ Repr(Nat)`
4. **`CoVar`** - coercion variables (for polymorphic coercions)

### Coercions vs μ Types

**Why coercions, not explicit fold/unfold?**

| Aspect | μ Types (fold/unfold) | Coercions |
|--------|----------------------|-----------|
| **Runtime overhead** | Explicit operations | **Zero-cost** (erased) |
| **Core AST** | Verbose (`fold`/`unfold` everywhere) | Clean (`e |> γ`) |
| **Optimization** | Hard to optimize away | Trivial (erase γ) |
| **Mutual recursion** | Complex (needs tupling or context) | **Natural** (axioms bridge nominal types) |
| **Elegance** | Operational | **Declarative** (witnesses equality) |

**Key insight:** Coercion passing is the industry standard (GHC, OCaml) because it separates **representation** from **nominal type** elegantly. The coercion `γ : T ~ Repr(T)` is proof that values of T and values of its representation are interchangeable.

**Example:**
```
-- User writes:
let x : Nat = Succ Zero

-- With μ types (verbose):
let x = fold(RepSucc(fold(RepZero)))

-- With coercions (elegant):
let x = RepSucc(RepZero) |> ax_Nat
```

Where `RepZero` and `RepSucc` are the representation constructors. The coercion `ax_Nat` witnesses that the representation type equals the nominal type `Nat`.

---

## Implementation Strategy

Given the complexity, we implement in phases:

### Phase 1: Core Infrastructure (Week 1-2)
- Add `Coercion` type to Core AST
- Add `Coerce` term constructor
- Add `Axiom` declarations
- Basic coercion equality checking

### Phase 2: Simple ADTs (Week 3-4)
- Non-recursive data types only
- Single SCC (no mutual recursion yet)
- Generate simple coercion axioms
- Constructor elaboration with coercions

### Phase 3: Mutual Recursion (Week 5-6)
- SCC analysis for type declarations
- Tagged sum representation
- Coercion axioms for mutual types
- Pattern matching with coercions

### Phase 4: Impredicativity (Week 7-8)
- Higher-rank type inference
- Partial inference with annotations
- Subsumption checking
- Integration with existing bidirectional elaborator

### Phase 5: Polish (Week 9-10)
- Error messages
- Exhaustiveness checking
- Optimization (coercion erasure)
- Testing

**Fallback Plan**: If Phase 3 (mutual recursion) proves too complex, fall back to:
- Explicit fold/unfold (original design)
- Simpler elaborator
- Less optimal but working implementation

---

## Open Questions

1. **Type Classes**: Would type classes improve DSL ergonomics?
2. **Coinductive Types**: Should we support codata/infinite types?
3. **Effects**: How to handle effects (IO, state) in the DSL?
4. **Erasure Strategy**: When exactly do we erase coercions? Before optimization or code generation?

---

**Last Updated**: 2026-03-07  
**Status**: Design updated with complexity acknowledged, ready for phased implementation
