# HsToCore Pattern Desugaring Architecture

**Status:** Validated
**Last Updated:** 2026-04-12
**Central Question:** How does GHC desugar patterns to Core, and what is the relationship between LYG and Core generation?

## Summary

GHC uses **two parallel systems** for pattern matching, contrary to initial assumptions:

1. **LYG (Lower Your Guards)** - Pattern match coverage checker ONLY
   - Generates warnings (exhaustiveness, redundancy)
   - Uses `PmGrd`, `GrdDag`, `Nabla` types
   - **Does NOT generate Core code**

2. **PatGroup-based system** - Actual Core code generator
   - Generates executable Core expressions
   - Uses `PatGroup`, `EquationInfo`, `MatchResult` types
   - Based on Wadler's pattern match compiler

The exploration corrected a misleading assumption that LYG is used as an IR for Core generation. The evidence shows LYG contains Core (`PmLet` with `CoreExpr`) only for coverage analysis, not for code generation.

## Key Claims

### Claim 1: LYG is NOT an IR for Core Generation

**Statement:** The Lower Your Guards system is used exclusively for pattern-match coverage checking and does not participate in Core code generation.

**Evidence:**

```haskell
-- LYG desugaring produces GrdDag for analysis only
-- GHC/HsToCore/Pmc/Desugar.hs:149-151
desugarPat :: Id -> Pat GhcTc -> DsM GrdDag

-- LYG checking produces CheckResult RedSets (warnings info)
-- GHC/HsToCore/Pmc/Check.hs:42
newtype CheckAction a = CA { unCA :: Nablas -> DsM (CheckResult a) }

-- CheckResult contains coverage info, not Core
-- GHC/HsToCore/Pmc/Types.hs:260-270
data CheckResult a = CheckResult
  { cr_ret :: !a           -- RedSets (redundancy info)
  , cr_uncov :: !Nablas    -- Uncovered patterns
  , cr_approx :: !Precision
  }
```

**Validation:** The `desugarPat` function in Pmc.Desugar is only called by `pmcPatBind` and `pmcMatches` (coverage checking entry points), never by the Core desugarer. The `CheckResult` type contains `RedSets` (for warnings), not Core expressions.

**Date:** 2026-04-12

---

### Claim 2: PatGroup-Based System Generates Core

**Statement:** GHC generates Core code using the PatGroup-based pattern match compiler, which operates independently from LYG.

**Evidence:**

```haskell
-- Core generation entry point
-- GHC/HsToCore/Match.hs:185-193
match :: [MatchId]
      -> Type
      -> [EquationInfo]
      -> DsM (MatchResult CoreExpr)  -- Returns Core!

-- Pattern classification for code generation
-- GHC/HsToCore/Match.hs:998-1014
data PatGroup
  = PgAny               -- Variables, wildcards
  | PgCon DataCon       -- Constructor patterns
  | PgSyn PatSyn [Type] -- Pattern synonyms
  | PgLit Literal       -- Literal patterns
  | ...

-- Constructor matching generates Core case
-- GHC/HsToCore/Match/Constructor.hs:94-111
matchConFamily :: NonEmpty Id
               -> Type
               -> NonEmpty (NonEmpty EquationInfoNE)
               -> DsM (MatchResult CoreExpr)
matchConFamily (var :| vars) ty groups
  = do let mult = idMult var
       alts <- mapM (fmap toRealAlt . matchOneConLike vars ty mult) groups
       return (mkCoAlgCaseMatchResult var ty alts)  -- Creates Core Case!
```

**Validation:** The `match` function returns `MatchResult CoreExpr`, which is converted to actual Core via `extractMatchResult`. This is called by `matchWrapper`, which is the entry point for desugaring all pattern matches (function definitions, case expressions, etc.).

**Date:** 2026-04-12

---

### Claim 3: Two Independent Desugaring Paths

**Statement:** The same source patterns are desugared twice: once by LYG for coverage checking, and once by the PatGroup system for Core generation.

**Evidence:**

In `matchWrapper` (GHC/HsToCore/Match.hs:792-833):

```haskell
matchWrapper ctxt scrs (MG { mg_alts = L _ matches, ... })
  = do  { ...
        -- FIRST: Coverage checking (LYG path)
        ; matches_nablas <-
            if isMatchContextPmChecked dflags origin ctxt
            then addHsScrutTmCs ... $
                 pmcMatches origin (DsMatchContext ctxt locn) new_vars matches
            else ...
        
        ; eqns_info   <- zipWithM mk_eqn_info matches matches_nablas
        
        -- SECOND: Core generation (PatGroup path)
        ; result_expr <- discard_warnings_if_skip_pmc origin $
                         matchEquations ctxt new_vars eqns_info rhs_ty
        ... }
```

**Note:** The LYG path is called first to collect coverage information, then the PatGroup path generates the actual Core. They operate on the same source patterns but produce completely different outputs.

**Date:** 2026-04-12

---

### Claim 4: CoPat Uses Let Bindings for Coercion

**Statement:** When desugaring patterns with type coercions (CoPat), GHC introduces let-bindings to convert the scrutinee variable to the pattern's type.

**Evidence:**

```haskell
-- CoPat handling in Match.hs:275-285
matchCoercion (var :| vars) ty eqns@(eqn1 :| _)
  = do  { let XPat (CoPat co pat _) = firstPat eqn1
        ; let pat_ty' = hsPatType pat
        ; var' <- newUniqueId var (idMult var) pat_ty'  -- Fresh var with inner type
        ; match_result <- match (var':vars) ty $ ...
        ; dsHsWrapper co $ \core_wrap -> do
        { let bind = NonRec var' (core_wrap (Var var))
        ; return (mkCoLetMatchResult bind match_result) } }
```

**Transformation:**
```haskell
-- Source:  case (x :: t1) of (p :: t2 |> co) -> rhs
-- Desugars to:
--   let x' = x |> co  -- x' :: t2
--   in case x' of p -> rhs
```

**Rationale:**
1. **Efficiency:** Avoids applying coercion multiple times
2. **Correctness:** Pattern matcher expects variable with inner type
3. **GADT support:** The coercion carries the type equality proof from GADT matching

**Date:** 2026-04-12

---

### Claim 5: HsWrapper Converts to Core Expression Transformer

**Statement:** The `dsHsWrapper` function converts HsWrapper evidence into Core expression transformers (functions of type `CoreExpr -> CoreExpr`).

**Evidence:**

```haskell
-- GHC/HsToCore/Binds.hs:1583-1594
dsHsWrapper :: HsWrapper -> ((CoreExpr -> CoreExpr) -> DsM a) -> DsM a
dsHsWrapper hs_wrap thing_inside
  = ds_hs_wrapper hs_wrap $ \ core_wrap ->
    addTyCs FromSource (hsWrapDictBinders hs_wrap) $
    thing_inside core_wrap

-- Core translation cases
-- GHC/HsToCore/Binds.hs:1596-1624
go WpHole            k = k $ \e -> e
go (WpCast co)       k = k $ \e -> mkCastDs e co
go (WpTyApp ty)      k = k $ \e -> App e (Type ty)
go (WpEvLam ev)      k = k $ Lam ev
go (WpEvApp tm)      k = do { core_tm <- dsEvTerm tm
                            ; k $ \e -> e `App` core_tm }
go (WpLet ev_binds)  k = dsTcEvBinds ev_binds $ \bs ->
                         k (mkCoreLets bs)
```

**Usage Pattern:**
```haskell
dsHsWrapper wrapper $ \core_wrap -> do
  let bind = NonRec var' (core_wrap (Var var))
  ...
```

The wrapper is applied to the variable to create the right-hand side of the let-binding.

**Date:** 2026-04-12

---

## System Architecture

```
Source Pattern Match
       │
       ├───► LYG Desugarer ──► GrdDag ──► LYG Checker ──► CheckResult
       │     (Pmc.Desugar)      (Pmc)       (warnings)     (RedSets)
       │                           (coverage only)
       │
       └───► PatGroup Matcher ──► MatchResult ──► CoreExpr
             (Match.hs)             (CoreExpr)     (Core)
             (code generation)
```

### Key Differences

| Aspect | LYG System | PatGroup System |
|--------|------------|-----------------|
| **Purpose** | Coverage checking | Code generation |
| **Output** | Warnings (RedSets) | Core expressions |
| **Pattern types** | `PmGrd`, `GrdDag` | `Pat GhcTc` (HsSyn) |
| **Equation structure** | `PmMatchGroup` | `EquationInfo` (linked list) |
| **Failure model** | `Nablas` (uncovered set) | `MR_Fallible` with fail expr |
| **Coercion handling** | `PmLet` with Core (for CSE) | Let-binding with fresh var |

## Open Questions

1. **Performance impact:** Does desugaring patterns twice (LYG + PatGroup) have measurable overhead?
2. **Alternative designs:** Could LYG be extended to also generate Core, eliminating the duplication?
3. **Historical context:** When was LYG added, and why wasn't the existing PatGroup system extended instead?

## Related Topics

- `upstream/ghc/analysis/LET_BINDING_ARCHITECTURE_EXPLORATION.md` - Let binding level hierarchy
- `upstream/ghc/analysis/PATTERN_TC_ANALYSIS.md` - Pattern type checking
- `upstream/ghc/analysis/VALBINDS_EXPLORATION.md` - Value binding representation

## Validation Notes

All claims validated against:
- GHC 9.x source code (upstream/ghc/compiler/GHC/HsToCore/)
- Direct source code inspection
- Cross-referencing between modules

**Validation Date:** 2026-04-12
