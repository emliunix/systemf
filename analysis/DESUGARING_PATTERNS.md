# Desugaring Patterns and Coercions

## Overview

This document explains how GHC desugars pattern match coercion patterns (`CoPat`) and implements the AABS2 rule's term substitution through Core-level let-bindings. Understanding this is crucial for tracing how type-checker evidence flows into the final Core representation.

---

## The AABS2 Rule and Its Implementation

### The Rule (from putting-2007-rules.tex)

```
AABS2:  ⊢^dsk σₐ ≤ σₓ ↦ f        Γ, x:σₓ ⊢^poly_↓ t : σᵣ ↦ e
       ─────────────────────────────────────────────────────────
       Γ ⊢_↓ λ(x::σₓ).t : σₐ → σᵣ ↦ λx::σₐ.[x ↦ (f x)]e
```

This rule handles checking an annotated lambda against a polymorphic function type. The key insight is the **term substitution** `[x ↦ (f x)]e` where `f` is the coercion witness from deep skolemization.

### GHC's Implementation Strategy

Rather than explicit term substitution, GHC uses **pattern-level wrappers** that become **let-bindings** in Core:

```
Paper:     λ(x::σₐ).[x ↦ (f x)]e
GHC Core:  λ(x::σₐ). let x' = f x in e[x'/x]
```

The substitution happens implicitly through variable binding and inlining.

---

## From SigPat to CoPat

### Phase 1: Type Checking

**Location**: `GHC/Tc/Gen/Pat.hs:759-770`

When type-checking a lambda argument with a type signature `\(x :: σₓ) -> e`:

```haskell
SigPat _ pat sig_ty -> do
  { (inner_ty, tv_binds, wcs, wrap) <-
      tcPatSig (inPatBind penv) sig_ty exp_pat_ty
      -- wrap :: σₐ ~~> σₓ (from tcSubTypePat)
  ; (pat', res) <- tcExtendNameTyVarEnv wcs      $
                   tcExtendNameTyVarEnv tv_binds $
                   tc_lpat (Scaled w_pat $ mkCheckExpType inner_ty) penv pat thing_inside
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty, res) }
```

**Key steps**:
1. `tcPatSig` performs subsumption check: `σₐ ≤ σₓ`
2. Returns wrapper `f :: σₐ ~ σₓ`
3. Creates `CoPat` via `mkHsWrapPat`

### The CoPat Data Type

**Location**: `GHC/Hs/Pat.hs:274-295`

```haskell
data XXPatGhcTc
  = CoPat
      { co_cpt_wrap :: HsWrapper     -- ^ The coercion wrapper f
      , co_pat_inner :: Pat GhcTc    -- ^ Inner pattern (VarPat x)
      , co_pat_ty :: Type            -- ^ Type of whole pattern (σₓ)
      }
```

The `CoPat` stores:
- The wrapper `f` (converts incoming value from σₐ to σₓ)
- The inner pattern (binds the variable at type σₓ)
- The pattern type

---

## Desugaring: matchCoercion

**Location**: `GHC/HsToCore/Match.hs:275-285`

```haskell
matchCoercion :: NonEmpty MatchId -> Type -> NonEmpty EquationInfoNE -> DsM (MatchResult CoreExpr)
matchCoercion (var :| vars) ty eqns@(eqn1 :| _)
  = do  { let XPat (CoPat co pat _) = firstPat eqn1
        ; let pat_ty' = hsPatType pat
        ; var' <- newUniqueId var (idMult var) pat_ty'   -- var' :: σₓ
        ; match_result <- match (var':vars) ty $ NE.toList $
            decomposeFirstPat getCoPat <$> eqns
        ; dsHsWrapper co $ \core_wrap -> do
        { let bind = NonRec var' (core_wrap (Var var))   -- var' = f var
        ; return (mkCoLetMatchResult bind match_result) } }
```

### What Happens:

1. **Extract** the `CoPat` from the pattern
2. **Create** fresh variable `var'` with type `σₓ`
3. **Desugar** remaining patterns with `var'` in scope
4. **Apply** wrapper to create binding: `var' = f var`
5. **Wrap** the match result with this let-binding

### Core Generation

The resulting Core looks like:

```haskell
\ (var :: σₐ) ->
  let var' :: σₓ = f var
  in e'  -- where e' uses var', not var
```

---

## Variable Binding Chain

### Step 1: VarPat Tidying

**Location**: `GHC/HsToCore/Match.hs:424-427`

```haskell
tidy1 v _ (VarPat _ (L _ var))
  = return (wrapBind var v, WildPat (idType var))
```

The `tidy1` function transforms:
```
case v of { x -> e }  ⟹  case v of { _ -> let x=v in e }
```

**Location**: `GHC/HsToCore/Utils.hs:247-250`

```haskell
wrapBind :: Var -> Var -> CoreExpr -> CoreExpr
wrapBind new old body
  | new==old    = body  -- Same var, no binding needed
  | otherwise   = Let (NonRec new (varToCoreExpr old)) body
```

### Step 2: CoPat Processing

Combining both transformations:

```haskell
-- Original pattern: CoPat f (VarPat x) σₓ

-- After tidy1 (VarPat inside CoPat):
-- CoPat f (WildPat σₓ)  with wrapBind x var'

-- After matchCoercion:
-- let var' = f var          -- from CoPat
-- in let x = var'            -- from VarPat
--    in e
```

The simplifier will later inline `x = var'` into the body.

---

## The WpFun Wrapper (Deep Subsumption)

For function types with deep subsumption, the wrapper becomes `WpFun`:

**Location**: `GHC/HsToCore/Binds.hs:1618-1624`

```haskell
go (WpFun w_co c1 c2 t _) k = -- See Note [Desugaring WpFun]
  do { x <- newSysLocalDs (mkScaled (subMultCoRKind w_co) t)
     ; go c1 $ \w1 ->
       go c2 $ \w2 ->
       let app f a = mkCoreApp f a
           arg     = w1 (Var x)
       in k (\e -> (Lam x (w2 (app e arg)))) }
```

This implements eta-expansion:
```haskell
(WpFun w_arg w_res)[ e ] = \x. w_res[ e w_arg[x] ]
```

### Example

For `σₐ = Int -> Int` and `σₓ = forall a. a -> a`:

```haskell
-- Wrapper: WpFun (WpTyApp Int) WpHole
-- Core:
\ (g :: Int -> Int) ->
  (\ (y :: Int) -> g y)  -- applied to @Int
```

---

## Complete Flow Example

### Source Code
```haskell
f :: (forall a. a -> a) -> Int
f (g :: Int -> Int) = g 42
```

### Type-Checked AST
```haskell
-- Pattern: CoPat wrap (VarPat g) (Int -> Int)
-- where wrap :: (forall a. a -> a) ~ (Int -> Int)
```

### Desugared Core
```haskell
f = \ (g_poly :: forall a. a -> a) ->
      let g :: Int -> Int = g_poly @Int
      in g 42
```

---

## Key Source References

| Concept | File | Line | Purpose |
|---------|------|------|---------|
| `CoPat` data type | `GHC/Hs/Pat.hs` | 274-295 | Coercion pattern representation |
| `mkHsWrapPat` | `GHC/Hs/Utils.hs` | 811-813 | Create CoPat from wrapper |
| `matchCoercion` | `GHC/HsToCore/Match.hs` | 275-285 | Desugar CoPat to let-binding |
| `dsHsWrapper` | `GHC/HsToCore/Binds.hs` | 1583-1624 | Wrapper → Core transformation |
| `wrapBind` | `GHC/HsToCore/Utils.hs` | 247-250 | Variable binding utility |
| `tcPatSig` | `GHC/Tc/Gen/Pat.hs` | 1008-1052 | Type-check pattern signatures |
| `WpFun` desugaring | `GHC/HsToCore/Binds.hs` | 1618-1624 | Eta-expansion for function wrappers |

---

## Summary

The AABS2 term substitution is implemented through:

1. **Pattern wrappers** (`CoPat`) attaching coercions to patterns
2. **Let-bindings** in Core connecting the incoming parameter to the coerced value
3. **Variable shadowing** where the pattern-bound variable refers to the coerced value
4. **Implicit substitution** via simplifier inlining

This approach avoids explicit AST transformation and leverages GHC's existing optimization infrastructure.

---

**Related Documents**:
- `HSWRAPPER_ARCHITECTURE.md` - Complete wrapper documentation
- `TYPE_INFERENCE.md` - Bidirectional type checking
- `HIGHERRANK_POLY.md` - Deep skolemization details
