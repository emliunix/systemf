# HsWrapper Architecture

## Overview

`HsWrapper` is GHC's mechanism for recording type-checker elaborations as **evidence terms** that guide the translation from surface Haskell to System FC Core. This document presents the complete architectural understanding derived from source code analysis.

## The Two-Phase Design

GHC uses a **decoupled two-phase architecture**:

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: TYPE CHECKING (GHC.Tc.*)                                   │
│  Surface Syntax (HsExpr GhcRn)                                       │
│       ↓                                                              │
│  Bidirectional Type Inference                                        │
│       ↓                                                              │
│  Evidence Collection → HsWrapper construction                        │
│       ↓                                                              │
│  Output: HsExpr GhcTc + HsWrapper annotations                        │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: DESUGARING (GHC.HsToCore.*)                                │
│  HsExpr GhcTc with HsWrapper                                         │
│       ↓                                                              │
│  HsWrapper interpretation (dsHsWrapper)                              │
│       ↓                                                              │
│  Output: CoreExpr (System FC)                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Why HsWrapper Exists

1. **Evidence Recording**: Records **what needs to be done** without doing it:
   - Type applications (`@Int`)
   - Dictionary applications (`$fNumInt`)
   - Coercions (GADT casts)
   - Evidence bindings (dictionary construction)

2. **Optimization Before Core**: Wrappers can be inspected and optimized:
   - Deep subsumption eta-reduction
   - Cast coalescing
   - Identity elimination

3. **Separation of Concerns**:
   - Type checker: Focus on inference and constraint solving
   - Desugarer: Handle Core AST construction mechanics

---

## The HsWrapper Data Type

**Location**: `GHC/Tc/Types/Evidence.hs` (lines 243-310)

```haskell
-- From GHC/Tc/Types/Evidence.hs
data HsWrapper
  = WpHole                              -- Identity: ty ~~> ty
  | WpSubType HsWrapper                 -- Deep subsumption marker
  | WpCompose HsWrapper HsWrapper       -- Sequential composition
  | WpFun SubMultCo HsWrapper HsWrapper TcTypeFRR TcType  -- Function wrapper
  | WpCast TcCoercionR                  -- Type coercion
  | WpEvLam EvVar                       -- Evidence lambda: \d. <hole>
  | WpEvApp EvTerm                      -- Evidence app: <hole> d
  | WpTyLam TyVar                       -- Type lambda: /\tv. <hole>
  | WpTyApp KindOrType                  -- Type app: <hole> @ty
  | WpLet TcEvBinds                     -- Evidence bindings
```

Notation: `wrap :: t1 ~~> t2` means the wrapper transforms an expression of type `t1` to type `t2`.

### 1. WpHole - Identity
- **Purpose**: Identity wrapper (no transformation)
- **Translation**: `\e -> e`
- **Created by**: `idHsWrapper`, or when coercions are reflexive

### 2. WpTyApp - Type Application
- **Purpose**: Explicit type application: `<hole> @type`
- **Translation**: `\e -> App e (Type ty)`
- **Created by**: `mkWpTyApps` during polymorphic instantiation
- **Example**: `id @Bool` → `WpTyApp Bool`

### 3. WpEvApp - Evidence Application
- **Purpose**: Dictionary application: `<hole> dict`
- **Translation**: `\e -> App e (dsEvTerm tm)`
- **Created by**: `mkWpEvApps` for type class evidence
- **Example**: `(+) $fNumInt` → `WpEvApp $fNumInt`

### 4. WpCast - Type Coercion
- **Purpose**: Type cast: `<hole> |> co`
- **Translation**: `\e -> Cast e co`
- **Created by**: `mkWpCastN/R` during unification/subsumption
- **Example**: GADT pattern matching coercions

### 5. WpTyLam - Type Abstraction
- **Purpose**: Type lambda: `/\tv. <hole>`
- **Translation**: `\e -> Lam tv e`
- **Created by**: `mkWpTyLams` during generalization

### 6. WpEvLam - Evidence Abstraction
- **Purpose**: Dictionary lambda: `\ev. <hole>`
- **Translation**: `\e -> Lam ev e`
- **Created by**: `mkWpEvLams` for dictionary abstraction

### 7. WpLet - Evidence Bindings
- **Purpose**: Let-bindings for evidence: `let binds in <hole>`
- **Translation**: `\e -> Let (dsEvBinds bs) e`
- **Created by**: `mkWpLet` for superclass dictionaries

### 8. WpFun - Function Wrapper
- **Purpose**: Function argument/result wrapping
- **Translation**: `\e -> Lam x (w2 (App e (w1 (Var x))))`
- **Created by**: `mkWpFun` for deep subsumption
- **Note**: Involves eta-expansion (see Note [Desugaring WpFun])

### 9. WpCompose - Sequential Composition
- **Purpose**: Composes two wrappers: `w1[w2[e]]`
- **Translation**: Function composition `w1 . w2`
- **Created by**: `(<.>)` operator
- **Note**: `w2` is applied first, then `w1`

### 10. WpSubType - Deep Subsumption Marker
- **Purpose**: Tags wrappers for deep subsumption optimization
- **Translation**: Optimizes payload via `optSubTypeHsWrapper`
- **Created by**: `mkWpSubType` during subtype checking
- **Note**: Semantically equivalent to its payload

---

## Smart Constructors and API

**Location**: `GHC/Tc/Types/Evidence.hs`

```haskell
-- Type applications
mkWpTyApps    :: [Type] -> HsWrapper          -- line 460-461

-- Evidence applications
mkWpEvApps    :: [EvTerm] -> HsWrapper        -- line 463-464
mkWpEvVarApps :: [EvVar] -> HsWrapper         -- line 466-467

-- Coercions
mkWpCastN     :: TcCoercionN -> HsWrapper     -- line 453-457
mkWpCastR     :: TcCoercionR -> HsWrapper     -- line 447-451

-- Abstractions
mkWpTyLams    :: [TyVar] -> HsWrapper         -- line 469-470
mkWpEvLams    :: [Var] -> HsWrapper           -- line 482-483

-- Bindings
mkWpLet       :: TcEvBinds -> HsWrapper       -- line 485-488

-- Function wrapping
mkWpFun       :: HsWrapper -> HsWrapper -> (SubMultCo, TcTypeFRR) -> TcType -> HsWrapper  -- line 392-417

-- Composition
(<.>)         :: HsWrapper -> HsWrapper -> HsWrapper  -- line 331-343
```

---

## Translation to Core

**Location**: `GHC/HsToCore/Binds.hs`

The desugarer translates wrappers to Core transformations:

```haskell
dsHsWrapper :: HsWrapper -> ((CoreExpr -> CoreExpr) -> DsM a) -> DsM a

go WpHole k = k $ \e -> e
go (WpTyApp ty) k = k $ \e -> App e (Type ty)
go (WpEvApp tm) k = do { core_tm <- dsEvTerm tm
                       ; k $ \e -> e `App` core_tm }
go (WpCast co) k = k $ \e -> mkCastDs e co
go (WpTyLam tv) k = k $ \e -> Lam tv e
go (WpEvLam ev) k = k $ \e -> Lam ev e
go (WpLet binds) k = dsTcEvBinds binds $ \bs ->
                     k (mkCoreLets bs)
go (w1 `WpCompose` w2) k = go w1 $ \f1 ->
                           go w2 $ \f2 ->
                           k (f1 . f2)
go (WpSubType w) k = go (optSubTypeHsWrapper w) k
```

---

## Wrapper Creation Sites

### Primary: Type Checker (GHC/Tc/)

**GHC/Tc/Utils/Unify.hs** - Subsumption checking:
```haskell
-- Creating function wrappers
let wrap_fun2 = mkWpFun idHsWrapper wrap_res ...

-- Creating let wrappers
return (mkWpLet ev_binds, result)

-- Creating cast wrappers
return (mkWpCastN co, result)
```

**GHC/Tc/Gen/Expr.hs** - Expression type checking:
```haskell
-- Implicit parameter wrappers
let wrap = mkWpEvVarApps [ip_dict] <.> mkWpTyApps [ip_name, ip_ty]

-- Typeable evidence wrappers
let wrap = mkWpEvVarApps [typeable_ev] <.> mkWpTyApps [expr_ty]
```

**GHC/Tc/Gen/App.hs** - Application checking:
```haskell
-- Visible type application
let wrap = mkWpTyApps [ty_arg]
```

**GHC/Tc/Gen/Pat.hs** - Pattern matching:
```haskell
-- Pattern coercion wrappers
return (mkWpCastN co, bndr_id)

-- View pattern wrappers
return (mkWpCastN (mkSymCo co) <.> wrap, res)
```

### Secondary: Desugaring

**GHC.HsToCore.Quote** (Template Haskell):
```haskell
monadWrapper = mkWpEvApps [...] <.> mkWpTyApps [...]
-- Immediately consumed by dsHsWrapper
```

**GHC.HsToCore.Arrows** (Arrow notation):
```haskell
mkHsWrap (mkWpTyApps [ty1, ty2]) left_id
-- For new AST fragments
```

---

## Where Wrappers Live in the AST

Wrappers appear **only in GhcTc-phase** types:

```haskell
-- In SyntaxExprTc (GHC/Hs/Expr.hs)
data SyntaxExprTc = SyntaxExprTc {
    syn_expr      :: HsExpr GhcTc,
    syn_arg_wraps :: [HsWrapper],
    syn_res_wrap  :: HsWrapper
}

-- In XXExprGhcTc via WrapExpr (GHC/Hs/Expr.hs)
data XXExprGhcTc
  = WrapExpr HsWrapper (HsExpr GhcTc)
  | ...

-- In FunBind (GHC/Hs/Binds.hs)
type instance XFunBind (GhcPass pL) GhcTc = (HsWrapper, [CoreTickish])

-- In ABExport (GHC/Hs/Binds.hs)
data ABExport = ABE {
    abe_wrap      :: HsWrapper,
    ...
}

-- In patterns (GHC/Hs/Pat.hs)
data CoPat = CoPat { co_cpt_wrap :: HsWrapper, ... }
data ConPatTc = ConPatTc { cpt_wrap :: HsWrapper, ... }
```

**Key Insight**: `HsWrapper` is fundamentally a type-checker concept tied to:
- `TcCoercion` (type coercions)
- `EvTerm` (evidence terms)
- `TcEvBinds` (evidence bindings)
- `TyVar` (type variables with Tc-specific info)

---

## Validation and Invariants

### Hypothesis 1: HsWrapper Only in GhcTc Types

**STATUS: ✓ CONFIRMED**

- No `HsWrapper` in `GhcPs`-indexed types
- No `HsWrapper` in `GhcRn`-indexed types
- All wrapper fields are in GhcTc-specific types:
  - `SyntaxExprTc` (explicitly GhcTc)
  - `XXExprGhcTc` (WrapExpr)
  - `XFunBind ... GhcTc`
  - `ABE`, `CoPat`, `ConPatTc`

### Hypothesis 2: Created Only During Type Checking

**STATUS: ⚠️ MOSTLY TRUE**

- **Primary creation**: Type checker (GHC/Tc/) - subsumption, unification, evidence
- **Secondary creation**: Desugaring for special cases:
  - Template Haskell quotation (immediately consumed)
  - Arrow notation (new AST fragments)
  - AST construction utilities

**Key distinction**: Desugaring-phase wrappers are either immediately consumed or attached to newly constructed `HsExpr GhcTc` that gets immediately desugared.

---

## Common Composition Patterns

### Pattern 1: Polymorphic Function with Dictionary
```haskell
mkWpTyApps [ty] <.> mkWpEvApps [dict]
-- Elaborates: f  -->  f @ty dict
```

### Pattern 2: Polymorphic Abstraction
```haskell
mkWpTyLams tvs <.> mkWpEvLams evs <.> mkWpLet binds
-- Elaborates: e  -->  /\tvs. \evs. let binds in e
```

### Pattern 3: Function with Coercions
```haskell
mkWpFun (mkWpCastN co_arg) (mkWpCastN co_res) ...
-- Elaborates: f  -->  \x. (f (x |> co_arg)) |> co_res
```

---

## Syntax → Rule → Wrapper Correspondence

| HsExpr Form | Type Checking Rule | Wrapper Pattern | Source Location |
|-------------|-------------------|-----------------|-----------------|
| `HsVar x` | `tcApp` → `tcInferAppHead` | `WpTyApp` / `WpEvApp` | `GHC/Tc/Gen/Expr.hs:311` |
| `HsApp f a` | `tcApp` chain | `WpCompose` | `GHC/Tc/Gen/App.hs:218-220` |
| `HsAppType f @ty` | `tcApp` VTA | `WpTyApp ty` | `GHC/Tc/Gen/App.hs:754` |
| `OpApp x + y` | `tcApp` operator | `WpEvApp dict` | `GHC/Tc/Gen/Expr.hs:313` |
| `HsLam p e` | `tcLambdaMatches` | `WpFun` / `WpTyLam` | `GHC/Tc/Gen/Expr.hs:367-369` |
| `HsCase e alts` | `tcExpr` case | `WpCast` (GADT) | `GHC/Tc/Gen/Pat.hs:346` |
| `HsLet b e` | `tcLocalBinds` | `WpLet` | Evidence bindings |
| `ExprWithTySig` | `tcApp` | Subsumption wrappers | `GHC/Tc/Gen/Expr.hs:315` |

---

## Wrapper Attachment Rules

| Wrapper Type | Attached To | Created By | Purpose |
|--------------|-------------|------------|---------|
| `WpTyApp`, `WpEvApp` | Function node | `tcInstFun` | Instantiate polymorphic function |
| `WpTyLam`, `WpEvLam` | Lambda node | `tcLambdaMatches` | Abstract over types/evidence |
| `WpFun` | Lambda node | Deep subsumption | Eta-expansion wrapper |
| `WpCast` | Variable/Lambda/Case | Unification, GADT | Type coercion |
| `WpLet` | Let node | `tcLocalBinds` | Evidence bindings |
| Result wrappers | Application node | `checkResultTy` | Match result to expected type |

**Critical Insight**: The application node stores **only result-type wrappers**:
```haskell
finishApp tc_head tc_args app_res_rho res_wrap
  = return (mkHsWrap res_wrap (rebuildHsApps tc_head tc_args))
  -- Only res_wrap here!
```

Function wrappers → attached to function head node  
Argument wrappers → attached to each argument node  
Result wrappers → attached to application node

---

## Key Design Principles

1. **Expression-to-Expression**: Each wrapper is a `CoreExpr -> CoreExpr` transformation

2. **Order Matters**: In `w1 <.> w2`, `w2` is applied first (like function composition)

3. **Identity Optimization**: `WpHole` eliminates unnecessary wrapper construction

4. **Cast Coalescing**: Multiple casts combine via transitivity

5. **Evidence Terms**: Wrappers are a DSL for type-checker evidence

---

## Detailed Examples

### Example 1: Polymorphic Function Application

**Source**: `id @Int 5`

**Type Checking**:
```haskell
-- Infers id's type: forall a. a -> a
-- Instantiation: a = Int
-- Builds wrapper: WpTyApp Int
result = mkHsWrap (WpTyApp Int) (HsVar id)
```

**Desugaring**:
```haskell
go (WpTyApp ty) k = k $ \e -> App e (Type ty)
-- Produces: App (Var id) (Type Int)
```

### Example 2: Type Class Method

**Source**: `1 + 2`

**Type Checking**:
```haskell
-- (+) :: forall a. Num a => a -> a -> a
-- a = Int, evidence: $fNumInt :: Num Int
wrap = WpTyApp Int <.> WpEvApp $fNumInt
```

**Desugaring**:
```haskell
-- Produces: App (App (Var (+)) (Type Int)) (Var $fNumInt)
```

### Example 3: GADT Pattern Match

**Source**:
```haskell
data T a where K :: Int -> T Bool
f (K x) = x  -- x :: Int, expected :: Bool
```

**Type Checking**:
```haskell
-- Coercion generated: co :: Int ~# Bool
-- Builds wrapper: WpCast (sym co)
result = mkHsWrap (WpCast (sym co)) (HsVar x)
```

**Desugaring**:
```haskell
go (WpCast co) k = k $ \e -> mkCastDs e co
-- Produces: Cast (Var x) (sym co)
```

---

## Source File Summary

### Type Checker (Creating Wrappers)
- `GHC/Tc/Types/Evidence.hs` - Wrapper definitions, smart constructors
- `GHC/Tc/Gen/Expr.hs` - Expression type checking
- `GHC/Tc/Gen/App.hs` - Application type checking
- `GHC/Tc/Gen/Head.hs` - Head expression inference
- `GHC/Tc/Gen/Pat.hs` - Pattern type checking
- `GHC/Tc/Utils/Unify.hs` - Subsumption, function wrappers

### Desugarer (Consuming Wrappers)
- `GHC.HsToCore.Binds` - Main wrapper desugaring (`dsHsWrapper`)
- `GHC.HsToCore.Expr` - Expression desugaring

---

## Conclusion

`HsWrapper` is GHC's **evidence recording mechanism** that:

1. **Records** type-checker elaborations (type apps, dictionaries, coercions)
2. **Enables** optimization before Core generation
3. **Decouples** type inference from Core construction
4. **Appears only** in GhcTc-phase types
5. **Guides** the desugarer in building System FC terms

This architecture separates the complexity of type inference from Core AST construction while preserving all necessary type information through the intermediate evidence layer.

---

**Related Documents**:
- `TYPE_INFERENCE.md` - Complete type inference system
- `CORE_SYSTEM_F.md` - Core language and translation
- `FLOW_DIAGRAMS.md` - Visual representations
