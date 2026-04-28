# Pattern Type-Checking: Complete Analysis

## Overview

This document analyzes how `tc_pat` handles the three core pattern forms:
- **VarPat** - Variable binding
- **SigPat** - Type-annotated pattern
- **ConPat** - Constructor pattern

For each, we consider two axes:
1. **Check vs Infer mode** - How the expected type is provided
2. **CoPat creation** - Whether a coercion wrapper is inserted

---

## Axis Definitions

### Check Mode
- Expected type provided via `Check ty`
- `tcSubTypePat` performs subsumption validation
- Wrapper may be created if types don't match exactly

### Infer Mode
- Expected type is a hole (`Infer infer_res`)
- `inferResultToType` extracts the type
- Types unify through the hole

### CoPat Creation
Created by `mkHsWrapPat` when the wrapper is non-identity:
```haskell
mkHsWrapPat :: HsWrapper -> Pat GhcTc -> Type -> Pat GhcTc
mkHsWrapPat co_fn p ty
  | isIdHsWrapper co_fn = p           -- No CoPat
  | otherwise            = XPat $ CoPat co_fn p ty  -- CoPat!
```

**Source**: `GHC/Hs/Utils.hs:811-813`
```

---

## VarPat Analysis

### VarPat + Check Mode

**Scenario**: `\x -> body` with expected pattern type `σ`

**Call chain**:
```
tc_lpat (Scaled w (Check σ)) → tc_pat → VarPat case
```

**Code** (`GHC/Tc/Gen/Pat.hs:620-625`):
```haskell
VarPat x (L l name) -> do
  { (wrap, id) <- tcPatBndr penv name scaled_exp_pat_ty
  ; res <- tcCheckUsage name w_pat $
           tcExtendIdEnv1 name id thing_inside
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (VarPat x (L l id)) pat_ty, res) }
```

**What `tcPatBndr` does** (`GHC/Tc/Gen/Pat.hs:348-352`):
```haskell
tcPatBndr _ bndr_name pat_ty = do
  { pat_ty <- expTypeToType (scaledThing pat_ty)
  ; return (idHsWrapper, mkLocalIdOrCoVar bndr_name pat_mult pat_ty) }
```

**Source**: `GHC/Tc/Gen/Pat.hs:315-356` (full function with LetPat cases)

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `idHsWrapper` (identity) |
| CoPat created? | **No** |
| Binder type | `σ` (from expected type) |

**Example**:
```haskell
-- (\x -> x + 1) :: Int -> Int
-- Expected pattern type: Int
-- Result: VarPat x with idHsWrapper, no CoPat
```

---

### VarPat + Infer Mode

**Scenario**: `case scrut of { x -> body }` where scrutinee type unknown

**Call chain**:
```
tc_lpat (Scaled w (Infer hole)) → tc_pat → VarPat case
```

**Code**:
```haskell
tcPatBndr _ bndr_name pat_ty = do
  { pat_ty <- expTypeToType (scaledThing pat_ty)  -- Reads the hole
  ; return (idHsWrapper, mkLocalIdOrCoVar bndr_name pat_mult pat_ty) }
```

**What `expTypeToType` does** (when given Infer):
```haskell
-- In GHC/Tc/Utils/TcMType.hs
expTypeToType (Infer inf_res) = inferResultToType inf_res
```

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `idHsWrapper` (identity) |
| CoPat created? | **No** |
| Binder type | Unifies with scrutinee type via hole |

**Example**:
```haskell
-- case unknown of { x -> x }  -- scrut has type hole
-- Hole gets filled when scrutinee is unified
-- Result: VarPat x with idHsWrapper, no CoPat
```

---

### VarPat Summary

| Mode | Expected Type | Wrapper | CoPat | Notes |
|------|--------------|---------|-------|-------|
| Check | `Check σ` | `idHsWrapper` | No | Expected type directly used |
| Infer | `Infer hole` | `idHsWrapper` | No | Hole filled by unification |

**Key insight**: `VarPat` never creates CoPat because:
1. In Check mode: Expected type is used directly
2. In Infer mode: Hole unifies, identity coercion

---

## SigPat Analysis

### SigPat + Check Mode

**Scenario**: `\ (x :: σ_sig) -> body` against expected type `σ_a`

**Call chain**:
```
tc_lpat (Check σ_a) → tc_pat → SigPat case
  → tcPatSig (σ_a, σ_sig) → returns wrap :: σ_a ~~> σ_sig
  → tc_lpat (Check σ_sig) → recurse on inner pattern
  → mkHsWrapPat wrap inner → CoPat!
```

**Code** (`GHC/Tc/Gen/Pat.hs:759-770`):
```haskell
SigPat _ pat sig_ty -> do
  { (inner_ty, tv_binds, wcs, wrap) <-
      tcPatSig (inPatBind penv) sig_ty exp_pat_ty
      -- wrap :: σ_a ~~> σ_sig
  
  ; (pat', res) <- tcExtendNameTyVarEnv wcs      $>
                   tcExtendNameTyVarEnv tv_binds $>
                   tc_lpat (Scaled w_pat $ mkCheckExpType inner_ty)
                           penv pat thing_inside
  
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty, res) }
```

**What `tcPatSig` does** (`GHC/Tc/Gen/Pat.hs:1008-1044`):
```haskell
tcPatSig in_pat_bind sig res_ty = do
  { (sig_wcs, sig_tvs, sig_ty) <- tcHsPatSigType ...  -- Type-check signature
  
  ; wrap <- tcSubTypePat PatSigOrigin PatSigCtxt res_ty sig_ty
      -- tcSubTypePat (Check σ_a) σ_sig
      -- Returns wrap :: σ_a ~~> σ_sig
  
  ; return (sig_ty, sig_tvs, sig_wcs, wrap) }
```

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `wrap :: σ_a ~~> σ_sig` (from `tcSubTypePat`) |
| CoPat created? | **Yes** (unless wrap is identity) |
| Inner pattern type | `σ_sig` |
| Whole pattern type | `σ_a` |

**AST output** (`GHC/Hs/Pat.hs:279-290`):
```haskell
CoPat
  { co_cpt_wrap = wrap  -- :: σ_a ~~> σ_sig
  , co_pat_inner = SigPat σ_sig (VarPat x)  -- Inner at σ_sig
  , co_pat_ty = σ_a }  -- Whole at σ_a
```

**Example**:
```haskell
-- (\(x :: Int -> Int) -> g x) :: (forall a. a -> a) -> Int
-- Expected σ_a = forall a. a -> a
-- Signature σ_sig = Int -> Int
-- wrap = deep skolemization wrapper
-- Result: CoPat wrap (SigPat (Int -> Int) (VarPat x))
```

---

### SigPat + Infer Mode

**Scenario**: Pattern signature in inference context

**Call chain**:
```
tc_lpat (Infer hole) → tc_pat → SigPat case
  → tcPatSig (hole, σ_sig)
  → fillInferResultNoInst σ_sig hole → co :: σ_sig ~ hole
  → tc_lpat (Check σ_sig) → recurse
  → mkHsWrapPat (mkWpCastN co) inner → CoPat!
```

**What `tcPatSig` does in Infer mode**:
```haskell
tcPatSig in_pat_bind sig res_ty@(Infer inf_res) = do
  { (sig_wcs, sig_tvs, sig_ty) <- tcHsPatSigType ...
  
  ; co <- fillInferResultNoInst sig_ty inf_res
      -- Unify hole with signature type
      -- co :: σ_sig ~ hole
  
  ; return (sig_ty, sig_tvs, sig_wcs, mkWpCastN (mkSymCo co)) }
```

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `mkWpCastN (mkSymCo co)` |
| CoPat created? | **Yes** (symmetry cast) |
| Hole filled with | `σ_sig` |

**Key insight**: The hole is filled with the signature type, not the other way around.

---

### SigPat Summary

| Mode | Expected Type | Wrapper | CoPat | Notes |
|------|--------------|---------|-------|-------|
| Check | `Check σ_a` | `wrap :: σ_a ~~> σ_sig` | **Yes** | Deep skolemization |
| Infer | `Infer hole` | `mkWpCastN sym(co)` | **Yes** | Hole ← σ_sig |

**Key insight**: `SigPat` always creates CoPat because:
1. In Check mode: The wrapper witnesses subsumption `σ_a ≤ σ_sig`
2. In Infer mode: The wrapper witnesses unification `hole = σ_sig`

---

## ConPat Analysis

### ConPat + Check Mode

**Scenario**: `case scrut of { Just x -> body }` with scrut type `σ`

**Call chain**:
```
tc_lpat (Check σ) → tc_pat → ConPat case
  → tcConPat → matchExpectedConTy σ Just
  → unify σ with Maybe α → returns wrap, ctxt_res_tys
  → tcConValArgs → check each argument pattern
  → mkHsWrapPat wrap (ConPat ...) → CoPat if wrap not identity
```

**Code** (`GHC/Tc/Gen/Pat.hs:830-833`):
```haskell
ConPat _ con arg_pats ->
  tcConPat penv con scaled_exp_pat_ty arg_pats thing_inside
```

**Full implementation** (`GHC/Tc/Gen/Pat.hs:1154-1268`):
```haskell
tcDataConPat ... pat_ty_scaled penv arg_pats thing_inside = do
  { let tycon = dataConTyCon data_con
  
  ; (wrap, ctxt_res_tys) <- matchExpectedConTy penv tycon pat_ty_scaled
      -- Unifies scrut type with constructor type
      -- Returns wrapper if coercion needed (data families)
  
  ; pat_ty <- readExpType (scaledThing pat_ty_scaled)
  
  ; tenv1 <- instTyVarsWith PatOrigin univ_tvs ctxt_res_tys
      -- Instantiate constructor's type vars
  
  ; (val_arg_pats', res) <- tcConValArgs ... arg_pats thing_inside
      -- Type-check argument patterns
  
  ; let res_pat = ConPat { pat_args = val_arg_pats', ... }
  
  ; return (mkHsWrapPat wrap res_pat pat_ty, res) }
```

**What `matchExpectedConTy` does**:
```haskell
matchExpectedConTy penv tycon pat_ty_scaled = do
  { pat_ty <- expTypeToType (scaledThing pat_ty_scaled)
  ; case tycon of
      -- For data families, need coercion
      FamilyTyCon _ -> do
        { (co, ty_args) <- matchExpectedTyConApp pat_ty tycon
        ; return (mkWpCastN co, ty_args) }
      -- For regular tycons, just split
      _ -> do
        { ty_args <- matchExpectedTyConApp pat_ty tycon
        ; return (idHsWrapper, ty_args) } }
```

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `idHsWrapper` or `mkWpCastN co` (data families) |
| CoPat created? | **Maybe** (only for data families) |
| Sub-pattern types | From `ctxt_res_tys` after unification |

**Example (regular)**:
```haskell
-- case x :: [Int] of { (a:b) -> body }
-- Expected: [Int]
-- ConPat: (:) with args at types [Int], Int
-- No CoPat (regular list tycon)
```

**Example (data family)**:
```haskell
-- data instance Map Int v = MapInt v
-- case x :: Map Int Bool of { MapInt y -> body }
-- Expected: Map Int Bool (family)
-- Actual: MapInt Bool (representation)
-- wrap = coercion family ~ representation
-- Result: CoPat wrap (ConPat (MapInt ...))
```

---

### ConPat + Infer Mode

**Scenario**: `case scrut of { Con x y -> body }` where scrutinee type unknown

**Call chain**:
```
tc_lpat (Infer hole) → tc_pat → ConPat case
  → tcConPat → matchExpectedConTy hole (data family?)
  → fillInferResultNoInst (dataConTy arg_tys) hole
  → unify hole with dataConType
  → returns wrap, instantiated arg types
  → tcConValArgs → check arguments
```

**What happens**:
1. Hole is the scrutinee type
2. Unify hole with constructor's type (after instantiation)
3. Extract argument types from unified type
4. Type-check sub-patterns with those argument types

**Result**:
| Aspect | Value |
|--------|-------|
| Wrapper | `idHsWrapper` |
| CoPat created? | **No** (hole unified directly) |
| Sub-pattern types | From unification result |

**Key insight**: No CoPat because:
- The hole IS the scrutinee type
- Unification directly connects scrutinee to constructor type
- No separate coercion needed

---

### ConPat Summary

| Mode | Expected Type | Wrapper | CoPat | Notes |
|------|--------------|---------|-------|-------|
| Check (regular) | `Check σ` | `idHsWrapper` | No | Direct unification |
| Check (family) | `Check σ` | `mkWpCastN co` | **Yes** | Coercion for representation |
| Infer | `Infer hole` | `idHsWrapper` | No | Hole unified with con type |

---

## Complete Decision Matrix

### VarPat

| Mode | Expected | Wrapper | CoPat | Reason |
|------|----------|---------|-------|--------|
| Check | `Check σ` | `idHsWrapper` | No | Expected used directly |
| Infer | `Infer hole` | `idHsWrapper` | No | Hole unified, identity |

### SigPat

| Mode | Expected | Wrapper | CoPat | Reason |
|------|----------|---------|-------|--------|
| Check | `Check σ_a` | `wrap :: σ_a ~~> σ_sig` | **Yes** | Subsumption check |
| Infer | `Infer hole` | `mkWpCastN sym(co)` | **Yes** | Hole filled with σ_sig |

### ConPat

| Mode | Constructor | Expected | Wrapper | CoPat | Reason |
|------|-------------|----------|---------|-------|--------|
| Check | Regular | `Check σ` | `idHsWrapper` | No | Direct unification |
| Check | Family | `Check σ` | `mkWpCastN co` | **Yes** | Representation coercion |
| Infer | Any | `Infer hole` | `idHsWrapper` | No | Hole unified with con type |

---

## When CoPat IS Created

1. **SigPat + Check**: `wrap :: σ_a ~~> σ_sig` (deep skolemization)
2. **SigPat + Infer**: `mkWpCastN sym(co)` (hole filled)
3. **ConPat + Check (family)**: `mkWpCastN co` (family/representation)

### When CoPat is NOT Created

1. **VarPat + any**: Identity wrapper always
2. **ConPat + Check (regular)**: Direct unification, no coercion
3. **ConPat + Infer**: Hole unified directly

---

## Desugaring: CoPat → Core

When CoPat is created, it's desugared by `matchCoercion` in `GHC/HsToCore/Match.hs`:

```haskell
matchCoercion (var :| vars) ty eqns = do
  { let XPat (CoPat co pat _) = firstPat eqn1
  ; var' <- newUniqueId var (idMult var) pat_ty'  -- var' :: σ_sig
  ; match_result <- match (var':vars) ty ...
  ; dsHsWrapper co $ \core_wrap -> do
  ; let bind = NonRec var' (core_wrap (Var var))  -- var' = wrap var
  ; return (mkCoLetMatchResult bind match_result) }
```

**Resulting Core**:
```haskell
-- Input: CoPat wrap (VarPat x) at σ_a
-- Output:
let x' = wrap scrutinee  -- x' at σ_sig
in body with x' in scope
```

---

## Visual Summary

```
tc_pat dispatch
    │
    ├── VarPat ──→ tcPatBndr ──→ mkLocalId ──→ identity wrap ──→ No CoPat
    │
    ├── SigPat ──→ tcPatSig ──→ tcSubTypePat ──→ non-identity wrap ──→ CoPat!
    │                 │
    │                 └── Check: wrap :: σ_a ~~> σ_sig
    │                 └── Infer: wrap :: hole ~~> σ_sig
    │
    └── ConPat ──→ tcConPat ──→ matchExpectedConTy
                   │
                   ├── Regular tycon ──→ identity wrap ──→ No CoPat
                   └── Family tycon ──→ mkWpCastN co ──→ CoPat!
```

---

## Source Code Reference

### Main Type-Checking Functions

| Function | File | Lines | Purpose |
|----------|------|-------|---------|
| `tc_pat` | `GHC/Tc/Gen/Pat.hs` | 611-976 | Main pattern dispatch |
| `tc_lpat` | `GHC/Tc/Gen/Pat.hs` | 449-456 | Pattern wrapper with span |
| `tcCheckPat` | `GHC/Tc/Gen/Pat.hs` | 221-225 | Check mode entry |
| `tcCheckPat_O` | `GHC/Tc/Gen/Pat.hs` | 228-236 | Check with custom origin |
| `tcInferPat` | `GHC/Tc/Gen/Pat.hs` | 210-219 | Infer mode entry |
| `tcPatBndr` | `GHC/Tc/Gen/Pat.hs` | 315-356 | Create pattern binder |
| `tcPatSig` | `GHC/Tc/Gen/Pat.hs` | 1008-1051 | Handle pattern signature |
| `tcConPat` | `GHC/Tc/Gen/Pat.hs` | 1127-1140 | Constructor pattern dispatcher |
| `tcDataConPat` | `GHC/Tc/Gen/Pat.hs` | 1154-1268 | Data constructor handling |
| `tcMatchPats` | `GHC/Tc/Gen/Pat.hs` | 116-207 | Match patterns with expected types |

### Pattern Data Types

| Type | File | Lines | Purpose |
|------|------|-------|---------|
| `CoPat` | `GHC/Hs/Pat.hs` | 279-290 | Coercion pattern wrapper |
| `XXPatGhcTc` | `GHC/Hs/Pat.hs` | 274-295 | Extension patterns (GhcTc) |
| `ConPatTc` | `GHC/Hs/Pat.hs` | 304-328 | Constructor pattern extension |
| `Scaled` | `GHC/Core/TyCo/Rep.hs` | 2107-2127 | Type with multiplicity |

### Wrapper Functions

| Function | File | Lines | Purpose |
|----------|------|-------|---------|
| `mkHsWrapPat` | `GHC/Hs/Utils.hs` | 811-816 | Create wrapped pattern |
| `tcSubTypePat` | `GHC/Tc/Utils/Unify.hs` | 1434-1447 | Pattern subsumption |
| `fillInferResultNoInst` | `GHC/Tc/Utils/Unify.hs` | 1171-1185 | Fill inference hole |

### Desugaring

| Function | File | Lines | Purpose |
|----------|------|-------|---------|
| `matchCoercion` | `GHC/HsToCore/Match.hs` | 275-285 | Desugar CoPat |
| `dsHsWrapper` | `GHC/HsToCore/Binds.hs` | ~1618 | Translate wrapper to Core |
| `mkWpCastN` | `GHC/Tc/Types/Evidence.hs` | 453-457 | Create cast wrapper |
| `idHsWrapper` | `GHC/Tc/Types/Evidence.hs` | 498-499 | Identity wrapper |

### Entry Points

| Function | File | Lines | Purpose |
|----------|------|-------|---------|
| `tcLambdaMatches` | `GHC/Tc/Gen/Match.hs` | 145-170 | Lambda pattern matching |
| `tcMatches` | `GHC/Tc/Gen/Match.hs` | 222-266 | General match handling |
| `tcExpr` | `GHC/Tc/Gen/Expr.hs` | ~332 | Main expression checker |

---

## Key Takeaways

1. **CoPat exists to record type coercions** that can't be expressed otherwise
2. **SigPat always creates CoPat** because the annotation may differ from context
3. **ConPat creates CoPat only for data families** where representation ≠ interface
4. **VarPat never creates CoPat** - it's always identity
5. **Desugaring converts CoPat to Core let-binding** with wrapper application
