# PgAny Generation and PatCo/PatSig Relationship

**Status:** Validated
**Last Updated:** 2026-04-13
**Central Question:** How does HsToCore translate typed variable patterns (PatSig, PatVar, PatCo) into the pattern match compiler's group classification (`PgAny`, `PgCo`), and does HsToCore eliminate the apparent redundancy between `PatSig` and `PatCo`?

## Summary

This exploration investigates the pipeline from type-checked patterns to HsToCore pattern groups, focusing on two related phenomena:

1. **PgAny generation and Core conversion:** Patterns that classify as `PgAny` (variables, wildcards, lazy patterns, embedded type patterns) bypass case-expression generation at their column. But they are not no-ops: they produce bindings, selector thunks, or coercion applications. We want the full Input → Transform → Output story.

2. **PatSig / PatVar / PatCo structural relationship:** In the typechecker, a signature pattern like `(x :: Int)` is represented as a `SigPat` wrapped in a `CoPat` (via `mkHsWrapPat`). The `SigPat` constructor is preserved even though the `CoPat` already carries the coercion wrapper. This looks like duplication. We investigate whether HsToCore eliminates this redundancy and how.

See also: [EQUATION_GROUPING_EXPLORATION.md](EQUATION_GROUPING_EXPLORATION.md) for the broader grouping algorithm.

## Scope

**IN:**
- `patGroup` classification for `PgAny` and `PgCo` in HsToCore
- `tidy1` behavior for `SigPat`, `VarPat`, `CoPat`, `LazyPat`
- `matchVariables` and `matchCoercion` as the Core-generation backends for `PgAny` and `PgCo`
- The `EquationInfo` → `MatchResult CoreExpr` pipeline for patterns that become `PgAny`
- How `mkHsWrapPat` constructs `CoPat` around `SigPat`/`VarPat` in the typechecker

**OUT:**
- Details of `tcPatSig` subsumption checking logic
- Pattern coverage checking (LYG)
- Core optimizations after pattern-match desugaring

## Entry Points

- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:264-267` — `matchVariables`
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:275-285` — `matchCoercion`
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:419-427` — `tidy1` for `SigPat`, `VarPat`
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:446-458` — `tidy1` for `LazyPat`
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1271-1299` — `patGroup`
- `upstream/ghc/compiler/GHC/Hs/Utils.hs:811-820` — `mkHsWrapPat`, `mkHsWrapPatCo`
- `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:760-770` — `SigPat` typechecking

## Assumptions to Validate

1. `tidy1` strips `SigPat` entirely, so the `SigPat` constructor never survives into the grouping phase.
2. A `VarPat` inside a `CoPat` (e.g. from `mkHsWrapPat` after `tcPatSig`) becomes `PgCo`, not `PgAny`.
3. `matchCoercion` strips the `CoPat`, then recurses into `match`, which will call `tidy1` on the inner pattern — thus any nested `SigPat` or `VarPat` is handled in the next column.
4. `PgAny` is generated not only for `VarPat` and `WildPat`, but also for `LazyPat` (via `mkSelectorBinds`) and `EmbTyPat`.
5. The apparent redundancy (both `SigPat` and `CoPat` carrying type information) is resolved in HsToCore because `tidy1` removes `SigPat` while `patGroup`/`matchCoercion` consumes the `CoPat` wrapper.

## Investigation Plan

1. **Read `tidy1` exhaustively** for all `PgAny`-related and `PgCo`-related patterns.
2. **Trace `patGroup`** to confirm which source patterns map to `PgAny` vs `PgCo`.
3. **Read `matchVariables` and `matchCoercion`** to understand the exact Core generated for each group.
4. **Cross-reference with typechecker** (`GHC/Tc/Gen/Pat.hs`, `GHC/Hs/Utils.hs`) to see how `SigPat` + `VarPat` become `CoPat`-wrapped AST nodes.
5. **Synthesize** whether HsToCore eliminates the `PatSig`/`PatCo` duplication.

## Claims

### Claim 1: tidy1 Eliminates SigPat Before Grouping

**Statement:** `tidy1` in `GHC/HsToCore/Match.hs` strips `SigPat` by recursing into its inner pattern, so `SigPat` never reaches `patGroup` or the grouping algorithm.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:420`

**Evidence:**
```haskell
tidy1 v g (SigPat _ pat _)    = tidy1 v g (unLoc pat)
```

**Status:** Validated
**Confidence:** High
**Notes:** If the `SigPat` is wrapped in a `CoPat`, `tidy1` does not see it directly; `matchCoercion` strips the `CoPat` first via `getCoPat`, and then the inner pattern enters `tidy1` in the next recursive `match` call.

---

### Claim 2: VarPat Becomes WildPat Under tidy1

**Statement:** `tidy1` converts a `VarPat` into a `WildPat` plus a binding wrapper (`wrapBind var v`), removing the variable pattern from the pattern tree and moving the binding into the wrapper.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:426-427`

**Evidence:**
```haskell
tidy1 v _ (VarPat _ (L _ var))
  = return (wrapBind var v, WildPat (idType var))
```

**Status:** Validated
**Confidence:** High
**Notes:** This means `VarPat` never appears in `patGroup` directly; by the time `patGroup` sees the pattern, it is a `WildPat`, which maps to `PgAny`.

---

### Claim 3: CoPat Patterns Classify as PgCo, Not PgAny

**Statement:** In `patGroup`, a `CoPat` always maps to `PgCo` using the type of the inner pattern, regardless of whether that inner pattern is a variable, wildcard, or constructor.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1296-1297`

**Evidence:**
```haskell
patGroup platform (XPat ext) = case ext of
  CoPat _ p _      -> PgCo (hsPatType p) -- Type of inner pattern
  ExpansionPat _ p -> patGroup platform p
```

**Status:** Validated
**Confidence:** High
**Notes:** Even a coercion-wrapped variable (`CoPat wrapper (VarPat ...) ty`) becomes `PgCo`, not `PgAny`. The grouping algorithm therefore separates coercion patterns from plain variables.

---

### Claim 4: matchCoercion Strips CoPat and Handles the Wrapper Separately

**Statement:** `matchCoercion` extracts the inner pattern from `CoPat` via `getCoPat`, applies the coercion wrapper to create a new `CoreExpr` binding, and then continues matching on the unwrapped inner pattern.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:275-285`

**Evidence:**
```haskell
matchCoercion (var :| vars) ty eqns@(eqn1 :| _)
  = do  { let XPat (CoPat co pat _) = firstPat eqn1
        ; let pat_ty' = hsPatType pat
        ; var' <- newUniqueId var (idMult var) pat_ty'
        ; match_result <- match (var':vars) ty $ NE.toList $
            decomposeFirstPat getCoPat <$> eqns
        ; dsHsWrapper co $ \core_wrap -> do
        { let bind = NonRec var' (core_wrap (Var var))
        ; return (mkCoLetMatchResult bind match_result) } }
```

**Status:** Validated
**Confidence:** High
**Notes:** This is the key transformation that resolves the `CoPat`: the coercion is applied to the match variable (`core_wrap (Var var)`), bound to a fresh variable `var'`, and the rest of the match proceeds on `var'` with the inner `pat`.

---

### Claim 5: HsToCore Eliminates the PatSig/PatCo Redundancy

**Statement:** The typechecker preserves both `SigPat` and its `CoPat` wrapper, but HsToCore eliminates this redundancy: `SigPat` is stripped by `tidy1`, and the `CoPat` wrapper is consumed by `matchCoercion`. By the time Core is generated, only the coercion application remains; the signature annotation itself has vanished.

**Source:**
- Typechecker: `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:770`
- HsToCore tidy: `upstream/ghc/compiler/GHC/HsToCore/Match.hs:420`
- HsToCore match: `upstream/ghc/compiler/GHC/HsToCore/Match.hs:275-285`

**Evidence (Typechecker):**
```haskell
; return (mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty, res)
```

**Evidence (HsToCore):**
```haskell
tidy1 v g (SigPat _ pat _)    = tidy1 v g (unLoc pat)

-- In matchCoercion:
let XPat (CoPat co pat _) = firstPat eqn1
match_result <- match (var':vars) ty $ NE.toList $
    decomposeFirstPat getCoPat <$> eqns
```

**Status:** Validated
**Confidence:** High
**Notes:** `mkHsWrapPat` (`Hs/Utils.hs:811-813`) can return a bare `SigPat` if the wrapper is identity, or a `CoPat`-wrapped `SigPat` otherwise. In either case, `tidy1` (`Match.hs:420`) strips `SigPat` before grouping. Any surviving `CoPat` is routed to `matchCoercion` (`Match.hs:275-285`). Thus HsToCore does eliminate the apparent redundancy.

---

### Claim 6: LazyPat Is Converted to WildPat by tidy1, Then Classified as PgAny

**Statement:** `LazyPat` never reaches `patGroup` directly. Instead, `tidy1` transforms it into a `WildPat` plus selector bindings (`mkSelectorBinds`). Only then does `patGroup` classify the resulting `WildPat` as `PgAny`. The selector bindings create deferred pattern-match failures embedded in let-bindings, not in the immediate case expression.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:446-458`

**Evidence:**
```haskell
tidy1 v _ (LazyPat _ pat)
  = putSrcSpanDs (getLocA pat) $
    do  { ...
        ; (_,sel_prs) <- mkSelectorBinds [] pat LazyPatCtx (Var v)
        ; let sel_binds =  [NonRec b rhs | (b,rhs) <- sel_prs]
        ; return (mkCoreLets sel_binds, WildPat (idType v)) }
```

And `patGroup` has no case for `LazyPat`:
```haskell
patGroup _ pat = pprPanic "patGroup" (ppr pat)
```

**Status:** Validated
**Confidence:** High
**Notes:** `patGroup` would panic if it received a `LazyPat` (`Match.hs:1299`). The correct chain is `LazyPat -> tidy1 -> WildPat -> patGroup -> PgAny`. This means `PgAny` can still "fail" — but the failure is deferred until the selector thunk is forced, rather than happening at the pattern-match site.

---

### Claim 7: EmbTyPat Also Maps to PgAny

**Statement:** `EmbTyPat` (embedded type patterns, used in type applications) is classified as `PgAny` in `patGroup`, implying it requires no case discrimination at runtime.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1295`

**Evidence:**
```haskell
patGroup _ EmbTyPat{} = PgAny
```

**Status:** Validated
**Confidence:** High
**Notes:** Like `VarPat` and `WildPat`, this is a compile-time-only construct that becomes a no-op at the value level during desugaring.

---

## Exploration Topics

- [ ] **PgAny Core output structure:** What exactly does `matchVariables` produce? It simply shifts equations and recurses, but what is the final `MatchResult` shape for a column of pure variables?
- [ ] **Nested failable patterns under PgAny:** If `LazyPat ~(Just x)` fails, where does the failure expression come from? Trace `mkSelectorBinds` and its interaction with `MR_Fallible`.
- [ ] **SigPat without CoPat:** Can `SigPat` ever reach HsToCore without a `CoPat` wrapper? If `mkHsWrapPat` receives an identity wrapper, it returns the pattern unchanged, so we could have a bare `SigPat`.
- [ ] **CoPat grouping granularity:** `sameGroup` for `PgCo` uses `eqType` on the inner pattern type. Does this mean two coercion patterns with different but coercible types are grouped separately? What Core does that generate?
- [ ] **PatSig type information recovery:** If `SigPat` is stripped by `tidy1`, is the signature type information ever needed again in HsToCore? Or is it purely a typechecking artifact?

## Related Topics

- [EQUATION_GROUPING_EXPLORATION.md](EQUATION_GROUPING_EXPLORATION.md) — The broader pattern-match grouping and failure-propagation mechanics.
