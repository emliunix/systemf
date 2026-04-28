# Pattern Matching in GHC — A Synthesized Overview

**Status:** Synthesized from source-validated explorations  
**Last Updated:** 2026-04-15  
**Scope:** End-to-end treatment of pattern matching in GHC, from surface syntax through type checking, code generation, and coverage checking.

---

## 1. The Pattern Language: Three Representations

Pattern matching in GHC passes through three distinct representations: the surface-level `Pat` AST, the match-group container `MatchGroup`, and the target `Core` `Case` expression.

### 1.1 Surface Patterns — `Pat GhcTc`

The type-checked surface syntax lives in `GHC/Hs/Pat.hs`. Key constructors include:

| Constructor | Meaning |
|-------------|---------|
| `VarPat` | Binds a variable (`x`) |
| `WildPat` | Wildcard (`_`) |
| `ConPat` | Constructor pattern (`Just x`, `(a,b)`) |
| `SigPat` | Type-annotated pattern (`x :: Int`) |
| `BangPat` | Strict pattern (`!x`) |
| `LazyPat` | Lazy pattern (`~(x,y)`) |
| `XPat (CoPat ...)` | Coercion wrapper (see §2.4) |

After type checking, every `Pat GhcTc` carries type information. Some patterns also carry evidence wrappers (e.g. `CoPat`) that record coercion proofs discovered during type checking.

### 1.2 Match Container — `MatchGroup`

`MatchGroup` (in `GHC/Hs/Expr.hs`) is the unified container for all multi-clause pattern-matching constructs:

```haskell
data MatchGroup p body
  = MG { mg_ext  :: XMG p body          -- Post-TC: MatchGroupTc
       , mg_alts :: XRec p [LMatch p body]  -- The alternatives
       }
```

After type checking, the extension is `MatchGroupTc`:

```haskell
data MatchGroupTc
  = MatchGroupTc
       { mg_arg_tys :: [Scaled Type]  -- t1..tn
       , mg_res_ty  :: Type           -- tr
       , mg_origin  :: Origin         -- Generated vs FromSource
       }
```

`MatchGroup` is used for function definitions, `case` expressions, lambda cases, and arrow syntax. It is *not* desugared directly into Core; instead, the pattern-match compiler (`HsToCore/Match.hs`) flattens it into `EquationInfo`s first.

### 1.3 Core Target — `Case`, `Alt`, `AltCon`

The ultimate output of pattern-match compilation is a Core `Case` expression (`GHC/Core.hs`):

```haskell
data Expr b
  = ...
  | Case (Expr b) b Type [Alt b]
  | ...

type Alt b = (AltCon, [b], Expr b)

data AltCon
  = DataAlt DataCon   -- Constructor alternative
  | LitAlt  Literal   -- Literal alternative (unlifted only)
  | DEFAULT           -- Catch-all
```

The `Case` binder (`b` between the scrutinee and the type) is the variable bound to the scrutinee value within each alternative. This is the representation consumed by the Core-to-Core pipeline and, eventually, the code generator.

---

## 2. Type Checking Patterns

### 2.1 Bidirectional Framework: Check vs Infer

GHC’s type checker for patterns is part of the broader bidirectional inference system. Patterns are checked with an *expected type* (`ExpType`):

```haskell
data ExpType = Check TcType
             | Infer !InferResult   -- mutable TcRef
```

- **Check mode:** The scrutinee type is known. The pattern must match against it. (`mkCheckExpType ty`)
- **Infer mode:** The scrutinee type is a hole (e.g. `case unknown of { x -> ... }`). The pattern fills the hole via unification.

This mode propagates into sub-patterns. Notably, constructor argument patterns are *always* checked in `Check` mode (`tcConArg` calls `mkCheckExpType arg_ty`).

### 2.2 Key Functions

| Function | File | Role |
|----------|------|------|
| `tcMatches` | `GHC/Tc/Gen/Match.hs` | Top-level coordinator for all match groups |
| `tcMatchPats` | `GHC/Tc/Gen/Pat.hs` | Checks a list of patterns against expected types |
| `tc_lpat` / `tc_pat` | `GHC/Tc/Gen/Pat.hs` | Main pattern dispatch |
| `tcPatBndr` | `GHC/Tc/Gen/Pat.hs` | Creates a binder id for `VarPat` |
| `tcPatSig` | `GHC/Tc/Gen/Pat.hs` | Handles `SigPat` subsumption |
| `tcConPat` / `tcDataConPat` | `GHC/Tc/Gen/Pat.hs` | Handles constructor patterns |

### 2.3 Polymorphism, Skolemisation, Instantiation, and Levels

When a polymorphic function has a user-written signature, the pattern types are obtained by **skolemisation** (`tcSkolemiseCompleteSig`), turning `forall a. a -> a` into `a_sk -> a_sk`. The patterns are then checked against the skolemised type in `Check` mode.

For **instantiation** of invisible arguments at use sites, `topInstantiate` splits off top-level `forall`s and constraints, creating fresh meta-tyvars and returning an `HsWrapper`. This is used when a pattern is checked against a polymorphic expected type.

**Levels** track the nesting depth of type variables. When filling an `InferResult` hole, `fillInferResultNoInst` promotes the inferred type to the hole’s level to maintain the level invariant. This prevents incorrectly generalised types from escaping their scope.

### 2.4 Coercion Wrappers and `CoPat`

When a pattern’s expected type does not exactly match the pattern’s declared type, the type checker produces an `HsWrapper` — a plan for transforming a Core expression. For patterns, this wrapper is attached as a `CoPat`:

```haskell
data XXPatGhcTc
  = CoPat
      { co_cpt_wrap  :: HsWrapper     -- e.g. deep-skolemisation wrapper
      , co_pat_inner :: Pat GhcTc     -- the actual pattern
      , co_pat_ty    :: Type          -- outer type
      }
```

When `CoPat` is desugared, `matchCoercion` turns it into a Core let-binding:

```haskell
-- Source: \(x :: σ_sig) -> ...  against expected σ_a
-- Core:   let x' = wrap x in ...
```

---

## 3. The Pattern Matching Compiler (HsToCore)

GHC uses a **PatGroup-based pattern match compiler** for Core code generation. It is based on Wadler/SPJ’s algorithm and operates independently from the coverage checker.

### 3.1 Architecture Overview

```
Source MatchGroup
       │
       ▼
  matchWrapper (entry point)
       │
       ├── selectMatchVars        ──► create scrutinee variables
       ├── pmcMatches (LYG)       ──► coverage check (optional)
       ├── mk_eqn_info            ──► flatten to EquationInfo
       └── matchEquations         ──► call match + extract Core
                  │
                  ▼
               match
                  │
                  ├── tidyEqnInfo  ──► simplify first column (e.g. VarPat → WildPat)
                  ├── groupEquations ──► group by PatGroup
                  ├── match_groups ──► dispatch to specialists
                  └── combineMatchResults ──► chain groups with backtracking
```

### 3.2 Data Structures

**`EquationInfo`** — a linked list of patterns leading to a RHS:

```haskell
data EquationInfo
  = EqnMatch { eqn_pat :: LPat GhcTc, eqn_rest :: EquationInfo }
  | EqnDone  (MatchResult CoreExpr)
```

**`MatchResult CoreExpr`** — CPS-encoded result with failure handling:

```haskell
data MatchResult a
  = MR_Infallible (DsM a)
  | MR_Fallible   (CoreExpr -> DsM a)
```

`MR_Fallible` takes a failure expression (e.g. `error "Non-exhaustive patterns"`) and produces the final Core. `combineMatchResults` chains them right-nested: if group 1 fails, try group 2.

### 3.3 `matchWrapper` — The Entry Point

`matchWrapper` (`GHC/HsToCore/Match.hs:761-833`) is the gateway for all pattern-match desugaring:

1. **`selectMatchVars`** — Creates fresh variables for matching. Reuses original binder names when possible (e.g. `f x = ...` uses `x` directly).
2. **Coverage check** — Calls `pmcMatches` (LYG) if enabled.
3. **`mk_eqn_info`** — For each `LMatch`, applies `decideBangHood` (for `-XStrict`), desugars the RHS via `dsGRHSs`, and builds an `EquationInfo`.
4. **`matchEquations`** — Calls `match`, generates the failure expression via `mkFailExpr`, and extracts Core with `extractMatchResult`.

### 3.4 Grouping and Matching

**`patGroup`** classifies the first-column pattern into a `PatGroup`:

```haskell
data PatGroup
  = PgAny               -- Variables, wildcards, lazy patterns
  | PgCon DataCon       -- Constructor patterns
  | PgSyn PatSyn [Type] -- Pattern synonyms
  | PgLit Literal       -- Literal patterns
  | PgN   FractionalLit -- Overloaded numeric literals
  | PgOverS FastString  -- Overloaded string literals
  | PgNpK Integer       -- n+k patterns
  | PgBang              -- Bang patterns
  | PgCo Type           -- Coercion patterns
  | PgView (LHsExpr GhcTc) Type -- View patterns
```

**`groupEquations`** groups equations by `sameGroup`, which determines if two patterns can share a single `Case` expression. For example, all `PgCon _` patterns share one case expression regardless of *which* constructor they are.

**`subGroupUniq`** further sub-groups constructor patterns by their specific `DataCon`. Then `matchConFamily` generates the actual Core alternatives.

### 3.5 Specialist Match Functions

| Function | Handles | Key Output |
|----------|---------|------------|
| `matchVariables` | `PgAny` (vars, wildcards) | Shifts column, recurses |
| `matchCoercion` | `PgCo` | Let-binding with wrapper application |
| `matchConFamily` | `PgCon` sub-groups | `mkCoAlgCaseMatchResult` |
| `matchLiterals` | `PgLit`, `PgN`, etc. | `mkCoPrimCaseMatchResult` |
| `matchPatSyn` | `PgSyn` | Pattern synonym expansion |

### 3.6 Constructor Matching Details

`matchConFamily` (`Match/Constructor.hs`) receives groups of equations for the *same* constructor. Within each group, record patterns are further sub-grouped by field order (`compatible_pats`), because `T {x=True, y=False}` and `T {y=False, x=True}` require different selector orderings.

For each sub-group, `matchOneConLike`:
1. Creates fresh argument variables (`selectMatchVars`).
2. Reorders them for record patterns (`select_arg_vars`).
3. Decomposes the constructor pattern into sub-patterns (`shift` / `conArgPats`).
4. Recursively calls `match` on the expanded equation list.

### 3.7 Failure Expression Sharing

A naive CPS encoding can duplicate the failure expression if it appears in multiple alternatives (e.g. `DEFAULT` branch + every `DataCon` branch). To prevent this, `shareFailureHandler` uses `mkFailurePair` to let-bind the failure thunk:

```haskell
mkFailurePair expr = do
  -- Creates: fail_fun = \_ -> expr
  -- Usage:   fail_fun void#
```

This is called from `combineMatchResults` (sibling backtracking) and `extractMatchResult` (top-level extraction).

---

## 4. LYG — Lower Your Guards (Coverage Checking)

GHC’s pattern-match coverage checker is **completely separate** from the PatGroup code generator. The same source patterns are desugared twice: once for warnings, once for Core.

### 4.1 Architecture

```
Source patterns
       │
       ▼
  Pmc.Desugar  ──►  GrdDag  ──►  LYG Checker  ──►  CheckResult
  (desugarPat)       (guards)      (coverage)        (warnings)
```

In `matchWrapper`, the LYG path runs first:

```haskell
matches_nablas <-
    if isMatchContextPmChecked ...
    then pmcMatches origin context new_vars matches
    else ...
```

Then the PatGroup path generates Core. They operate on the same patterns but produce completely different outputs.

### 4.2 Key Data Structures

| LYG Type | Purpose |
|----------|---------|
| `PmGrd` | Single guard (pattern match, let, type constraint) |
| `GrdDag` | Guarded DAG of patterns |
| `Nabla` | Set of value abstractions (uncovered patterns) |
| `CheckResult` | Redundancy and exhaustiveness information |

### 4.3 Why Two Systems?

- **LYG** is designed for precision in coverage analysis (GADT-aware, term-level constraints).
- **PatGroup** is the mature, battle-tested Core generator based on Wadler’s pattern match compiler.

While it may seem redundant to desugar twice, the two systems have different requirements: LYG needs to reason about *possible* values, while PatGroup needs to generate *efficient* case expressions with minimal code duplication.

---

## 5. Complete Flow: A Function Definition

Consider a simple function:

```haskell
f :: Bool -> Int
f True  = 1
f False = 2
```

### Type Checking Phase
1. `tcPolyCheck` skolemises the signature.
2. `tcFunBindMatches` calls `tcMatches` with expected pattern type `Bool` and result type `Int`.
3. `tc_pat` checks each `ConPat` against `Bool`, confirming `True` and `False` are valid.
4. RHSs are checked against `Int`.
5. No `CoPat` is generated (regular constructors, exact type match).

### Desugaring Phase
1. `matchWrapper` receives the `MatchGroup`.
2. `selectMatchVars` creates a fresh variable `x :: Bool`.
3. `pmcMatches` runs LYG and confirms exhaustive.
4. `mk_eqn_info` builds two `EquationInfo`s:
   - `EqnMatch True  (EqnDone (MR_Infallible 1))`
   - `EqnMatch False (EqnDone (MR_Infallible 2))`
5. `match` tidies, groups by `PgCon`, sub-groups by `DataCon`.
6. `matchConFamily` generates:
   ```haskell
   case x of
     True  -> 1
     False -> 2
   ```
   (No `DEFAULT` because exhaustive.)

---

## 6. Source Reference Map

| Topic | File | Key Lines |
|-------|------|-----------|
| `Pat` AST | `GHC/Hs/Pat.hs` | Pattern definitions |
| `MatchGroup` | `GHC/Hs/Expr.hs` | 855–865, 1734–1739 |
| Core `Case` | `GHC/Core.hs` | 254–266, 286–294 |
| Pattern TC entry | `GHC/Tc/Gen/Match.hs` | 222–266 |
| Pattern dispatch | `GHC/Tc/Gen/Pat.hs` | 611–976 |
| `ExpType` | `GHC/Tc/Utils/TcType.hs` | ~500 |
| Hole filling | `GHC/Tc/Utils/Unify.hs` | 1122–1169 |
| `matchWrapper` | `GHC/HsToCore/Match.hs` | 761–833 |
| `match` | `GHC/HsToCore/Match.hs` | 195–214 |
| `EquationInfo` / `MatchResult` | `GHC/HsToCore/Monad.hs` | 139–157, 189–213 |
| `matchConFamily` | `GHC/HsToCore/Match/Constructor.hs` | 94–107 |
| `mkFailurePair` | `GHC/HsToCore/Utils.hs` | 824–836 |
| LYG desugarer | `GHC/HsToCore/Pmc/Desugar.hs` | 149–151 |
| LYG checker | `GHC/HsToCore/Pmc/Check.hs` | 42 |

---

## 7. Related Exploration Documents

This summary synthesizes the following validated analyses:

- `HSTOCORE_PATTERN_DESUGARING_EXPLORATION.md` — LYG vs PatGroup separation
- `PATTERN_TC_ANALYSIS.md` — `VarPat`, `SigPat`, `ConPat` type checking
- `PATTERN_TC_FACTS.md` — Shared-hole mechanism and branch coordination
- `PATTERN_MODE_EXPLORATION.md` — Check vs Infer mode propagation
- `EQUATION_GROUPING_EXPLORATION.md` — `PatGroup`, grouping algorithm, `MatchResult` CPS
- `CONSTRUCTOR_MATCHING_EXPLORATION.md` — `matchConFamily`, record sub-grouping
- `PGANY_AND_PATCO_EXPLORATION.md` — `tidy1`, `matchVariables`, `matchCoercion`
- `MATCHRESULT_FAILURE_HANDLER_EXPLORATION.md` — `shareFailureHandler`, `mkFailurePair`
- `DESUGARING_PATTERNS.md` — AABS2 rule, `CoPat` → Core let-bindings
- `TYPE_INFERENCE.md` — Bidirectional inference, `ExpType`, skolemisation
- `HSWRAPPER_ARCHITECTURE.md` — `HsWrapper` design and translation

---

**Takeaway:** GHC pattern matching is a pipeline of three major phases — type checking (bidirectional, wrapper-producing), Core generation (PatGroup-based mixture-rule compiler), and coverage checking (LYG, entirely separate). Each phase has its own IR, invariants, and concerns, unified at the `MatchGroup` boundary.
