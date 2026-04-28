# ABExport Wrapper (abe_wrap) Mechanism Exploration

**Status:** Validated
**Last Updated:** 2026-04-22
**Central Question:** How does the wrapper (abe_wrap) work when poly and mono types differ?
**Topics:** ABExport, HsWrapper, impedance matching, desugaring, polymorphism, GHC

## Planning

**Scopes:**
- IN: mkExport wrapper creation, impedance matching concept, desugaring application sites, ABExport wrapper note
- OUT: Full type inference algorithm, evidence term generation, deep subsumption mechanics

**Entry Points:**
- `compiler/GHC/Tc/Gen/Bind.hs:895-936` — mkExport creates the wrapper
- `compiler/GHC/Tc/Gen/Bind.hs:1238` — Note [Impedance matching]
- `compiler/GHC/HsToCore/Binds.hs:289` — single export wrapper application
- `compiler/GHC/HsToCore/Binds.hs:366` — general case wrapper application
- `compiler/GHC/Hs/Binds.hs:260` — Note [ABExport wrapper]

**Assumptions:**
- The wrapper bridges between the group-generalized type and the individually-generalized type
- HsWrapper is a source-level representation that desugars to CoreExpr -> CoreExpr

## Context from Parent Exploration

From `ABSBINDS_CORE_TRANSLATION_EXPLORATION.md`:
- ABExport has `abe_wrap :: HsWrapper` field for "Poly -> mono conversion"
- The wrapper is applied in three places in `dsAbsBinds`: single export (line 289), no-tyvar case (line 326), and general case (line 366)
- Open Question: "How does the wrapper (abe_wrap) work when poly and mono types differ?"

## Facts

### Fact 1: Wrapper Creation in mkExport
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:895-936`
**Comment:** The wrapper is created by comparing `sel_poly_ty` (group-generalized) against `poly_ty` (individual poly id type). If they differ, `tcSubTypeSigma` computes the impedance matcher.
```haskell
mkExport prag_fn residual insoluble qtvs theta
         (MBI { mbi_poly_name = poly_name
              , mbi_sig       = mb_sig
              , mbi_mono_id   = mono_id
              , mbi_mono_mult = mono_mult })
  = do  { mono_ty <- liftZonkM $ zonkTcType (idType mono_id)
        ; poly_id <- mkInferredPolyId residual insoluble qtvs theta poly_name mb_sig mono_ty
        ...
        ; let poly_ty     = idType poly_id
              sel_poly_ty = mkInfSigmaTy qtvs theta mono_ty
                -- This type is just going into tcSubType,
                -- so Inferred vs. Specified doesn't matter
        ...
        ; wrap <- if sel_poly_ty `eqType` poly_ty  -- NB: eqType ignores visibility
                  then return idHsWrapper  -- Fast path
                  else tcSubTypeSigma (ImpedanceMatching poly_id)
                                      sig_ctxt sel_poly_ty poly_ty
                       -- See Note [Impedance matching]
        ; return (Scaled mono_mult $
                  ABE { abe_wrap = wrap
                        -- abe_wrap :: (forall qtvs. theta => mono_ty) ~ idType poly_id
                      , abe_poly  = poly_id
                      , abe_mono  = mono_id
                      , abe_prags = SpecPrags spec_prags }) }
```

### Fact 2: Impedance Matching Concept
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1238-1273`
**Comment:** When mutually recursive bindings share constraints but each is polymorphic in different type variables, the "group type" has all qtvs and all constraints, while each individual poly id may have fewer. Impedance matching bridges this gap via subsumption checking, which can involve defaulting.
```haskell
Note [Impedance matching]
~~~~~~~~~~~~~~~~~~~~~~~~~
Consider
   f 0 x = x
   f n x = g [] (not x)
   g [] y = f 10 y
   g _  y = f 9  y

After typechecking we'll get
  f_mono_ty :: a -> Bool -> Bool
  g_mono_ty :: [b] -> Bool -> Bool
with constraints
  (Eq a, Num a)

Note that f is polymorphic in 'a' and g in 'b'; and these are not linked.
The types we really want for f and g are
   f :: forall a. (Eq a, Num a) => a -> Bool -> Bool
   g :: forall b. [b] -> Bool -> Bool

We can get these by "impedance matching":
   tuple :: forall a b. (Eq a, Num a) => (a -> Bool -> Bool, [b] -> Bool -> Bool)
   tuple a b d1 d1 = let ...bind f_mono, g_mono in (f_mono, g_mono)

   f a d1 d2 = case tuple a Any d1 d2 of (f_mono, g_mono) -> f_mono
   g b = case tuple Integer b dEqInteger dNumInteger of (f_mono,g_mono) -> g_mono
```

### Fact 3: Wrapper Applied in Single Export Case
**Source:** `compiler/GHC/HsToCore/Binds.hs:280-308`
**Comment:** For the common single-export case, `dsHsWrapper` converts the HsWrapper to a Core-level function transformer `core_wrap :: CoreExpr -> CoreExpr`, which is applied around the lambda-abstracted body.
```haskell
| [export] <- exports
, ABE { abe_poly = global_id, abe_mono = local_id
      , abe_wrap = wrap, abe_prags = prags } <- export
...
= do { dsHsWrapper wrap $ \core_wrap -> do -- Usually the identity
     { let rhs = core_wrap $
                 mkLams tyvars $ mkLams dicts $
                 mkCoreLets ds_ev_binds $
                 body
       ... } }
```

### Fact 4: Wrapper Applied in General Case with Tuple Selector
**Source:** `compiler/GHC/HsToCore/Binds.hs:361-377`
**Comment:** In the general case, the wrapper is applied around the lambda-abstracted tuple selector. The wrapper transforms the type from the group-generalized tuple projection to the individual polymorphic type.
```haskell
; let mk_bind (ABE { abe_wrap = wrap
                   , abe_poly = global
                   , abe_mono = local, abe_prags = spec_prags })
                   -- See Note [ABExport wrapper] in "GHC.Hs.Binds"
        = do { tup_id  <- newSysLocalMDs tup_ty
             ; dsHsWrapper wrap $ \core_wrap -> do
             { let rhs = core_wrap $ mkLams tyvars $ mkLams dicts $
                         mkBigTupleSelector all_locals local tup_id $
                         mkVarApps (Var poly_tup_id) (tyvars ++ dicts)
               ... } }
```

### Fact 5: Wrapper is Identity When Types Match Exactly
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:921-922` and `compiler/GHC/Tc/Types/Evidence.hs:499`
**Comment:** The fast path returns `idHsWrapper` (which is `WpHole`) when `sel_poly_ty` and `poly_ty` are exactly equal (modulo visibility). This is the common case.
```haskell
; wrap <- if sel_poly_ty `eqType` poly_ty  -- NB: eqType ignores visibility
          then return idHsWrapper  -- Fast path
          else tcSubTypeSigma ...
```
And in Evidence.hs:
```haskell
idHsWrapper = WpHole
```

### Fact 6: HsWrapper Desugars to CoreExpr -> CoreExpr
**Source:** `compiler/GHC/HsToCore/Binds.hs:1596-1614`
**Comment:** `dsHsWrapper` recursively translates HsWrapper constructors into Core expression transformers. WpHole becomes identity, WpCast becomes mkCastDs, WpTyLam becomes Lam, WpEvApp becomes App with evidence term, etc.
```haskell
ds_hs_wrapper :: HsWrapper
              -> ((CoreExpr -> CoreExpr) -> DsM a)
              -> DsM a
ds_hs_wrapper hs_wrap
  = go hs_wrap
  where
    go WpHole            k = k $ \e -> e
    go (WpSubType w)     k = go (optSubTypeHsWrapper w) k
    go (WpTyApp ty)      k = k $ \e -> App e (Type ty)
    go (WpEvLam ev)      k = k $ Lam ev
    go (WpTyLam tv)      k = k $ Lam tv
    go (WpCast co)       k = assert (coercionRole co == Representational) $
                             k $ \e -> mkCastDs e co
    go (WpEvApp tm)      k = do { core_tm <- dsEvTerm tm
                                ; k $ \e -> e `App` core_tm }
    go (WpLet ev_binds)  k = dsTcEvBinds ev_binds $ \bs ->
                             k (mkCoreLets bs)
```

### Fact 7: ABExport Wrapper Note Explains the Core Scenario
**Source:** `compiler/GHC/Hs/Binds.hs:399-415`
**Comment:** The note gives a concrete example where `f` and `g` are extracted from a tuple with more type variables than either individually needs. The wrapper handles the mismatch between the tuple's generalized type and each export's actual type.
```haskell
Note [ABExport wrapper]
~~~~~~~~~~~~~~~~~~~~~~~
Consider
   (f,g) = (\x.x, \y.y)
This ultimately desugars to something like this:
   tup :: forall a b. (a->a, b->b)
   tup = /\a b. (\x:a.x, \y:b.y)
   f :: forall a. a -> a
   f = /\a. case tup a Any of
               (fm::a->a,gm:Any->Any) -> fm
   ...similarly for g...

The abe_wrap field deals with impedance-matching between
    (/\a b. case tup a b of { (f,g) -> f })
and the thing we really want, which may have fewer type
variables.  The action happens in GHC.Tc.Gen.Bind.mkExport.
```

### Fact 8: tcPolyCheck Uses Identity Wrapper
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:613`
**Comment:** When a binding has a complete type signature (`tcPolyCheck`), the mono_id is created with exactly the signature's rho type, and the wrapper is always identity because there is no inference gap to bridge.
```haskell
export = ABE { abe_wrap  = idHsWrapper
             , abe_poly  = poly_id
             , abe_mono  = poly_id2
             , abe_prags = SpecPrags spec_prags }
```

## Claims

### Claim 1: The Wrapper is Identity in the Common Case
**Analysis:** References Fact 1 and Fact 5. In `mkExport`, the wrapper is `idHsWrapper` (WpHole) when `sel_poly_ty `eqType` poly_ty`. This fast path is taken when the group-generalized type exactly matches the individual poly id's type. This is the common case for simple bindings where all type variables and constraints are shared uniformly across the group. The comment "Usually the identity" at `GHC/HsToCore/Binds.hs:289` confirms this.
**Status:** Validated
**Validation:** VALIDATED: Yes, Source Check: Verified, Logic Check: Sound
**Confidence:** High

### Claim 2: Impedance Matching Handles Type Variable Mismatch via Subsumption
**Analysis:** References Fact 1, Fact 2, and Fact 7. When a binding group is generalized jointly, the "group type" quantifies over all type variables and constraints shared by the group. But each individual binding may only need a subset. For example, `f` needs `a` but not `b`, while `g` needs `b` but not `a`. The wrapper is computed by `tcSubTypeSigma` which checks that the group type `forall qtvs. theta => mono_ty` is more polymorphic than the individual `poly_ty`. The resulting `HsWrapper` captures the instantiation (type applications, evidence applications, and possibly casts) needed to transform from the group type to the individual type. This can involve defaulting (e.g., `Num a` defaulting to `Integer`).
**Status:** Validated
**Validation:** VALIDATED: Yes, Source Check: Verified, Logic Check: Sound
**Confidence:** High

### Claim 3: The Wrapper is Applied as a Core-Level Expression Transformer in All Desugaring Cases
**Analysis:** References Fact 3, Fact 4, and Fact 6. In all three branches of `dsAbsBinds` (single export at line 289, no-tyvar at line 326, general case at line 366), `dsHsWrapper` converts the `HsWrapper` into `core_wrap :: CoreExpr -> CoreExpr`. This transformer is composed with the lambda-abstracted body. For single export: `core_wrap $ mkLams tyvars $ mkLams dicts $ ... body`. For general case: `core_wrap $ mkLams tyvars $ mkLams dicts $ mkBigTupleSelector ...`. When the wrapper is identity (WpHole), `core_wrap` is `\e -> e` and has no effect. When non-identity, it inserts type applications, evidence applications, or casts as needed.
**Status:** Validated
**Validation:** VALIDATED: Yes, Source Check: Verified, Logic Check: Sound
**Confidence:** High

### Claim 4: Wrapper Non-Identity Arises from Partial Type Signatures and Non-Uniform Constraint Distribution
**Analysis:** References Fact 1, Fact 2, and Fact 8. The wrapper is non-identity in two main scenarios: (1) When bindings in a group have different sets of quantified type variables (as in the `f`/`g` example in Note [Impedance matching]), and (2) When some bindings have partial type signatures that constrain the generalized type differently than the group type. The `tcPolyCheck` case (complete signature) always uses identity because the signature fully determines the type with no inference gap. The `mkExport` case (inferred/generalized) is where the impedance matching occurs.
**Status:** Partial
**Validation:** VALIDATED: Partial, Source Check: Partial, Logic Check: Sound
**Confidence:** Medium

## Notes

**Note 1:** The term "impedance matching" is an electrical engineering analogy: the group type is like a transmission line with certain characteristics, and each individual binding may need a "matching network" (the wrapper) to adapt to its specific type.

**Note 2:** The `sel_poly_ty = mkInfSigmaTy qtvs theta mono_ty` constructs the type "as if" the binding were generalized with the group's full set of type variables and constraints. The `poly_ty = idType poly_id` is the actual generalized type, which may have fewer quantifiers. The wrapper proves the subsumption relation.

**Note 3:** The `eqType` fast path ignores visibility (Inferred vs Specified), which is why the comment notes "Inferred vs. Specified doesn't matter" for the `tcSubType` call.

## Open Questions

- [ ] What specific HsWrapper constructors are produced by `tcSubTypeSigma` in the impedance matching case? (WpTyApp? WpEvApp? WpCast?)
- [ ] Can the wrapper ever involve WpLet (evidence bindings) in the impedance matching case?
- [ ] How does deep subsumption interact with impedance matching? (See Note [Deep subsumption and WpSubType])
- [ ] Are there test cases in the GHC test suite that exercise non-identity impedance matching wrappers?

## Related Topics
- `ABSBINDS_CORE_TRANSLATION_EXPLORATION.md` — Parent exploration on AbsBinds Core translation
- `POLY_RECURSIVE_BINDINGS_GHC.md` — Broader coverage of the typechecking pipeline
- `compiler/GHC/Tc/Types/Evidence.hs` — HsWrapper data type and operations
- `compiler/GHC/Tc/Utils/Unify.hs` — tcSubTypeSigma implementation
