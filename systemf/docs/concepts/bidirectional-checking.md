# Bidirectional Type Checking

**The two-mode type system that makes inference practical.**

---

## The Core Idea

Bidirectional type checking splits type checking into two modes (Pierce & Turner, 1998):

```
infer(term, ctx)  →  type        (synthesis - bottom-up)
check(term, type, ctx)           (verification - top-down)
```

**Key insight**: Sometimes you know the type and need to check a term. Sometimes you have a term and need to figure out its type. Using both directions gives you more power than either alone.

## The Two Modes

### 1. Inference Mode (⇒)

**Rule**: Given a term, synthesize its type.

```
Γ ⊢ e ⇒ τ

"In context Γ, term e has type τ"
```

**Works for**:
- Variables (look up in context)
- Literals (obvious types)
- Applications (if function type is known)
- Type annotations

**Example**:
```haskell
-- infer(42, ctx) = Int
-- infer("hello", ctx) = String
-- infer(x, ctx) = Int  (if x :: Int in ctx)
```

### 2. Checking Mode (⇐)

**Rule**: Given a term and expected type, verify they match.

```
Γ ⊢ e ⇐ τ

"To infer (e :: τ):
 - Check e against τ
 - Return τ"
```

**Works for**:
- Lambda abstractions (when expected type is an arrow)
- Type annotations
- Any term (by inferring and comparing)

**Example**:
```haskell
-- check(λ(x :: Int) -> x, Int -> Int)  ✓  (parameter must be Int, body returns Int)
-- check(42, String)                   ✗  (42 doesn't have type String)
```

## Visual Flow

```
Top-Down (Checking)          Bottom-Up (Inference)
                      
    τ flows down                 τ flows up
         ↓                           ↑
    ┌─────────┐                ┌─────────┐
    │  check  │                │  infer  │
    │   (⇐)   │                │   (⇒)   │
    └─────────┘                └─────────┘
         ↑                           ↓
    term provided               term analyzed
```

## Rules in Detail

### Variable (Inference Only)

```
(x : τ) ∈ Γ
─────────────
Γ ⊢ x ⇒ τ

"Look up the variable's type in the context"
```

### Lambda (Checking Mode)

```
Γ, x : σ ⊢ e ⇐ τ
──────────────────
Γ ⊢ (λx. e) ⇐ (σ → τ)

"To check λx.e against σ→τ:
 - Add x : σ to context
 - Check e against τ"
```

This is the **key rule** - checking mode handles lambdas beautifully because the expected type tells us what `x` should be.

### Application (Modes Switch)

```
Γ ⊢ f ⇒ (σ → τ)    Γ ⊢ a ⇐ σ
─────────────────────────────
Γ ⊢ (f a) ⇒ τ

"To infer the type of (f a):
 - Infer f's type (must be a function σ→τ)
 - Check a against σ (we know what type it should have!)
 - Result type is τ"
```

Notice: **inference for function, checking for argument**. This is where the magic happens!

### Type Annotation (Bridge)

```
Γ ⊢ e ⇐ τ
────────────────
Γ ⊢ (e : τ) ⇒ τ

"To infer (e : τ):
 - Check e against τ
 - Return τ"
```

Annotations let you **switch modes**: they provide the type needed for checking.

## Why Bidirectional?

### Without Bidirectional (Hindley-Milner Only)

```haskell
-- This works
id = λx -> x          -- Inferred: forall a. a -> a
id 3                  -- OK

-- This is hard
foo f = f 42          -- f : ??
                      -- Can't infer f's type without annotation
```

### With Bidirectional

```haskell
-- With annotation, checking works
foo :: (forall a. a -> a) -> Int
foo f = f 42          -- OK! Check f against (forall a. a -> a)

-- Type flows down
(λ(x :: Int) -> x + 1) :: Int -> Int
--                       ↑
--                       Expected type
```

**Benefits**:
1. **Decidable**: Always terminates (unlike full System F inference)
2. **Controllable**: Programmer guides inference via annotations
3. **Better errors**: Know what was expected vs what was found

## Limitations

Bidirectional checking alone **cannot handle**:

1. **Polymorphic function arguments**:
   ```haskell
   foo f = (f 3, f True)  -- f needs polymorphic type
                          -- Can't infer without annotation
   ```

2. **Higher-rank types**:
   ```haskell
   bar :: (forall a. a -> a) -> Int
   bar f = ...
   
   bar (λx -> x)          -- Need annotation on the lambda
   ```

## The Gap: Why Unification is Needed

Bidirectional checking works great when types flow in a consistent direction. But for polymorphism, you need to **solve constraints**.

```systemf
id :: ∀a. a → a
id 3
```

Here:
- `id` has type `∀a. a → a`
- `3` has type `Int`
- We need to **unify** `a` with `Int`

Pure bidirectional checking doesn't do unification. That's where the elaborator extends it.

## In System F

### Core Checker (Pure Bidirectional)

The Core checker (`core/checker.py`) is **pure** bidirectional:
- No meta-variables
- No unification
- All types must be explicit
- Type applications are implicit: `id 3`  -- type inferred automatically

### Surface Elaborator (Extended)

The Surface elaborator extends bidirectional with unification:
- Creates meta-variables for unknown types
- Unifies them with constraints
- Generates explicit Core code
- Type variables from `forall` signatures scope into the body, allowing:
  ```systemf
  id :: ∀a. a → a
  id = λ(x :: a) → x  -- 'a' refers to the 'a' in the signature
  ```

See [Implicit Instantiation](./implicit-instantiation.md) for how they combine.

## Summary

| Mode | Direction | Input | Output | Best For |
|------|-----------|-------|--------|----------|
| **infer** | Bottom-up | Term | Type | Variables, literals |
| **check** | Top-down | Term + Type | ✓/✗ | Lambdas, annotations |

**The key insight**: Bidirectional checking alone handles simple cases. For polymorphism, you need to add unification. System F uses both in an **interleaved** fashion.

## References

- **Pierce & Turner (1998)**: "Local Type Inference" - Original bidirectional paper
- **Dunfield & Krishnaswami (2013)**: "Complete and Easy Bidirectional Typechecking for Higher-Rank Polymorphism"
- **Pierce (2002)**: "Types and Programming Languages" - Chapter 16
