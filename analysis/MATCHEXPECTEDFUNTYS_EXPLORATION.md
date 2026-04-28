# matchExpectedFunTys Exploration Analysis

**Status**: Complete  
**Last Updated**: 2026-04-09  
**Central Question**: How does `matchExpectedFunTys` decompose function types and handle skolemisation?

---

## Overview

`matchExpectedFunTys` is a critical type-checking function in GHC that checks whether a sigma type has the form of an n-ary function. It decomposes the type into argument types and a result type, passing them to a callback while returning a coercion wrapper.

**Used for**:
- Lambda expressions (`\x -> e`)
- Function definitions with patterns
- Operator sections (e.g., `(+ x)`, `(f 3)`)

**Source Location**: `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs`, lines 717-970

---

## Function Signature

```haskell
matchExpectedFunTys :: forall a.
                       ExpectedFunTyOrigin  -- Herald for error messages
                    -> UserTypeCtxt         -- Context (e.g., FunSigCtxt, GenSigCtxt)
                    -> VisArity             -- Number of visible arguments expected
                    -> ExpSigmaType         -- The type to decompose
                    -> ([ExpPatType] -> ExpRhoType -> TcM a)  -- Callback
                    -> TcM (HsWrapper, a)   -- Returns wrapper + result
```

**Key Invariant**: If `matchExpectedFunTys n ty = (wrap, _)` then:
- `wrap :: (t1 -> ... -> tn -> ty_r) ~~> ty`
- `[t1, ..., tn]` and `ty_r` are passed to the callback

---

## Two Main Cases

### 1. Infer Mode (Line 809)

When the expected type is `Infer inf_res`:

```haskell
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside
  = do { arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]
       ; res_ty  <- newInferExpType (ir_inst inf_res)
       ; result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty
       ; -- ... fill the inference result and return wrapper
       }
```

**Behavior**:
- Creates fresh meta type variables for arguments
- Creates a fresh inference hole for the result
- Calls the callback with these inferred types
- After callback completes, reads the types and fills the `InferResult`

### 2. Check Mode (Line 824)

When the expected type is `Check top_ty`:

```haskell
matchExpectedFunTys herald ctx arity (Check top_ty) thing_inside
  = check arity [] top_ty
```

The `check` helper recursively processes the type structure.

---

## Check Mode Implementation Details

### The `check` Helper Function (Lines 827-945)

The `check` function has signature:
```haskell
check :: VisArity -> [ExpPatType] -> TcSigmaType -> TcM (HsWrapper, a)
```

**Parameters**:
- `n_req`: Number of visible arguments still needed
- `rev_pat_tys`: Accumulated pattern types (in reverse order)
- `ty`: Current type being analyzed

### Case 1: Skolemise Quantifiers (Lines 835-851)

```haskell
check n_req rev_pat_tys ty
  | isSigmaTy ty                     -- An invisible quantifier at the top
    || (n_req > 0 && isForAllTy ty)  -- A visible quantifier at top, and we need it
  = do { rec { (n_req', wrap_gen, tv_nms, bndrs, given, inner_ty) <- 
                 skolemiseRequired skol_info n_req ty
             ; let sig_skol = SigSkol ctx top_ty (tv_nms `zip` skol_tvs)
                   skol_tvs = binderVars bndrs
             ; skol_info <- mkSkolemInfo sig_skol }
       ; (ev_binds, (wrap_res, result))
            <- checkConstraints (getSkolemInfo skol_info) skol_tvs given $
               check n_req' (reverse (map ExpForAllPatTy bndrs) ++ rev_pat_tys) inner_ty
       ; return (wrap_gen <.> mkWpLet ev_binds <.> wrap_res, result) }
```

**Skolem References**:
- **Line 838**: `skolemiseRequired` - Skolemises visible type binders
- **Line 839**: `SigSkol` with `skol_tvs` - Creates signature skolem info
- **Line 840**: `skol_tvs = binderVars bndrs` - Extracts skolem type variables
- **Line 841**: `mkSkolemInfo` - Creates skolem information for error messages
- **Line 845**: `checkConstraints` with `skol_tvs` - Builds implication constraint

### Case 2: Base Case - No More Args (Lines 857-867)

```haskell
check n_req rev_pat_tys rho_ty
  | n_req == 0
  = do { let pat_tys = reverse rev_pat_tys
       ; ds_flag <- getDeepSubsumptionFlag
       ; case ds_flag of
           Shallow -> do { res <- thing_inside pat_tys (mkCheckExpType rho_ty)
                         ; return (idHsWrapper, res) }
           deep    -> tcSkolemiseGeneral deep ctx top_ty rho_ty $ \_ rho_ty ->
                      thing_inside pat_tys (mkCheckExpType rho_ty) }
```

**Skolem Reference**:
- **Line 864**: `tcSkolemiseGeneral` - Performs deep skolemisation when DeepSubsumption is enabled

### Case 3: Function Types (Lines 871-900)

```haskell
check n_req rev_pat_tys (FunTy { ft_af = af, ft_mult = mult
                               , ft_arg = arg_ty, ft_res = res_ty })
  = assert (isVisibleFunArg af) $
    do { let arg_pos = arity - n_req + 1
       ; (arg_co, arg_ty_frr) <- hasFixedRuntimeRep (FRRExpectedFunTy herald arg_pos) arg_ty
       ; let scaled_arg_ty_frr = Scaled mult arg_ty_frr
       ; (res_wrap, result) <- check (n_req - 1)
                                     (mkCheckExpFunPatTy scaled_arg_ty_frr : rev_pat_tys)
                                     res_ty
       ; -- ... construct wrapper
       }
```

Ensures argument types have Fixed RuntimeRep (FRR) before recursing.

### Case 4: Meta Type Variables (Lines 904-909)

```haskell
check n_req rev_pat_tys ty@(TyVarTy tv)
  | isMetaTyVar tv
  = do { cts <- readMetaTyVar tv
       ; case cts of
           Indirect ty' -> check n_req rev_pat_tys ty'
           Flexi        -> defer n_req rev_pat_tys ty }
```

Handles unfilled meta type variables by deferring to unification.

---

## Skolem References Summary

| Line | Reference | Purpose |
|------|-----------|---------|
| 838 | `skolemiseRequired` | Skolemises visible quantifiers needed for arguments |
| 839 | `SigSkol` with `skol_tvs` | Creates signature skolem information linking original names to skolems |
| 841 | `mkSkolemInfo` | Creates SkolemInfo for error reporting and tracking |
| 845 | `checkConstraints` with `skol_tvs` | Builds implication constraint with skolems as bound variables |
| 864 | `tcSkolemiseGeneral` | Deep skolemisation of result type when DeepSubsumption is on |
| 1198 | `fillInferResultNoInst` | Mention of skolem-escape checking in existential/GADT contexts |
| 1425 | `isDeeplySkolemised` | Assertion that actual type is deeply skolemised before subsumption |

**Key Skolem-Escape Protection** (from `fillInferResultNoInst`, line 1198):
```haskell
-- Existentials: be careful about skolem-escape
```

The function uses `promoteTcType` to prevent skolem escape by:
1. Creating a fresh unification variable at the outer level
2. Emitting an equality constraint
3. Filling the hole with the unification variable

---

## Key Invariants

### Fixed RuntimeRep Invariant (Note [Return arguments with a fixed RuntimeRep])

From lines 731-781:

> It's important that these functions return argument types that have a fixed runtime representation, otherwise we would be in violation of the representation-polymorphism invariants.

The function ensures all returned argument types have syntactically fixed RuntimeRep by:
1. Calling `hasFixedRuntimeRep` on each argument type (line 875)
2. Inserting casts when necessary to ensure FRR
3. Creating wrappers that apply these casts

**Example** (from the Note):
```haskell
type F :: Type -> RuntimeRep
type family F a where { F Int = LiftedRep }

type Dual :: Type -> Type
type family Dual a where
  Dual a = a -> ()

f :: forall (a :: TYPE (F Int)). Dual a
f = \ x -> ()
```

The function handles this by inserting casts around argument types to ensure fixed runtime representation.

---

## Call Sites

### 1. Lambda Expressions - `tcLambdaMatches`

**Location**: `GHC.Tc.Gen.Match`, line 155

```haskell
tcLambdaMatches e lam_variant matches invis_pat_tys res_ty
  =  do { arity <- checkArgCounts matches
        ; (wrapper, r)
            <- matchExpectedFunTys herald GenSigCtxt arity res_ty $ \ pat_tys rhs_ty ->
               tcMatches ctxt tc_body (invis_pat_tys ++ pat_tys) rhs_ty matches
        ; return (wrapper, r) }
```

**Purpose**: Type-check lambda expressions by matching expected function types against the lambda's arity.

### 2. Function Bindings - `tcFunBindMatches`

**Location**: `GHC.Tc.Gen.Match`, line 120

```haskell
tcFunBindMatches ctxt fun_name mult matches invis_pat_tys exp_ty
  = assertPpr (funBindPrecondition matches) (pprMatches matches) $
    do  { arity <- checkArgCounts matches
        ; (wrap_fun, r)
             <- matchExpectedFunTys herald ctxt arity exp_ty $ \ pat_tys rhs_ty ->
                tcScalingUsage mult $
                do { tcMatches mctxt tcBody (invis_pat_tys ++ pat_tys) rhs_ty matches }
        ; return (wrap_fun, r) }
```

**Purpose**: Type-check function definitions by decomposing the expected type to match the function's patterns.

### 3. Operator Sections - Syntax Operations

**Location**: `GHC.Tc.Gen.Expr`, line 986

```haskell
go rho_ty (SynFun arg_shape res_shape)
  = do { ( match_wrapper
         , ( ( (result, arg_ty, res_ty, op_mult)
             , res_wrapper )
           , arg_wrapper1, [], arg_wrapper2 ) )
           <- matchExpectedFunTys herald GenSigCtxt 1 (mkCheckExpType rho_ty) $
              \ [ExpFunPatTy arg_ty] res_ty ->
              do { -- ... type check argument and result
                 }
       ; -- ... construct wrappers
       }
```

**Purpose**: Type-check rebindable syntax operations that expect function types.

**Herald Examples** (from Note [Herald for matchExpectedFunTys], lines 676-713):
- `"The equation(s) for 'f' have"` - Function definitions
- `"The abstraction (\\x.e) takes"` - Lambda expressions
- `"The section (+ x) expects"` - Operator sections
- `"The function 'f' is applied to"` - Function applications

---

## Deep Subsumption Support

The function supports the `DeepSubsumption` language extension:

```haskell
-- Line 857-867
check n_req rev_pat_tys rho_ty
  | n_req == 0
  = do { let pat_tys = reverse rev_pat_tys
       ; ds_flag <- getDeepSubsumptionFlag
       ; case ds_flag of
           Shallow -> do { res <- thing_inside pat_tys (mkCheckExpType rho_ty)
                         ; return (idHsWrapper, res) }
           deep    -> tcSkolemiseGeneral deep ctx top_ty rho_ty $ \_ rho_ty ->
                      thing_inside pat_tys (mkCheckExpType rho_ty) }
```

When DeepSubsumption is enabled, `tcSkolemiseGeneral` performs deep skolemisation on the remaining type, skolemising quantifiers even when they're nested under function arrows.

---

## Related Topics

### Related Functions

1. **`matchActualFunTys`** (line 249): Like `matchExpectedFunTys` but for "actual" types in function application
2. **`matchActualFunTy`** (line 139): Matches a single function type
3. **`tcSkolemiseGeneral`** (line 424): General skolemisation routine
4. **`deeplySkolemise`** (line 2275): Deep skolemisation for DeepSubsumption

### Related Notes in Unify.hs

- **Note [Skolemisation overview]** (line 287): Overview of skolemisation strategy
- **Note [Herald for matchExpectedFunTys]** (line 676): Error message construction
- **Note [matchExpectedFunTys]** (line 715): General overview (lines 717-730)
- **Note [Return arguments with a fixed RuntimeRep]** (line 731): FRR invariant
- **Note [fillInferResult]** (line 1187): Handling inference results with skolem-escape protection

### Related Modules

- `GHC.Tc.Gen.Match`: Lambda and function binding type-checking
- `GHC.Tc.Gen.Expr`: Expression type-checking
- `GHC.Tc.Utils.Concrete`: Fixed RuntimeRep checking (`hasFixedRuntimeRep`)
- `GHC.Tc.Utils.Instantiate`: Skolemisation routines

---

## Open Questions

1. **Interaction with Required Foralls**: How does `matchExpectedFunTys` interact with visible forall quantifiers (e.g., `forall a -> ty`)? The code handles this in line 837, but edge cases may exist.

2. **Performance Impact**: The Note at line 898 mentions this function is "called a lot". Are there opportunities for optimization, especially in the common case where argument types are already FRR?

3. **Error Message Quality**: How well do the error messages guide users when there's an arity mismatch? The herald system (lines 676-713) attempts to provide good messages, but complex cases with nested foralls may be confusing.

---

## Evidence Sources

| Claim | Evidence |
|-------|----------|
| Function signature and behavior | Lines 792-808 |
| Infer mode implementation | Lines 809-822 |
| Check mode implementation | Lines 824-945 |
| Skolem handling in Check mode | Lines 835-851 |
| Deep subsumption support | Lines 857-867 |
| FRR invariant | Lines 731-781, 875 |
| Call sites identified | Grep results from `GHC.Tc.Gen.Match` and `GHC.Tc.Gen.Expr` |
| Skolem references | Lines 838-845, 864, 1198, 1425 |
