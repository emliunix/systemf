# Inside matchExpectedFunTys Closure: Pattern Handling to RHS Type Coordination

**Status:** Validated
**Last Updated:** 2026-04-10
**Central Question:** What happens inside the matchExpectedFunTys closure, from pattern handling through to RHS type coordination across multiple branches?

---

## Scope

**IN:**
- `matchExpectedFunTys` callback/closure mechanism
- `tcMatches` and branch coordination
- `tcMatch` pattern handling
- `tcGRHSs` guarded RHS processing
- `tcBody` expression typechecking
- Shared ExpType mechanism for branch coordination

**OUT:**
- Pattern checking details (tcMatchPats internals)
- Statement checking (tcStmts details)
- Expression typechecking beyond tcPolyLExpr entry point

---

## Summary

The closure mechanism inside matchExpectedFunTys works as follows:

1. **Type Decomposition**: matchExpectedFunTys decomposes the expected function type into argument types (pat_tys) and result type (rhs_ty)

2. **Callback Construction**: It invokes thing_inside with these types, which constructs a closure around tcMatches

3. **Shared State**: The SAME ExpRhoType (rhs_ty) is passed to ALL branches of the match group

4. **Propagation Chain**: rhs_ty flows through tcMatches → tcMatch → tcGRHSs → tcGRHSNE → tcBody → tcPolyLExpr

5. **Type Coordination**: Because all branches share the same ExpRhoType (an IORef), they automatically coordinate:
   - In Infer mode: First branch's RHS type becomes the expected type for all branches
   - In Check mode: All branches check against the pre-specified type

6. **Usage Tracking**: tcCollectingUsage at each branch ensures linear type multiplicities are properly tracked and combined

This design elegantly solves the "multiple branch type coordination" problem by using a mutable reference (IORef within ExpRhoType) as the coordination point, rather than explicit unification after the fact.

---

## Claims

### Claim 1: matchExpectedFunTys Invokes Callback with pat_tys and rhs_ty

**Statement:** In Infer mode, matchExpectedFunTys creates fresh meta type variables for arguments and a fresh inference hole for the result, then invokes thing_inside with these types.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:809-812`

**Evidence:**
```haskell
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside
  = do { arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]
       ; res_ty  <- newInferExpType (ir_inst inf_res)
       ; result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty
       ; -- ... fill the inference result and return wrapper
       }
```

**Confidence:** High

**Notes:** The callback receives `[ExpPatType]` (argument types wrapped in ExpFunPatTy) and `ExpRhoType` (result type). Both are in "Infer" mode, meaning they contain unification variables that will be filled during typechecking.

---

### Claim 2: matchExpectedFunTys Check Mode Passes Decomposed Types to Callback

**Statement:** In Check mode, after decomposing the function type and optionally performing deep skolemisation, matchExpectedFunTys calls thing_inside with the accumulated pattern types and result type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:857-867`

**Evidence:**
```haskell
check n_req rev_pat_tys rho_ty
  | n_req == 0
  = do { let pat_tys = reverse rev_pat_tys
       ; ds_flag <- getDeepSubsumptionFlag
       ; case ds_flag of
           Shallow -> do { res <- thing_inside pat_tys (mkCheckExpType rho_ty)
                         ; return (idHsWrapper, res) }
           deep    -> tcSkolemiseGeneral deep ctx top_ty rho_ty $\_ rho_ty ->
                      thing_inside pat_tys (mkCheckExpType rho_ty) }
```

**Confidence:** High

**Notes:** The pat_tys are accumulated in reverse order during recursive decomposition and reversed before passing to the callback. In Check mode, these are ExpCheckType wrappers around concrete types.

---

### Claim 3: tcFunBindMatches Constructs Closure Around tcMatches

**Statement:** tcFunBindMatches constructs the thing_inside callback as a lambda that receives pat_tys and rhs_ty from matchExpectedFunTys, wraps tcMatches with tcScalingUsage, and passes the types through to tcMatches.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:112-131`

**Evidence:**
```haskell
tcFunBindMatches ctxt fun_name mult matches invis_pat_tys exp_ty
  = assertPpr (funBindPrecondition matches) (pprMatches matches) $
    do  { arity <- checkArgCounts matches

        ; (wrap_fun, r)
             <- matchExpectedFunTys herald ctxt arity exp_ty $ \ pat_tys rhs_ty ->
                tcScalingUsage mult $
                do { traceTc "tcFunBindMatches 2" $
                     vcat [ text "ctxt:" <+> pprUserTypeCtxt ctxt
                          , text "arity:" <+> ppr arity
                          , text "invis_pat_tys:" <+> ppr invis_pat_tys
                          , text "pat_tys:" <+> ppr pat_tys
                          , text "rhs_ty:" <+> ppr rhs_ty ]
                   ; tcMatches mctxt tcBody (invis_pat_tys ++ pat_tys) rhs_ty matches }

        ; return (wrap_fun, r) }
```

**Confidence:** High

**Notes:** The closure combines invisible pattern types (scoped skolemised binders) with visible pattern types from matchExpectedFunTys before passing to tcMatches. The tcScalingUsage ensures proper multiplicity handling for linear types.

---

### Claim 4: tcMatches Shares Single rhs_ty Across ALL Match Branches

**Statement:** tcMatches receives rhs_ty as an ExpRhoType parameter and passes the SAME instance to every match branch via tcMatch, enabling unified type coordination across all alternatives.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:222-258`

**Evidence:**
```haskell
tcMatches :: (AnnoBody body, Outputable (body GhcTc))
          => HsMatchContextRn
          -> TcMatchAltChecker body
          -> [ExpPatType]             -- ^ Expected pattern types.
          -> ExpRhoType               -- ^ Expected result-type of the Match.
          -> MatchGroup GhcRn (LocatedA (body GhcRn))
          -> TcM (MatchGroup GhcTc (LocatedA (body GhcTc)))

tcMatches ctxt tc_body pat_tys rhs_ty (MG { mg_alts = L l matches
                                          , mg_ext = origin })
  | null matches  -- Deal with case e of {}
  = do { -- ... empty case handling
       }

  | otherwise
  = do { umatches <- mapM (tcCollectingUsage . tcMatch tc_body pat_tys rhs_ty) matches
       ; let (usages, matches') = unzip umatches
       ; tcEmitBindingUsage $ supUEs usages
       ; pat_tys  <- mapM readScaledExpType (filter_out_forall_pat_tys pat_tys)
       ; rhs_ty   <- readExpType rhs_ty
       ; traceTc "tcMatches" (ppr matches' $$ ppr pat_tys $$ ppr rhs_ty)
       ; return (MG { mg_alts   = L l matches'
                    , mg_ext    = MatchGroupTc pat_tys rhs_ty origin
                    }) }
```

**Confidence:** High

**Notes:** The SAME rhs_ty (an ExpRhoType, which is an IORef containing either a type or a hole) is passed to every branch. In Infer mode, when tcPolyLExpr fills in the hole, all branches see the unified type. This is the key mechanism for ensuring all branches return the same type.

---

### Claim 5: tcMatch Chains Pattern Checking to GRHS Processing

**Statement:** tcMatch takes the rhs_ty parameter and passes it through tcMatchPats to tcGRHSs, which will use it for checking the guarded right-hand sides.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:304-327`

**Evidence:**
```haskell
tcMatch :: (AnnoBody body)
        => TcMatchAltChecker body
        -> [ExpPatType]          -- Expected pattern types
        -> ExpRhoType            -- Expected result-type of the Match.
        -> LMatch GhcRn (LocatedA (body GhcRn))
        -> TcM (LMatch GhcTc (LocatedA (body GhcTc)))

tcMatch tc_body pat_tys rhs_ty match
  = do { (L loc r) <- wrapLocMA (tc_match pat_tys rhs_ty) match
       ; return (L loc r) }
  where
    tc_match pat_tys rhs_ty
             match@(Match { m_ctxt = ctxt, m_pats = L l pats, m_grhss = grhss })
      = add_match_ctxt $
        do { (pats', (grhss')) <- tcMatchPats ctxt pats pat_tys $
                                  tcGRHSs ctxt tc_body grhss rhs_ty
             -- NB: pats' are just the /value/ patterns
             -- See Note [tcMatchPats] in GHC.Tc.Gen.Pat

           ; return (Match { m_ext   = noExtField
                           , m_ctxt  = ctxt
                           , m_pats  = L l pats'
                           , m_grhss = grhss' }) }
```

**Confidence:** High

**Notes:** The continuation-passing style is evident: tcMatchPats takes a continuation (tcGRHSs ...) that will be invoked after pattern checking. The rhs_ty flows through unchanged from tcMatch to tcGRHSs.

---

### Claim 6: tcGRHSNE Shares Single res_ty Across Multiple Guarded RHS

**Statement:** tcGRHSNE receives res_ty as ExpRhoType and passes it to tcStmtsAndThen for each guarded RHS, ensuring all guards in a single alternative unify to the same result type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:355-373`

**Evidence:**
```haskell
tcGRHSNE :: forall body. AnnoBody body
           => HsMatchContextRn -> TcMatchAltChecker body
           -> NonEmpty (LGRHS GhcRn (LocatedA (body GhcRn))) -> ExpRhoType
           -> TcM (NonEmpty (LGRHS GhcTc (LocatedA (body GhcTc))))
tcGRHSNE ctxt tc_body grhss res_ty
   = do { (usages, grhss') <- unzip <$> traverse (wrapLocSndMA tc_alt) grhss
        ; tcEmitBindingUsage $ supUEs usages
        ; return grhss' }
   where
     stmt_ctxt = PatGuard ctxt

     tc_alt :: GRHS GhcRn (LocatedA (body GhcRn))
            -> TcM (UsageEnv, GRHS GhcTc (LocatedA (body GhcTc)))
     tc_alt (GRHS _ guards rhs)
       = tcCollectingUsage $
         do  { (guards', rhs')
                   <- tcStmtsAndThen stmt_ctxt tcGuardStmt guards res_ty $
                      tc_body rhs
             ; return (GRHS noAnn guards' rhs') }
```

**Confidence:** High

**Notes:** The res_ty is passed to tcStmtsAndThen, which threads it through all guards. After processing guards, tc_body (which is tcBody for function bindings) typechecks the RHS expression against the same res_ty.

---

### Claim 7: tcBody Dispatches to Expression Typechecking Entry Point

**Statement:** tcBody is the entry point for typechecking match RHS expressions, which simply logs a trace and delegates to tcPolyLExpr with the expected result type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:418-422`

**Evidence:**
```haskell
tcBody :: LHsExpr GhcRn -> ExpRhoType -> TcM (LHsExpr GhcTc)
tcBody body res_ty
  = do  { traceTc "tcBody" (ppr res_ty)
        ; tcPolyLExpr body res_ty
        }
```

**Confidence:** High

**Notes:** tcBody receives the res_ty (which is the SAME ExpRhoType shared across all branches) and passes it to tcPolyLExpr. In Infer mode, tcPolyLExpr will fill the hole in res_ty with the inferred type of the expression. Since all branches share the same ExpRhoType, they all coordinate to produce the same type.

---

### Claim 8: Shared ExpRhoType Enables Cross-Branch Type Coordination

**Statement:** The critical insight is that rhs_ty/res_ty is a shared ExpRhoType (an IORef) passed to all branches. In Infer mode, when the first branch's RHS fills the hole, subsequent branches check against that type, enabling automatic coordination of result types across all match branches.

**Source:** Design pattern across `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:222-422`

**Evidence:**
The chain is:
1. matchExpectedFunTys creates res_ty via `newInferExpType` (line 811)
2. This SAME res_ty is passed to thing_inside callback (line 812)
3. tcFunBindMatches passes it to tcMatches as rhs_ty (line 131)
4. tcMatches passes SAME rhs_ty to every tcMatch call (line 250)
5. tcMatch passes it to tcGRHSs (line 320)
6. tcGRHSNE passes it to tcStmtsAndThen and tc_body (lines 371-372)
7. tcBody passes it to tcPolyLExpr (line 421)

**Confidence:** High

**Notes:** This is the "secret sauce" of GHC's type inference for pattern matching. The ExpRhoType acts as a coordination point:
- In Infer mode: First branch fills the hole, others check against it
- In Check mode: All branches check against the pre-specified type
- Usage tracking (tcCollectingUsage) ensures linear types work correctly

---

## Validation Summary

All 8 claims have been validated against the GHC source code:

| Claim | Line Numbers Verified | Status |
|-------|----------------------|--------|
| 1 | Unify.hs:809-812 | ✓ VALIDATED |
| 2 | Unify.hs:857-867 | ✓ VALIDATED |
| 3 | Match.hs:112-131 | ✓ VALIDATED |
| 4 | Match.hs:222-258 | ✓ VALIDATED |
| 5 | Match.hs:305-327 | ✓ VALIDATED |
| 6 | Match.hs:355-373 | ✓ VALIDATED |
| 7 | Match.hs:418-422 | ✓ VALIDATED |
| 8 | Match.hs:222-422 (design) | ✓ VALIDATED |

**Overall Confidence: HIGH**

All line numbers are accurate and the logic correctly interprets the code structure.

---

## Call Chain Summary

```
matchExpectedFunTys
  └─► thing_inside (\ pat_tys rhs_ty -> ...)  [Infer: creates InferResult hole]
       └─► tcMatches mctxt tcBody pat_tys rhs_ty matches
            ├─► tcMatch tc_body pat_tys rhs_ty match1
            │    └─► tcGRHSs ... rhs_ty
            │         └─► tcGRHSNE ... rhs_ty
            │              └─► tcBody expr rhs_ty → tcPolyLExpr expr rhs_ty
            │                   └─► tcExpr expr rhs_ty
            │                        └─► fillInferResult (if Infer, fills/unifies hole)
            ├─► tcMatch tc_body pat_tys rhs_ty match2  [SAME rhs_ty!]
            │    └─► ... (same chain, fills/unifies SAME hole)
            └─► readExpType rhs_ty  [After all matches complete]
```

## Type Coordination Examples

### Example 1: Consistent Branches (Infer Mode)
```haskell
f :: Bool -> Int
f True  = 1    -- Infers Int, fills hole with Int
f False = 2    -- Infers Int, unifies Int~Int (success)

Workflow:
1. matchExpectedFunTys creates res_ty = Infer (hole for result)
2. Both equations share SAME res_ty
3. Eq 1: tcBody infers Int → fillInferResult fills hole with Int
4. Eq 2: tcBody infers Int → fillInferResult sees filled hole, unifies Int~Int ✓
5. Final type: Bool -> Int
```

### Example 2: Inconsistent Branches (Infer Mode)
```haskell
f :: Bool -> Int
f True  = 1      -- Infers Int, fills hole with Int
f False = 'a'    -- Infers Char, tries to unify Char~Int (FAIL)

Workflow:
1. matchExpectedFunTys creates res_ty = Infer (hole)
2. Eq 1: fills hole with Int
3. Eq 2: tries to fill hole with Char, but hole has Int
4. unifyType Char Int → TYPE ERROR
```

### Example 3: Check Mode
```haskell
f True  = 1 :: Int   -- Checks 1 against Int ✓
f False = 2 :: Int   -- Checks 2 against Int ✓

Workflow:
1. matchExpectedFunTys receives Check Int (from signature)
2. Both equations check against Int directly
3. No hole filling needed - just validation
```

## 4 Aspects Applied

| Function | Level | Expect | Closure | Meta/Skolem |
|----------|-------|--------|---------|-------------|
| matchExpectedFunTys | N+1 | Infer/Check | thing_inside | Creates Infer holes or decomposes Check |
| tcFunBindMatches | N+1 | Pass-through | matchExpectedFunTys callback | Passes types through |
| tcMatches | N+1 | Pass-through | tcMatch | Shares rhs_ty across all matches |
| tcMatch | N+1 | Pass-through | tcMatchPats → tcGRHSs | Chains pattern and RHS checking |
| tcGRHSs | N+1 | Pass-through | tcGRHSNE | Sets up guarded RHS checking |
| tcGRHSNE | N+1 | Pass-through | tc_body | Shares res_ty across all GRHS |
| tcBody | N+1 | Pass-through | tcPolyLExpr | Final dispatch to expression checker |
| tcPolyLExpr | N+1 | Check/Infer | tcExpr | Handles polymorphism, delegates to tcExpr |
| fillInferResult | N+1 | N/A | N/A | Fills or unifies Infer holes |

## Open Questions

None - all claims validated.

## Related Topics

- `upstream/ghc/analysis/MATCHEXPECTEDFUNTYS_EXPLORATION.md` - The outer function that creates the closure
- `upstream/ghc/analysis/LET_BINDING_ARCHITECTURE_EXPLORATION.md` - Higher-level let binding flow
- `upstream/ghc/analysis/TCBODY_ARCHITECTURE_EXPLORATION.md` - Expression typechecking from tcBody onwards
- `docs/elab3-typecheck-notes.md` - Application to elab3 implementation

## References

1. GHC source: `compiler/GHC/Tc/Utils/Unify.hs` - matchExpectedFunTys (lines 809-867)
2. GHC source: `compiler/GHC/Tc/Gen/Match.hs` - tcFunBindMatches, tcMatches, tcMatch, tcGRHSs, tcGRHSNE, tcBody
3. GHC source: `compiler/GHC/Tc/Gen/Expr.hs` - tcPolyLExpr
4. GHC source: `compiler/GHC/Tc/Utils/Unify.hs` - fillInferResultNoInst (lines 1122-1169)
