# Recursive vs Non-Recursive Binding Split Exploration

**Status:** In Progress
**Last Updated:** 2026-04-22
**Central Question:** What is the fundamental architectural difference between recursive and non-recursive bindings that drives GHC's special cases?
**Topics:** recursive bindings, non-recursive bindings, type inference, higher-rank types, impredicative types

## Planning

**Scopes:**
- IN: The fundamental split between recursive and non-recursive bindings in `tcMonoBinds`, how this split enables or disables higher-rank and impredicative inference, and implications for elab3 architecture
- OUT: Core desugaring details, evidence generation, dictionary passing, strict bindings, SCC analysis

**Entry Points:**
- `compiler/GHC/Tc/Gen/Bind.hs:1295-1325` — Special case 1: non-recursive FunBind
- `compiler/GHC/Tc/Gen/Bind.hs:1326-1376` — Special case 2: non-recursive PatBind
- `compiler/GHC/Tc/Gen/Bind.hs:1381-1399` — General case (recursive and signatured bindings)
- `compiler/GHC/Tc/Gen/Bind.hs:1401-1460` — Notes explaining the special cases
- `compiler/GHC/Tc/Gen/Bind.hs:1490-1537` — tcLhs FunBind/PatBind (general case LHS processing)

## Context from Parent Explorations

This exploration synthesizes findings from three prior investigations:

1. **TC_SPECIAL_CASES_EXPLORATION.md** documented that GHC has two special cases in `tcMonoBinds` for non-recursive bindings (FunBind and PatBind) that use `runInferRhoFRR` to infer RHS types before creating binders, while the general case creates monomorphic IDs with fresh unification variables first.

2. **ABSBINDS_CORE_TRANSLATION_EXPLORATION.md** and **POLY_RECURSIVE_BINDINGS_GHC.md** established the two-phase structure of recursive binding typechecking: `tcLhs` creates mono IDs, then `tcExtendRecIds` brings them into scope for RHS checking, followed by joint generalization via `tcPolyInfer`.

3. **LET_BINDING_ARCHITECTURE_EXPLORATION.md** analyzed the Levels/Expect/Closure/Meta-Skolem model, showing that Infer mode creates metas while Check mode creates skolems, and that the general case forces a checking-like mode by creating binders before seeing RHSs.

The gap: none of these explorations explicitly named the *fundamental architectural insight* that ties them together. This document fills that gap.

---

## Facts

### Fact 1: Recursive Bindings MUST Create Mono IDs Before Checking RHSs
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1381-1399` (general case)
**Comment:** In the general case, `tcMonoBinds` first processes all LHSes via `tcLhs`, creating monomorphic Ids with fresh unification variables for binders without signatures. Only then does it extend the environment and check RHSs. This ordering is mandatory for recursive bindings because the binder must be in scope when its own RHS is typechecked.
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
In the FunBind `tcLhs` case without a signature, this creates a fresh unification variable:
```haskell
  | otherwise  -- No type signature
  = do { mono_ty <- newOpenFlexiTyVarTy    -- Fresh unification variable!
       ; mult <- newMultiplicityVar
       ; mono_id <- newLetBndr no_gen name mult mono_ty
       ; ... }
```

### Fact 2: Non-Recursive FunBind Can Infer RHS Type First, Then Create Binder
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1295-1325` (special case 1)
**Comment:** When a single non-recursive FunBind has no type signature, the binder is NOT mentioned in its own RHS. This frees GHC to infer the RHS type first using `runInferRhoFRR` (which creates an inference hole), and only then create the monomorphic binder from the inferred type. This enables higher-rank type inference because the inference hole can be filled with a polytype.
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

### Fact 3: Non-Recursive PatBind Can Infer RHS Type First, Then Check Pattern
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1326-1376` (special case 2)
**Comment:** Similarly, for a non-recursive PatBind with no signatures on any binders, GHC infers the RHS type first via `runInferRhoFRR`, then checks the pattern against that inferred type using `tcLetPat` with `mkCheckExpType`. This enables impredicative type inference for pattern-bound variables because the inferred RHS type may contain nested foralls that would be lost if a unification variable were created first.
```haskell
tcMonoBinds is_rec sig_fn no_gen
           [L b_loc (PatBind { pat_lhs = pat, pat_rhs = grhss, pat_mods = mods })]
  | NonRecursive <- is_rec   -- ...binder isn't mentioned in RHS
  , all (isNothing . sig_fn) bndrs
  = addErrCtxt (PatMonoBindsCtxt pat grhss) $
    do { mult <- tcMultiplicityOnPatBind mods

       ; (grhss', pat_ty) <- runInferRhoFRR FRRPatBind $ \ exp_ty ->
                          tcGRHSsPat mult grhss exp_ty

       ; let exp_pat_ty :: Scaled ExpSigmaTypeFRR
             exp_pat_ty = Scaled mult (mkCheckExpType pat_ty)
       ; (_, (pat', mbis)) <- tcCollectingUsage $
                         tcLetPat (const Nothing) no_gen pat exp_pat_ty $ do
                           tcEmitBindingUsage bottomUE
                           mapM lookupMBI bndrs

       ; return ( singleton $ L b_loc $ ... , mbis ) }
```

### Fact 4: The General Case Cannot Handle Higher-Rank or Impredicative Types
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1401-1460` (Notes)
**Comment:** The general case creates a monomorphic Id with a unification variable (`newOpenFlexiTyVarTy`) before seeing the RHS. When the RHS has a higher-rank type (e.g., `\(x::forall a. a->a) -> body`), unifying the mono_ty with the inferred RHS type fails because a unification variable cannot be unified with a polytype. The special cases avoid this by inferring first, then creating the binder.

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

### Fact 6: The Two Special Cases Share a Common Structure
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1295-1376`
**Comment:** Both special cases follow the same pattern: (1) check `NonRecursive`, (2) check no signatures, (3) use `runInferRhoFRR` to infer the RHS type first, (4) then construct the binder from the inferred type. Both return `MonoBindInfo` records that participate in generalization via `tcPolyInfer` just like the general case.

| Step | FunBind Special Case | PatBind Special Case |
|------|----------------------|----------------------|
| RecFlag check | `NonRecursive <- is_rec` | `NonRecursive <- is_rec` |
| Signature check | `Nothing <- sig_fn name` | `all (isNothing . sig_fn) bndrs` |
| RHS inference | `runInferRhoFRR` + `tcFunBindMatches` | `runInferRhoFRR` + `tcGRHSsPat` |
| Binder creation | `newLetBndr no_gen name mult rhs_ty'` | via `tcLetPat` + `lookupMBI` |
| Return | `MonoBindInfo` + typechecked bind | `MonoBindInfo` + typechecked bind |

### Fact 7: The Key Difference is `newOpenFlexiTyVarTy` vs `runInferRhoFRR`
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1295-1399` (contrasting special and general cases)
**Comment:** The general case uses `newOpenFlexiTyVarTy` to create a unification variable for the binder's type BEFORE seeing the RHS. This variable is a `TauTv` meta that can only unify with monomorphic types. The special cases use `runInferRhoFRR` which creates an `ExpType` inference hole (backed by an `IORef`) that can be filled with ANY type, including higher-rank or impredicative polytypes, AFTER the RHS has been fully typechecked. This is the mechanism-level difference that enables the feature-level difference.

---

## Claims

### Claim 1: The Fundamental Architectural Insight — Recursion Forces LHS-First Ordering
**Analysis:** Facts 1, 2, 3, 4, and 7.
**Status:** Draft
**Confidence:** High

The special cases exist because of a single, fundamental constraint: **recursive bindings require the binder to be in scope before its RHS is typechecked**. This forces a left-to-right (LHS-first) ordering in the general case: create binder with a type variable, then check RHS against that variable. Non-recursive bindings break this dependency chain — the binder is NOT referenced in its own RHS — which allows GHC to reverse the order: infer RHS type first, then create the binder.

This ordering reversal is not merely an optimization; it is **architecturally necessary** for higher-rank and impredicative inference. The LHS-first ordering forces "checking mode" semantics (the RHS is checked against a known, though flexible, type). The RHS-first ordering enables "inference mode" semantics (the RHS type is synthesized bottom-up). Inference mode is strictly more powerful because:

1. **Higher-rank functions:** When `f = \(x::forall a. a->a) -> body`, the lambda's type is `forall a. a->a -> body_ty`. In checking mode against a unification variable, this fails because a TauTv cannot unify with a polytype. In inference mode, the lambda type is synthesized and assigned directly to `f`.

2. **Impredicative patterns:** When `(x,y) = combine head ids`, the RHS type may be `((forall a. [a]->a), [forall a. a->a])`. In checking mode against a unification variable, the nested foralls are lost. In inference mode, the type is preserved and the pattern is checked against it.

The key mechanism difference: `newOpenFlexiTyVarTy` creates a rigidly monomorphic placeholder, while `runInferRhoFRR` creates a polymorphism-capable hole.

### Claim 2: The Split Creates Two Distinct Type Inference Pipelines
**Analysis:** Facts 1, 2, 3, 6, and 7.
**Status:** Draft
**Confidence:** High

The recursive/non-recursive split creates two fundamentally different pipelines within `tcMonoBinds`:

**Pipeline A: Recursive / Signatured (General Case)**
```
tcLhs (create mono IDs with fresh TauTvs)
  -> tcExtendRecIds (add to env)
  -> tcRhs (check RHSs against known types)
  -> return MonoBindInfo for generalization
```
- **Direction:** Top-down (checking)
- **Variable creation:** `newOpenFlexiTyVarTy` → TauTv metas
- **Capabilities:** Monomorphic and rank-1 polymorphic inference only
- **Required for:** Recursive bindings, bindings with signatures

**Pipeline B: Non-Recursive / No-Signature (Special Cases)**
```
runInferRhoFRR (infer RHS type via ExpType hole)
  -> create binder from inferred type
  -> return MonoBindInfo for generalization
```
- **Direction:** Bottom-up (inference)
- **Variable creation:** `runInferRhoFRR` → InferResult hole
- **Capabilities:** Higher-rank and impredicative inference
- **Enabled by:** Non-recursive bindings without signatures

Both pipelines converge on `MonoBindInfo` and feed into the same generalization machinery (`tcPolyInfer`), but they arrive there through opposite directions. This is a classic example of bidirectional type inference: the general case is "checking-biased" while the special cases are "inference-biased."

### Claim 3: For elab3, the General Case is Sufficient for Core Soundness; Special Cases are Feature Enablers
**Analysis:** Facts 4, 5, and synthesis from ABSBINDS_CORE_TRANSLATION_EXPLORATION.md.
**Status:** Draft
**Confidence:** Medium

For elab3's recursive binding support, the architectural decision is clear:

1. **The general case (Pipeline A) is sufficient for soundness.** It correctly handles all recursive bindings, all bindings with signatures, and all monomorphic/rank-1 polymorphic inference. It is the minimal viable implementation.

2. **The special cases (Pipeline B) are feature enablers, not correctness requirements.** Without them:
   - Non-recursive functions with higher-rank arguments require explicit type signatures (usability regression, not unsoundness)
   - Pattern bindings with impredicative types fail or require annotations (usability regression, not unsoundness)

3. **Implementation path:** elab3 should implement Pipeline A first. Pipeline B can be added incrementally by adding pattern-match guards before the general case in `tcMonoBinds`, exactly as GHC does:
   ```haskell
   tcMonoBinds is_rec sig_fn no_gen binds
     -- Special case 1: non-recursive FunBind, no sig
     | NonRecursive <- is_rec, [single FunBind] <- binds, ... = ...
     -- Special case 2: non-recursive PatBind, no sigs
     | NonRecursive <- is_rec, [single PatBind] <- binds, ... = ...
     -- General case: everything else
     | otherwise = ...
   ```

4. **The `RecFlag` distinction is semantic, not syntactic.** GHC's `NonRecursive` means "binder not mentioned in RHS" (determined by dependency analysis), not merely "not marked recursive." elab3 must compute this accurately for the special cases to be sound.

### Claim 4: The Signature Restriction Reveals a Deep Tension in Bidirectional Inference
**Analysis:** Facts 4 and 5.
**Status:** Draft
**Confidence:** High

The requirement that special cases apply only when NO binder has a signature reveals a fundamental tension: **bidirectional type inference cannot simultaneously check and infer in the same binding group.** When a signature exists, the expected type is known and must be pushed inward (checking mode). When no signature exists, the type is unknown and must be synthesized (inference mode). These modes are incompatible within a single binding because:

- Checking mode creates skolems (rigid variables that cannot unify)
- Inference mode creates metas (flexible variables that can unify)
- A single RHS cannot be both checked against a skolem and inferred as a meta

GHC resolves this by requiring uniformity: either ALL binders in a group have signatures (checking mode via `tcPolyCheck`) or NONE do (inference mode via special cases or general case). Mixed groups fall back to the general case, which is checking-biased and loses higher-rank/impredicative capabilities for the unsignatured binders.

This tension is intrinsic to bidirectional type systems and will apply equally to elab3 if it supports both explicit signatures and higher-rank inference.

---

## Comparison Table: Recursive vs Non-Recursive Bindings

| Aspect | Recursive Bindings | Non-Recursive Bindings (No Sig) |
|--------|-------------------|--------------------------------|
| **Binder in RHS?** | Yes — must be in scope | No — not referenced |
| **Processing order** | LHS first, then RHS | RHS first, then LHS |
| **Binder type creation** | `newOpenFlexiTyVarTy` (TauTv) | `runInferRhoFRR` (InferResult hole) |
| **Mode** | Checking-biased | Inference-biased |
| **Higher-rank inference** | Not supported without signature | Supported (FunBind special case) |
| **Impredicative inference** | Not supported without signature | Supported (PatBind special case) |
| **Signatures allowed?** | Yes (pushed inward) | No (would force checking mode) |
| **Generalization** | Joint via `tcPolyInfer` | Joint via `tcPolyInfer` |
| **Core output** | `AbsBinds` with mono/poly pair | `AbsBinds` with mono/poly pair |
| **GHC source** | `Bind.hs:1381-1399` | `Bind.hs:1295-1376` |

---

## Notes

**Note 1: Why GHC calls them "special cases"**
The special cases are pattern-match guards that appear BEFORE the general case in `tcMonoBinds`. They handle specific syntactic shapes (single non-recursive FunBind, single non-recursive PatBind). The general case is the catch-all. This is a classic GHC pattern: optimize the common/special cases first, fall through to the general case.

**Note 2: The special cases still produce `AbsBinds`**
Despite bypassing the general case's two-phase structure, the special cases still return `MonoBindInfo` records that feed into `tcPolyInfer` and produce `AbsBinds` nodes. The difference is in HOW the mono_id's type is determined (inferred vs. fresh unification variable), not in the overall pipeline architecture.

**Note 3: Fixed Runtime Representation (FRR) is orthogonal**
Both special cases use `runInferRhoFRR` (not plain `runInferRho`) to ensure let-binder types have representable runtime types (#23176). This is a recent GHC addition that applies regardless of recursive vs non-recursive distinction. elab3 may not need FRR checks initially.

**Note 4: The `RecFlag` is computed, not parsed**
GHC computes `RecFlag` via dependency analysis (`stronglyConnCompFromEdgedVerticesUniq`). A binding group is `NonRecursive` only if no binder appears free in any RHS. This is semantic non-recursion, not syntactic. elab3 must implement similar dependency analysis for the special cases to be applicable.

---

## Open Questions

- [ ] Does elab3 currently compute semantic `RecFlag` (dependency analysis), or only syntactic? The special cases require semantic non-recursion.
- [ ] Does elab3 support higher-rank types at all? If not, the FunBind special case may be moot initially.
- [ ] Does elab3 support impredicative types? The PatBind special case only matters with `-XImpredicativeTypes`.
- [ ] How should elab3 handle mixed signature groups (some binders with sigs, some without)? GHC falls back to the general case; is this acceptable for elab3?
- [ ] Should elab3 implement the special cases as pattern-match guards before the general case (GHC style), or as a separate pass?
- [ ] What is the interaction between these special cases and elab3's current `AbsBinds`-like representation? Do the special cases require any changes to Core generation?

---

## Related Topics

- [TC_SPECIAL_CASES_EXPLORATION.md](TC_SPECIAL_CASES_EXPLORATION.md) — Detailed analysis of the special cases with full code snippets
- [ABSBINDS_CORE_TRANSLATION_EXPLORATION.md](ABSBINDS_CORE_TRANSLATION_EXPLORATION.md) — Generalisation and AbsBinds generation
- [POLY_RECURSIVE_BINDINGS_GHC.md](POLY_RECURSIVE_BINDINGS_GHC.md) — Broader coverage of the typechecking pipeline
- [LET_BINDING_ARCHITECTURE_EXPLORATION.md](LET_BINDING_ARCHITECTURE_EXPLORATION.md) — Levels/Expect/Closure/Meta-Skolem model
- [HIGHERRANK_POLY.md](HIGHERRANK_POLY.md) — Higher-rank polymorphism mechanisms
- [SKOLEMISATION_QUANTIFICATION_EXPLORATION.md](SKOLEMISATION_QUANTIFICATION_EXPLORATION.md) — How polytypes are skolemised during checking
