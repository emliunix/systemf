# Pattern Matching Type Checking - Confirmed Facts

## Overview
This document records source-validated facts about GHC's pattern matching type checking mechanism, discovered through systematic exploration of the GHC compiler source code.

---

## 1. Core Architecture

### 1.1 Unified Interface: tcMatches

**Location:** `GHC/Tc/Gen/Match.hs:222`

`tcMatches` is the unified coordinator for pattern matching across different constructs:

```haskell
tcMatches :: (AnnoBody body, Outputable (body GhcTc))
          => HsMatchContextRn
          -> TcMatchAltChecker body
          -> [ExpPatType]             -- Expected pattern types
          -> ExpRhoType               -- Expected result-type (SHARED)
          -> MatchGroup GhcRn (LocatedA (body GhcRn))
          -> TcM (MatchGroup GhcTc (LocatedA (body GhcTc)))
```

**Key insight:** Same function handles both function definitions and case expressions.

### 1.2 Two Parent Callers

**For function bindings** (`tcFunBindMatches`, Match.hs:131):
- Pattern types: `invis_pat_tys ++ pat_tys` (may include visible type patterns `@a`)
- tc_body: Hardcoded `tcBody`
- Result type: `rhs_ty` from `matchExpectedFunTys`

**For case expressions** (`tcCaseMatches`, Match.hs:188):
- Pattern types: `[ExpFunPatTy (Scaled mult (Check scrut_ty))]` (single scrutinee)
- tc_body: Parameter passed from parent
- Result type: `res_ty` inherited from context

### 1.3 Pattern Type Taxonomy

**ExpFunPatTy** (`GHC/Tc/Utils/TcType.hs:507`):
- For value patterns (`x`, `(a, b)`, `Just y`)
- Always visible

**ExpForAllPatTy** (`GHC/Tc/Utils/TcType.hs:508`):
- For type patterns (`@a` with `-XTypeApplications`)
- Visible only if binder is `Required` (explicit `forall a ->`)

---

## 2. Branch Coordination Mechanism

### 2.1 The Shared Hole

**Key mechanism:** All branches share the same `ExpRhoType` (mutable cell/TcRef).

**Code location:** `GHC/Tc/Utils/Unify.hs:1122-1169` (`fillInferResultNoInst`)

```haskell
fillInferResultNoInst act_res_ty (IR { ir_ref = ref })
  = do { mb_exp_res_ty <- readTcRef ref
       ; case mb_exp_res_ty of
            Just exp_res_ty  -- HOLE FILLED
               -> unifyType Nothing act_res_ty exp_res_ty
            Nothing          -- HOLE EMPTY
               -> writeTcRef ref (Just act_res_ty) }
```

### 2.2 Branch Execution Strategy

**First branch:** Fills hole with its inferred type (assignment)
**Subsequent branches:** Unify with existing type (compatibility check)

**Design note** (`GHC/Tc/Utils/Unify.hs:1130-1142`):
```haskell
-- We progressively refine the type stored in 'ref',
-- for example when inferring types across multiple equations.
--
-- Example:
--   \ x -> case y of { True -> x ; False -> 3 :: Int }
--
-- When inferring the return type of this function, we will create
-- an 'Infer' 'ExpType', which will first be filled by the type of 'x'
-- after typechecking the first equation, and then filled again with
-- the type 'Int', at which point we want to ensure that we unify
-- the type of 'x' with 'Int'.
```

### 2.3 Universal Application

This mechanism is used by:
- **Case expressions:** Each alternative's RHS
- **If expressions:** Both branches via `tcMonoExpr b1 res_ty` and `tcMonoExpr b2 res_ty`
- **Function equations:** All equations of a function

**Convergence point:** All call `tcWrapResult` → `tcSubTypeMono` → `fillInferResultNoInst`

---

## 3. Mode Behavior

### 3.1 Check vs Infer

**Mode is determined by `ExpType`:**
```haskell
data ExpType = Check TcType
             | Infer !InferResult  -- Contains TcRef (mutable cell)
```

### 3.2 Mode Flow

**Pattern matching (scrutinee):** Check mode throughout
- Created by `mkCheckExpType scrut_ty` in `tcCaseMatches`
- Passed through entire pipeline without mode switches

**Result type (branches):** Depends on parent context
- Can be Check (known type) or Infer (hole to fill)
- All branches use same mode via shared `res_ty`

### 3.3 Mode State Transitions

**Important:** There are NO mode switches in the pipeline.

The `expTypeToType` boundary (`GHC/Tc/Utils/TcMType`):
- Check mode: Returns the known type directly
- Infer mode: Reads hole, returns current content

After this point, everything works with `TcType` — mode distinction disappears.

---

## 4. Data Constructor Pattern Handling

### 4.1 Type Constructor Revelation

In `tcDataConPat` (`GHC/Tc/Gen/Pat.hs:1157`):
```haskell
tycon = dataConTyCon data_con  -- T is known immediately from syntax!
```

The constructor syntax (`Cons`, `Just`, etc.) immediately reveals which type constructor is being matched.

### 4.2 Type Argument Handling

**Check mode:** Verify scrutinee type matches constructor's type
**Infer mode:** Create template `T meta1 meta2` and unify with scrutinee hole

**Key insight:** The data constructor reveals T, but type arguments may be unknown (unification variables).

### 4.3 ConPatTc Structure

**Location:** `GHC/Hs/Pat.hs` (XXPatGhcTc for ConPat)

```haskell
cpt_wrap :: HsWrapper     -- Identity (WpHole) for regular constructors
          -- Non-identity only for pattern synonyms
```

**For regular data constructors:** `cpt_wrap = idHsWrapper` (no wrapper)

---

## 5. HsWrapper and Desugaring

### 5.1 Where Wrappers Are Generated

**Data families only:** `CoPat` created when representation type ≠ family type
**Pattern signatures:** `SigPat` always creates `CoPat`
**Regular constructors:** No wrapper

### 5.2 Wrapper Consumption

**Location:** `GHC/HsToCore/Match.hs:275` (`matchCoercion`)

```haskell
matchCoercion (var :| vars) ty eqns
  = do { let XPat (CoPat wrap pat _) = firstPat eqn1
       ; dsHsWrapper wrap $ \core_wrap -> do
       { let bind = NonRec var' (core_wrap (Var var))
       ; return (mkCoLetMatchResult bind match_result) } }
```

**Translation:** HsWrapper becomes Core let-binding: `let var' = wrap(var) in ...`

### 5.3 No-Op for Regular Constructors

For `ConPatTc` with `cpt_wrap = idHsWrapper`:
- No `CoPat` wrapper
- `matchConFamily` handles directly (ignores `cpt_wrap`)
- No let-binding generated

---

## 6. Polymorphic Functions (Contrast)

### 6.1 Top-Level with Signature

**Entry:** `tcPolyCheck` (`GHC/Tc/Gen/Bind.hs:564`)

**Different mechanism:** Uses **skolemisation**, not unification

```haskell
tcSkolemiseCompleteSig sig $ \invis_pat_tys rho_ty ->
  tcFunBindMatches ... (mkCheckExpType rho_ty)
```

**Flow:**
1. `forall a. a -> a` → skolemise → `a_sk -> a_sk`
2. Check patterns against `a_sk`
3. Check body against `a_sk`
4. No hole-filling — type is known from signature

### 6.2 Key Difference

| Aspect | Case branches | Polymorphic function |
|--------|---------------|---------------------|
| Result type | Shared hole (Infer) or known (Check) | Skolemised from signature |
| Coordination | Unification across branches | Single checking type |
| Type vars | Existentials/GADT | Universal (skolem constants) |

---

## 7. If Expressions

### 7.1 Type Checking

**Location:** `GHC/Tc/Gen/Expr.hs:521-526`

```haskell
tcExpr (HsIf x pred b1 b2) res_ty
  = do { pred'    <- tcCheckMonoExpr pred boolTy
       ; (u1,b1') <- tcCollectingUsage $ tcMonoExpr b1 res_ty
       ; (u2,b2') <- tcCollectingUsage $ tcMonoExpr b2 res_ty
       ; tcEmitBindingUsage (supUE u1 u2)
       ; return (HsIf x pred' b1' b2') }
```

**Key:** Both branches use same `res_ty` → same hole-filling mechanism as case.

### 7.2 Desugaring

**Location:** `GHC/HsToCore/Expr.hs` → `GHC/Core/Make.hs:208-212`

```haskell
mkIfThenElse guard then_expr else_expr
  = mkWildCase guard (linear boolTy) (exprType then_expr)
         [ Alt (DataAlt falseDataCon) [] else_expr,
           Alt (DataAlt trueDataCon)  [] then_expr ]
```

**Result:** `if-then-else` becomes `case` on Bool in Core.

---

## 8. Wired-In Types (Bool)

### 8.1 Dual Existence

**Source file:** `libraries/ghc-internal/src/GHC/Internal/Types.hs`
```haskell
data {-# CTYPE "HsBool" #-} Bool = False | True
```

**Compiler primitive:** `GHC.Builtin.Types` creates wired-in `TyCon` referencing same module

### 8.2 Mechanism

1. GHC creates `TyCon` at compiler boot time (doesn't read interface)
2. Wired-in `TyCon` points to source module name `GHC.Internal.Types`
3. When compiling the source, GHC connects wired-in and source definitions

### 8.3 Cannot Be Hidden

Bool and other wired-in types are **compiler primitives** — you can avoid the names by not importing, but cannot truly hide them.

---

## 9. Invariants and Preconditions

### 9.1 tcMatchPats Precondition

**Location:** `GHC/Tc/Gen/Pat.hs:124-128`

```
number of visible pats == number of visible pat_tys
```

**Visible =** value patterns (not `@a` type patterns)

### 9.2 Mode Consistency

**Verified:** Check mode throughout pattern matching pipeline (scrutinee side)
**Reason:** `mkCheckExpType` creates Check at entry, no switches occur

### 9.3 Result Type Sharing

**Invariant:** Single `res_ty` shared across ALL branches
**Enforced by:** `tcMatches` passing same parameter to each `tcMatch` call

---

## Summary

The pattern matching type checking system uses a **shared mutable hole** (`ExpRhoType` with `TcRef`) for coordinating result types across branches. This is universal across:
- Case expressions
- If-then-else  
- Function equations

The first branch to execute sets the type standard; subsequent branches must unify with it. This provides implicit coordination without explicit "join" points in the code structure.

Regular data constructor patterns use **no wrappers** — the `ConPatTc.cpt_wrap` field is identity. Wrappers only appear for:
- Data families (representation vs family type mismatch)
- Pattern signatures (explicit type annotation)
