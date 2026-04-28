# Higher-Rank Polymorphism with Bidirectional Type Inference

## Overview

This document analyzes how GHC handles **higher-rank polymorphism** using bidirectional type inference, focusing on:
- Type annotations (`(e :: type)`)
- Lambda annotations (`\(x :: Int) -> e`)
- Deep subsumption for function arguments
- **Excludes**: type classes, instances, evidence, dictionaries

## Key Insight: Skolemisation

The core mechanism for higher-rank polymorphism is **skolemisation** - converting `forall`-bound type variables to rigid **skolem constants** during type checking.

```haskell
-- Checking (\x -> x) :: forall a. a -> a
-- 1. Skolemise: forall a. a -> a  becomes  a_sk -> a_sk
-- 2. Check lambda: \x -> x against a_sk -> a_sk  
-- 3. x gets type a_sk, body must return a_sk
```

## The Bidirectional Type Checking Rules

### Rule 1: Type Annotation (e :: σ)

**Location**: `GHC/Tc/Gen/Expr.hs.tcPolyLExprSig` (line 137)

```haskell
tcPolyLExprSig :: LHsExpr GhcRn -> TcCompleteSig -> TcM (LHsExpr GhcTc)
tcPolyLExprSig (L loc expr) sig
  = setSrcSpanA loc $
    do { expr' <- tcPolyExprCheck expr (Right sig)
       ; return (L loc expr') }
```

**Rule**: Push the signature type into the expression (checking mode).

**Example**:
```haskell
(id :: forall a. a -> a) @Int
-- 1. Signature: forall a. a -> a
-- 2. Check id against this type
-- 3. Then apply @Int (visible type application)
```

### Rule 2: Lambda Against Polymorphic Type

**Location**: `GHC/Tc/Gen/Expr.hs.tcPolyExprCheck` (lines 179-184)

```haskell
tc_body e@(HsLam x lam_variant matches)
  = do { (wrap, matches') <- tcLambdaMatches e lam_variant matches pat_tys
                                                  (mkCheckExpType rho_ty)
       ; return (mkHsWrap wrap $ HsLam x lam_variant matches') }
```

**Rule**: When checking `\x -> e` against `forall a. ρ`:
1. Skolemise `a` to `a_sk`
2. Check lambda against `a_sk -> ρ[a_sk/a]`
3. Bind `x` with type from argument position

### Rule 3: Application with Polymorphic Argument

**Location**: `GHC/Tc/Gen/App.hs.tcApp` (line 218)

```haskell
-- f :: (forall a. a -> a) -> Int
-- f (\x -> x)

-- Pushes (forall a. a -> a) into the argument
```

**Rule**: When checking `f e` where `f` expects `σ`:
- Push expected type `σ` into argument `e`
- Use `tcCheckPolyExpr` for polymorphic argument types

## Deep Subsumption (Optional Extension)

### What is Deep Subsumption?

**Location**: Note [Deep subsumption] (`GHC/Tc/Utils/Unify.hs:1727`)

Deep subsumption allows **nested `forall` types** in function argument positions to be compared structurally.

**See**: `TYPE_INFERENCE.md` Part 6.4 for Deep Skolemisation.

```haskell
-- Without deep subsumption:
--   (forall a. Int -> a -> a)  <=  (Int -> forall b. b -> b)
--   Fails! Different forall placement

-- With deep subsumption:
--   Same comparison succeeds
--   Deeply skolemise both sides first
```

### How It Works

**Location**: `tc_sub_type_deep` in `GHC/Tc/Utils/Unify.hs`

```haskell
-- Deep subsumption order matters!
--   (forall a. Int -> a -> a)  <=  (Int -> forall b. b -> b)
-- 
-- Step 1: Deep skolemise RHS: Int -> b_sk -> b_sk
-- Step 2: Instantiate LHS: Int -> a_sk -> a_sk  
-- Step 3: Check: a_sk ~ b_sk ✓
```

**Key functions**:
- `tcSkolemise Deep` - skolemise nested foralls
- `tc_sub_type_deep` - deep subsumption checking
- `getDeepSubsumptionFlag` - check if extension enabled

### Deep Subsumption is Structural

**Important**: Unlike type classes, deep subsumption does **not** require runtime evidence. It's purely a **type checking transformation**.

```haskell
-- Type class: needs dictionary at runtime
foo :: Num a => a -> a
foo x = x + 1  -- Needs Num dictionary

-- Higher-rank: purely compile-time type manipulation  
bar :: (forall a. a -> a) -> Int
bar f = f 0    -- No runtime evidence needed!
```

## Lambda with Type Patterns

### Type-Annotated Lambda Binders

**Location**: `GHC/Tc/Gen/Match.hs.tcMatchPats` (called from `tcLambdaMatches`)

```haskell
f :: forall a b. a -> b -> (a, b)
f @p x @q y = (x, y)

-- Type checking:
-- 1. Skolemise forall a b: get a_sk, b_sk
-- 2. Match @p with a_sk
-- 3. Match x with a_sk  
-- 4. Match @q with b_sk
-- 5. Match y with b_sk
```

**Key insight**: From `Note [Skolemisation overview]` (`GHC/Tc/Utils/Unify.hs:287-312`):
> "We must line up `p`, `q` with the skolemised `a` and `b`"

The skolemised type variables must align with explicit type binders in the lambda.

## Skolemisation Functions

### Core API

| Function | Location | Purpose |
|----------|----------|---------|
| `tcSkolemiseCompleteSig` | `GHC/Tc/Utils/Unify.hs:470` | Skolemise complete signature |
| `tcSkolemiseExpectedType` | `GHC/Tc/Utils/Unify.hs:480` | Skolemise pushed-in type |
| `tcSkolemiseGeneral` | `GHC/Tc/Utils/Unify.hs` | General skolemisation with depth flag |
| `tcDeeplySkolemise` | `GHC/Tc/Utils/Unify.hs` | Deep skolemisation (for signatures) |

### Skolemisation Flags

```haskell
data SkolemisationFlag = Shallow | Deep

-- Shallow: only top-level forall
-- Deep: nested foralls in function arguments too
```

## Source Code Map

### Type Checking Entry Points

| Function | File | Line | Purpose |
|----------|------|------|---------|
| `tcCheckPolyExpr` | `GHC/Tc/Gen/Expr.hs` | 112 | Check expr against sigma type |
| `tcCheckPolyExprNC` | `GHC/Tc/Gen/Expr.hs` | 113 | Same, no context |
| `tcPolyLExpr` | `GHC/Tc/Gen/Expr.hs` | 117 | Core checking function |
| `tcPolyExprCheck` | `GHC/Tc/Gen/Expr.hs` | 163 | Polymorphic checking logic |
| `tcPolyLExprSig` | `GHC/Tc/Gen/Expr.hs` | 137 | Handle (e :: sig) |
| `tcApp` | `GHC/Tc/Gen/App.hs` | 218 | Application checking |
| `tcLambdaMatches` | `GHC/Tc/Gen/Match.hs` | - | Lambda with type patterns |

### Skolemisation

| Function | File | Line | Purpose |
|----------|------|------|---------|
| `tcSkolemiseCompleteSig` | `GHC/Tc/Utils/Unify.hs` | 470 | Signature skolemisation |
| `tcSkolemiseExpectedType` | `GHC/Tc/Utils/Unify.hs` | 480 | Expected type skolemisation |
| `tc_sub_type` | `GHC/Tc/Utils/Unify.hs` | 1537 | Subsumption checking |
| `tc_sub_type_deep` | `GHC/Tc/Utils/Unify.hs` | - | Deep subsumption |

## Concrete Examples

### Example 1: Basic Higher-Rank

```haskell
apply :: (forall a. a -> a) -> Int -> Int
apply f x = f x

-- Type checking apply:
-- 1. f has type (forall a. a -> a)
-- 2. x has type Int
-- 3. f x: instantiate a = Int, apply
```

### Example 2: Nested Higher-Rank

```haskell
nested :: ((forall a. a -> a) -> Int) -> Int
nested g = g id

-- Type checking:
-- 1. g expects (forall a. a -> a) -> Int
-- 2. id has type forall a. a -> a
-- 3. With deep subsumption: id can be passed to g
```

### Example 3: Type Pattern Alignment

```haskell
poly :: forall a b. a -> b -> (a, b)
poly @x v @y w = (v, w)

-- Type checking:
-- 1. Skolemise: a_sk, b_sk
-- 2. Match @x ~ a_sk
-- 3. Match v ~ a_sk
-- 4. Match @y ~ b_sk  
-- 5. Match w ~ b_sk
-- 6. Body (v,w) :: (a_sk, b_sk) ✓
```

## Comparison: Higher-Rank vs Type Classes

| Aspect | Higher-Rank Polymorphism | Type Classes |
|--------|-------------------------|--------------|
| **Mechanism** | Skolemisation | Constraint solving |
| **Runtime** | No evidence needed | Dictionary passing |
| **Wrapper** | Type coercion only | WpEvApp for dictionaries |
| **Checking** | Bidirectional, structural | Instance resolution |
| **Extension** | DeepSubsumption | Various class extensions |

## Summary

GHC handles higher-rank polymorphism through:

1. **Skolemisation** - converting `forall` to rigid type constants
2. **Bidirectional checking** - pushing expected types into expressions  
3. **Deep subsumption** (optional) - structural comparison of nested polymorphism
4. **Type pattern alignment** - matching lambda binders with skolemised types

The key difference from type classes: **higher-rank is purely compile-time type manipulation**, with no runtime evidence required.

## Key Source References

- **Note [Skolemisation overview]**: `GHC/Tc/Utils/Unify.hs:287`
- **Note [Deep subsumption]**: `GHC/Tc/Utils/Unify.hs:1727`
- **Note [Deep skolemisation]**: `GHC/Tc/Utils/Unify.hs`
- **tcPolyExprCheck**: `GHC/Tc/Gen/Expr.hs:163`
- **tcLambdaMatches**: `GHC/Tc/Gen/Match.hs`
