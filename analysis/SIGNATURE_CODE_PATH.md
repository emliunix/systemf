# Code Path: Function with Complete Type Signature

This document traces the exact code path for a top-level function with a complete type signature:

```haskell
id :: a -> a
id x = x
```

## Overview

When a function has a **complete type signature**, GHC takes a different code path than inferred bindings. The signature is checked against the implementation, rather than being inferred from it.

## Complete Call Chain

```
tcRnModule (GHC/Tc/Module.hs:200)
  └── tcRnModuleTcRnM (GHC/Tc/Module.hs:235)
        └── tcRnSrcDecls (GHC/Tc/Module.hs:546)
              └── tcTopSrcDecls (GHC/Tc/Module.hs:1702)
                    └── tcTopBinds (GHC/Tc/Module.hs:1736)
                          └── tcValBinds (GHC/Tc/Gen/Bind.hs:260)
                                ├── tcTySigs (line 265-266)  ← Type-check signature first!
                                └── tcExtendSigIds (line 276)  ← Add poly_id to environment
                                      └── tcBindGroups (line 278)
                                            └── tc_group (line 334)
                                                  └── tc_nonrec_group (line 344)
                                                        └── tcPolyBinds (line 470)
                                                              └── decideGeneralisationPlan (line 478)
                                                                    └── CheckGen path (line 1806)
                                                                          └── tcPolyCheck (line 564)
                                                                                └── tcSkolemiseCompleteSig (line 585)
                                                                                      └── tcSkolemiseGeneral Shallow
                                                                                            └── tcFunBindMatches (line 593)
                                                                                                  └── tcExpr (checking mode with expected type a -> a)
```

## Detailed Step-by-Step

### Step 1: Process the Signature

**`tcValBinds`** `GHC/Tc/Gen/Bind.hs:260-289`

```haskell
tcValBinds top_lvl grps sigs thing_inside
  = do { (poly_ids, sig_fn) <- tcAddPatSynPlaceholders patsyns $
                                 tcTySigs sigs   -- ← HERE! Process signatures first
       ; tcExtendSigIds top_lvl poly_ids $      -- ← Add poly_id to environment
     do { ... }}
```

**`tcTySigs`** processes `id :: a -> a` and creates a `TcCompleteSig` with:
- `sig_bndr = poly_id` with type `forall a. a -> a`
- The polymorphic Id is added to the environment immediately!

### Step 2: Decide the Generalisation Plan

**`decideGeneralisationPlan`** `GHC/Tc/Gen/Bind.hs:1800-1851`

```haskell
decideGeneralisationPlan dflags top_lvl closed_type sig_fn lbinds
  | Just (bind, sig) <- one_funbind_with_sig = CheckGen bind sig  -- ← This path!
  | generalise_binds                         = InferGen
  | otherwise                                = NoGen
  where
    one_funbind_with_sig
      | [lbind@(L _ (FunBind { fun_id = v }))] <- lbinds
      , Just (TcIdSig (TcCompleteSig sig)) <- sig_fn (unLoc v)  -- ← Matches!
      = Just (lbind, sig)
```

For `id :: a -> a`:
- Single `FunBind` with name `id`
- `sig_fn id` returns `Just (TcIdSig (TcCompleteSig sig))`
- Result: **`CheckGen`** plan!

### Step 3: Check Against the Signature

**`tcPolyCheck`** `GHC/Tc/Gen/Bind.hs:564-629`

```haskell
tcPolyCheck prag_fn
            sig@(CSig { sig_bndr = poly_id, sig_ctxt = ctxt })
            (L bind_loc (FunBind { fun_id = L nm_loc name
                                 , fun_matches = matches }))
  = do { traceTc "tcPolyCheck" (ppr sig)
       ; mono_name <- newNameAt (nameOccName name) (locA nm_loc)
       ; mult <- newMultiplicityVar
       
       -- KEY STEP: Skolemise the complete signature
       ; (wrap_gen, (wrap_res, matches'))
              <- tcSkolemiseCompleteSig sig $ \invis_pat_tys rho_ty ->

                 let mono_id = mkLocalId mono_name (idMult poly_id) rho_ty in
                 tcExtendBinderStack [TcIdBndr mono_id NotTopLevel] $
                 setSrcSpanA bind_loc  $
                 -- Check RHS against the expected type from signature
                 tcFunBindMatches ctxt mono_name mult matches invis_pat_tys 
                                  (mkCheckExpType rho_ty)  -- ← CHECKING mode!
       ... }
```

**Key points:**
- `poly_id` has type `forall a. a -> a` (from the signature)
- `tcSkolemiseCompleteSig` skolemises the forall-bound variables
- `rho_ty` becomes `a_sk -> a_sk` (rho type with skolem)
- `mkCheckExpType rho_ty` creates **checking mode**!

### Step 4: Skolemise the Signature

**`tcSkolemiseCompleteSig`** `GHC/Tc/Utils/Unify.hs:463-478`

```haskell
tcSkolemiseCompleteSig (CSig { sig_bndr = poly_id, sig_ctxt = ctxt, sig_loc = loc })
                       thing_inside
  = do { let poly_ty = idType poly_id  -- ∀a. a → a
       ; tcSkolemiseGeneral Shallow ctxt poly_ty poly_ty $ \tv_prs rho_ty ->
         tcExtendNameTyVarEnv (map (fmap binderVar) tv_prs) $  -- Bind a ↦ a_sk
         thing_inside (map (mkInvisExpPatType . snd) tv_prs) rho_ty }
         --                                    ^^^^^^^^^
         -- rho_ty is now a_sk -> a_sk
```

**Skolemisation:**
- `forall a. a -> a` → `a_sk -> a_sk` (rho type)
- `a_sk` is a **skolem constant** (rigid type variable)
- The skolem is brought into scope in the type environment

### Step 5: Type-Check the Function Body

**`tcFunBindMatches`** `GHC/Tc/Gen/Match.hs:112` with **checking mode**

```haskell
tcFunBindMatches ctxt mono_name mult matches invis_pat_tys 
                 (mkCheckExpType rho_ty)  -- Check mode: a_sk -> a_sk
  = do { arity <- checkArgCounts matches  -- arity = 1
       ; (wrap_fun, r)
              <- matchExpectedFunTys herald ctxt arity 
                                    (mkCheckExpType rho_ty)  -- Check mode
                                    $ \pat_tys rhs_ty -> ... }
```

**`matchExpectedFunTys`** `GHC/Tc/Utils/Unify.hs:824` for Check mode:

```haskell
matchExpectedFunTys herald ctx arity (Check top_ty) thing_inside
  = check arity [] top_ty
  where
    -- Decompose a_sk -> a_sk into:
    --   arg_ty = a_sk
    --   res_ty = a_sk
    check n_req rev_pat_tys (FunTy { ft_arg = arg_ty, ft_res = res_ty })
      = do { ...
           ; (res_wrap, result) <- check (n_req - 1)
                                         (mkCheckExpFunPatTy scaled_arg_ty_frr : rev_pat_tys)
                                         res_ty }
```

### Step 6: Type-Check the Lambda Body

**`tcExpr`** `GHC/Tc/Gen/Expr.hs:290` in **checking mode**

Since we're in checking mode with expected type `a_sk`, the body `x` is checked against `a_sk`.

```haskell
tcExpr (HsVar {}) res_ty = tcApp e res_ty  -- Variable occurrence
-- res_ty = Check a_sk
```

The variable `x` (bound by the lambda) has type `a_sk`, so checking succeeds!

### Step 7: Create the AbsBinds

Back in `tcPolyCheck`, after type-checking:

```haskell
; let export = ABE { abe_wrap  = idHsWrapper
                   , abe_poly  = poly_id       -- forall a. a -> a
                   , abe_mono  = poly_id2      -- a_sk -> a_sk
                   , abe_prags = SpecPrags spec_prags }

      abs_bind = L bind_loc $ XHsBindsLR $
                 AbsBinds { abs_tvs      = []           -- No need to abstract!
                          , abs_ev_vars  = []
                          , abs_ev_binds = []
                          , abs_exports  = [export]
                          , abs_binds    = [L bind_loc bind']
                          , abs_sig      = True }       -- Has signature
```

**Key difference:**
- `abs_tvs = []` - No type variables to abstract because they're already in `poly_id`
- `abs_sig = True` - Marks that this binding had a complete signature

## Comparison: Signature vs No Signature

| Aspect | With Signature (`id :: a -> a`) | Without Signature (`id x = x`) |
|--------|-------------------------------|-------------------------------|
| **Plan** | `CheckGen` | `InferGen` |
| **Function** | `tcPolyCheck` | `tcPolyInfer` |
| **Mode** | Checking (against expected type) | Inference (creates fresh hole) |
| **Generalization** | Skolemise existing signature | `simplifyInfer` quantifies over inferred vars |
| **abs_tvs** | `[]` (already polymorphic) | `[qtvs]` (freshly quantified) |
| **abs_sig** | `True` | `False` |
| **Result** | Direct checking | Generalization at let |

## Key Insight

With a complete signature, GHC:

1. **Trusts the signature** - Uses it as the ground truth
2. **Skolemises** - Replaces `forall a` with rigid `a_sk` 
3. **Checks the body** - Verifies it has the expected type
4. **No generalization** - The type is already polymorphic, no need to infer and generalize

This is why complete signatures allow **polymorphic recursion** and more precise types than inference alone!

## See Also

- `tcPolyCheck` `GHC/Tc/Gen/Bind.hs:564`
- `tcSkolemiseCompleteSig` `GHC/Tc/Utils/Unify.hs:463`
- `tcSkolemiseGeneral` `GHC/Tc/Utils/Unify.hs:492`
- Note [Skolemisation overview] in `GHC/Tc/Utils/Unify`

---

*Document based on GHC source code analysis*
