# MatchResult Failure Handler and DsWrapper Mechanics

**Status:** Validated
**Last Updated:** 2026-04-13
**Central Question:** How does GHC's HsToCore pattern match compiler manage auxiliary bindings (`DsWrapper`) and prevent duplication of failure expressions when combining and extracting `MatchResult` values?

## Summary

During HsToCore desugaring, `tidy1` simplifies patterns and produces `DsWrapper` values (extra bindings). These wrappers do **not** live inside `EquationInfo`; they float alongside equations and are composed in bulk by `match`. Meanwhile, `MatchResult` encodes potential failure via CPS (`MR_Fallible`). When sibling groups are combined with `combineMatchResults`, they form a right-nested chain where earlier groups fall through to later groups on failure. However, a single `MatchResult` can reference its failure parameter in multiple places (e.g., `DEFAULT` branch plus every alternative in a case expression). `shareFailureHandler` exists to prevent **intra-group** duplication by let-binding the failure expression once before it is used in multiple alternatives.

## Scope

**IN:**
- `tidy1`, `tidyEqnInfo`, and `DsWrapper` propagation
- `match` column processing and wrapper bulk application
- `combineMatchResults` sibling chaining
- `shareFailureHandler` and `mkFailurePair`
- `extractMatchResult` top-level extraction
- `mkCoPrimCaseMatchResult` and `mkDataConCase` as sources of multi-use `fail`

**OUT:**
- Core optimizer behavior after desugaring
- CPR analysis details
- Pattern coverage checking (LYG)

## Entry Points

- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:197-213` — `match` function
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:391-405` — `tidyEqnInfo`
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:407-433` — `tidy1`
- `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:218-234` — `extractMatchResult`, `combineMatchResults`
- `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:279-284` — `mkCoPrimCaseMatchResult`
- `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:346-388` — `mkDataConCase`
- `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:824-848` — `mkFailurePair`, `shareFailureHandler`

## Assumptions to Validate

1. `EquationInfo` contains no field for `DsWrapper`; wrappers float alongside it.
2. `match` applies all `DsWrapper`s from a column in bulk via `foldr (.) id` around the entire `MatchResult`.
3. `combineMatchResults` builds a right-nested CPS chain of failure handlers.
4. A single `MatchResult` can use its failure parameter in multiple case alternatives.
5. `shareFailureHandler` is called from both `combineMatchResults` and `extractMatchResult`, not only from sibling combination.
6. `mkFailurePair` wraps the failure expression in `\_ -> expr` so it can be let-bound safely (unboxed types, CPR avoidance).

## Investigation Plan

1. Verify `EquationInfo` has no wrapper field in `Monad.hs`.
2. Verify `tidyEqnInfo` returns `(DsWrapper, EquationInfo)` and `match` collects them.
3. Verify `combineMatchResults` creates the right-nested chain.
4. Verify `mkCoPrimCaseMatchResult` and `mkDataConCase` use `fail` in multiple alternatives.
5. Trace all call sites of `shareFailureHandler` to confirm the complete hierarchy.
6. Verify `mkFailurePair` generates a lambda wrapper.

## Claims

### Claim 1: EquationInfo Has No Field for DsWrapper

**Statement:** The `EquationInfo` data type does not contain a `DsWrapper` field. `DsWrapper` values produced by `tidy1` float alongside `EquationInfo` as separate return values and are only later composed by `match`.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Monad.hs:139-150`

**Evidence:**
```haskell
data EquationInfo
  = EqnMatch  { eqn_pat :: LPat GhcTc
              , eqn_rest :: EquationInfo }
  | EqnDone   (MatchResult CoreExpr)
```

And `tidyEqnInfo` returns a tuple:
```haskell
tidyEqnInfo :: Id -> EquationInfo -> DsM (DsWrapper, EquationInfo)
tidyEqnInfo v eqn@(EqnMatch { eqn_pat = (L loc pat) }) = do
  (wrap, pat') <- tidy1 v (...) pat
  return (wrap, eqn{eqn_pat = L loc pat' })
```

**Status:** Validated
**Confidence:** High
**Validated:** 2026-04-13

---

### Claim 2: match Applies DsWrappers in Bulk Around the Entire Column Result

**Statement:** In `match`, the wrappers from all equations in the current column are collected into `[DsWrapper]`, composed with `foldr (.) id`, and applied to the entire `MatchResult CoreExpr` for that column via `<$>`.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:203, 211-212`

**Evidence:**
```haskell
match (v:vs) ty eqns = do
  { (aux_binds, tidy_eqns) <- mapAndUnzipM (tidyEqnInfo v) eqns
  ; let grouped = groupEquations platform tidy_eqns
  ; match_results <- match_groups grouped
  ; return $ foldr (.) id aux_binds <$>
      foldr1 combineMatchResults match_results
  }
```

**Status:** Validated
**Confidence:** High
**Validated:** 2026-04-13

---

### Claim 3: combineMatchResults Builds a Right-Nested CPS Chain

**Statement:** `combineMatchResults` links two `MatchResult` values so that the first group's failure handler is the result of running the second group with the top-level failure expression. This creates a right-nested structure.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:224-234`

**Evidence:**
```haskell
combineMatchResults match_result1@(MR_Infallible _) _
  = match_result1
combineMatchResults match_result1 match_result2 =
  case shareFailureHandler match_result1 of
    MR_Infallible _ -> match_result1
    MR_Fallible body_fn1 -> MR_Fallible $ \fail_expr ->
      body_fn1 =<< runMatchResult fail_expr match_result2
```

**Status:** Validated
**Confidence:** High
**Validated:** 2026-04-13

---

### Claim 4: A Single MatchResult Can Use Its Fail Parameter in Multiple Alternatives

**Statement:** `mkCoPrimCaseMatchResult` passes the `fail` parameter into every literal alternative via `mapM (mk_alt fail)` and also places it directly in the `DEFAULT` branch, meaning a single `MatchResult` uses `fail` in multiple case alternatives.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:279-284`

**Evidence:**
```haskell
mkCoPrimCaseMatchResult var ty match_alts
  = MR_Fallible mk_case
  where
    mk_case fail = do
        alts <- mapM (mk_alt fail) sorted_alts
        return (Case (Var var) var ty (Alt DEFAULT [] fail : alts))
```

Similarly, `mkDataConCase` threads `fail` into every constructor alternative plus the `DEFAULT` branch via `traverse mk_alt` combined with `mk_default` under `liftA2`.

**Status:** Validated
**Confidence:** High
**Validated:** 2026-04-13

---

### Claim 5: shareFailureHandler Is Called from Both Sibling Combination and Top-Level Extraction

**Statement:** `shareFailureHandler` is invoked from `combineMatchResults` (sibling chaining inside `match`), from `extractMatchResult` (top-level extraction in `matchEquations` and `matchSinglePat`), and from `dsHandleMonadicFailure`.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:222, 230, 879`

**Evidence:**
```haskell
extractMatchResult match_result failure_expr =
  runMatchResult failure_expr (shareFailureHandler match_result)

combineMatchResults match_result1 match_result2 =
  case shareFailureHandler match_result1 of ...

dsHandleMonadicFailure ctx pat res_ty match m_fail_op =
  case shareFailureHandler match of ...
```

**Status:** Draft
**Confidence:** High

---

### Claim 6: mkFailurePair Wraps the Failure Expression in a Lambda

**Statement:** `mkFailurePair` wraps the failure expression in `\ _ -> expr` and creates a binding `NonRec fail_fun_var (Lam real_arg expr)`, producing a shared handler `App (Var fail_fun_var) unboxedUnitExpr`.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Utils.hs:829-834`

**Evidence:**
```haskell
mkFailurePair expr = do
  fail_fun_var <- newFailLocalMDs (unboxedUnitTy `mkVisFunTyMany` ty)
  fail_fun_arg <- newSysLocalMDs unboxedUnitTy
  let real_arg = setOneShotLambda fail_fun_arg
  return ( NonRec fail_fun_var (Lam real_arg expr)
         , App (Var fail_fun_var) unboxedUnitExpr )
```

**Status:** Validated
**Confidence:** High
**Validated:** 2026-04-13

---

## Exploration Topics

- [ ] **Why `mkFailurePair` uses unboxed unit:** Is it purely for CPR/thunk avoidance, or does it also solve a type-system issue with unboxed result types?
- [ ] **`mkDataConCase` exact duplication scenario:** Can we construct a concrete example where `shareFailureHandler` avoids exponential code blow-up?
- [ ] **Interaction with `aux_binds` and `shareFailureHandler`:** Do the `DsWrapper` bulk lets and the failure-handler let ever get reordered or interfere?
- [ ] **Monadic failure path:** How does `dsHandleMonadicFailure` differ from the regular `matchEquations` path in terms of failure expression sharing?

## Related Topics

- [PGANY_AND_PATCO_EXPLORATION.md](PGANY_AND_PATCO_EXPLORATION.md) — How patterns become `PgAny`/`PgCo` and how `tidy1` produces wrappers.
- [EQUATION_GROUPING_EXPLORATION.md](EQUATION_GROUPING_EXPLORATION.md) — The broader grouping algorithm and `MatchResult` CPS overview.
