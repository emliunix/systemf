# Closure Flow in GHC Type Inference: From matchExpectedFunTys to RHS

**Status:** Validated  
**Last Updated:** 2026-04-10  
**Central Question:** How does the closure callback in matchExpectedFunTys handle patterns and coordinate RHS type checking across multiple branches?

---

## Summary

This exploration traces the flow from `matchExpectedFunTys` through the closure callback (`thing_inside`) to the actual RHS type checking. When `matchExpectedFunTys` decomposes a function type into argument types and result type, it calls a callback with these types. This callback chain goes through `tcFunBindMatches` → `tcMatches` → `tcMatchPats` → `tcGRHSs` → `tcGRHSNE` → `tcBody` → `tcPolyLExpr`.

The critical mechanism is that the **same `ExpRhoType` (result type) is shared across all branches/equations**, enabling type coordination through hole filling (Infer mode) or validation (Check mode).

---

## Claims

### Claim 1: matchExpectedFunTys creates Infer holes, not raw meta variables

**Statement:** In Infer mode, `matchExpectedFunTys` creates `ExpType/Infer` objects (typed holes via `InferResult`), not direct meta type variables. These holes are mutable cells that get filled during type checking.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:809-822`

**Evidence:**
```haskell
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside
  = do { arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]
       ; res_ty  <- newInferExpType (ir_inst inf_res)     -- Creates Infer (IR {...})
       ; result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty
       ; ... }
```

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/TcMType.hs:433-441`

**Evidence:**
```haskell
new_inferExpType iif ifrr
  = do { u <- newUnique
       ; tclvl <- getTcLevel
       ; ref <- newMutVar Nothing  -- Mutable hole
       ; return (Infer (IR { ir_uniq = u, ir_lvl = tclvl
                           , ir_inst = iif, ir_frr  = ifrr
                           , ir_ref  = ref })) }  -- Infer with mutable hole
```

**Status:** Validated  
**Confidence:** High

---

### Claim 2: The closure callback receives pat_tys and rhs_ty via thing_inside

**Statement:** After decomposing the function type, `matchExpectedFunTys` calls `thing_inside pat_tys rhs_ty` where `pat_tys` are the argument types and `rhs_ty` is the shared result type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:812`

**Evidence:**
```haskell
result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty  -- Callback invocation
```

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:120-131`

**Evidence:**
```haskell
tcFunBindMatches ctxt fun_name mult matches invis_pat_tys exp_ty
  = ...
    do { (wrap_fun, r)
            <- matchExpectedFunTys herald ctxt arity exp_ty $ \ pat_tys rhs_ty ->  -- Receives args
               tcScalingUsage mult $
               do { ...
                    ; tcMatches mctxt tcBody (invis_pat_tys ++ pat_tys) rhs_ty matches } }  -- Passes to tcMatches
```

**Status:** Validated  
**Confidence:** High

---

### Claim 3: tcMatches passes the SAME rhs_ty to all match branches

**Statement:** `tcMatches` iterates over all match alternatives using the same `rhs_ty` (ExpRhoType), ensuring all branches coordinate their result types through the same hole or expected type.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:250`

**Evidence:**
```haskell
umatches <- mapM (tcCollectingUsage . tcMatch tc_body pat_tys rhs_ty) matches
                                                     -- ^^^ SAME rhs_ty for ALL matches
```

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:306-320`

**Evidence:**
```haskell
tcMatch tc_body pat_tys rhs_ty match  -- rhs_ty passed through
  = do { ...
         do { (pats', (grhss')) <- tcMatchPats ctxt pats pat_tys $
                                   tcGRHSs ctxt tc_body grhss rhs_ty  -- SAME rhs_ty
```

**Status:** Validated  
**Confidence:** High

---

### Claim 4: Multiple guarded RHS share the same res_ty through tcGRHSNE

**Statement:** Within a single match, multiple guarded right-hand sides (GRHS) are processed by `tcGRHSNE` which traverses all guards and the final RHS expression using the same `res_ty`.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:359-373`

**Evidence:**
```haskell
tcGRHSNE ctxt tc_body grhss res_ty  -- res_ty shared
   = do { (usages, grhss') <- unzip <$> traverse (wrapLocSndMA tc_alt) grhss
        ; ... }
  where
    tc_alt (GRHS _ guards rhs)
      = tcCollectingUsage $
        do { (guards', rhs')
                 <- tcStmtsAndThen stmt_ctxt tcGuardStmt guards res_ty $
                    tc_body rhs  -- tc_body called with SAME res_ty for each GRHS
```

**Status:** Validated  
**Confidence:** High

---

### Claim 5: tcBody dispatches to tcPolyLExpr with the shared ExpRhoType

**Statement:** `tcBody` is the final function in the chain that receives the shared `ExpRhoType` and dispatches to `tcPolyLExpr` for actual expression type checking.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:418-421`

**Evidence:**
```haskell
tcBody :: LHsExpr GhcRn -> ExpRhoType -> TcM (LHsExpr GhcTc)
tcBody body res_ty
  = do  { traceTc "tcBody" (ppr res_ty)
        ; tcPolyLExpr body res_ty }  -- Dispatches to expression checker
```

**Status:** Validated  
**Confidence:** High

---

### Claim 6: Branch coordination works via hole filling in Infer mode

**Statement:** When multiple branches (function equations or case alternatives) typecheck in Infer mode, the first branch fills the shared hole with its inferred type, and subsequent branches unify their types with the already-filled hole, naturally implementing type joining.

**Source:** `upstream/ghc/compiler/GHC/Tc/Utils/Unify.hs:1122-1169`

**Evidence:**
```haskell
fillInferResultNoInst act_res_ty (IR { ir_ref = ref, ir_lvl = res_lvl, ... })
  = do { mb_exp_res_ty <- readTcRef ref
       ; case mb_exp_res_ty of
            Just exp_res_ty  -- HOLE ALREADY FILLED
               -> do { ...
                     ; unifyType Nothing act_res_ty exp_res_ty }  -- UNIFY with existing
            Nothing          -- HOLE EMPTY
               -> do { ...
                     ; writeTcRef ref (Just act_res_ty) } }  -- FILL hole
```

**Status:** Validated  
**Confidence:** High

---

### Claim 7: Check mode validates each branch against the expected type

**Statement:** In Check mode, the shared `res_ty` is `Check expected_ty`, so each branch typechecks against the same expected type. If any branch fails to match, a type error is raised immediately.

**Source:** `upstream/ghc/compiler/GHC/Tc/Gen/Match.hs:418-421` (with Check context)

**Evidence:**
```haskell
tcBody body res_ty  -- res_ty could be Check expected_ty
  = do  { ...
        ; tcPolyLExpr body res_ty }  -- Typechecks body against res_ty
```

**Status:** Validated  
**Confidence:** Medium (behavior is implied but not explicitly shown in this specific location)

---

## Open Questions

- [ ] How does tcPolyLExpr handle the dispatch to tcExpr vs tcCheckPolyExpr?
- [ ] What happens when matchExpectedFunTys encounters a polymorphic expected type in Check mode?
- [ ] How does the pattern type checking (tcMatchPats) extend the environment before RHS checking?

---

## Related Topics

- `LET_BINDING_ARCHITECTURE_EXPLORATION.md` - Higher-level let binding flow
- `MATCHEXPECTEDFUNTYS_EXPLORATION.md` - matchExpectedFunTys function details

---

## Evidence Index

| Claim | Primary Source | Supporting Source |
|-------|---------------|-------------------|
| 1 | Unify.hs:809-822 | TcMType.hs:433-441 |
| 2 | Unify.hs:812 | Match.hs:120-131 |
| 3 | Match.hs:250 | Match.hs:306-320 |
| 4 | Match.hs:359-373 | - |
| 5 | Match.hs:418-421 | - |
| 6 | Unify.hs:1122-1169 | - |
| 7 | Match.hs:418-421 | (implied behavior) |

---

## Validation Notes

**Completed:** 2026-04-10

| Claim | Validated | Source Check | Logic Check | Notes |
|-------|-----------|--------------|-------------|-------|
| **1** | ✅ Yes | ✅ Verified | ✅ Sound | `matchExpectedFunTys` creates `Infer` holes via `newInferExpType` |
| **2** | ✅ Yes | ✅ Verified | ✅ Sound | Callback receives `pat_tys` and `rhs_ty`, passed to `tcMatches` |
| **3** | ✅ Yes | ✅ Verified | ✅ Sound | Same `rhs_ty` passed to all branches via `mapM` |
| **4** | ✅ Yes | ✅ Verified | ✅ Sound | `tcGRHSNE` shares `res_ty` across all GRHS alternatives |
| **5** | ✅ Yes | ✅ Verified | ✅ Sound | `tcBody` dispatches to `tcPolyLExpr` |
| **6** | ✅ Yes | ✅ Verified | ✅ Sound | `fillInferResultNoInst` implements hole filling/unification |
| **7** | ⚠️ Partial | ⚠️ Mismatch | ⚠️ Questionable | Claim cites correct function but wrong evidence for Check mode behavior |

**Overall:** 6 of 7 claims fully validated. Claim 7 has correct concept but needs better evidence citation.

**Status:** Validated