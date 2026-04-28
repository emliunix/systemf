# Typechecker Special Cases Exploration

**Status:** In Progress
**Last Updated:** 2026-04-22
**Central Question:** What special cases does GHC's typechecker handle for non-recursive bindings, and why?
**Topics:** tcMonoBinds, non-recursive bindings, higher-rank types, impredicative types

## Planning

**Scopes:**
- IN: tcMonoBinds special cases (non-recursive FunBind, non-recursive PatBind), inference vs checking modes, higher-rank and impredicative type inference
- OUT: Generalisation (AbsBinds), evidence generation, Core desugaring, recursive binding groups

**Entry Points:**
- `compiler/GHC/Tc/Gen/Bind.hs:1296-1325` — Special case 1: non-recursive function bindings
- `compiler/GHC/Tc/Gen/Bind.hs:1327-1355` — Special case 2: non-recursive pattern bindings
- `compiler/GHC/Tc/Gen/Bind.hs:1378-1399` — General case
- `compiler/GHC/Tc/Gen/Bind.hs:1401-1460` — Notes explaining the special cases
- `compiler/GHC/Tc/Gen/Bind.hs:1484-1511` — tcLhs FunBind (general case LHS processing)
- `compiler/GHC/Tc/Gen/Bind.hs:1513-1537` — tcLhs PatBind (general case LHS processing)
- `compiler/GHC/Tc/Utils/TcMType.hs:533-537` — runInferRhoFRR / runInferSigmaFRR
- `compiler/GHC/Tc/Utils/Unify.hs:287-406` — Note [Skolemisation overview]

## Facts

### Fact 1: Special Case 1 — Non-Recursive Function Bindings (Higher-Rank Inference)
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1296-1325`
**Comment:** When a single non-recursive FunBind has no type signature, GHC infers the RHS type first (using runInferRhoFRR with IIF_DeepRho), then creates the monomorphic binder from that inferred type. This enables higher-rank type inference.
```haskell
tcMonoBinds is_rec sig_fn no_gen
           [ L b_loc (FunBind { fun_id = L nm_loc name
                              , fun_matches = matches })]
                             -- Single function binding,
  | NonRecursive <- is_rec   -- ...binder isn't mentioned in RHS
  , Nothing <- sig_fn name   -- ...with no type signature
  = setSrcSpanA b_loc    $
    do  { mult <- newMultiplicityVar

        ; ((co_fn, matches'), rhs_ty')
            <- runInferRhoFRR (FRRBinder name) $ \ exp_ty ->
                 -- runInferRhoFRR: the type of a let-binder must have
                 -- a fixed runtime rep. See #23176
               tcExtendBinderStack [TcIdBndr_ExpType name exp_ty NotTopLevel] $
               tcFunBindMatches (InfSigCtxt name) name mult matches [] exp_ty
        ; mono_id <- newLetBndr no_gen name mult rhs_ty'

        ; return (singleton $ L b_loc $
                     FunBind { fun_id      = L nm_loc mono_id,
                               fun_matches = matches',
                               fun_ext     = (co_fn, []) },
                  [MBI { mbi_poly_name = name
                       , mbi_sig       = Nothing
                       , mbi_mono_id   = mono_id
                       , mbi_mono_mult = mult }]) }
```

### Fact 2: Special Case 2 — Non-Recursive Pattern Bindings (Impredicative Inference)
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1327-1374`
**Comment:** When a non-recursive PatBind has no signatures for any binders, GHC infers the RHS type first (runInferRhoFRR), then checks the pattern against that inferred type (via tcLetPat with mkCheckExpType). This enables impredicative type inference for pattern-bound variables.
```haskell
tcMonoBinds is_rec sig_fn no_gen
           [L b_loc (PatBind { pat_lhs = pat, pat_rhs = grhss, pat_mult = mult_ann })]
  | NonRecursive <- is_rec   -- ...binder isn't mentioned in RHS
  , all (isNothing . sig_fn) bndrs
  = addErrCtxt (PatMonoBindsCtxt pat grhss) $
    do { mult <- tcMultAnnOnPatBind mult_ann

       ; (grhss', pat_ty) <- runInferRhoFRR FRRPatBind $ \ exp_ty ->
                          tcGRHSsPat mult grhss exp_ty

       ; let exp_pat_ty :: Scaled ExpSigmaTypeFRR
             exp_pat_ty = Scaled mult (mkCheckExpType pat_ty)
       ; (_, (pat', mbis)) <- tcCollectingUsage $
                         tcLetPat (const Nothing) no_gen pat exp_pat_ty $ do
                           tcEmitBindingUsage bottomUE
                           mapM lookupMBI bndrs
        ...
       ; return ( singleton $ L b_loc $
                     PatBind { pat_lhs = pat', pat_rhs = grhss'
                             , pat_ext = (pat_ty, ([],[]))
                             , pat_mult = setTcMultAnn mult mult_ann }
                , mbis ) }
  where
    bndrs = collectPatBinders CollNoDictBinders pat
```

### Fact 3: General Case — LHS-First Approach with Fresh Unification Variables
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1378-1399` and `tcLhs` (lines 1484-1511)
**Comment:** In the general case, tcMonoBinds first processes all LHSes (tcLhs), creating monomorphic Ids with fresh unification variables for binders without signatures. Then it extends the environment with these mono_ids and typechecks the RHSs. This is necessary for recursive bindings but limits inference capabilities.
```haskell
-- GENERAL CASE
tcMonoBinds _ sig_fn no_gen binds
  = do  { tc_binds <- mapM (wrapLocMA (tcLhs sig_fn no_gen)) binds

        -- Bring the monomorphic Ids, into scope for the RHSs
        ; let mono_infos = getMonoBindInfo tc_binds
              rhs_id_env = [ (name, mono_id)
                           | MBI { mbi_poly_name = name
                                 , mbi_sig       = mb_sig
                                 , mbi_mono_id   = mono_id } <- mono_infos
                           , case mb_sig of
                               Just sig -> isPartialSig sig
                               Nothing  -> True ]

        ; binds' <- tcExtendRecIds rhs_id_env $
                    mapM (wrapLocMA tcRhs) tc_binds

        ; return (binds', mono_infos) }
```

In the FunBind tcLhs case without a signature:
```haskell
  | otherwise  -- No type signature
  = do { mono_ty <- newOpenFlexiTyVarTy    -- Fresh unification variable!
       ; mult <- newMultiplicityVar
       ; mono_id <- newLetBndr no_gen name mult mono_ty
       ; ... }
```

### Fact 4: Why the General Case Cannot Handle Higher-Rank or Impredicative Types
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1401-1460` (Notes)
**Comment:** The general case creates a monomorphic Id with a unification variable before seeing the RHS. When the RHS has a higher-rank type (e.g., `\(x::forall a. a->a) -> body`), unifying the mono_ty with the inferred RHS type fails because a unification variable cannot be unified with a polytype. The special case avoids this by inferring first, then creating the binder.

From Note [Special case for non-recursive function bindings]:
```
In the special case of
* A non-recursive FunBind
* With no type signature
we infer the type of the right hand side first (it may have a
higher-rank type) and *then* make the monomorphic Id for the LHS e.g.
   f = \(x::forall a. a->a) -> <body>
We want to infer a higher-rank type for f
```

From Note [Special case for non-recursive pattern bindings]:
```
In the special case of
* A pattern binding
* With no type signature for any of the binders
we can /infer/ the type of the RHS, and /check/ the pattern
against that type.  For example (#18323)

  ids :: [forall a. a -> a]
  combine :: (forall a . [a] -> a) -> [forall a. a -> a]
          -> ((forall a . [a] -> a), [forall a. a -> a])

  (x,y) = combine head ids

with -XImpredicativeTypes we can infer a good type for
(combine head ids), and use that to tell us the polymorphic
types of x and y.
```

### Fact 5: The Signature Restriction — Why "No Signatures" is Required
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1439-1458`
**Comment:** If any binder has a signature, the special case cannot apply because signatures must be pushed inward (checking mode). Mixed signatures (some binders with, some without) are fundamentally problematic — you cannot simultaneously check against known signatures and infer polymorphic types for others.

From the Note:
```
Why do we require no type signatures on /any/ of the binders?
Consider
   x :: forall a. a->a
   y :: forall a. a->a
   (x,y) = (id,id)

Here we should /check/ the RHS with expected type
  (forall a. a->a, forall a. a->a).

If we have no signatures, we can the approach of this Note
to /infer/ the type of the RHS.

But what if we have some signatures, but not all? Say this:
  p :: forall a. a->a
  (p,q) = (id,  (\(x::forall b. b->b). x True))

Here we want to push p's signature inwards, i.e. /checking/, to
correctly elaborate 'id'. But we want to /infer/ q's higher rank
type.  There seems to be no way to do this.  So currently we only
switch to inference when we have no signature for any of the binders.
```

### Fact 6: runInferRhoFRR vs runInferSigmaFRR — Instantiation Matters
**Source:** `compiler/GHC/Tc/Utils/TcMType.hs:519-537` and `compiler/GHC/Tc/Utils/TcType.hs:434-449`
**Comment:** The special cases use runInferRhoFRR (IIF_DeepRho) which deeply instantiates the inferred type, while the general PatBind LHS uses runInferSigmaFRR (IIF_Sigma) which returns an uninstantiated sigma type. This difference is crucial: patterns need sigma types to preserve polymorphism during pattern matching, while expression inference needs rho types for unification.
```haskell
-- Special case 1 (FunBind): uses runInferRhoFRR
runInferRhoFRR :: FixedRuntimeRepContext -> (ExpRhoTypeFRR -> TcM a) -> TcM (a, TcRhoTypeFRR)
runInferRhoFRR frr_orig = runInfer IIF_DeepRho (IFRR_Check frr_orig)

-- Special case 2 (PatBind): also uses runInferRhoFRR for RHS
runInferRhoFRR FRRPatBind $ \ exp_ty -> tcGRHSsPat mult grhss exp_ty

-- General case PatBind LHS: uses runInferSigmaFRR
tcLhs sig_fn no_gen (PatBind { ... })
  = ... runInferSigmaFRR FRRPatBind $ \ exp_ty -> tcLetPat ...
```

From `compiler/GHC/Tc/Utils/TcType.hs:434-449`:
```haskell
data InferInstFlag
  = IIF_Sigma       -- Trying to infer a SigmaType
                    -- Don't instantiate at all, regardless of DeepSubsumption
                    -- Typically used when inferring the type of a pattern

  | IIF_DeepRho     -- Trying to infer a possibly-deep RhoType (depending on DeepSubsumption)
                    -- If DeepSubsumption is off, same as IIF_ShallowRho
                    -- If DeepSubsumption is on, instantiate deeply before filling the hole
```

## Claims

### Claim 1: The Special Cases Exist to Break the Chicken-and-Egg Problem of Inference vs Checking
**Analysis:** Facts 1, 2, 3, and 4.
**Status:** Draft
**Confidence:** High

The general case must create monomorphic binders before typechecking RHSs because recursive bindings need the binder in scope. This forces "checking mode" — the RHS is checked against a known (though initially flexible) type. For non-recursive bindings, the binder is NOT mentioned in the RHS, so GHC can delay binder creation until after RHS inference. This enables "inference mode" for the RHS, which is strictly more powerful for higher-rank and impredicative types.

The key insight: `newOpenFlexiTyVarTy` (general case) creates a unification variable that cannot be unified with a polytype. But `runInferRhoFRR` (special cases) creates an ExpType hole that can be filled with any type, including higher-rank or impredicative ones, after the RHS has been fully typechecked.

### Claim 2: The Two Special Cases Share a Common Structure but Serve Different Type System Features
**Analysis:** Facts 1, 2, and 6.
**Status:** Draft
**Confidence:** High

Both special cases:
1. Check `NonRecursive` — binder not mentioned in RHS
2. Check no signatures — cannot mix inference and checking
3. Use `runInferRhoFRR` to infer the RHS type first
4. Then construct the binder from the inferred type

But they differ in purpose:
- **FunBind special case** enables higher-rank type inference. The function `f = \(x::forall a. a->a) -> body` can be given type `forall a. (forall b. b->b) -> a` because the lambda's type is inferred before f's binder is created.
- **PatBind special case** enables impredicative type inference. Pattern binders like `(x,y) = combine head ids` can bind polymorphic variables because the tuple's type is inferred first, then the pattern is checked against that inferred type.

### Claim 3: For elab3, These Special Cases Are Optional but Important for Feature Parity
**Analysis:** Facts 1, 2, 3, 4, and 5.
**Status:** Draft
**Confidence:** Medium

elab3's recursive binding support (AbsBinds, wrapper generation) handles the general case. The special cases are optimizations that enable specific type system features:

1. **Without the FunBind special case:** Non-recursive functions with higher-rank arguments would require explicit type signatures. This is a usability regression but not unsound.

2. **Without the PatBind special case:** Pattern bindings with impredicative types would fail or require annotations. Again, a usability regression.

3. **Implementation path:** The general case (LHS-first with fresh unification variables) is simpler and sufficient for monomorphic and rank-1 polymorphic bindings. The special cases can be added later as incremental improvements.

However, if elab3 aims to support `-XImpredicativeTypes` or higher-rank polymorphism without explicit signatures on every binding, these special cases become essential. The key implementation decision is whether `tcMonoBinds` should dispatch on `NonRecursive` + `no signatures` before falling through to the general case.

## Notes

- The special cases are guarded by pattern matching on `tcMonoBinds` arguments, with the general case as a catch-all at the end. This is a classic GHC pattern: handle special cases first, fall through to general case.
- Both special cases use `runInferRhoFRR` which ensures Fixed Runtime Representation (FRR). This is a recent GHC addition (#23176) that ensures let-binder types have representable runtime types.
- The PatBind special case has an interesting multiplicity workaround: it emits `bottomUE` (bottom usage environment) to bypass linearity checks in `tcLetPat`, then discards it with `tcCollectingUsage`. This is because pattern-matching and binding have different control flows.
- The general case's `tcLhs` for PatBind uses `runInferSigmaFRR` (not Rho) because patterns need to preserve sigma types for polymorphic binders. This is a subtle but important distinction.

## Open Questions

- [ ] Does elab3 currently support higher-rank types at all? If not, the FunBind special case may be moot initially.
- [ ] Does elab3 support impredicative types? The PatBind special case only matters with `-XImpredicativeTypes`.
- [ ] How does elab3 handle the `RecFlag` vs actual syntactic recursion distinction? GHC's `NonRecursive` means "binder not mentioned in RHS", not just "not marked recursive".
- [ ] Should elab3's `tcMonoBinds` equivalent follow the same pattern-match order (special cases first, general case last)?
- [ ] What is the interaction between these special cases and the generalisation plan (NoGen vs InferGen)? The special cases still create `MonoBindInfo` records that participate in generalisation via `tcPolyInfer`.

## Related Topics

- [ABSBINDS_CORE_TRANSLATION_EXPLORATION.md](ABSBINDS_CORE_TRANSLATION_EXPLORATION.md) — Generalisation and AbsBinds generation
- [MATCHEXPECTEDFUNTYS_EXPLORATION.md](MATCHEXPECTEDFUNTYS_EXPLORATION.md) — Function type decomposition and skolemisation
- [SKOLEMISATION_QUANTIFICATION_EXPLORATION.md](SKOLEMISATION_QUANTIFICATION_EXPLORATION.md) — How polytypes are skolemised during checking
- [PATTERN_TC_ANALYSIS.md](PATTERN_TC_ANALYSIS.md) — Pattern typechecking details
