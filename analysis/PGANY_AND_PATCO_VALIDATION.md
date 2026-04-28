# Validation Report: PGANY_AND_PATCO_EXPLORATION.md

**Target:** `/home/liu/Documents/bub/analysis/PGANY_AND_PATCO_EXPLORATION.md`  
**Reference:** `/home/liu/Documents/bub/.agents/skills/exploration/REFERENCE.md`  
**Date:** 2026-04-13

---

## Claim 1: tidy1 Eliminates SigPat Before Grouping

**Statement:** `tidy1` in `GHC/HsToCore/Match.hs` strips `SigPat` by recursing into its inner pattern, so `SigPat` never reaches `patGroup` or the grouping algorithm.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** `tidy1` at `upstream/ghc/compiler/GHC/HsToCore/Match.hs:420` matches `tidy1 v g (SigPat _ pat _) = tidy1 v g (unLoc pat)`. The POST CONDITION comment at `Match.hs:398-399` explicitly states that after `tidyEqnInfo` (which calls `tidy1`), the head pattern is "one of these for which `patGroup` is defined." `patGroup` has no case for `SigPat`, confirming it never survives tidying.

---

## Claim 2: VarPat Becomes WildPat Under tidy1

**Statement:** `tidy1` converts a `VarPat` into a `WildPat` plus a binding wrapper (`wrapBind var v`), removing the variable pattern from the pattern tree and moving the binding into the wrapper.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** Evidence at `upstream/ghc/compiler/GHC/HsToCore/Match.hs:426-427` is exact: `tidy1 v _ (VarPat _ (L _ var)) = return (wrapBind var v, WildPat (idType var))`. This is consistent with `matchVariables` (`Match.hs:264-267`) assuming no real variable patterns remain.

---

## Claim 3: CoPat Patterns Classify as PgCo, Not PgAny

**Statement:** In `patGroup`, a `CoPat` always maps to `PgCo` using the type of the inner pattern, regardless of whether that inner pattern is a variable, wildcard, or constructor.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1296-1297` shows `CoPat _ p _ -> PgCo (hsPatType p)`. There is no conditional on the inner pattern `p`. This correctly separates coercion-wrapped variables from plain variables (`PgAny`).

---

## Claim 4: matchCoercion Strips CoPat and Handles the Wrapper Separately

**Statement:** `matchCoercion` extracts the inner pattern from `CoPat` via `getCoPat`, applies the coercion wrapper to create a new `CoreExpr` binding, and then continues matching on the unwrapped inner pattern.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** Evidence at `upstream/ghc/compiler/GHC/HsToCore/Match.hs:275-285` matches exactly. It destructures `CoPat co pat _`, strips it with `getCoPat` via `decomposeFirstPat`, creates a fresh `var'`, and binds `NonRec var' (core_wrap (Var var))`. The recursive `match` call processes the inner `pat` against `var'`.

---

## Claim 5: HsToCore Eliminates the PatSig/PatCo Redundancy

**Statement:** The typechecker preserves both `SigPat` and its `CoPat` wrapper, but HsToCore eliminates this redundancy: `SigPat` is stripped by `tidy1`, and the `CoPat` wrapper is consumed by `matchCoercion`. By the time Core is generated, only the coercion application remains; the signature annotation itself has vanished.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** The typechecker evidence at `upstream/ghc/compiler/GHC/Tc/Gen/Pat.hs:770` shows `mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty`. `mkHsWrapPat` (`GHC/Hs/Utils.hs:811-813`) can return a bare `SigPat` if the wrapper is identity, or a `CoPat`-wrapped `SigPat` otherwise. In either case, `tidy1` (`Match.hs:420`) strips `SigPat` before grouping. Any surviving `CoPat` is routed to `matchCoercion` (`Match.hs:275-285`). Thus HsToCore does eliminate the apparent redundancy. The exploration's concern about bare `SigPat` is valid but does not invalidate the claim, because `tidy1` handles it regardless.

---

## Claim 6: LazyPat Generates PgAny via mkSelectorBinds

**Statement:** `LazyPat` is classified as `PgAny` by `patGroup`, but `tidy1` transforms it into a `WildPat` plus selector bindings (`mkSelectorBinds`). These selector bindings create deferred pattern-match failures embedded in let-bindings, not in the immediate case expression.

- **VALIDATED:** Partial
- **Source Check:** Mismatch at `Match.hs:1299`
- **Logic Check:** Questionable
- **Notes:** The evidence for the `tidy1` transformation at `Match.hs:446-458` is correct: `LazyPat` is converted to `WildPat` with `mkSelectorBinds`. However, the first clause of the claim is **false**: `LazyPat` is **never** seen by `patGroup`. `patGroup` has no case for `LazyPat`; if it received one, it would panic at `Match.hs:1299` (`pprPanic "patGroup"`). The correct chain is: `tidy1` transforms `LazyPat` -> `WildPat`, and then `patGroup` classifies `WildPat` as `PgAny`. The claim conflates the transformation step with the classification step. The outcome (deferred failure via selector thunks) is correct, but the mechanism attributed to `patGroup` directly is wrong.

---

## Claim 7: EmbTyPat Also Maps to PgAny

**Statement:** `EmbTyPat` (embedded type patterns, used in type applications) is classified as `PgAny` in `patGroup`, implying it requires no case discrimination at runtime.

- **VALIDATED:** Yes
- **Source Check:** Verified
- **Logic Check:** Sound
- **Notes:** Evidence at `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1295` is exact: `patGroup _ EmbTyPat{} = PgAny`. This is consistent with the nature of embedded type patterns as compile-time-only constructs.

---

## Summary

| Claim | Validated | Issue |
|-------|-----------|-------|
| 1 | Yes | None |
| 2 | Yes | None |
| 3 | Yes | None |
| 4 | Yes | None |
| 5 | Yes | None (bare `SigPat` path confirmed harmless) |
| 6 | Partial | `LazyPat` never reaches `patGroup`; `tidy1` converts it to `WildPat` first |
| 7 | Yes | None |
