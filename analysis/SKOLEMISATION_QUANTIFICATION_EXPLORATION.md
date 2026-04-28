# GHC Skolemisation and Quantification Mechanisms

**Status:** Validated
**Last Updated:** 2026-04-09
**Central Question:** How does GHC handle skolemisation during type checking and generalisation during type inference?

## Summary

This exploration documents GHC's dual mechanism for handling polymorphic types: **skolemisation** (for checking polymorphic types) and **generalisation** (for inferring polymorphic types). Both mechanisms use TcLevel tracking to manage variable scope and escape checking.

Key findings:
- **12 skolemise functions** exist in GHC's type checker, each serving different purposes
- **Skolemisation** pushes TcLevel to N+1, creates SkolemTv TcTyVars at that level
- **Generalisation** (`simplifyInfer`) finds MetaTvs at level N+1 and quantifies them
- **Quantified variables** become SkolemTvs, stored in forall binders of the inferred type
- **Type variable hierarchy**: Var → TyVar/TcTyVar/Id; TcTyVar → TcTyVarDetails (SkolemTv/MetaTv/RuntimeUnk)

## Claims

### Claim 1: GHC has 12 distinct skolemise-related functions

**Statement:** The GHC type checker contains 12 functions related to skolemisation, located primarily in Instantiate.hs and Unify.hs, each serving different scenarios (top-level, deep, invisible binders, etc.).

**Source:** `compiler/GHC/Tc/Utils/Instantiate.hs`, `compiler/GHC/Tc/Utils/Unify.hs`

**Evidence:**
| Function | Location | Purpose |
|----------|----------|---------|
| `topSkolemise` | Instantiate.hs:205 | Skolemises top-level foralls (shallow, en-bloc) |
| `deeplySkolemise` | Unify.hs:2281 | Skolemises nested foralls under arrows (deep) |
| `tcSkolemiseGeneral` | Unify.hs:435 | High-level wrapper; calls topSkolemise or deeplySkolemise + checkConstraints |
| `tcSkolemise` | Unify.hs:495 | Main entry point |
| `tcSkolemiseCompleteSig` | Unify.hs:470 | User-written complete type signatures |
| `tcSkolemiseExpectedType` | Unify.hs:489 | Expected types from context |
| `tcSkolemiseInvisibleBndrs` | Instantiate.hs:639 | Invisible binders only |
| `skolemiseRequired` | Instantiate.hs:237 | Required binders + trailing invisibles |
| `checkConstraints` | Unify.hs:508 | Builds implication after skolemisation |
| `tcInstSkolTyVarBndrsX` | Instantiate.hs:594 | Creates SkolemTv at pushed level |
| `skolemiseQuantifiedTyVar` | TcMType.hs:1761 | Zonking: meta → skolem |
| `skolemiseUnboundMetaTyVar` | TcMType.hs:1906 | Zonking: unbound meta → TyVar |

**Discovered:** 2026-04-09

---

### Claim 2: Skolemisation pushes TcLevel and creates SkolemTv at that level

**Statement:** The skolemisation process increments the TcLevel (to N+1) and creates fresh SkolemTv TcTyVars at that level. These skolems are immutable (rigid) and cannot be unified with.

**Source:** `compiler/GHC/Tc/Utils/Instantiate.hs:576`

**Evidence:**
```haskell
-- From tcInstSkolTyVarBndrsX
details = SkolemTv skol_info (pushTcLevel tc_lvl) False
```

**Source:** `compiler/GHC/Tc/Utils/Unify.hs:2281-2320` (deeplySkolemise)

**Evidence:**
```haskell
deeplySkolemise :: TcSigmaType -> TcM (HsWrapper, [TcTyVar], [EvVar], TcRhoType)
-- ^ Skolemise the top foralls, and continue to skolemise under function arrows
deeplySkolemise ty
  = do { (wrap1, tvs1, given1, rho1) <- topSkolemise ty
       ; (wrap2, tvs2, given2, rho2) <- go rho1
       ; return (wrap1 <.> wrap2, tvs1 ++ tvs2, given1 ++ given2, rho2) }
```

**Discovered:** 2026-04-09

---

### Claim 3: Generalisation (simplifyInfer) uses the same level discipline

**Statement:** Type inference generalisation (`tcPolyInfer` → `simplifyInfer`) uses the same TcLevel mechanism: it pushes to level N+1, collects constraints, then finds and quantifies over MetaTvs at that level.

**Source:** `compiler/GHC/Tc/Gen/Bind.hs:721-724`

**Evidence:**
```haskell
tcPolyInfer ...
  = do { (tclvl, wanted, (binds', mono_infos))
             <- pushLevelAndCaptureConstraints  $
                tcMonoBinds rec_tc tc_sig_fn LetLclBndr bind_list
       ; ...
       ; ((qtvs, givens, ev_binds, insoluble), residual)
             <- captureConstraints $
                simplifyInfer top_lvl tclvl infer_mode sigs name_taus wanted
```

**Source:** `compiler/GHC/Tc/Solver.hs:932-942`

**Evidence:**
```haskell
simplifyInfer :: TopLevelFlag
              -> TcLevel               -- ^ rhs_tclvl: level N+1 where constraints generated
              -> InferMode
              -> [TcIdSigInst]
              -> [(Name, TcTauType)]   -- ^ Variables to be generalised
              -> WantedConstraints
              -> TcM ([TcTyVar], [EvVar], TcEvBinds, Bool)
```

**Discovered:** 2026-04-09

---

### Claim 4: outerLevelTyVars filters variables from outer levels (≤N)

**Statement:** The `outerLevelTyVars` function keeps only variables where `rhs_tclvl > var_level`, meaning variables from outer levels (≤N) are identified as "outer" and excluded from quantification.

**Source:** `compiler/GHC/Tc/Solver.hs:1609-1619`

**Evidence:**
```haskell
outerLevelTyVars :: TcLevel -> TcTyVarSet -> TcTyVarSet
-- Find just the tyvars that are bound outside rhs_tc_lvl
outerLevelTyVars rhs_tclvl tvs
  = filterVarSet is_outer_tv tvs
  where
    is_outer_tv tcv
     | isTcTyVar tcv
     = rhs_tclvl `strictlyDeeperThan` tcTyVarLevel tcv
     | otherwise
     = False
```

**Discovered:** 2026-04-09

---

### Claim 5: quantifyTyVars turns MetaTvs into SkolemTvs

**Statement:** The `quantifyTyVars` function converts remaining MetaTvs (at level N+1) into SkolemTvs, which become the quantified type variables bound by forall in the inferred type.

**Source:** `compiler/GHC/Tc/Utils/TcMType.hs:1728-1729`

**Evidence:**
```haskell
zonk_quant tkv
  | otherwise
  = Just <$> skolemiseQuantifiedTyVar skol_info tkv
```

**Source:** `compiler/GHC/Tc/Utils/TcMType.hs:1761-1776`

**Evidence:**
```haskell
skolemiseQuantifiedTyVar skol_info tv
  = case tcTyVarDetails tv of
      MetaTv {} -> skolemiseUnboundMetaTyVar skol_info tv
      SkolemTv _ lvl _ -> do
        { kind <- zonkTcType (tyVarKind tv)
        ; let details = SkolemTv skol_info lvl False
              name = tyVarName tv
        ; return (mkTcTyVar name kind details) }
```

**Source:** `compiler/GHC/Tc/Utils/TcMType.hs:1906-1926`

**Evidence:**
```haskell
skolemiseUnboundMetaTyVar skol_info tv
  = ...
    do  { ...
        ; let details    = SkolemTv skol_info (pushTcLevel tc_lvl) False
              final_tv   = mkTcTyVar final_name kind details
        ; traceZonk "Skolemising" (ppr tv <+> text ":=" <+> ppr final_tv)
        ; writeMetaTyVar tv (mkTyVarTy final_tv)
        ; return final_tv }
```

**Discovered:** 2026-04-09

---

### Claim 6: The SkolemTvs are used in forall binders of the inferred type

**Statement:** The qtvs returned by `quantifyTyVars` are directly used to construct the forall type via `mkInfForAllTys` or `mkInvisForAllTys`.

**Source:** `compiler/GHC/Tc/Gen/Bind.hs:970`

**Evidence:**
```haskell
; let inferred_poly_ty = mkInvisForAllTys binders (mkPhiTy theta' mono_ty')
```

**Source:** `compiler/GHC/Tc/Utils/TcType.hs:1427-1437`

**Evidence:**
```haskell
mkInfSigmaTy :: HasDebugCallStack => [TyCoVar] -> [PredType] -> Type -> Type
mkInfSigmaTy tyvars theta ty = mkSigmaTy (mkForAllTyBinders Inferred tyvars) theta ty

mkSigmaTy :: HasDebugCallStack => [ForAllTyBinder] -> [PredType] -> Type -> Type
mkSigmaTy bndrs theta tau = mkForAllTys bndrs (mkPhiTy theta tau)
```

**Discovered:** 2026-04-09

---

### Claim 7: GHC Var type has three main constructors

**Statement:** The `Var` type has three constructors: `TyVar` (for Core IR), `TcTyVar` (for type checking), and `Id` (for term-level identifiers).

**Source:** `compiler/GHC/Types/Var.hs:256-284`

**Evidence:**
```haskell
data Var
  = TyVar {  -- Type and kind variables (post-typecheck)
        varName    :: !Name,
        realUnique :: {-# UNPACK #-} !Unique,
        varType    :: Kind
 }
  | TcTyVar {                           -- Used only during type inference
        varName        :: !Name,
        realUnique     :: {-# UNPACK #-} !Unique,
        varType        :: Kind,
        tc_tv_details  :: TcTyVarDetails
  }
  | Id {
        varName    :: !Name,
        realUnique :: {-# UNPACK #-} !Unique,
        varType    :: Type,
        varMult    :: Mult,
        idScope    :: IdScope,
        id_details :: IdDetails,
        id_info    :: IdInfo }
```

**Discovered:** 2026-04-09

---

### Claim 8: TcTyVarDetails contains SkolemTv, MetaTv, or RuntimeUnk

**Statement:** `TcTyVarDetails` is NOT a constructor of Var, but rather a field within `TcTyVar`. It has three constructors: `SkolemTv` (immutable/rigid), `MetaTv` (mutable unification var), and `RuntimeUnk` (GHCi interactive).

**Source:** `compiler/GHC/Tc/Utils/TcType.hs:634-651`

**Evidence:**
```haskell
data TcTyVarDetails
  = SkolemTv      -- A skolem (immutable, rigid)
       SkolemInfo -- Provenance info for error messages
       TcLevel    -- Level of the implication that binds it
       Bool       -- Overlappable?

  | RuntimeUnk    -- GHCi interactive context

  | MetaTv { mtv_info  :: MetaInfo      -- What kind of meta-var
           , mtv_ref   :: IORef MetaDetails  -- Mutable!
           , mtv_tclvl :: TcLevel }
```

**Discovered:** 2026-04-09

---

### Claim 9: The dual pattern: skolemisation vs generalisation

**Statement:** Skolemisation and generalisation use the same level discipline but in opposite directions:
- Skolemisation: ∀a. → create SkolemTvs at level N+1
- Generalisation: find MetaTvs at level N+1 → ∀a.

**Source:** `compiler/GHC/Tc/Utils/TcType.hs:591-610` (Note [TyVars and TcTyVars during type checking])

**Evidence:**
```
Skolemisation Pattern:
  pushTcLevel to N+1
  → create fresh SkolemTvs at N+1
  → check at this level
  → skolems are rigid (cannot unify)

Generalisation Pattern:
  pushLevelAndCaptureConstraints to N+1
  → create fresh MetaTvs at N+1 during checking
  → filter outer_tvs (level ≤N) via outerLevelTyVars
  → quantifyTyVars turns remaining metas → SkolemTvs
  → create forall type with these skolems
```

**Discovered:** 2026-04-09

## Open Questions

- [ ] How does deeplySkolemise handle nested foralls under function arrows?
- [ ] What is the exact relationship between TcLevel and implication constraints?
- [ ] How do super skolems (overlappable) work in instance lookup?

## Related Topics

- GHC_TYPE_HIERARCHY.md - Detailed type hierarchy documentation
- SKOLEMISE_TRACE.md - Step-by-step trace of deeplySkolemise
- TYPE_INFERENCE.md - Comprehensive GHC type inference overview
- HIGHERRANK_POLY.md - Higher-rank polymorphism mechanisms

## Files Referenced

- `compiler/GHC/Tc/Utils/Instantiate.hs`
- `compiler/GHC/Tc/Utils/Unify.hs`
- `compiler/GHC/Tc/Utils/TcMType.hs`
- `compiler/GHC/Tc/Utils/TcType.hs`
- `compiler/GHC/Tc/Solver.hs`
- `compiler/GHC/Tc/Gen/Bind.hs`
- `compiler/GHC/Types/Var.hs`
