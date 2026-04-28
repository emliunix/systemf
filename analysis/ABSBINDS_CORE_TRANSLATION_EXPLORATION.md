# AbsBinds and Core Translation Exploration

**Status:** Validated
**Last Updated:** 2026-04-22
**Central Question:** How does GHC's AbsBinds structure translate to Core, and what optimizations exist for special cases?
**Topics:** AbsBinds, Core translation, recursive bindings, polymorphism, GHC

## Planning

**Scopes:** 
- IN: AbsBinds structure, Core translation rules, special cases (monomorphic, single-export)
- OUT: Type inference algorithm, evidence handling, strict bindings

**Entry Points:**
- `compiler/GHC/Hs/Binds.hs:167` — AbsBinds data type
- `compiler/GHC/Hs/Binds.hs:201` — ABExport data type  
- `compiler/GHC/HsToCore/Binds.hs:263` — dsAbsBinds function
- `compiler/GHC/Tc/Gen/Bind.hs:714` — tcPolyInfer
- `compiler/GHC/Tc/Gen/Bind.hs:1289` — tcMonoBinds

## Facts

### Fact 1: AbsBinds Data Type
**Source:** `compiler/GHC/Hs/Binds.hs:167`
**Comment:** Typechecker output representing generalized binding group
```haskell
data AbsBinds = AbsBinds {
    abs_tvs      :: [TyVar],       -- Quantified type variables
    abs_ev_vars  :: [EvVar],       -- Evidence variables (dictionaries)
    abs_exports  :: [ABExport],    -- Poly/mono pairs
    abs_ev_binds :: [TcEvBinds],   -- Evidence bindings
    abs_binds    :: LHsBinds GhcTc -- Monomorphic bindings
}
```

### Fact 2: ABExport Data Type
**Source:** `compiler/GHC/Hs/Binds.hs:201`
**Comment:** Connects external poly name to internal mono name
```haskell
data ABExport = ABE {
    abe_poly  :: Id,         -- Exported polymorphic id
    abe_mono  :: Id,         -- Internal monomorphic id
    abe_wrap  :: HsWrapper,  -- Poly -> mono conversion
    abe_prags :: TcSpecPrags -- SPECIALISE pragmas
}
```

### Fact 3: Single Export Optimization
**Source:** `compiler/GHC/HsToCore/Binds.hs:280-308`
**Comment:** Most common case - no tuple needed
```haskell
| [export] <- exports
, ABE { abe_poly = global_id, abe_mono = local_id
      , abe_wrap = wrap, abe_prags = prags } <- export
= do { ...
   ; let rhs = core_wrap $
               mkLams tyvars $ mkLams dicts $
               mkCoreLets ds_ev_binds $
               body
         body | has_sig
              , [(_, lrhs)] <- bind_prs
              = lrhs
              | otherwise
              = mkLetRec bind_prs (Var local_id)
   ... }
```

### Fact 4: No TyVars No Dicts Case
**Source:** `compiler/GHC/HsToCore/Binds.hs:316-336`
**Comment:** Monomorphic group - direct mapping without tuple
```haskell
| null tyvars, null dicts
= do { let mk_main (ABE { abe_poly = gbl_id, abe_mono = lcl_id
                        , abe_wrap = wrap })
             = do { dsHsWrapper wrap $ \core_wrap -> do
                  { return ( gbl_id `setInlinePragma` defaultInlinePragma
                           , core_wrap (Var lcl_id)) } }
     ; main_prs <- mapM mk_main exports
     ; let bind_prs' = map mk_aux_bind bind_prs
           final_prs | is_singleton = wrap_first_bind (mkCoreLets ds_ev_binds) bind_prs'
                     | otherwise = flattenBinds ds_ev_binds ++ bind_prs'
     ; return (force_vars, final_prs ++ main_prs ) }
```

### Fact 5: General Case with Tuple
**Source:** `compiler/GHC/HsToCore/Binds.hs:340-383`
**Comment:** Multiple exports with type variables use tuple packaging
```haskell
| otherwise
= do { let aux_binds = Rec (map mk_aux_bind bind_prs)
           locals       = map abe_mono exports
           all_locals   = locals ++ new_force_vars
           tup_expr     = mkBigCoreVarTup all_locals
           tup_ty       = exprType tup_expr
     ; let poly_tup_rhs = mkLams tyvars $ mkLams dicts $
                          mkCoreLets ds_ev_binds $
                          mkLet aux_binds $
                          tup_expr
     ... }
```

### Fact 6: tcPolyInfer Pushes Level Once
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:722-724`
**Comment:** Joint generalization - single level push for entire group
```haskell
tcPolyInfer top_lvl rec_tc prag_fn tc_sig_fn bind_list
  = do { (tclvl, wanted, (binds', mono_infos))
             <- pushLevelAndCaptureConstraints  $
                tcMonoBinds rec_tc tc_sig_fn LetLclBndr bind_list
       ... }
```

### Fact 7: tcMonoBinds Two-Phase Structure
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1379-1399`
**Comment:** Creates mono IDs first, then extends env for RHS checking
```haskell
tcMonoBinds _ sig_fn no_gen binds
  = do  { tc_binds <- mapM (wrapLocMA (tcLhs sig_fn no_gen)) binds
        ; let mono_infos = getMonoBindInfo tc_binds
              rhs_id_env = [ (name, mono_id) | ... ]
        ; binds' <- tcExtendRecIds rhs_id_env $
                    mapM (wrapLocMA tcRhs) tc_binds
        ; return (binds', mono_infos) }
```

## Claims

### Claim 1: Single Export is the Most Common Case
**Analysis:** References Fact 3. The first case in dsAbsBinds handles `[export] <- exports`, meaning single export. This is described as "A very important common case: one exported variable. Non-recursive bindings come through this way. So do self-recursive bindings." The code generates `mkLetRec bind_prs (Var local_id)` directly without tuple packaging.
**Status:** Validated
**Source Check:** Verified at `GHC/HsToCore/Binds.hs:274-308`
**Logic Check:** Sound
**Confidence:** High

### Claim 2: Monomorphic Groups Skip Tuple Packaging
**Analysis:** References Fact 4. When `null tyvars && null dicts`, the poly_id and mono_id have the same type. The desugaring becomes direct: `f = fm; g = gm` instead of tuple+selector. This is an optimization to avoid "quadratic-sized tuple desugaring" (from Note [The no-tyvar no-dict case]).
**Status:** Validated
**Source Check:** Verified at `GHC/HsToCore/Binds.hs:316-336`
**Logic Check:** Sound
**Confidence:** High

### Claim 3: Joint Generalization Requires Single Level Push
**Analysis:** References Fact 6 and Fact 7. `tcPolyInfer` calls `pushLevelAndCaptureConstraints` once, then `tcMonoBinds` creates all mono IDs and checks all RHSs within that level. This ensures all metas created during RHS checking are at the same level (N+1), allowing `simplifyInfer` to collect and quantify them jointly. If each binding pushed its own level, metas would be at different levels and couldn't be quantified together.
**Status:** Validated
**Source Check:** Verified at `GHC/Tc/Gen/Bind.hs:722-724` and `GHC/Tc/Gen/Bind.hs:1379-1399`
**Logic Check:** Sound
**Confidence:** High

### Claim 4: The Tuple in General Case Avoids Binding Group Duplication
**Analysis:** References Fact 5. The naive translation would duplicate the entire letrec per export: `f = /\a. letrec {...} in fm` and `g = /\a. letrec {...} in gm`. The tuple packages all monomorphic ids once: `poly_tup = /\a. letrec {...} in (fm, gm)`, then each export selects its component. This is crucial when the binding group is large.
**Status:** Validated
**Source Check:** Verified at `GHC/HsToCore/Binds.hs:340-383`
**Logic Check:** Sound
**Confidence:** High

### Claim 5: The Recursive/Non-Recursive Split is the Root Cause of All Special Cases
**Analysis:** References findings from RECURSIVE_VS_NONRECURSIVE_SPLIT_EXPLORATION.md. The fundamental constraint is that recursive bindings require the binder to be in scope before RHS typechecking, forcing LHS-first ordering with `newOpenFlexiTyVarTy` (checking mode). Non-recursive bindings can reverse this order, using `runInferRhoFRR` to infer the RHS first (inference mode), enabling higher-rank and impredicative types. This explains why:
- Single export optimization exists (common recursive pattern)
- Monomorphic group optimization exists (no quantification needed)
- Non-recursive FunBind special case exists (higher-rank inference)
- Non-recursive PatBind special case exists (impredicative inference)
**Status:** Validated
**Source Check:** Verified at `GHC/Tc/Gen/Bind.hs:1295-1399`
**Logic Check:** Sound
**Confidence:** High

## Notes

**Note 1:** This exploration focuses on the Core translation aspect of AbsBinds. The type inference pipeline (tcPolyInfer, tcMonoBinds) is covered only to the extent needed to understand why the Core translation has this structure.

**Note 2:** For elab3 implementation, the key decision is whether to:
- Add AbsBinds-like node to Core AST (more faithful to GHC)
- Or directly generate the optimized Core (simpler but less modular)

**Note 3:** The three cases in dsAbsBinds (single export, no tyvars, general) form a hierarchy. Single export is most common. No-tyvars is a simplification of general case. Implementation should handle them in this priority order.

## Open Questions
- [x] How does the wrapper (abe_wrap) work when poly and mono types differ? (See ABEXPORT_WRAPPER_EXPLORATION.md)
- [x] What is the fundamental difference between recursive and non-recursive binding typechecking? (See RECURSIVE_VS_NONRECURSIVE_SPLIT_EXPLORATION.md)
- [ ] What happens with pattern bindings in recursive groups?
- [ ] How does elab3's current letrec structure compare to GHC's Rec?

## Related Topics
- `POLY_RECURSIVE_BINDINGS_GHC.md` — Broader coverage of the typechecking pipeline
- `ABEXPORT_WRAPPER_EXPLORATION.md` — Detailed analysis of abe_wrap mechanism and impedance matching
- `RECURSIVE_VS_NONRECURSIVE_SPLIT_EXPLORATION.md` — Fundamental architectural insight on recursive vs non-recursive split
