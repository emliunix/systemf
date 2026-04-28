# Pattern Mode Propagation (Check vs Infer) — Exploration

**Status:** Validated
**Last Updated:** 2026-04-12
**Central Question:** In upstream GHC pattern typechecking, how do `Check` vs `Infer` (`ExpType`) modes behave for `VarPat`, `SigPat`, and `ConPat`, and how do they propagate to subpatterns (esp. constructor arguments)?

## Scope

**IN**
- Upstream GHC evidence for pattern mode flow in:
  - `VarPat` binder typing
  - `SigPat` (pattern signatures)
  - `ConPat` (constructor patterns), especially how value-argument patterns are checked
- Helpers that can affect mode/type behavior: `tcSubTypePat`, `fillInferResultNoInst`, level/FRR invariants.

**OUT**
- Coverage checking / desugaring (HsToCore) except where it directly constrains `ExpType` behavior.
- Non-core pattern forms (view patterns, overloaded list patterns, etc.) except if they reuse the same primitives.

## Claims

### Claim 1: Value-argument subpatterns of a `ConPat` are always typechecked in `Check` mode.

**Statement:** In constructor patterns, once the constructor argument types are determined, each value-argument subpattern is checked with `mkCheckExpType arg_ty`; i.e. constructor subpatterns do not receive `Infer` expected types.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1612-1650, 1796-1799`

**Evidence:**

```haskell
-- tcConValArgs dispatches tcConArg across value arg patterns
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1612-1622
; (arg_pats', res) <- tcMultiple tcConArg penv pats_w_tys thing_inside

-- tcConArg forces mkCheckExpType for each arg pattern
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1796-1799
tcConArg penv (arg_pat, Scaled arg_mult arg_ty)
  = tc_lpat (Scaled arg_mult (mkCheckExpType arg_ty)) penv arg_pat
```

**Status:** Validated

---

### Claim 2: `SigPat` forces checking of the inner pattern against the signature type, and uses `tcSubTypePat` to relate the outer expected type to the signature type.

**Statement:** When typechecking a pattern signature `(pat :: sig_ty)`, GHC computes a wrapper `wrap` by calling `tcPatSig … exp_pat_ty`, then checks the inner `pat` in `Check inner_ty` (where `inner_ty` is the signature type used “inside” the signature).

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:758-771, 1008-1044`

**Evidence:**

```haskell
-- SigPat case: compute (inner_ty, ..., wrap), then check inner pat with mkCheckExpType inner_ty
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:758-771
SigPat _ pat sig_ty -> do
  { (inner_ty, tv_binds, wcs, wrap) <- tcPatSig (inPatBind penv) sig_ty exp_pat_ty
  ; (pat', res) <- ... tc_lpat (Scaled w_pat $ mkCheckExpType inner_ty) penv pat thing_inside
  ; ...
  ; return (mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty, res) }

-- tcPatSig calls tcSubTypePat to relate res_ty to sig_ty
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1008-1044
wrap <- ... tcSubTypePat PatSigOrigin PatSigCtxt res_ty sig_ty
```

**Status:** Validated

---

### Claim 3: When `tcSubTypePat` is given an `Infer` expected type, it fills the infer-hole with the *expected* sigma type (no instantiation) and returns a cast wrapper.

**Statement:** In patterns, `tcSubTypePat _ _ (Infer inf_res) ty_expected` calls `fillInferResultNoInst ty_expected inf_res` (commented “In patterns we do not instantiate”), and returns `mkWpCastN (mkSymCo co)`.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1434-1446`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1434-1446

tcSubTypePat _ _ (Infer inf_res) ty_expected
  = do { co <- fillInferResultNoInst ty_expected inf_res
               -- In patterns we do not instantatiate
       ; return (mkWpCastN (mkSymCo co)) }
```

**Status:** Validated

---

### Claim 4: In the `Check` case, `tcSubTypePat` delegates to the general subsumption worker but uses `unifyTypeET` (swapped polarity) for unification.

**Statement:** `tcSubTypePat inst_orig ctxt (Check ty_actual) ty_expected` calls `tc_sub_type unifyTypeET … ty_actual ty_expected`; `unifyTypeET` is defined as `unifyTypeAndEmit` with `uo_actual`/`uo_expected` swapped “for error messages”, and is used when typechecking patterns.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1437-1442, 2456-2465`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1437-1442

tcSubTypePat inst_orig ctxt (Check ty_actual) ty_expected
  = tc_sub_type unifyTypeET inst_orig ctxt ty_actual ty_expected

-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:2456-2467

unifyTypeET :: TcTauType -> TcTauType -> TcM CoercionN
-- Like unifyType, but swap expected and actual in error messages
-- This is used when typechecking patterns
unifyTypeET ty1 ty2
  = unifyTypeAndEmit TypeLevel origin ty1 ty2
  where
    origin = TypeEqOrigin { uo_actual   = ty2
                          , uo_expected = ty1
                          , ... }
```

**Status:** Validated

---

### Claim 5: `fillInferResultNoInst` enforces a level invariant when filling/joining an `InferResult` hole.

**Statement:** When filling an `InferResult` hole, `fillInferResultNoInst` promotes the type to the hole’s `ir_lvl` (via `promoteTcType res_lvl act_res_ty`) before writing it. When joining against an already-filled hole, it unifies `act_res_ty` with the stored type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1122-1169`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1122-1169

case mb_exp_res_ty of
  Just exp_res_ty -> ... unifyType Nothing act_res_ty exp_res_ty
  Nothing -> do { (prom_co, act_res_ty) <- promoteTcType res_lvl act_res_ty
                ; ...
                ; writeTcRef ref (Just act_res_ty)
                ; return final_co }
```

**Status:** Validated

---

### Claim 6: In Let-pattern bindings, the `Infer` binder path asserts it cannot happen under a constructor that “bumped the level”, because constructor args are checked.

**Statement:** In `tcPatBndr`’s `LetPat`/no-signature case, the `Infer` branch asserts `bind_lvl sameDepthAs ir_lvl infer_res` and comments that if we were under a constructor that bumped the level “we'd be in checking mode (see tcConArg)”.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:331-342`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:331-342
Infer infer_res -> assert (bind_lvl `sameDepthAs` ir_lvl infer_res) $
  -- If we were under a constructor that bumped the
  -- level, we'd be in checking mode (see tcConArg)
  do { bndr_ty <- inferResultToType infer_res
     ; return (mkNomReflCo bndr_ty, bndr_ty) }
```

**Status:** Validated

---

### Claim 7: `expTypeToType` erases `Check`/`Infer` by producing a `TcType`; `Infer` is forced to a monotype.

**Statement:** `expTypeToType` returns the underlying type for `Check`, and for `Infer` it calls `inferResultToType`, which ensures the result is a monotype (and allocates a fresh meta-tyvar if the hole is empty).

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/TcMType.hs:472-475, 477-498, 502-511`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/TcMType.hs:472-475
expTypeToType :: ExpType -> TcM TcType
expTypeToType (Check ty)      = return ty
expTypeToType (Infer inf_res) = inferResultToType inf_res

-- upstream/ghc/compiler/GHC/Tc/Utils/TcMType.hs:477-498
inferResultToType (IR { ... , ir_ref = ref, ... })
  = do { mb_inferred_ty <- readTcRef ref
       ; tau <- case mb_inferred_ty of
            Just ty -> do { ensureMonoType ty
                          ; return ty }
            Nothing -> do { tau <- new_meta
                          ; writeMutVar ref (Just tau)
                          ; return tau }
       ; ...
       ; return tau }

{- upstream/ghc/compiler/GHC/Tc/Utils/TcMType.hs:502-511
Note [inferResultToType]
expTypeToType and inferResultType convert an InferResult to a monotype.
It must be a monotype because if the InferResult isn't already filled in,
we fill it in with a unification variable (hence monotype).
-}
```

**Status:** Validated

---

### Claim 8: `fillInferResultNoInst` is the primitive used to fill/join an `InferResult` hole, enforcing level and FRR invariants.

**Statement:** `fillInferResultNoInst` is the core operation behind “hole filling/joining” for `Infer` expected types; it unifies on re-fill, and on first fill it promotes the type to the hole’s level and (optionally) enforces a fixed RuntimeRep.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1122-1176`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1122-1169
case mb_exp_res_ty of
  Just exp_res_ty -> ... unifyType Nothing act_res_ty exp_res_ty
  Nothing -> do { (prom_co, act_res_ty) <- promoteTcType res_lvl act_res_ty
                ; (frr_co, act_res_ty) <- case mb_frr of ...
                ; ...
                ; writeTcRef ref (Just act_res_ty)
                ; return final_co }
```

**Status:** Validated

---

### Claim 9: `matchExpectedTyConApp` matches a `TyConApp` directly, or if given a meta-tyvar it allocates fresh argument metas and unifies a template `T args` with the original type.

**Statement:** `matchExpectedTyConApp tc orig_ty` returns `(Refl, args)` when `orig_ty` is already `TyConApp tc args`; if `orig_ty` is a meta-tyvar, it follows `Indirect` pointers, but on `Flexi` (or other non-matching types) it creates fresh meta tyvars for `tyConTyVars tc`, builds `tc_template = T args`, unifies `tc_template ~ orig_ty`, and returns `(co, args)`.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1026-1068`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1026-1068
go ty@(TyConApp tycon args)
  | tc == tycon = return (mkNomReflCo ty, args)

go (TyVarTy tv)
  | isMetaTyVar tv
  = do { cts <- readMetaTyVar tv
       ; case cts of
           Indirect ty -> go ty
           Flexi       -> defer }

defer
  = do { (_, arg_tvs) <- newMetaTyVars (tyConTyVars tc)
       ; let args = mkTyVarTys arg_tvs
             tc_template = mkTyConApp tc args
       ; co <- unifyType Nothing tc_template orig_ty
       ; return (co, args) }
```

    **Status:** Validated

---

### Claim 10: `topInstantiate` instantiates only *outer invisible* foralls and constraints, returning a wrapper `inner_ty ~~> sigma`.

**Statement:** `topInstantiate orig sigma` splits off invisible foralls and `theta =>` constraints at the top of `sigma`, instantiates those foralls with fresh metas, emits evidence for constraints, and recursively repeats until no top invisible forall or `=>` remains; it returns a wrapper composing these instantiations.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Instantiate.hs:282-318`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Utils/Instantiate.hs:282-289
topInstantiate :: CtOrigin -> TcSigmaType -> TcM (HsWrapper, TcRhoType)
-- Instantiate outer invisible binders ...
-- then  wrap :: inner_ty ~~> ty

-- upstream/ghc/compiler/GHC/Tc/Utils/Instantiate.hs:287-318
topInstantiate orig sigma
  | (tvs,   phi_ty)  <- tcSplitSomeForAllTyVars isInvisibleForAllTyFlag sigma
  , (theta, body_ty) <- tcSplitPhiTy phi_ty
  , not (null tvs && null theta)
  = do { (subst, inst_tvs) <- newMetaTyVarsX empty_subst tvs
       ; let inst_theta = substTheta subst theta
             inst_body  = substTy subst body_ty
       ; wrap1 <- instCall orig (mkTyVarTys inst_tvs) inst_theta
       ; (wrap2, inner_body) <- topInstantiate orig inst_body
       ; return (wrap2 <.> wrap1, inner_body) }
  | otherwise
  = return (idHsWrapper, sigma)
```

**Status:** Validated

---

### Claim 11: `matchExpectedPatTy` is a standard helper to (1) force the `ExpType` to a `TcType`, (2) `topInstantiate` it, then (3) run a matcher over the resulting rho-type, returning a wrapper.

**Statement:** `matchExpectedPatTy inner_match penv pat_ty` calls `expTypeToType` on `pat_ty`, then `topInstantiate` to obtain a rho-type, runs `inner_match` on that rho-type, and returns a wrapper that composes the instantiation wrapper with a cast derived from the coercion returned by `inner_match`.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1396-1403`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1396-1403
matchExpectedPatTy inner_match (PE { pe_orig = orig }) pat_ty
  = do { pat_ty <- expTypeToType pat_ty
       ; (wrap, pat_rho) <- topInstantiate orig pat_ty
       ; (co, res) <- inner_match pat_rho
       ; return (mkWpCastN (mkSymCo co) <.> wrap, res) }
```

**Status:** Validated

---

### Claim 12: `matchExpectedConTy` uses `expTypeToType` + `topInstantiate` and then either `matchExpectedTyConApp` (normal case) or a data-family-specific unification/coercion path.

**Statement:** `matchExpectedConTy penv data_tc exp_pat_ty` first forces the pattern type via `expTypeToType` and `topInstantiate`. In the non-family case it calls `matchExpectedTyConApp data_tc pat_rho` and returns a wrapper `mkWpCastN (mkSymCo coi) <.> wrap`. In the data-family case it instead unifies against the family TyCon and then builds a representational coercion into the representation TyCon.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1418-1456`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1418-1424 (both branches)
matchExpectedConTy (PE { pe_orig = orig }) data_tc exp_pat_ty
  = do { pat_ty <- expTypeToType (scaledThing exp_pat_ty)
       ; (wrap, pat_rho) <- topInstantiate orig pat_ty
       ; ... }

-- upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:1449-1456 (non-family case)
| otherwise
  = do { pat_ty <- expTypeToType (scaledThing exp_pat_ty)
       ; (wrap, pat_rho) <- topInstantiate orig pat_ty
       ; (coi, tys) <- matchExpectedTyConApp data_tc pat_rho
       ; return (mkWpCastN (mkSymCo coi) <.> wrap, tys) }
```

**Status:** Validated

---

### Claim 13: `mkHsWrapPat` only produces a `CoPat` when the wrapper is non-identity.

**Statement:** `mkHsWrapPat w pat ty` returns `pat` unchanged when `w` is `idHsWrapper`; otherwise it constructs `CoPat w pat ty`.

**Source:** `upstream/ghc/compiler/GHC/Hs/Utils.hs:811-813`

**Evidence:**

```haskell
-- upstream/ghc/compiler/GHC/Hs/Utils.hs:811-813
mkHsWrapPat :: HsWrapper -> Pat GhcTc -> Type -> Pat GhcTc
mkHsWrapPat co_fn p ty | isIdHsWrapper co_fn = p
                       | otherwise           = XPat $ CoPat co_fn p ty
```

**Status:** Validated

## Open Questions
- [ ] For `VarPat` (non-LetPat), which helper forces `Infer` to a `TcType`? (Expect: `expTypeToType` via `tcPatBndr`.)
- [ ] Are there any pattern forms that *do* pass `Infer` to a subpattern (other than via the shared “overall pattern” ExpType)?

## Related
- `analysis/PATTERN_TC_FACTS.md` (existing consolidated facts; different format)
