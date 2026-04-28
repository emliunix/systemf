# Pattern Matching and Case Expressions in GHC

**Status:** Validated  
**Last Updated:** 2026-04-15  
**Central Question:** How does GHC represent, typecheck, and lower pattern matching from surface syntax through Core, and what invariants govern the `Case` construct?

## Summary

This exploration synthesizes findings across the GHC pattern-match pipeline: surface `MatchGroup` containers, the bidirectional typechecking of patterns (both equation-style via `tcMatches` and binding-style via `tcLetPat`), the Scott-encoding theoretical basis for `Case`, and the concrete design of GHC Core `Case` with its explicit binder and result type. Key architectural insights include the two-system separation (LYG for coverage, PatGroup for Core generation), the universal convergence of all pattern typechecking at `tc_pat`, and the reversed control flow of `PatBind` relative to `FunBind`/`MatchGroup`.

## Claims

### Claim 1: mkIfThenElse is Defined in Core/Make and Produces a Case Expression
**Statement:** `mkIfThenElse` is not defined in `HsToCore/Utils.hs`; it lives in `GHC.Core.Make` and compiles an if-expression into a Core `Case` on `Bool` with `DataAlt` alternatives for `True` and `False`.
**Source:** `compiler/GHC/Core/Make.hs:204-212`
**Evidence:**
```haskell
mkIfThenElse guard then_expr else_expr
  = mkWildCase guard (linear boolTy) (exprType then_expr)
         [ Alt (DataAlt falseDataCon) [] else_expr,
           Alt (DataAlt trueDataCon)  [] then_expr ]

mkWildCase scrut (Scaled w scrut_ty) res_ty alts
  = Case scrut (mkWildValBinder w scrut_ty) res_ty alts
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 2: GHC Core Case Requires an Explicit Result Type for Four Reasons
**Statement:** The `Type` field in `Case (Expr b) b Type [Alt b]` is mandatory because (1) empty case has no alternatives to infer from, (2) it is faster in deeply-nested situations than recursive `exprType`, (3) the RHS type may mention out-of-scope pattern-bound variables (e.g. phantom synonyms must be expanded before caching), and (4) Core Lint uses it to reject invalid existential escapes.
**Source:** `compiler/GHC/Core.hs:217-250` (Note [Why does Case have a 'Type' field?])
**Evidence:**
```haskell
-- It works when there are no alternatives (see case invariant 1 above)
-- It might be faster in deeply-nested situations.
-- exprType of the RHS is (S a), but we cannot make that be the 'ty'
-- because 'a' is simply not in scope there.
-- The type stored in the case is checked with lintInTy.
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 3: The Case Binder Exists Because the Pattern Match Compiler Works with Column Binders
**Statement:** The case binder `b` in `Case (Expr b) b Type [Alt b]` is semantically essential because the PatGroup-based pattern match compiler (`match`, `matchConFamily`) maintains a vector of `MatchId`s (column variables). When generating a constructor split, it uses the column variable `var` as the scrutinee and derives the case binder from it (via `mkWildCase` using `idScaledType var` for algebraic constructors, or directly reusing `var` for primitive cases).
**Source:** `compiler/GHC/HsToCore/Match.hs:185-197`, `compiler/GHC/HsToCore/Match/Constructor.hs:94-107`, `compiler/GHC/HsToCore/Utils.hs:275-284,362-364`
**Evidence:**
```haskell
-- Primitive case: var is reused directly as the binder
mkCoPrimCaseMatchResult var ty match_alts = MR_Fallible mk_case
  where mk_case fail = do { alts <- mapM (mk_alt fail) sorted_alts
                          ; return (Case (Var var) var ty (Alt DEFAULT [] fail : alts)) }

-- Algebraic case: binder derived from var's type via mkWildCase
mkDataConCase var ty alts@(alt1 :| _)
  where mk_case def alts = mkWildCase (Var var) (idScaledType var) ty $
                           maybeToList def ++ alts
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 4: Untyped Scott Encoding Has No Return Type; It Emerges Only in System F
**Statement:** In UTLC, pattern matching is just application: `case e of { K₁ -> a; K₂ -> b }` becomes `e a b`. The return type is completely implicit. When lifted to System F, the Scott-encoded datatype becomes polymorphic in result type `R` (e.g. `List A ≡ ∀R. R → (A → List A → R) → R`), and GHC Core caches that `R` directly on the `Case` constructor.
**Source:** Theoretical reconstruction validated against `docs/core-spec/CoreSyn.ott:75`
**Evidence:**
```ott
-- CoreSyn.ott syntax for Case:
| case e as n return t of </ alti // | // i /> :: Case
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 5: Core Lam Does Not Support Patterns
**Statement:** GHC Core `Lam` binds exactly one bare variable (`Lam b (Expr b)`). All pattern matching is desugared into `Case` expressions before reaching Core.
**Source:** `compiler/GHC/Core.hs:258`, `compiler/Language/Haskell/Syntax/Expr.hs:342-344`
**Evidence:**
```haskell
data Expr b = ... | Lam b (Expr b) | Case (Expr b) b Type [Alt b] | ...
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 6: MatchGroup is an Out-of-Tree Container Reused Across Multiple Constructs
**Statement:** `MatchGroup` is not a constructor of `HsExpr`. It is a standalone parameterized data type embedded as a field inside `HsLam`, `HsCase`, `HsLamCase`, `FunBind`, and arrow syntax commands.
**Source:** `compiler/Language/Haskell/Syntax/Expr.hs:855-865`, `compiler/Language/Haskell/Syntax/Expr.hs:342-402`
**Evidence:**
```haskell
data MatchGroup p body
  = MG { mg_ext :: XMG p body, mg_alts :: XRec p [LMatch p body] }

| HsLam  (XLam p) HsLamVariant (MatchGroup p (LHsExpr p))
| HsCase (XCase p) (LHsExpr p) (MatchGroup p (LHsExpr p))
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 7: tcMatches Produces MatchGroup GhcTc with MatchGroupTc Extension
**Statement:** `tcMatches` is the central worker for typechecking `MatchGroup`. It consumes `MatchGroup GhcRn body` and produces `MatchGroup GhcTc body` where the extension `mg_ext` is upgraded from `Origin` to `MatchGroupTc` carrying argument types and result type.
**Source:** `compiler/GHC/Tc/Gen/Match.hs:222-258`
**Evidence:**
```haskell
tcMatches ctxt tc_body pat_tys rhs_ty (MG { mg_alts = L l matches, mg_ext = origin })
  = do { ...
       ; return (MG { mg_alts = L l matches'
                    , mg_ext = MatchGroupTc pat_tys rhs_ty origin }) }
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 8: PatBind Has Opposite Control Flow to MatchGroup-Based Equations
**Statement:** `let (a, b) = e in ...` is represented as `PatBind { pat_lhs, pat_rhs }`, not `MatchGroup`. Its typechecking flow reverses the equation order: the RHS is typechecked first (to infer the scrutinee type), and then the pattern is checked against that inferred type via `tcLetPat`.
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1327-1374`, `compiler/Language/Haskell/Syntax/Binds.hs:212-218`
**Evidence:**
```haskell
-- SPECIAL CASE 2: non-recursive pattern binding
(grhss', pat_ty) <- runInferRhoFRR FRRPatBind $ \exp_ty ->
                       tcGRHSsPat mult grhss exp_ty
let exp_pat_ty = Scaled mult (mkCheckExpType pat_ty)
(_, (pat', mbis)) <- tcLetPat (const Nothing) no_gen pat exp_pat_ty $ ...
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 9: tcLetPat Does Not Call tcMatches; Both Converge at tc_lpat / tc_pat
**Statement:** Despite their different control flows, `tcMatches` and `tcLetPat` share the same underlying pattern typechecker. `tcMatches` → `tcMatchPats` → `tc_lpat` → `tc_pat`. `tcLetPat` → `tc_lpat` → `tc_pat`. The universality comes from the `PatEnv` context (distinguishing `LamPat` from `LetPat`) and the CPS `thing_inside` continuation.
**Source:** `compiler/GHC/Tc/Gen/Pat.hs:83-99`, `compiler/GHC/Tc/Gen/Pat.hs:133-207`, `compiler/GHC/Tc/Gen/Pat.hs:611-625`
**Evidence:**
```haskell
tcLetPat sig_fn no_gen pat pat_ty thing_inside
  = do { ... ; tc_lpat pat_ty penv pat thing_inside }

tcMatchPats match_ctxt pats pat_tys thing_inside
  = do { ...
       ; loop (pat : pats) (ExpFunPatTy pat_ty : pat_tys)
           = do { (p, (ps, res)) <- tc_lpat pat_ty penv pat $ loop pats pat_tys
                ; return (p : ps, res) } }
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 10: tc_pat Receives Both Check and Infer Modes Depending on Caller
**Statement:** Contrary to the intuition that equation patterns are always in `Check` mode, `tcFunBindMatches` can pass `Infer` mode when called from `tcMonoBinds`' non-recursive no-signature special case via `runInferRhoFRR`. `matchExpectedFunTys` explicitly preserves the mode: if the input is `Infer`, it creates fresh `Infer` holes for argument types.
**Source:** `compiler/GHC/Tc/Gen/Bind.hs:1307-1315`, `compiler/GHC/Tc/Utils/Unify.hs:807-822`
**Evidence:**
```haskell
-- Postcondition:
--   If exp_ty is Check {}, then [ExpPatType] and ExpRhoType results are all Check{}
--   If exp_ty is Infer {}, then [ExpPatType] and ExpRhoType results are all Infer{}
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside
  = do { arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]
       ; res_ty  <- newInferExpType (ir_inst inf_res)
       ; result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty
       ... }
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

---

### Claim 11: The Base Case of tcMatchPats Calls the RHS Checker in the Extended Environment
**Statement:** When `tcMatchPats` finishes processing all patterns (`loop [] pat_tys`), it restores the original error context and calls `thing_inside` — which is the RHS typechecker — returning an empty list of translated patterns along with the RHS result.
**Source:** `compiler/GHC/Tc/Gen/Pat.hs:148-151`
**Evidence:**
```haskell
loop [] pat_tys
  = assertPpr (not (any isVisibleExpPatType pat_tys)) ... $
    do { res <- setErrCtxt err_ctxt thing_inside
       ; return ([], res) }
```
**VALIDATED:** Yes  
**Source Check:** Verified  
**Logic Check:** Sound  
**Notes:** None

## Open Questions

- [ ] How exactly does LYG desugar GADT patterns into its guard DAG, and where does it diverge from PatGroup semantics?
- [ ] What is the full set of invariants checked by Core Lint for `Case` beyond the six documented ones?

## Related Topics

- `PATTERN_MATCHING_IN_GHC_SUMMARY.md` — Synthesized overview of the full pipeline
- `VALBINDS_EXPLORATION.md` — AST representation of value bindings
- `EQUATION_GROUPING_EXPLORATION.md` — PatGroup algorithm internals
- `PATTERN_TC_ANALYSIS.md` — Pattern typechecking behavior matrix
- `DESUGARING_PATTERNS.md` — CoPat → Core let-bindings
