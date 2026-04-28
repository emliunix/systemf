# GHC Type Inference System

## Overview

GHC implements **bidirectional type inference**, which allows the compiler to type-check expressions in two complementary modes:

1. **Checking Mode** (↓): An expected type is provided, and the expression is checked against it
2. **Inference Mode** (↑): The type of an expression is inferred from its structure

This approach enables flexible type-checking while maintaining strong type safety.

---

### 0.6 Pattern Typing in GHC

In GHC, **patterns are not a separate phase** - they are part of lambda type-checking from the beginning.

#### The Call Chain

```
tcExpr (HsLam ...)  -- Lambda expression
    │
    ▼
tcLambdaMatches     -- Extract pattern types from expected function type
    │
    ▼
tcMatches          -- Type-check each match alternative
    │
    ▼
tcMatchPats        -- Match patterns with pattern types
    │
    ▼
tc_lpat            -- Type-check each pattern
```

#### Pattern Checking Flow

For `\ (x :: σ_x) -> body` against expected type `σ_a → σ_r`:

1. **`tcLambdaMatches`** splits `σ_a → σ_r` into pattern type `σ_a` and result type `σ_r`
2. **`tc_lpat`** is called with expected pattern type `σ_a`
3. For `SigPat` (annotated pattern):
   - **`tcPatSig`** calls `tcSubTypePat σ_a σ_x`
   - Returns wrapper `wrap :: σ_a ~~> σ_x` (deep skolemization)
4. **`mkHsWrapPat wrap`** creates the `CoPat` in the type-checked AST

#### The AABS2 Implementation

In the paper, AABS2 handles annotated lambdas explicitly. In GHC:

```
Paper:     Γ ⊢_↓ λ(x::σₓ).t : σₐ → σᵣ ↦ λx::σₐ.[x ↦ (f x)]e
                     └──────────┬──────────┘
                     tcLambdaMatches extracts σₐ
                                      │
                                      ▼
              tcPatSig: tcSubTypePat σₐ σₓ → wrap :: σₐ ~~> σₓ
                                      │
                                      ▼
              CoPat wraps VarPat, binding x at type σₓ
                                      │
                                      ▼
              matchCoercion desugars: let x' = wrap var in body
```

#### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `tcLambdaMatches` | `GHC/Tc/Gen/Match.hs` | Split function type into patterns |
| `tcMatchPats` | `GHC/Tc/Gen/Pat.hs` | Match patterns with expected types |
| `tc_lpat` | `GHC/Tc/Gen/Pat.hs` | Type-check single pattern |
| `tcPatSig` | `GHC/Tc/Gen/Pat.hs` | Handle `SigPat` (annotation check) |
| `tcSubTypePat` | `GHC/Tc/Utils/Unify.hs` | Subsumption for patterns |
| `matchCoercion` | `GHC/HsToCore/Match.hs` | Desugar CoPat to Core |

#### Pattern Type Environments

| Pattern | Binding Created | Wrapper |
|---------|-----------------|---------|
| `VarPat x` | `x :: τ` | Identity |
| `SigPat x :: σ` | `x :: σ` | `wrap :: σ_a ~~> σ` |
| `ConPat` | Multiple | Constructor-specific |

---

## Part 0.7: Complete Pattern Matching Reference

This section documents how `tc_pat` handles each pattern form.

### Overview: The Pattern Type-Checking Dispatch

```
tc_pat :: Scaled ExpSigmaTypeFRR -> PatEnv -> Pat GhcRn -> TcM (Pat GhcTc, a)
```

The `tc_pat` function is a case expression that dispatches on the pattern form:

| Pattern | Handler | Key Operation |
|---------|---------|---------------|
| `VarPat` | `VarPat` case | `tcPatBndr` creates binder |
| `WildPat` | `WildPat` case | Skip binding, read type |
| `SigPat` | `SigPat` case | `tcPatSig` subsumption |
| `ConPat` | `ConPat` case | `tcConPat` |
| `TuplePat` | `TuplePat` case | Split tuple type |
| `ListPat` | `ListPat` case | Split list type |
| `LitPat` | `LitPat` case | Unify with literal type |
| `NPat` | `NPat` case | Overloaded literal |
| `NPlusKPat` | `NPlusKPat` case | `(+k)` pattern |
| `ViewPat` | `ViewPat` case | Infer view type |
| `BangPat` | `BangPat` case | Recurse on inner |
| `ParPat` | `ParPat` case | Recurse on inner |
| `AsPat` | `AsPat` case | Two-phase binding |
| `LazyPat` | `LazyPat` case | Capture constraints |
| `OrPat` | `OrPat` case | Multiple alternatives |

---

### 0.7.1 VarPat - Variable Binding

```haskell
VarPat x (L l name) -> do
  { (wrap, id) <- tcPatBndr penv name scaled_exp_pat_ty
  ; res <- tcCheckUsage name w_pat $
           tcExtendIdEnv1 name id thing_inside
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (VarPat x (L l id)) pat_ty, res) }
```

**What happens:**
1. `tcPatBndr` creates a new `Id` with the pattern's type
2. Check usage (multiplicity) with `tcCheckUsage`
3. Extend environment with `name → id`
4. Read the final pattern type

**Result:** `VarPat` with no wrapper (identity).

---

### 0.7.2 WildPat - Underscore Pattern

```haskell
WildPat _ -> do
  { checkManyPattern OtherPatternReason (noLocA ps_pat) scaled_exp_pat_ty
  ; res <- thing_inside
  ; pat_ty <- expTypeToType exp_pat_ty
  ; return (WildPat pat_ty, res) }
```

**What happens:**
1. Check multiplicity is valid
2. Just run `thing_inside` (no binder added)
3. Read the pattern type

**Result:** `WildPat` with type annotation.

---

### 0.7.3 SigPat - Type-Annotated Pattern

```haskell
SigPat _ pat sig_ty -> do
  { (inner_ty, tv_binds, wcs, wrap) <-
      tcPatSig (inPatBind penv) sig_ty exp_pat_ty
      -- wrap :: σ_expected ~~> σ_signature
  ; (pat', res) <- tcExtendNameTyVarEnv wcs      $
                   tcExtendNameTyVarEnv tv_binds $
                   tc_lpat (Scaled w_pat $ mkCheckExpType inner_ty) penv pat thing_inside
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (SigPat inner_ty pat' sig_ty) pat_ty, res) }
```

**What happens:**
1. `tcPatSig` does subsumption check: `σ_expected ≤ σ_signature`
2. Returns wrapper `wrap :: σ_expected ~~> σ_signature`
3. Type-check inner pattern with signature type
4. Wrap result with `mkHsWrapPat` → creates `CoPat`

**CoPat creation:**
```haskell
mkHsWrapPat :: HsWrapper -> Pat GhcTc -> Type -> Pat GhcTc
mkHsWrapPat co_fn p ty 
  | isIdHsWrapper co_fn = p  -- No wrapper needed
  | otherwise           = XPat $ CoPat co_fn p ty
```

---

### 0.7.4 CoPat - The Wrapper Pattern

**Location**: `GHC/Hs/Pat.hs:274-290`

```haskell
data XXPatGhcTc
  = CoPat
      { co_cpt_wrap :: HsWrapper  -- coercion: t1 ~ t2
      , co_pat_inner :: Pat GhcTc  -- inner pattern
      , co_pat_ty :: Type         -- type of whole pattern: t1
      }
```

**Semantics:**
```
If co :: t1 ~ t2 and p :: t2
then (CoPat co p) :: t1
```

**Example:** `\(x :: Int -> Int) -> body` against `σ_a = (forall a. a->a) → Int`
- Expected type for pattern: `forall a. a->a`
- Signature type: `Int -> Int`
- Wrapper: `wrap :: (forall a. a->a) ~~> (Int -> Int)` (deep skolemization)
- Inner pattern: `VarPat x :: Int -> Int`
- Result: `CoPat wrap (VarPat x) (forall a. a->a)`

**Desugaring** (in `GHC/HsToCore/Match.hs`):
```haskell
matchCoercion (var :| vars) ty eqns = do
  { let XPat (CoPat co pat _) = firstPat eqn1
  ; var' <- newUniqueId var (idMult var) pat_ty'  -- var' :: σ_x
  ; match_result <- match (var':vars) ty ...
  ; dsHsWrapper co $ \core_wrap -> do
  ; let bind = NonRec var' (core_wrap (Var var))  -- var' = wrap var
  ; return (mkCoLetMatchResult bind match_result) }
```

---

### 0.7.5 ConPat - Data Constructor Pattern

```haskell
ConPat _ con arg_pats ->
  tcConPat penv con scaled_exp_pat_ty arg_pats thing_inside
```

**What happens:**
1. `tcConPat` looks up the constructor
2. Unifies expected type with constructor's type
3. Extracts argument types
4. Type-checks each sub-pattern with `tc_lpats`

**Result:** `ConPatTc` with:
- `cpt_arg_tys`: Universal argument types
- `cpt_tvs`: Existentially bound type variables
- `cpt_dicts`: dictionaries
- `cpt_binds`: evidence bindings
- `cpt_wrap`: extra wrapper (for pattern synonyms)

---

### 0.7.6 TuplePat, ListPat - Product Patterns

**TuplePat:**
```haskell
TuplePat _ pats boxity -> do
  { (coi, arg_tys) <- matchExpectedPatTy (matchExpectedTyConApp tc) penv exp_pat_ty
  ; (pats', res) <- tc_lpats (map (Scaled w_pat . mkCheckExpType) arg_tys)
                             penv pats thing_inside
  ; ... return (mkHsWrapPat coi (TuplePat ...) pat_ty, res) }
```

**ListPat:**
```haskell
ListPat _ pats -> do
  { (coi, elt_ty) <- matchExpectedPatTy matchExpectedListTy penv exp_pat_ty
  ; (pats', res) <- tc_lpats (map (Scaled w_pat . mkCheckExpType) (repeat elt_ty))
                             penv pats thing_inside
  ; ... return (mkHsWrapPat coi (ListPat ...) pat_ty, res) }
```

**Key:** `matchExpectedPatTy` unifies expected type with type constructor, returns:
- Coercion `coi` if unification needed
- Extracted element/argument types

---

### 0.7.7 LitPat, NPat - Literal Patterns

**LitPat (simple literal):**
```haskell
LitPat x simple_lit -> do
  { let lit_ty = hsLitType simple_lit
  ; wrap <- tcSubTypePat_GenSigCtxt penv exp_pat_ty lit_ty
  ; res  <- thing_inside
  ; pat_ty <- readExpType exp_pat_ty
  ; return (mkHsWrapPat wrap (LitPat ...) pat_ty, res) }
```

**NPat (overloaded literal):**
```haskell
NPat _ (L l over_lit) mb_neg eq -> do
  { -- Use rebindable syntax for equality
  ; ((lit', mb_neg'), eq')
      <- tcSyntaxOp orig eq [SynType exp_pat_ty, SynAny] boolTy $
         \ [neg_lit_ty] _ -> newOverloadedLit over_lit ...
  ; res <- thing_inside
  ; return (NPat pat_ty (L l lit') mb_neg' eq', res) }
```

---

### 0.7.8 ViewPat - View Pattern

```haskell
ViewPat _ view_expr inner_pat -> do
  { -- Infer view expression type
  ; (view_expr', view_expr_rho) <- tcInferExpr IIF_ShallowRho view_expr
  
  ; -- Match to get arrow type
  ; (view_expr_co1, Scaled _mult view_arg_ty, view_res_ty)
      <- matchActualFunTy ... view_expr_rho view_expr_rho
  
  ; -- Check overall pattern type against view argument
  ; view_expr_wrap2 <- tcSubTypePat_GenSigCtxt penv exp_pat_ty view_arg_ty
  
  ; -- Type-check inner pattern with view result type
  ; (inner_pat', res) <- tc_lpat (Scaled w_pat (mkCheckExpType view_res_ty))
                                  penv inner_pat thing_inside
  ; ... }
```

**Desugaring:** `(view_expr -> inner)` becomes:
```haskell
let x = view_expr scrutinee
in match x of inner_pat
```

---

### 0.7.9 AsPat - As-Pattern

```haskell
AsPat x (L nm_loc name) pat -> do
  { (wrap, bndr_id) <- tcPatBndr penv name scaled_exp_pat_ty
  ; (pat', res) <- tcExtendIdEnv1 name bndr_id $
                    tc_lpat (Scaled w_pat (mkCheckExpType $ idType bndr_id))
                            penv pat thing_inside
  ; ... return (mkHsWrapPat wrap (AsPat ... pat') pat_ty, res) }
```

**Key:** Two-phase type-checking:
1. Create binder at outer type
2. Check inner pattern against `idType bndr_id`

---

### 0.7.10 LazyPat - Lazy Pattern

```haskell
LazyPat x pat -> do
  { checkManyPattern LazyPatternReason ...
  ; (pat', (res, pat_ct))
      <- tc_lpat ... (captureConstraints thing_inside)
  ; emitConstraints pat_ct  -- "hop" constraints around pattern
  ; ... }
```

**Note:** Constraints generated inside `thing_inside` are "hopped around" the pattern - they can't use dictionaries bound by the pattern.

---

### 0.7.11 OrPat - Or-Pattern (View Patterns Extension)

```haskell
OrPat _ pats -> do
  { let pats_list   = NE.toList pats
        pat_exp_tys = map (const scaled_exp_pat_ty) pats_list
  ; (pats_list', (res, pat_ct)) <- tc_lpats pat_exp_tys ... 
                                    (captureConstraints thing_inside)
  ; emitConstraints pat_ct
  ; ... }
```

**Key:** All alternatives get the same expected type. Constraints are captured separately for each branch.

---

### 0.7.12 Pattern Type Summary

| Pattern Form | Creates Binder | Creates Wrapper | Nested Patterns |
|-------------|---------------|----------------|-----------------|
| `VarPat` | Yes (at τ) | Identity | No |
| `WildPat` | No | N/A | No |
| `SigPat` | Yes (at σ) | Yes (σ_e ~~> σ) | Yes |
| `ConPat` | Yes (multiple) | Maybe | Yes |
| `TuplePat` | Yes (multiple) | Maybe | Yes |
| `ListPat` | Yes (multiple) | Maybe | Yes |
| `LitPat` | No | Yes (τ_e ~~> lit_ty) | No |
| `NPat` | No | No (equality handled separately) | No |
| `NPlusKPat` | Yes (at var_ty) | Yes (var_ty) | No |
| `ViewPat` | No | Yes (WpFun composed) | Yes (inner) |
| `AsPat` | Yes (at τ) | Yes | Yes |
| `LazyPat` | Yes (inside) | No | Yes |
| `OrPat` | Yes (per alt) | Maybe | Yes |

---

## Part 0: The Foundation

This section covers the basic framework: the AST phases, the type-checking monad, and the key conventions.

### 0.1 The AST Phases

GHC processes the AST through a series of phases:

```
Parser          Renamer          Type Checker         Desugarer         Core
   │                │                 │                   │              │
   ▼                ▼                 ▼                   ▼              ▼
HsExpr        HsExpr          HsExpr             HsExpr          CoreExpr
GhcPs         GhcRn           GhcTc              GhcTc
 (no type)    (Name)          (Id + Type)        + HsWrapper
                               + Wrappers
```

**Phase descriptions:**

| Phase | AST Index | Variable Type | Type Info |
|-------|-----------|--------------|-----------|
| Parsed | `GhcPs` | N/A | No type information |
| Renamed | `GhcRn` | `Name` | Scope resolution only |
| Typechecked | `GhcTc` | `Id` (= Name + Type) | Full types + evidence |

**Key insight**: In `GhcTc`, variables are represented as `Id` (not `Name`), where `Id = Name` with an attached type via `idType :: Id -> Type`.

**Location**: `GHC/Hs/Expr.hs` defines the `HsExpr` type parameterized by pass:
```haskell
data HsExpr (p :: Pass) = ...
-- p ~ 'Parsed, 'Renamed, or 'Typechecked
```

### 0.2 The Type-Checking Monad (`TcM`)

The type-checker runs in the `TcM` monad, defined in `GHC/Tc/Utils/Monad.hs`.

**What TcM provides:**

1. **Type Environment** - Maps `Name` to `Id`:
   ```haskell
   tcLookupId :: Name -> TcM Id
   tcLookupId name = do
       thing <- tcLookupIdMaybe name
       case thing of
           Just (ATcId { tct_id = id }) -> return id
           ...
   ```

2. **Constraint Collection** - Gathers type constraints:
   ```haskell
   emitWanted :: CtOrigin -> PredType -> TcM EvTerm
   emitSimpleWC :: TcM WantedConstraints
   ```

3. **Level Tracking** - Prevents untouchable variables from escaping:
   ```haskell
   newtype TcLevel = TcLevel Int
   pushTcLevel :: TcM a -> TcM a
   ```

4. **Unification Variables** - Mutable meta-type variables:
   ```haskell
   data TcTyVarDetails
     = MetaTv { mtv_ref :: IORef MetaDetails, mtv_tclvl :: TcLevel }
     | SkolemTv { ... }
   
   newFlexiTyVarTy :: Kind -> TcM Type
   unifyType :: Type -> Type -> TcM Coercion
   ```

5. **Evidence Management** - Records type class dictionaries, etc.:
   ```haskell
   newEvVar :: PredType -> TcM EvVar
   emitWantedEvVar :: CtOrigin -> PredType -> TcM EvVar
   ```

**The TcTyThing universe** - What's in the environment:
```haskell
data TcTyThing
  = AGlobal TyThing                    -- Imported or top-level
  | ATcId { tct_id :: Id               -- Local variable with type
          , tct_info :: IdBindingInfo } -- Binding metadata
  | ATyVar Name TcTyVar                -- Type variable
  | ...
```

### 0.3 The `ExpType` Convention

`ExpType` is the central abstraction for bidirectional type inference:

```haskell
-- GHC/Tc/Utils/TcType.hs
data ExpType
  = Check TcType         -- We have an expected type
  | Infer !InferResult   -- We have a hole to fill

-- Type synonyms for documentation
type ExpSigmaType = ExpType  -- May have foralls
type ExpRhoType   = ExpType  -- No foralls at top level
type ExpSigmaTypeFRR = ExpType  -- Fixed RuntimeRep
```

**The two modes:**

| Constructor | Meaning | Usage |
|-------------|---------|-------|
| `Check ty` | "Validate against this type" | Outside-in, known type context |
| `Infer hole` | "Infer and fill this hole" | Inside-out, unknown type context |

**The inference hole:**
```haskell
data InferResult = IR {
    ir_uniq :: Unique,           -- Debugging identifier
    ir_lvl  :: TcLevel,         -- Level for untouchable tracking
    ir_ref  :: IORef (Maybe TcType),  -- Mutable reference
    ir_inst :: InferInstFlag,    -- Instantiation control
    ir_frr  :: InferFRRFlag     -- Fixed RuntimeRep checking
}
```

**Key functions:**
```haskell
-- Create
newInferExpType :: InferInstFlag -> TcM ExpType
mkCheckExpType  :: TcType -> ExpType

-- Use
runInfer :: InferInstFlag -> InferFRRFlag 
          -> (ExpType -> TcM a) 
          -> TcM (a, TcType)
-- Creates hole, runs computation, reads result

readExpType :: ExpType -> TcM TcType
-- Reads filled hole (or creates fresh var if still empty)
```

**Pattern type-checking also uses this convention:**
```haskell
tcCheckPat :: HsMatchContextRn
           -> LPat GhcRn 
           -> Scaled ExpSigmaTypeFRR   -- Expected pattern type
           -> TcM a 
           -> TcM (LPat GhcTc, a)

tcInferPat :: FixedRuntimeRepContext
            -> HsMatchContextRn 
            -> LPat GhcRn 
            -> TcM a 
            -> TcM ((LPat GhcTc, a), ExpSigmaTypeFRR)  -- Inferred type
```

### 0.4 Evidence Recording (`HsWrapper`)

During type-checking, GHC records *evidence terms* that justify type transformations. These are stored as `HsWrapper` annotations in the `GhcTc` AST.

```haskell
-- GHC/Tc/Types/Evidence.hs
data HsWrapper
  = WpHole                              -- Identity
  | WpCast TcCoercionR                  -- Type coercion: e |> co
  | WpTyApp KindOrType                  -- Type application: e @ty
  | WpEvApp EvTerm                      -- Dictionary application: e d
  | WpEvLam EvVar                       -- Dictionary lambda: \d. e
  | WpTyLam TyVar                       -- Type lambda: /\a. e
  | WpFun SubMultCo Wp Wp TcType TcType -- Function wrapper
  | WpCompose HsWrapper HsWrapper        -- Composition: w1 ∘ w2
  | WpLet TcEvBinds                     -- Evidence let-binding
  | WpSubType HsWrapper                 -- Deep subsumption marker
```

Wrappers are later translated to Core by the desugarer (`dsHsWrapper`).

**See**: `HSWRAPPER_ARCHITECTURE.md` for complete details.

### 0.5 Mode Dispatch: How tcExpr Works

The main entry point handles both modes uniformly:

```haskell
-- GHC/Tc/Gen/Expr.hs
tcExpr :: HsExpr GhcRn -> ExpRhoType -> TcM (HsExpr GhcTc)

-- Special cases for applications (Quick Look optimization)
tcExpr e@(HsVar {})    res_ty = tcApp e res_ty
tcExpr e@(HsApp {})    res_ty = tcApp e res_ty
tcExpr e@(OpApp {})    res_ty = tcApp e res_ty
tcExpr e@(HsLam {})    res_ty = tcLambdaMatches e ... res_ty
-- ... etc
```

**Core principle**: Each AST node is processed exactly once, in exactly one mode. Mode switches occur at parent-child boundaries.

---

## Part 1: ExpType Deep Dive

### 1.1 ExpType Data Structure

```haskell
data ExpType = Check TcType
             | Infer !InferResult

data InferResult = IR { 
    ir_uniq :: Unique
  , ir_lvl  :: TcLevel            -- For untouchable tracking
  , ir_frr  :: InferFRRFlag       -- Fixed RuntimeRep
  , ir_inst :: InferInstFlag      -- Instantiation behavior
  , ir_ref  :: IORef (Maybe TcType)
}
```

### 1.2 Instantiation Control

**Location**: `GHC/Tc/Utils/TcType.hs`

```haskell
data InferInstFlag
  = IIF_Sigma       -- Don't instantiate; preserve foralls
  | IIF_ShallowRho  -- Top-level instantiation only
  | IIF_DeepRho     -- Deep instantiation (DeepSubsumption)
```

- **`IIF_Sigma`**: Preserves polymorphism (used for pattern types)
- **`IIF_ShallowRho`**: Removes top-level foralls and constraints
- **`IIF_DeepRho`**: Removes nested foralls for impredicative polymorphism

### 1.3 Fixed Runtime Representation

```haskell
data InferFRRFlag
  = IFRR_Check FixedRuntimeRepContext  -- Check FRR
  | IFRR_Any                           -- No check needed
```

Ensures inferred types satisfy representation polymorphism constraints.

---

## Part 2: Type Checking Modes

### 2.1 Mode Semantics

| Mode | Direction | When Used |
|------|-----------|-----------|
| **Check** | Outside-in | Type annotation available, lambda body, argument positions |
| **Infer** | Inside-out | Let RHS, function head, no annotation available |

### 2.2 Mode Switching at Boundaries

Mode switches occur at **parent-child boundaries**, not by reprocessing:

**Example 1: Application (Infer Parent)**
```haskell
f x  -- Infer mode
├── f: Infer mode (need to know f's type)
└── x: Check mode (know expected type from f)
```

**Example 2: Lambda (Check Parent)**
```haskell
(\x -> e) :: Int -> Bool  -- Check mode
├── x: Gets type Int (from annotation)
└── e: Check mode against Bool
```

### 2.3 Where Generalization Happens

**Critical: Generalization ONLY occurs at let-bindings!**

```haskell
let f = \x -> x in ...
     ^^^^^^^^^^^^
          │
          └── tcPolyInfer generalizes: alpha -> alpha  ===>  forall a. a -> a
```

**Location**: `tcPolyInfer` in `GHC/Tc/Gen/Bind.hs`, `simplifyInfer` in `GHC/Tc/Solver/Simplify.hs`

**Generalization Pipeline:**
```
Let-binding
    │
    ├── tcPolyInfer
    │       ├── Infer RHS → rho type (monomorphic)
    │       ├── simplifyInfer
    │       │       ├── Find free vars
    │       │       └── Create polymorphic type
    │       └── Return: AbsBinds with forall
    │
    └── f :: forall a. a -> a  (now polymorphic!)

Later uses:
    f 1    -- instantiates: f @Int
    f True -- instantiates: f @Bool
```

### 2.4 Common Misconceptions

1. **"Application produces polymorphic types"** - Wrong! Applications produce rho types.
2. **"checkResultTy generalizes"** - Wrong! It creates wrappers for result-type matching, not generalization.
3. **"Both modes check and infer"** - Wrong! Each node is processed once. Mode switches happen when calling children.

---

## Part 3: Type Storage During Inference

### 3.1 Three Storage Mechanisms

**1. In Variable Ids (Primary)**
```haskell
-- Extracting the type:
hsExprType (HsVar _ (L _ id)) = idType id
```

**2. In Extension Fields**
```haskell
-- These have type fields in GhcTc phase:
hsExprType (HsDo ty _ _) = ty
hsExprType (ExplicitList ty _) = ty
hsExprType (HsMultiIf ty _) = ty
```

**3. Via HsWrapper and WrapExpr**
```haskell
-- Type transformations via wrapper:
mkHsWrap :: HsWrapper -> HsExpr GhcTc -> HsExpr GhcTc
mkHsWrap co_fn e | isIdHsWrapper co_fn = e
                 | otherwise           = XExpr (WrapExpr co_fn e)

-- Extracting type through wrapper:
hsExprType (XExpr (WrapExpr wrap e)) = hsWrapperType wrap $ hsExprType e
```

### 3.2 Meta-Variables During Inference

**Location**: `GHC/Types/Var.hs` (for `TcTyVarDetails`, `MetaDetails`)

```haskell
data TcTyVarDetails
  = MetaTv { 
      mtv_info  :: MetaInfo,
      mtv_ref   :: IORef MetaDetails,  -- Mutable!
      mtv_tclvl :: TcLevel
    }

data MetaDetails
  = Flexi             -- Unfilled
  | Indirect TcType   -- Filled: points to actual type
```

When unification finds two types should be equal:
```haskell
writeMetaTyVar :: TcTyVar -> TcType -> TcM ()
-- Updates the IORef with (Indirect ty)
```
**Location**: `GHC/Tc/Utils/TcMType.hs`

### 3.3 The Zonking Process

Zonking replaces mutable meta-variables with their final types.

**Two Zonkers:**
1. **Intra-typechecking**: Used during type checking, leaves unfilled meta-vars as-is
2. **Final zonk**: Used after type checking completes, replaces ALL meta-vars

### 3.4 IdBindingInfo and Generalization

```haskell
data IdBindingInfo
    = NotLetBound              -- Bound by lambda or case
    | LetBound ClosedTypeId    -- Bound by let
```

Examples:
```haskell
-- Can generalize (closed type)
let g = map not          -- g :: forall a. [Bool] -> [Bool]
-- tct_info = LetBound True

-- Cannot generalize (depends on x)
\x -> let g y = x + y    -- g :: Int -> Int (monomorphic)
-- tct_info = LetBound False

-- Cannot generalize (lambda-bound)
\x -> x + 1              -- x is NotLetBound
```

---

## Part 4: Main Type-Checking Functions

### 4.1 Entry Points

**Location**: All functions in `GHC/Tc/Gen/Expr.hs` unless otherwise noted

**Checking Functions** (provided with expected type):
```haskell
tcCheckPolyExpr, tcCheckPolyExprNC
    :: LHsExpr GhcRn -> TcSigmaType -> TcM (LHsExpr GhcTc)
-- Check against polymorphic type; handles forall-introduction

tcCheckMonoExpr, tcCheckMonoExprNC
    :: LHsExpr GhcRn -> TcRhoType -> TcM (LHsExpr GhcTc)
-- Check against monomorphic type

tcMonoExpr, tcMonoExprNC
    :: LHsExpr GhcRn -> ExpRhoType -> TcM (LHsExpr GhcTc)
-- Check against expected monomorphic type (checking or inference mode)
```

**Inference Functions** (infer the type):
```haskell
tcInferSigma :: LHsExpr GhcRn -> TcM (LHsExpr GhcTc, TcSigmaType)
-- Infer full polymorphic type (preserves foralls)

tcInferRho, tcInferRhoNC :: LHsExpr GhcRn -> TcM (LHsExpr GhcTc, TcRhoType)
-- Infer instantiated type (no top-level foralls)

tcInferRhoFRR, tcInferRhoFRRNC 
    :: FixedRuntimeRepContext -> LHsExpr GhcRn -> TcM (LHsExpr GhcTc, TcRhoType)
-- Infer with fixed runtime representation checking
```

**The Main Function**:
```haskell
tcExpr :: HsExpr GhcRn -> ExpRhoType -> TcM (HsExpr GhcTc)
-- Main entry point for expression type checking
```

### 4.2 The Inference Flow

**Location**: `GHC/Tc/Utils/TcMType.hs`

**1. Create an inference hole**:
```haskell
newInferExpType :: InferInstFlag -> TcM ExpType
```

**2. Type-check the expression**:
```haskell
runInfer iif ifrr tc_check
  = do { res_ty <- newInferExpType iif ifrr
       ; result <- tc_check res_ty      -- Pass the hole
       ; res_ty <- readExpType res_ty   -- Read filled hole
       ; return (result, res_ty) }
```

**3. Fill the hole**:
```haskell
inferResultToType :: InferResult -> TcM Type
```
- Reads the IORef to get the inferred type
- If empty, creates a fresh unification variable
- Applies instantiation according to `InferInstFlag`

### 4.3 Mode Dispatch in tcExpr

**Location**: `GHC/Tc/Gen/Expr.hs` (main dispatch), `GHC/Tc/Gen/App.hs` (tcApp), `GHC/Tc/Gen/Match.hs` (tcLam)

Special cases for efficiency:
```haskell
tcExpr e@(HsVar {})       res_ty = tcApp e res_ty
tcExpr e@(HsApp {})       res_ty = tcApp e res_ty
tcExpr e@(HsAppType {})   res_ty = tcApp e res_ty
tcExpr e@(HsOverLit _ lit) res_ty = ...
tcExpr (HsLam {}) res_ty = tcLam ... res_ty
```

These special cases leverage the expected type to drive type-checking (Quick Look, overload resolution, etc.).

---

## Part 5: Key Implementation Files

### 5.1 GHC/Tc/Utils/TcType.hs
**Purpose**: Type definitions for type checking

Key types: `ExpType`, `InferResult`, `InferInstFlag`, `InferFRRFlag`

**Why Important**: This is where bidirectional type inference is defined. `ExpType` is the key data structure.

### 5.2 GHC/Tc/Utils/TcMType.hs
**Purpose**: Operations on `ExpType` and inference result manipulation

Key functions and locations:
- `newInferExpType` (line 725) - Create inference hole
- `readExpType` (line 779) - Extract inferred type
- `runInfer` (line 348) - Complete inference workflow
- `expTypeToType` (line 815) - Convert ExpType to concrete type

**Why Important**: Implements the mechanics of bidirectional inference.

### 5.3 GHC/Tc/Gen/Expr.hs
**Purpose**: Main expression type checker

Key functions and locations:
- `tcExpr` (line 332) - Main expression type checker
- `tcCheckPolyExpr` (line 180) - Check against polymorphic type
- `tcInferRho` (line 270) - Infer monomorphic type
- `tcLam` (line ~500) - Lambda expression handling

**Why Important**: This is the main expression type checker. Understanding `tcExpr` is key.

### 5.4 GHC/Tc/Gen/App.hs
**Purpose**: Application type checking with Quick Look optimization

Key function: `tcApp`

**Quick Look**: Uses expected type to guide:
- Type variable instantiation
- Overload resolution
- Impredicative polymorphism

**Why Important**: Application checking is where bidirectional inference shines.

### 5.5 GHC/Tc/Gen/Match.hs
**Purpose**: Pattern matching and lambda expression type checking

Key functions and locations:
- `tcLambdaMatches` (line 145) - Lambda pattern type extraction
- `tcMatches` (line 222) - Match group handling
- `tcMatchPats` (line 133) - Pattern/expected type matching

**Why Important**: Pattern matching is a major source of type information.

### 5.6 GHC/Tc/Gen/Pat.hs
**Purpose**: Pattern type-checking

Key functions and locations:
- `tc_pat` (line 611) - Main pattern dispatch
- `tcCheckPat` (line 221) - Check mode entry
- `tcInferPat` (line 210) - Infer mode entry
- `tcPatBndr` (line 315) - Variable binder creation
- `tcPatSig` (line 1008) - Signature pattern handling

**Why Important**: Patterns bind variables and must unify with scrutinee types.

**See also**: `PATTERN_TC_ANALYSIS.md` for complete pattern analysis with CoPat details.

### 5.7 GHC/Tc/Utils/Unify.hs
**Purpose**: Unification and constraint generation

Key functions and locations:
- `unifyExpType` (line ~1425) - Unify ExpType with concrete type
- `fillInferResult` (line 1171) - Fill inference hole
- `tcSubTypePat` (line 1434) - Pattern subsumption check
- `deeplySkolemise` (line ~2200) - Deep skolemization for polymorphism

```haskell
unifyExpType :: ExpRhoType -> TcRhoType -> TcM TcCoercionN
unifyExpType (Check ty1) ty2 = unifyType ty1 ty2
unifyExpType (Infer inf_res) ty2 = fillInferResult ty2 inf_res
```

**Why Important**: Where `ExpType` interacts with unification.

### 5.8 GHC/Tc/Solver/Solve.hs
**Purpose**: Main constraint solving engine

Key functions: `solveSimpleWanteds`, `solveWanteds`

**Why Important**: Type inference generates constraints; solver determines consequences.

---

## Part 6: Design Principles

### 6.1 Linear Usage
Each `ExpType` should be used exactly once:
- Created once via `newInferExpType` or `mkCheckExpType`
- Passed to a single type-checker
- Read once via `readExpType`

### 6.2 Hole-Based Inference
Using `IORef` for inference holes:
- **Pro**: More controlled, avoids unification complexity
- **Pro**: Can track invariants precisely
- **Con**: Requires careful sequencing

### 6.3 Mode Polymorphism
Functions like `tcExpr` work uniformly in both modes through `ExpType`:
- Same code path handles both checking and inference
- Key efficiency and maintainability feature

### 6.4 Deep Skolemisation
With DeepSubsumption enabled, when in checking mode:
```
Check rho_deep_skolemised
```
Enables impredicative polymorphism and proper handling of higher-rank types.

**See**: `HIGHERRANK_POLY.md` for detailed coverage of higher-rank polymorphism and Deep Subsumption.

### 6.5 TcLevel Tracking
`ir_lvl` field prevents "untouchable" variables from being unified:
- Handles GADT refinements correctly
- Example: `data T where MkT :: (Int -> Int) -> a -> T` - existential `a` must not escape

---

## Part 7: Integration with Other Systems

### 7.1 Quick Look
Uses expected type to drive type application inference:
```haskell
tcApp e res_ty  -- res_ty guides Quick Look
```

### 7.2 Constraint Solving
- **Checking mode**: constraints from expected type
- **Inference mode**: constraints generated by expression

### 7.3 Impredicative Polymorphism
With DeepSubsumption, deeply skolemised `ExpType` enables:
- Inference of impredicative instantiations
- Proper handling of `forall` in argument position

---

## Part 8: Related Documentation

### 8.1 HsWrapper and Desugaring

After type-checking, `HsWrapper` annotations are translated to Core by the desugarer:

**Key file**: `GHC/HsToCore/Binds.hs`
- `dsHsWrapper` - Main translation function

**See**: `HSWRAPPER_ARCHITECTURE.md` for complete wrapper details and `CORE_SYSTEM_F.md` for Core translation.

### 8.2 Pattern Desugaring

Pattern matching is desugared in `GHC/HsToCore/Match.hs`:

**Key functions and locations**:
- `match` (line 185) - Main pattern matching desugarer
- `matchCoercion` (line 275) - Handles `CoPat` (type-annotated patterns)
- `matchVariables` (line 264) - Variable patterns
- `matchConFamily` (line ~227) - Constructor patterns

**See**: `DESUGARING_PATTERNS.md` for complete pattern desugaring including AABS2 implementation.

### 8.3 The Complete Pipeline

```
Source Code
    │
    ▼
┌─────────────────┐
│  Renamer        │  GhcRn (Name)
│  (GHC/Renamer)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Type Checker   │  GhcTc (Id + HsWrapper)
│  (GHC/Tc/*)    │  TYPE_INFERENCE.md
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Desugarer      │  CoreExpr
│  (GHC/HsToCore)│  CORE_SYSTEM_F.md
└─────────────────┘
```

---

## Summary

GHC's type inference pipeline consists of four phases:

1. **Renaming**: `GhcRn` - Names resolved, types not yet known
2. **Type Checking**: `GhcTc` - Types attached to variables, evidence recorded
3. **Desugaring**: Core - Wrappers translated, syntactic sugar removed
4. **Optimization**: Core - Transformations before code generation

**Key Takeaways:**
1. One mode per node: Never both check and infer for same node
2. Generalization at let: Only `tcPolyInfer` creates polymorphic types
3. Applications consume: Polymorphic types via instantiation, not generalization
4. Type storage: In Id (primary), extension fields, or via WrapExpr
5. Mode switches: At parent-child boundaries based on context
6. Evidence flows: HsWrapper → dsHsWrapper → CoreExpr
