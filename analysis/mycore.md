# MyCore: A Minimal Core Calculus with ADTs

A simplified core language based on GHC Core (System FC), retaining only the essential features for algebraic data types (ADTs) with type variables and pattern matching.

## Overview

This system captures the essence of typed lambda calculus with:
- Parametric polymorphism (type variables)
- Algebraic data types (ADTs)
- Pattern matching via case expressions

All advanced features have been removed: coercions, kinds, type families, GADTs, join points, evidence, roles, and unboxed types.

---

## 1. Syntax

### 1.1 Types

```
τ, σ ::= α                 type variable
       | T ⟨τ₁ ... τₙ⟩    type constructor application (n ≥ 0)
       | τ₁ → τ₂          function type
       | ∀α. τ            polymorphic type
```

**Notation:**
- `α, β, γ` range over type variables
- `T, U` range over type constructors
- `⟨τ₁ ... τₙ⟩` denotes a (possibly empty) list of type arguments

### 1.2 Expressions

```
e, u ::= x                 variable
       | lit               literal
       | e₁ e₂             application
       | λx:τ. e           lambda abstraction
       | let x:τ = u in e  non-recursive let-binding
       | let rec bindings in e  recursive let-binding
       | case e as x:τ of alts   pattern match
       | Λα. e             type abstraction (big lambda)
       | e τ               type application

bindings ::= x₁:τ₁ = e₁; ... ; xₙ:τₙ = eₙ

alts ::= alt₁ | ... | altₙ

alt ::= K ⟨x₁ ... xₙ⟩ → e    constructor pattern
      | lit → e              literal pattern
      | _ → e                default/wildcard
```

**Notation:**
- `x, y, z` range over term variables
- `K` ranges over data constructors
- `lit` ranges over literals (integers, characters, etc.)

### 1.3 Type Declarations

Type constructors are declared separately:

```
data T α₁ ... αₙ = K₁ τ₁₁ ... τ₁ₘ₁ | ... | Kₖ τₖ₁ ... τₖₘₖ
```

Each data constructor `Kᵢ` has type:
```
Kᵢ : ∀α₁...αₙ. τᵢ₁ → ... → τᵢₘᵢ → T α₁ ... αₙ
```

---

## 2. Typing Rules

### 2.1 Contexts

A typing context `Γ` tracks both term and type variable bindings:

```
Γ ::= ∅ | Γ, x:τ | Γ, α
```

### 2.2 Type Formation

Before checking expressions, we must verify types are well-formed:

```
α ∈ Γ
───────────── (Ty-Var)
Γ ⊢ α ok

Γ ⊢ τ₁ ok    Γ ⊢ τ₂ ok
────────────────────── (Ty-Fun)
Γ ⊢ τ₁ → τ₂ ok

Γ ⊢ τᵢ ok  (for all i)    arity(T) = n
────────────────────────────────────── (Ty-Con)
Γ ⊢ T ⟨τ₁ ... τₙ⟩ ok

Γ, α ⊢ τ ok
──────────── (Ty-Forall)
Γ ⊢ ∀α. τ ok
```

### 2.3 Expression Typing

```
x:τ ∈ Γ
───────── (Var)
Γ ⊢ x : τ

lit has type base(lit) in literal table
─────────────────────────────────────── (Lit)
Γ ⊢ lit : base(lit)

Γ ⊢ e₁ : τ₁ → τ₂    Γ ⊢ e₂ : τ₁
──────────────────────────────── (App)
Γ ⊢ e₁ e₂ : τ₂

Γ, x:τ₁ ⊢ e : τ₂
────────────────── (Lam)
Γ ⊢ λx:τ₁. e : τ₁ → τ₂

Γ ⊢ u : τ₁    Γ, x:τ₁ ⊢ e : τ₂
──────────────────────────────── (Let)
Γ ⊢ let x:τ₁ = u in e : τ₂

Γ, x₁:τ₁ ... xₙ:τₙ ⊢ eᵢ : τᵢ  (for all i)
Γ, x₁:τ₁ ... xₙ:τₙ ⊢ e : τ
──────────────────────────────────────────────────── (LetRec)
Γ ⊢ let rec (xᵢ:τᵢ = eᵢ) in e : τ

Γ ⊢ e : T ⟨σ₁...σₙ⟩    Γ, x:T ⟨σ₁...σₙ⟩ ⊢alt altᵢ : τ  (for all i)
────────────────────────────────────────────────────────────────── (Case)
Γ ⊢ case e as x:T ⟨σ₁...σₙ⟩ of (altᵢ) : τ

Γ, α ⊢ e : τ
────────────────── (TyLam)
Γ ⊢ Λα. e : ∀α. τ

Γ ⊢ e : ∀α. τ₁    Γ ⊢ τ₂ ok
──────────────────────────── (TyApp)
Γ ⊢ e τ₂ : τ₁[α ↦ τ₂]
```

### 2.4 Alternative Typing

The judgment `Γ; σ ⊢alt alt : τ` checks that an alternative matches values of type `σ` and produces result type `τ`:

```
K : ∀α₁...αₙ. τ₁' → ... → τₘ' → T α₁...αₙ ∈ data constructors
σ = T ⟨σ₁...σₙ⟩
Γ, x₁:τ₁'[αᵢ↦σᵢ]...xₘ:τₘ'[αᵢ↦σᵢ] ⊢ e : τ
─────────────────────────────────────────────────────────────────── (DataAlt)
Γ; T ⟨σ₁...σₙ⟩ ⊢alt K ⟨x₁...xₘ⟩ → e : τ

lit has type σ    Γ ⊢ e : τ
────────────────────────────────── (LitAlt)
Γ; σ ⊢alt lit → e : τ

Γ ⊢ e : τ
──────────────── (Default)
Γ; σ ⊢alt _ → e : τ
```

---

## 3. Example: List Type

### Type Declaration

```
data List α = Nil | Cons α (List α)
```

This declares:
- Type constructor `List` with arity 1
- Data constructor `Nil : ∀α. List α`
- Data constructor `Cons : ∀α. α → List α → List α`

### Example Functions

**Length:**
```
length : ∀α. List α → Int
length = Λα. λxs:List α.
  case xs as y:List α of
    Nil → 0
    Cons (h:α) (t:List α) → 1 + (length α t)
```

**Type derivation sketch for length:**

```
α, y:List α, h:α, t:List α ⊢ 1 + (length α t) : Int
────────────────────────────────────────────────────── (by arithmetic rules)
α, y:List α; List α ⊢alt Cons h t → 1 + (length α t) : Int

α, y:List α ⊢ 0 : Int
──────────────────────
α, y:List α; List α ⊢alt Nil → 0 : Int

α ⊢ Nil : ∀α. List α    α ⊢ Cons : ∀α. α → List α → List α
────────────────────────────────────────────────────────────
α, y:List α ⊢alt [alternatives] : Int
──────────────────────────────────────────────────────────── (Case)
α, y:List α ⊢ case y of ... : Int
──────────────────────────────────────────────────────────── (Lam)
α ⊢ λy:List α. case y of ... : List α → Int
──────────────────────────────────────────────────────────── (TyLam)
⊢ Λα. λy:List α. case y of ... : ∀α. List α → Int
```

**Map:**
```
map : ∀α. ∀β. (α → β) → List α → List β
map = Λα. Λβ. λf:(α → β). λxs:List α.
  case xs as y:List α of
    Nil → Nil β
    Cons (h:α) (t:List α) → Cons β (f h) (map α β f t)
```

---

## 4. Relationship to Full GHC Core

### Removed Features

| Feature | Reason for Removal |
|---------|-------------------|
| Coercions (g) | System FC equality proofs—unnecessary for basic ADTs |
| Casts (e \|> g) | Requires coercion system |
| Kinds (κ) | Simplified to `*` (lifted types only) |
| Join points | Optimization feature, not semantically essential |
| Roles (Nom/Rep/Ph) | Coercion system feature |
| Type families | Complex extension, not basic ADTs |
| GADTs | Requires coercion constraints and evidence |
| Newtypes | Requires coercion system |
| Evidence | Dictionary passing for type classes |
| Type-level literals | Type-level computation feature |
| Unboxed types | Primitive types with different semantics |

### Why `case e as x:τ`?

In the minimal system, the `as x:τ` clause binds the scrutinee to name `x`. In full GHC Core, this is essential for:

1. **GADTs:** The type of the result may depend on the scrutinee's type
2. **Scoped type variables:** Type variables can be referenced within the case body
3. **Evidence passing:** Dictionary evidence for type classes

In our minimal system without GADTs, this could theoretically be omitted, but we keep it for:
- Uniformity with the full system
- Potential extension to GADTs
- Explicit binding of the scrutinee for clarity

### Why No `return τ`?

Unlike full GHC Core, our minimal system **omits** the explicit return type annotation because:

1. Without GADTs, all branches return the same type `τ`
2. The type can be inferred from context
3. Simpler syntax for teaching/understanding

In full GHC Core, `return τ` is mandatory for:
- GADT pattern matching where different branches return different types
- Syntax-directed type checking without unification
- Explicitness in the compiler IR

---

## 5. Metatheory (Sketch)

### Type Safety

**Theorem (Preservation):** If `Γ ⊢ e : τ` and `e → e'`, then `Γ ⊢ e' : τ`.

**Theorem (Progress):** If `⊢ e : τ` and `e` is not a value, then there exists `e'` such that `e → e'`.

**Values:**
```
v ::= λx:τ. e       lambda abstraction
    | Λα. e         type abstraction
    | K ⟨τ₁...τₙ⟩ v₁ ... vₘ  fully applied constructor
    | lit           literal
```

### Operational Semantics (Big-Step)

```
e ⇓ v
──────────────────────────── (Case-Constr)
case (K v₁...vₙ) as x:τ of (... | K x₁...xₙ → e | ...) ⇓ e[x₁↦v₁]...[xₙ↦vₙ][x↦K v₁...vₙ]

e ⇓ lit    e' ⇓ v
──────────────────────────── (Case-Lit)
case lit as x:τ of (... | lit → e' | ...) ⇓ v

e ⇓ v'    v' doesn't match previous patterns    e'' ⇓ v
────────────────────────────────────────────────────────────────── (Case-Default)
case v' as x:τ of (... | _ → e'') ⇓ v
```

---

## 6. Implementation Notes

### Type Constructor Representation

Each type constructor `T` has:
- **Arity:** Number of type parameters `n`
- **Data constructors:** List of constructor types
- **Kinding:** Implicitly `T : * → ... → *` (n times)

### Data Constructor Representation

Each data constructor `K` for type `T α₁...αₙ` has a **representation type**:
```
K : ∀α₁...αₙ. τ₁ → ... → τₘ → T α₁...αₙ
```

When pattern matching, we instantiate type variables `αᵢ` with the actual type arguments `σᵢ` from the scrutinee type `T ⟨σ₁...σₙ⟩`.

### Pattern Matching Semantics

Pattern matching proceeds top-to-bottom through alternatives:
1. **Constructor pattern:** Matches if the scrutinee is that constructor; binds pattern variables
2. **Literal pattern:** Matches if the scrutinee equals that literal
3. **Default:** Matches anything, no binding

Patterns are **exhaustive** if they cover all possible constructors of the type.

---

## 7. Example: Type-Polymorphic Input with Monomorphic Output

A good test case showing how type parameters flow through pattern matching when the output type differs from the input type.

### Surface Haskell

```haskell
go = \xs ->
  case xs of
    Nil       -> Nil
    Cons a as -> Cons 1 (go as)
```

**Type:** `go : List Int -> List Int`

This function replaces every element with `1`, converting any list to a list of `Int`s with the same length (essentially `map (const 1)`).

### Core Language Translation

```haskell
go : ∀α. List α -> List Int
go = Λα. \xs:List α ->
  case xs as y:List α of
    Nil -> Nil @Int
    Cons (a:α) (as:List α) -> Cons @Int 1 (go @α as)
```

### Type Checking

| Expression | Type | Notes |
|------------|------|-------|
| `go` | `∀α. List α -> List Int` | Polymorphic function type |
| `go @α` | `List α -> List Int` | Type application |
| `xs` | `List α` | Bound by lambda |
| `as` | `List α` | Pattern-bound from `Cons` |
| `go @α as` | `List Int` | Recursive call |
| `Cons @Int 1 (...)` | `List Int` | Returns `List Int` |
| `Nil @Int` | `List Int` | Polymorphic `Nil` instantiated to `Int` |

**Key insight:** The function is polymorphic in its *input* (accepts any `List α`) but monomorphic in its *output* (always produces `List Int`). The type parameter `α` flows through the pattern match but does not appear in the result type.

---

## References

- GHC Core Specification: `upstream/ghc/docs/core-spec/`
- System FC papers: Various publications by SPJ et al.
- Original motivation: Simplified core calculus for teaching and prototyping
