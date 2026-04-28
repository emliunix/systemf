# Paper Rules to GHC Code Correspondence

## Overview

This document maps the bidirectional type system rules from "Practical Type Inference for Higher-Rank Types" (2007) to their implementation in GHC, with focus on HsWrapper creation.

---

## Rule Mapping Table

| Paper Rule | Judgment Form | GHC Function | HsWrapper Created |
|------------|---------------|--------------|-------------------|
| **INST1** | `⊢↑inst ∀ā.ρ ≤ [ā↦τ]ρ ↦ f` | `topInstantiate` | `WpTyApp` + `WpEvApp` composition |
| **INST2** | `⊢↓inst σ ≤ ρ ↦ f` | `tc_sub_type_ds` with `Shallow` flag | Combined wrapper from subsumption |
| **PRPOLY** | `pr(∀ā.ρ₁) = ∀āḇ.ρ₂ ↦ f` | `tcDeepSplitSigmaTy_maybe` + manual wrapper | `WpTyLam` composition |
| **PRFUN** | `pr(σ₁→σ₂) = ∀ā.(σ₁→ρ₂) ↦ f` | `deeplySkolemise` / `deeplyInstantiate` | `WpFun` + `WpTyLam` composition |
| **PRMONO** | `pr(τ) = τ ↦ λx:τ.x` | Identity (no wrapper needed) | `WpHole` |
| **DEEP-SKOL** | `⊢dsk σ₁ ≤ σ₂ ↦ f` | `deeplySkolemise` | `WpTyLam` + `WpEvLam` + `WpEta` |
| **SPEC** | `⊢dsk* ∀ā.ρ₁ ≤ ρ₂ ↦ f` | `topInstantiate` in `go1` of `tc_sub_type_deep` | `WpTyApp` + `WpEvApp` |
| **FUN** | `⊢dsk* (σ₁→σ₂) ≤ (σ₃→σ₄) ↦ f` | `go_fun` in `tc_sub_type_deep` | `WpFun` via `mkWpFun_FRR` |
| **MONO** | `⊢dsk* τ ≤ τ ↦ λx:τ.x` | `just_unify` or identity | `WpHole` or `WpCast` |

---

## Detailed Correspondences

### 1. INST1 (Synthesis Mode Instantiation)

**Paper Rule:**
```
⊢↑inst ∀ā.ρ ≤ [ā↦τ]ρ ↦ λx:(∀ā.ρ). x τ̄
```

**GHC Implementation:** `topInstantiate` in `GHC/Tc/Utils/Instantiate.hs` (lines 275-310)

```haskell
topInstantiate :: CtOrigin -> TcSigmaType -> TcM (HsWrapper, TcRhoType)
-- Returns: (wrap, inner_ty) where wrap :: inner_ty ~~> ty
```

**Wrapper Construction:**
- Creates fresh meta type variables for quantified type variables
- Calls `instCall` to create evidence for constraints
- Composes with recursive `topInstantiate` for nested foralls
- Returns composition: `wrap2 <.> wrap1`

**HsWrapper Components:**
- `WpTyApp` for type applications
- `WpEvApp` for dictionary applications
- Composed with `<.>` operator

**Code Reference:** `GHC/Tc/Utils/Instantiate.hs:275-310`

---

#### Detailed Trace: `topInstantiate` HsWrapper Structure

**Example Input:** `sigma = forall a b. (Num a, Ord b) => a -> b -> Int`

**Step 1: Split the type**
```haskell
(tvs, phi_ty)  = tcSplitSomeForAllTyVars ... sigma
-- tvs = [a, b]
(theta, body_ty) = tcSplitPhiTy phi_ty  
-- theta = [Num a, Ord b], body_ty = a -> b -> Int
```

**Step 2: Create fresh meta type variables**
```haskell
(subst, inst_tvs) <- newMetaTyVarsX empty_subst tvs
-- inst_tvs = [a1, b1] (fresh metavariables)
-- subst = [a:=a1, b:=b1]

let inst_theta = substTheta subst theta
    inst_body  = substTy subst body_ty
-- inst_theta = [Num a1, Ord b1]
-- inst_body = a1 -> b1 -> Int
```

**Step 3: `instCall` creates `wrap1`**
```haskell
wrap1 <- instCall orig (mkTyVarTys inst_tvs) inst_theta
```

`instCall` (lines 359-368):
```haskell
instCall orig tys theta = do
  { dict_app <- instCallConstraints orig theta
  ; return (dict_app <.> mkWpTyApps tys) }
```

`instCallConstraints [Num a1, Ord b1]` (lines 371-382):
- Emits wanted constraints for each predicate
- Creates evidence variables: `ev1 :: Num a1`, `ev2 :: Ord b1`
- Returns: `mkWpEvApps [ev1, ev2]`

`mkWpEvApps` (lines 463-464):
```haskell
mkWpEvApps args = mk_co_app_fn WpEvApp args
-- foldr (\x wrap -> wrap <.> WpEvApp x) WpHole [ev1, ev2]
-- = WpEvApp ev2 <.> WpEvApp ev1
```

`mkWpTyApps [a1, b1]` (lines 460-461):
```haskell
mkWpTyApps tys = mk_co_app_fn WpTyApp tys
-- foldr (\x wrap -> wrap <.> WpTyApp x) WpHole [a1, b1]  
-- = WpTyApp b1 <.> WpTyApp a1
```

**Combined `wrap1`:**
```
wrap1 = (WpEvApp ev2 <.> WpEvApp ev1) <.> (WpTyApp b1 <.> WpTyApp a1)
```

**Step 4: Recursive call**
```haskell
(wrap2, inner_body) <- topInstantiate orig inst_body
-- inst_body = a1 -> b1 -> Int has no foralls/constraints
-- Returns: (idHsWrapper, a1 -> b1 -> Int)
```

**Final result:**
```haskell
return (wrap2 <.> wrap1, inner_body)
-- in_wrap = idHsWrapper <.> wrap1 = wrap1
-- in_rho = a1 -> b1 -> Int
```

**Complete `in_wrap` structure:**
```
WpCompose
  (WpCompose (WpEvApp ev2) (WpEvApp ev1))
  (WpCompose (WpTyApp b1) (WpTyApp a1))
```

Or fully expanded (right-associative composition):
```
WpEvApp ev2 <.> WpEvApp ev1 <.> WpTyApp b1 <.> WpTyApp a1
```

**Elaboration effect:**
```haskell
e  -->  (((e @a1) @b1) ev1) ev2
```

Where:
- `ev1 :: Num a1` - dictionary evidence for `Num` constraint
- `ev2 :: Ord b1` - dictionary evidence for `Ord` constraint

---

#### Evidence in `WpEvApp`

The evidence terms (`EvTerm` / `EvExpr`) represent:
- **Type class dictionaries** (e.g., `$fNumInt :: Num Int`)
- **Implicit parameters**
- **Equality proofs** (`~`)

**Evidence creation flow:**
1. `emitWanted orig pred` - Creates evidence variable for constraint
2. Evidence is solved later by the constraint solver
3. `WpEvApp` applies the evidence to discharge the constraint

This matches the paper's elaboration:
```
λx:(∀a b. Num a => Ord b => ...). x τ₁ τ₂ dict₁ dict₂
```

---

### 2. INST2 (Checking Mode Instantiation)

**Paper Rule:**
```
⊢dsk σ ≤ ρ ↦ f
------------------
⊢↓inst σ ≤ ρ ↦ f
```

**GHC Implementation:** `tc_sub_type_ds` in `GHC/Tc/Utils/Unify.hs` (lines 1564-1588)

When in checking mode with `Shallow` flag, calls `tc_sub_type_shallow`:

```haskell
tc_sub_type_shallow :: ... -> TcM HsWrapper
tc_sub_type_shallow unify inst_orig ty_actual sk_rho
  = do { (wrap, rho_a) <- topInstantiate inst_orig ty_actual
       ; cow           <- unify rho_a sk_rho
       ; return (mkWpCastN cow <.> wrap) }
```

**Wrapper Construction:**
- First instantiates `ty_actual` using `topInstantiate`
- Then unifies the instantiated type with expected type
- Composes cast wrapper with instantiation wrapper

**HsWrapper Components:**
- Result of `topInstantiate` (as above)
- `WpCastN` from unification

**Code Reference:** `GHC/Tc/Utils/Unify.hs:1591-1599`

---

### 3. PRPOLY (Prenex Conversion for Polytypes)

**Paper Rule:**
```
pr(ρ₁) = ∀ḇ.ρ₂ ↦ f    ā ∉ ḇ
-------------------------------------
pr(∀ā.ρ₁) = ∀āḇ.ρ₂ ↦ λx:(∀āḇ.ρ₂). Λā. f (x ā)
```

**GHC Implementation:** Partially in `tcDeepSplitSigmaTy_maybe` + wrapper building logic

This rule's logic is distributed across:
1. `tcDeepSplitSigmaTy_maybe` - identifies the quantified structure
2. `deeplySkolemise` / `deeplyInstantiate` - handles the actual conversion

The witness `f` in the paper is built by recursively processing the inner type.

**Code Reference:** 
- `GHC/Tc/Utils/Unify.hs:2341-2365` (tcDeepSplitSigmaTy_maybe)
- Type structure analysis in `tc_sub_type_deep`

---

### 4. PRFUN (Prenex Conversion for Functions)

**Paper Rule:**
```
pr(σ₂) = ∀ā.ρ₂ ↦ f    ā ∉ ftv(σ₁)
-----------------------------------------------
pr(σ₁→σ₂) = ∀ā.(σ₁→ρ₂) ↦ λx:(∀ā.σ₁→ρ₂). λy:σ₁. f (Λā. x ā y)
```

**GHC Implementation:** `deeplySkolemise` in `GHC/Tc/Utils/Unify.hs` (lines 2275-2304)

```haskell
deeplySkolemise :: SkolemInfo -> TcSigmaType
                -> TcM ( HsWrapper
                       , [(Name,TcInvisTVBinder)]
                       , [EvVar]
                       , TcRhoType )
```

**Wrapper Construction:**
- Uses `tcDeepSplitSigmaTy_maybe` to find nested quantifiers
- Creates eta-expansion wrapper with `mkWpEta`
- Composes type lambdas, evidence lambdas, and inner wrapper

**HsWrapper Components:**
- `WpTyLam` for type abstractions
- `WpEvLam` for evidence abstractions
- `WpEta` for eta-expansion
- Composed with `<.>`

**Key insight from Note [Deep skolemisation]:**
```
if  deeplySkolemise ty = (wrap, tvs, evs, rho)
    e :: rho
then wrap e :: ty
    and 'wrap' binds tvs, evs
```

**Code Reference:** `GHC/Tc/Utils/Unify.hs:2275-2304`

---

### 5. PRMONO (Prenex for Monotypes)

**Paper Rule:**
```
pr(τ) = τ ↦ λx:τ.x
```

**GHC Implementation:** Identity - no wrapper needed

When a type has no foralls or constraints to move, no wrapper is produced.

**HsWrapper:** `WpHole` (identity wrapper)

**Code Reference:** Used implicitly when `tcDeepSplitSigmaTy_maybe` returns `Nothing`

---

### 6. DEEP-SKOL (Deep Skolemization)

**Paper Rule:**
```
pr(σ₂) = ∀ā.ρ ↦ f₁    ā ∉ fv(σ₁)    ⊢dsk* σ₁ ≤ ρ ↦ f₂
---------------------------------------------------------
⊢dsk σ₁ ≤ σ₂ ↦ λx:σ₁. f₁ (Λā. f₂ x)
```

**GHC Implementation:** `deeplySkolemise` (same as PRFUN)

This is essentially the same operation as PRFUN - prenex conversion with skolemization. The witness records how to eta-expand and introduce type/evidence binders.

**HsWrapper Components:**
- `WpTyLam` (type abstraction)
- `WpEvLam` (evidence abstraction)  
- `WpEta` (eta expansion via `mkWpEta`)

**Code Reference:** `GHC/Tc/Utils/Unify.hs:2275-2304`

---

### 6.5. Key Insight: pr(σ) Witness vs GHC Wrapper

**The Core Equivalence:**

The paper's `pr(σ) = ∀ā.ρ ↦ f` and GHC's `deeplySkolemise` implement the same transformation with slightly different wrapper types:

| Aspect | Paper | GHC |
|--------|-------|-----|
| **Prenex Type** | `∀ā.ρ` | `ρ` (with skolems as free vars) |
| **Witness Type** | `f :: (∀ā.ρ) → σ` | `wrap :: ρ → σ` |
| **Application** | `f (Λā. e)` | `wrap e` |
| **Generalization** | Explicit `Λā.` | Fused into wrapper via `mkWpTyLams` |

**Why They Are Equivalent:**

**Paper's approach (explicit):**
```haskell
-- 1. Check at ρ with skolems: e :: ρ
-- 2. Generalize: Λā. e :: ∀ā.ρ  
-- 3. Apply witness: f (Λā. e) :: σ
```

**GHC's approach (fused):**
```haskell
-- 1. Check at ρ with skolems: e :: ρ
-- 2. Apply wrapper: wrap e :: σ
--    where wrap = λe. f (Λā. e)
```

**The wrapper fusion:**
```haskell
-- GHC's wrap combines steps 2-3:
wrap = mkWpTyLams tvs <.> inner_wrap
--       ↑ generalization    ↑ conversion

-- Applied to term:
wrap e = mkWpTyLams tvs (inner_wrap e)
       = Λs₁. ... Λsₙ. (inner_wrap e)
       ≅ f (Λā. e)  -- Same result!
```

**When the Types Are Already Prenex:**

For simple types like `∀a.a→a`:
- Paper's `f` is essentially identity: `λx.(∀a.a→a). x`
- GHC's wrapper is just `mkWpTyLams [s]` 
- No complex `f` needed because the type is already in prenex form

**For nested types** like `∀a. a → ∀b. b → a`:
- Paper's `f` from `pr(σ)` handles the impedance mismatch
- GHC's wrapper includes `mkWpEta` for proper nesting
- Both achieve the same round-trip transformation

**Practical Implementation Note:**

When implementing, you can choose:
1. **Paper style**: Explicit generalization then apply `f`
2. **GHC style**: Fused wrapper that generalizes internally

GHC's approach is more efficient (single wrapper application), while the paper's is more explicit for reasoning.

---

### 7. SPEC (Specialization in Auxiliary Subsumption)

**Paper Rule:**
```
⊢dsk* [ā↦τ]ρ₁ ≤ ρ₂ ↦ f
-------------------------------------------
⊢dsk* ∀ā.ρ₁ ≤ ρ₂ ↦ λx:(∀ā.ρ₁). f (x τ̄)
```

**GHC Implementation:** `go1` case in `tc_sub_type_deep` (lines 2096-2103)

```haskell
go1 ty_a ty_e
  | let (tvs, theta, _) = tcSplitSigmaTy ty_a
  , not (null tvs && null theta)
  = do { (in_wrap, in_rho) <- topInstantiate inst_orig ty_a
       ; body_wrap <- go in_rho ty_e
       ; return (body_wrap <.> in_wrap) }
```

**Wrapper Direction Analysis:**
- `in_wrap :: ty_a ~~> in_rho` - Goes from polymorphic to instantiated
  - Applies type arguments: `x @τ₁ @τ₂ ...`
  - Applies evidence arguments for constraints
- `body_wrap :: in_rho ~~> ty_e` - Recursive check on instantiated types
- `body_wrap <.> in_wrap :: ty_a ~~> ty_e` - Combined witness

This matches the paper's witness `λx:(∀ā.ρ₁). f (x τ̄)`:
- Takes `x` of polymorphic type `∀ā.ρ₁`
- Applies type arguments `x τ̄` to get `in_rho`
- Applies `f` (the body_wrap) to get `ty_e`

**HsWrapper Components:**
- `in_wrap` from `topInstantiate`: composition of `WpTyApp` and `WpEvApp`
- `body_wrap`: recursive wrapper (SPEC, FUN, or MONO)
- Combined via `WpCompose` (`<.>` operator)

**Code Reference:** `GHC/Tc/Utils/Unify.hs:2098-2103`

---

### 8. FUN (Function Subsumption)

**Paper Rule:**
```
⊢dsk σ₃ ≤ σ₁ ↦ f₁    ⊢dsk* σ₂ ≤ σ₄ ↦ f₂
--------------------------------------------------
⊢dsk* (σ₁→σ₂) ≤ (σ₃→σ₄) ↦ λx:(σ₁→σ₂). λy:σ₃. f₂ (x (f₁ y))
```

**GHC Implementation:** `go_fun` in `tc_sub_type_deep` (lines 2146-2179)

```haskell
go_fun :: FunTyFlag -> Mult -> TcType -> TcType
       -> FunTyFlag -> Mult -> TcType -> TcType
       -> TcM HsWrapper
go_fun act_af act_mult act_arg act_res exp_af exp_mult exp_arg exp_res
  = do { arg_wrap  <- tc_sub_type_ds (tc_fun, Argument pos) ...
       ; res_wrap  <- tc_sub_type_deep (tc_fun, Result pos) ...
       ; wp_mult <- ...  -- multiplicity handling
       ; fun_wrap <- mkWpFun_FRR ... arg_wrap res_wrap
       ; return fun_wrap }
```

**Wrapper Construction:**
- Recursively checks argument subsumption (contravariant - sides swapped)
- Recursively checks result subsumption (covariant)
- Calls `mkWpFun_FRR` to build function wrapper

**HsWrapper Components:**
- `WpFun` (via `mkWpFun_FRR`)
- Contains `arg_wrap` and `res_wrap` as sub-wrappers
- May optimize to `WpCast` if both sub-wrappers are casts

**Key Code in `mkWpFun_FRR`:**
```haskell
-- If both arg_wrap and res_wrap are casts, use FunCo
| Just arg_co <- getWpCo_maybe arg_wrap ...
, Just res_co <- getWpCast_maybe res_wrap ...
= return (mkWpCastR (mkSubMultFunCo ... (mkSymCo arg_co) res_co))

-- Otherwise, build WpFun with eta expansion
| otherwise
= do { ...
     ; return (mkWpFun arg_wrap_frr res_wrap (sub_mult, exp_arg_frr) exp_res) }
```

**Code Reference:** 
- `GHC/Tc/Utils/Unify.hs:2146-2179` (go_fun)
- `GHC/Tc/Utils/Unify.hs:2189-2249` (mkWpFun_FRR)

---

### 9. MONO (Monotype Reflexivity)

**Paper Rule:**
```
⊢dsk* τ ≤ τ ↦ λx:τ.x
```

**GHC Implementation:** Two cases

**Case 1 - In `go1`:** Falls through to `just_unify`
```haskell
go1 ty_a ty_e = just_unify ty_a ty_e

just_unify ty_a ty_e = do { cow <- unify ty_a ty_e
                          ; return (mkWpCastN cow) }
```

**Case 2 - If types are identical:** May return `idHsWrapper` (WpHole)

**HsWrapper Components:**
- `WpCastN` if unification produces a coercion
- `WpHole` if types are already equal

**Code Reference:** `GHC/Tc/Utils/Unify.hs:2139-2143`

---

## Wrapper Composition Summary

| Operation | Paper Notation | GHC Operator |
|-----------|---------------|--------------|
| Sequential composition | f₂ ∘ f₁ | `w1 <.> w2` (w2 applied first) |
| Type application | - | `WpTyApp ty` |
| Evidence application | - | `WpEvApp tm` |
| Type abstraction | Λā. | `WpTyLam tv` |
| Evidence abstraction | λd:θ. | `WpEvLam ev` |
| Function wrapper | - | `WpFun arg_wrap res_wrap ...` |
| Type cast | - | `WpCast co` |
| Identity | λx.x | `WpHole` |

---

## Key Files and Locations

1. **Wrapper Definition:** `GHC/Tc/Types/Evidence.hs:243-310`
2. **Wrapper Constructors:** `GHC/Tc/Types/Evidence.hs:331-488`
3. **Deep Subsumption:** `GHC/Tc/Utils/Unify.hs:1564-2249`
4. **Instantiation:** `GHC/Tc/Utils/Instantiate.hs:275-310`
5. **Deep Skolemization:** `GHC/Tc/Utils/Unify.hs:2275-2304`
6. **Wrapper Desugaring:** `GHC/HsToCore/Binds.hs` (dsHsWrapper)

---

## Status

- [x] INST1 → topInstantiate
- [x] INST2 → tc_sub_type_ds
- [x] PRPOLY → tcDeepSplitSigmaTy_maybe + wrapper building
- [x] PRFUN → deeplySkolemise/deeplyInstantiate
- [x] PRMONO → idHsWrapper
- [x] DEEP-SKOL → deeplySkolemise
- [x] SPEC → topInstantiate in go1
- [x] FUN → go_fun + mkWpFun_FRR
- [x] MONO → just_unify / idHsWrapper
