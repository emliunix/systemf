# matchExpectedFunTys Call Graph and Closure Passing Map

**Status**: Complete  
**Last Updated**: 2026-04-09  
**Central Question**: How do functions orchestrate type-checking via closure passing through matchExpectedFunTys?

---

## Function List

### Primary Entry Points (Drivers)

1. **tcFunBindMatches** - Driver for function bindings
2. **tcLambdaMatches** - Driver for lambda expressions
3. **tcPolyExprCheck** - Driver for polymorphic expression checking

### Core Type Decomposition

4. **matchExpectedFunTys** - Decomposes expected function types
5. **tcMatches** - Type-checks match groups
6. **tcMatch** - Type-checks individual matches
7. **tcMatchPats** - Type-checks patterns

### Supporting Functions

8. **tcSkolemiseCompleteSig** - Skolemises complete signatures
9. **tcSkolemiseGeneral** - General skolemisation
10. **checkConstraints** - Builds implication constraints
11. **tcGRHSs** - Type-checks guarded right-hand sides

---

## Compact Function Signatures & Closure Contracts

| Function | Key Arguments (Type) | Closure Arguments | Closure Returns | Overall Returns |
|----------|---------------------|-------------------|-----------------|-----------------|
| **tcFunBindMatches** | `ctxt::UserTypeCtxt`, `fun_name::Name`, `mult::Mult`, `matches::MatchGroup`, `invis_pat_tys::[ExpPatType]`, `exp_ty::ExpRhoType` | `pat_tys::[ExpPatType]`, `rhs_ty::ExpRhoType` | `MatchGroup GhcTc` | `(HsWrapper, MatchGroup GhcTc)` |
| **tcLambdaMatches** | `e::HsExpr GhcRn`, `lam_variant::HsLamVariant`, `matches::MatchGroup`, `invis_pat_tys::[ExpPatType]`, `res_ty::ExpSigmaType` | `pat_tys::[ExpPatType]`, `rhs_ty::ExpRhoType` | `MatchGroup GhcTc` | `(HsWrapper, MatchGroup GhcTc)` |
| **matchExpectedFunTys** | `herald::ExpectedFunTyOrigin`, `ctxt::UserTypeCtxt`, `arity::VisArity`, `exp_ty::ExpSigmaType`, `thing_inside::Closure` | `pat_tys::[ExpPatType]`, `res_ty::ExpRhoType` | `a` (polymorphic) | `(HsWrapper, a)` |
| **tcMatches** | `ctxt::HsMatchContextRn`, `tc_body::TcMatchAltChecker`, `pat_tys::[ExpPatType]`, `rhs_ty::ExpRhoType`, `matches::MatchGroup` | N/A (terminal) | N/A | `MatchGroup GhcTc` |
| **tcMatch** | `tc_body::TcMatchAltChecker`, `pat_tys::[ExpPatType]`, `rhs_ty::ExpRhoType`, `match::LMatch` | N/A (terminal) | N/A | `LMatch GhcTc` |
| **tcPolyExprCheck** | `sig::TcSigmaType`, `e::HsExpr GhcRn`, `res_ty::ExpRhoType` | `pat_tys::[ExpPatType]`, `rho_ty::TcRhoType` | `HsExpr GhcTc` | `(HsWrapper, HsExpr GhcTc)` |
| **tcSkolemiseCompleteSig** | `sig::TcSigInfo`, `thing_inside::Closure` | `pat_tys::[ExpPatType]`, `rho_ty::TcRhoType` | `a` | `a` |

**Key Insight**: The closure arguments (`pat_tys`, `rhs_ty`/`res_ty`/`rho_ty`) represent the **decomposed function type** - essentially the return value of the type decomposition performed by `matchExpectedFunTys` or skolemisation functions.

---

## tcSkolemiseCompleteSig: The Signature Skolemiser

**Location**: `GHC.Tc.Utils.Unify:463-478`

**Purpose**: Skolemises a **complete type signature** (e.g., `f :: forall a. a -> a`) and sets up the environment for type-checking the function body.

### Implementation

```haskell
tcSkolemiseCompleteSig :: HasDebugCallStack => TcCompleteSig
                       -> ([ExpPatType] -> TcRhoType -> TcM result)
                       -> TcM (HsWrapper, result)

tcSkolemiseCompleteSig (CSig { sig_bndr = poly_id, sig_ctxt = ctxt, sig_loc = loc })
                       thing_inside
  = do { cur_loc <- getSrcSpanM
       ; let poly_ty = idType poly_id
       ; setSrcSpan loc $   -- Sets the location for the implication constraint
         tcSkolemiseGeneral Shallow ctxt poly_ty poly_ty $ \tv_prs rho_ty ->
         setSrcSpan cur_loc $ -- Revert to the original location
         tcExtendNameTyVarEnv (map (fmap binderVar) tv_prs) $
         thing_inside (map (mkInvisExpPatType . snd) tv_prs) rho_ty }
```

### Step-by-Step Breakdown

1. **Extract the polymorphic type**: Gets `poly_ty` from `sig_bndr` (the Id from the signature)

2. **Call `tcSkolemiseGeneral`** with:
   - `Shallow`: Shallow skolemisation mode
   - `ctxt`: User type context (from signature)
   - `poly_ty`: The type to skolemise
   - `\tv_prs rho_ty -> ...`: The closure

3. **Extend environment**: `tcExtendNameTyVarEnv` brings skolemised type variables into scope
   - `tv_prs :: [(Name, InvisTVBinder)]` - pairs of original names and skolem binders

4. **Call `thing_inside`** with:
   - `map (mkInvisExpPatType . snd) tv_prs`: Invisible pattern types from skolems → `[ExpPatType]`
   - `rho_ty`: The rho-type (body of the type after skolemising)

### What it Returns

- `HsWrapper`: A coercion wrapper that converts between the skolemised type and the original polymorphic type
- `result`: Whatever the closure returns

### The Wrapper Type

The wrapper has type: `spec_ty ~~> expected_ty`

Where:
- `spec_ty`: The instantiated/skolemised type (monomorphic)
- `expected_ty`: The original polymorphic type from the signature

### Key Difference from matchExpectedFunTys

| Aspect | tcSkolemiseCompleteSig | matchExpectedFunTys |
|--------|------------------------|---------------------|
| **Input** | `TcCompleteSig` (from signature) | `ExpSigmaType` (expected type) |
| **Skolemisation** | Shallow only | Shallow or Deep |
| **When called** | Before tcFunBindMatches | Inside tcFunBindMatches |
| **Pattern types** | Returns invisible types only | Returns visible types only |
| **Use case** | Functions with complete signatures | All function type checking |

### Example

For `f :: forall a. Eq a => a -> a`:

1. `poly_ty = forall a. Eq a => a -> a`
2. After `tcSkolemiseGeneral Shallow`:
   - `tv_prs = [(a, a_sk)]` where `a_sk` is a skolem
   - `rho_ty = a_sk -> a_sk` (after removing `forall a` and `Eq a =>`)
3. Closure receives:
   - `invis_pat_tys = [ExpForAllPatTy a_sk, ExpForAllPatTy (Eq a_sk)]` (invisible)
   - `rho_ty = a_sk -> a_sk`
4. Then `tcFunBindMatches` is called with these, and will decompose `a_sk -> a_sk` into visible argument types

---

## Closure Construction Sites: Where Everything Combines

The closures are the **coordination points** where type decomposition results are combined with the actual work of type-checking. Here are the three main closure construction sites:

### Site 1: tcPolyCheck (Complete Signature Path)

**Location**: `Bind.hs:585-593`

**What it does**: Constructs a closure that receives skolemised types from the signature and calls `tcFunBindMatches`.

```haskell
-- OUTER CLOSURE: Passed to tcSkolemiseCompleteSig
\invis_pat_tys rho_ty ->
  let mono_id = mkLocalId mono_name (idMult poly_id) rho_ty in
  tcExtendBinderStack [TcIdBndr mono_id NotTopLevel] $
  setSrcSpanA bind_loc  $
  -- INNER CALL: Direct call to tcFunBindMatches (NO CLOSURE HERE)
  tcFunBindMatches ctxt mono_name mult matches invis_pat_tys (mkCheckExpType rho_ty)
```

**Key Insight**: 
- `tcPolyCheck` does NOT pass a closure to `tcFunBindMatches`
- Instead, it passes `invis_pat_tys` and `rho_ty` **directly** as arguments
- The closure work is done by `tcSkolemiseCompleteSig`, not `matchExpectedFunTys`

**What the closure captures**:
- `mono_name`: Fresh name for the monomorphic binding
- `poly_id`: The polymorphic Id from the signature
- `ctxt`: User type context
- `mult`: Multiplicity
- `matches`: The match group
- `bind_loc`: Source location

---

### Site 2: tcFunBindMatches (The Real Closure Constructor)

**Location**: `Match.hs:120-131`

**What it does**: This is where the **real closure construction** happens - the closure that gets passed to `matchExpectedFunTys`.

```haskell
-- CLOSURE CONSTRUCTION: Passed to matchExpectedFunTys
\ pat_tys rhs_ty ->
  tcScalingUsage mult $
    do { traceTc "tcFunBindMatches 2" $
         vcat [ text "ctxt:" <+> pprUserTypeCtxt ctxt
              , text "arity:" <+> ppr arity
              , text "invis_pat_tys:" <+> ppr invis_pat_tys
              , text "pat_tys:" <+> ppr pat_tys
              , text "rhs_ty:" <+> ppr rhs_ty ]
       ; tcMatches mctxt tcBody (invis_pat_tys ++ pat_tys) rhs_ty matches }
```

**What the closure captures**:
- `mult`: Multiplicity for linear types (line 121)
- `ctxt`: User type context (used in trace, line 125)
- `arity`: Function arity (used in trace, line 126)
- `invis_pat_tys`: Invisible pattern types from prior skolemisation (line 127)
- `mctxt`: Match context for pattern checking (line 131)
- `tcBody`: Function to type-check RHS bodies (line 131)
- `matches`: The match group to type-check (line 131)

**The Magic**: 
- Combines `invis_pat_tys` (invisible binders) with `pat_tys` (visible args) → `[ExpPatType]`
- Calls `tcMatches` with the combined pattern types and the result type `rhs_ty`

---

### Site 3: tcLambdaMatches (Lambda Closure)

**Location**: `Match.hs:155-156`

**What it does**: Constructs a closure for lambda expressions, very similar to `tcFunBindMatches`.

```haskell
-- CLOSURE CONSTRUCTION: Passed to matchExpectedFunTys
\ pat_tys rhs_ty ->
  tcMatches ctxt tc_body (invis_pat_tys ++ pat_tys) rhs_ty matches
```

**What the closure captures**:
- `ctxt`: Lambda alternative context
- `tc_body`: Body type-checker (tcBody or tcBodyNC)
- `invis_pat_tys`: Previously skolemised invisible binders
- `matches`: The match group

**Difference from tcFunBindMatches**:
- Simpler - no multiplicity handling
- No tracing
- Same pattern: combines invisible + visible pattern types

---

## Summary: The Closure Pattern

### The Universal Pattern

```haskell
-- 1. OUTER CLOSURE: Skolemisation (if needed)
outer_function $ \intermediate_types ->
  
  -- 2. TYPE DECOMPOSITION: Calls matchExpectedFunTys with inner closure
  matchExpectedFunTys ... $ \pat_tys rhs_ty ->
    
    -- 3. INNER CLOSURE: Combines types and does the work
    actual_work (combine invisible_and_visible pat_tys) rhs_ty
```

### Three Variations

| Variation | Outer Closure | matchExpectedFunTys | Pattern Type Combination |
|-----------|---------------|---------------------|--------------------------|
| **Complete Signature** | `tcSkolemiseCompleteSig` | Direct call (no closure) | `invis_pat_tys` passed directly |
| **Function Binding** | None | Closure passed | `invis_pat_tys ++ pat_tys` |
| **Lambda** | None | Closure passed | `invis_pat_tys ++ pat_tys` |

### Key Observation

**tcPolyCheck is different** - it uses `tcSkolemiseCompleteSig` to handle the signature skolemisation OUTSIDE of `matchExpectedFunTys`. The closure is at the `tcSkolemiseCompleteSig` level, not the `matchExpectedFunTys` level.

**tcFunBindMatches and tcLambdaMatches** - both construct closures that are passed to `matchExpectedFunTys`. The skolemisation happens INSIDE `matchExpectedFunTys`.

---

## Closure Captures: What Gets Bundled

### tcPolyCheck Closure Captures
- Signature info (`poly_id`)
- Source location (`bind_loc`)
- Context (`ctxt`)
- Multiplicity (`mult`)
- Matches (`matches`)

### tcFunBindMatches Closure Captures
- Multiplicity (`mult`)
- Context info (`ctxt`, `mctxt`)
- Pattern types (`invis_pat_tys`)
- Body checker (`tcBody`)
- Matches (`matches`)

### tcLambdaMatches Closure Captures
- Context (`ctxt`)
- Body checker (`tc_body`)
- Pattern types (`invis_pat_tys`)
- Matches (`matches`)

---

## Ultimate Entry Points: The Generalisation Plan Decision

Both `tcPolyCheck` and `tcMonoBinds` are called from **`tcPolyBinds`** (the main binding type-checker) based on the **Generalisation Plan** determined by `decideGeneralisationPlan`.

### The Decision Point (tcPolyBinds)

**Location**: `Bind.hs:478-483`

```haskell
decideGeneralisationPlan dflags top_lvl closed sig_fn bind_list
case plan of
    NoGen              -> tcPolyNoGen rec_tc prag_fn sig_fn bind_list
                         -- ...which calls tcMonoBinds
    InferGen           -> tcPolyInfer top_lvl rec_tc prag_fn sig_fn bind_list
                         -- ...which calls tcMonoBinds
    CheckGen lbind sig -> tcPolyCheck prag_fn sig lbind
                         -- ...which calls tcFunBindMatches directly
```

### When Each Path is Taken

| Plan | Condition | Caller of tcFunBindMatches | Type Signature? |
|------|-----------|----------------------------|-----------------|
| **CheckGen** | Single function with **complete signature** | `tcPolyCheck` (direct) | `f :: Int -> Int` |
| **InferGen** | Multiple bindings or **partial signatures** | `tcMonoBinds` → `tcRhs` | `f :: _ -> _` or none |
| **NoGen** | Local bindings with MonoLocalBinds | `tcMonoBinds` (special case) | None |

### Key Differences

**tcPolyCheck Path (CheckGen):**
- **Used for**: Functions with **complete type signatures** (e.g., `f :: Int -> Int`)
- **Skolemisation**: Calls `tcSkolemiseCompleteSig` first to skolemise the signature
- **Expected Type**: The type comes from the signature (already known)
- **Pattern Types**: Receives invisible pattern types from skolemisation
- **Flow**: `tcSkolemiseCompleteSig` → `tcFunBindMatches` (with skolemised types)

**tcMonoBinds Path (InferGen/NoGen):**
- **Used for**: Functions **without signatures** or with **partial signatures** (e.g., `f :: _ -> _`)
- **Skolemisation**: Done inside `matchExpectedFunTys` as needed
- **Expected Type**: Fresh unification variable (to be inferred)
- **Pattern Types**: Empty `[]` initially
- **Two sub-cases**:
  1. **Special Case** (lines 1297-1326): Direct call for non-recursive, no-sig functions
  2. **General Case** (lines 1379-1399): Via `tcLhs` → `tcRhs` → `tcFunBindMatches`

### Complete Call Hierarchy

```
tcPolyBinds (main entry point)
    ↓
decideGeneralisationPlan
    ↓
    ├─ CheckGen (complete signature)
    │   ↓
    │   tcPolyCheck
    │       ↓ calls (with closure)
    │       tcSkolemiseCompleteSig
    │           ↓ invokes closure
    │           tcFunBindMatches (direct)
    │               ↓ calls with closure
    │               matchExpectedFunTys
    │
    ├─ InferGen (partial sig or no sig)
    │   ↓
    │   tcPolyInfer
    │       ↓
    │       tcMonoBinds
    │           ↓
    │           ├─ Special case: direct tcFunBindMatches
    │           └─ General case: tcLhs → tcRhs → tcFunBindMatches
    │
    └─ NoGen (local, no generalisation)
        ↓
        tcPolyNoGen
            ↓
            tcMonoBinds (same as above)
```

### Summary Table: Who Calls Whom

| Caller | Location | Purpose | Arguments Passed |
|--------|----------|---------|------------------|
| **tcPolyCheck** | `Bind.hs:585-593` | Type-checks functions with **complete signatures** | `ctxt`, `mono_name`, `mult`, `matches`, `invis_pat_tys`, `rho_ty` |
| **tcMonoBinds (Special Case 1)** | `Bind.hs:1307-1315` | Non-recursive function **without signature** | `InfSigCtxt name`, `name`, `mult`, `matches`, `[]`, `exp_ty` |
| **tcRhs** | `Bind.hs:1593-1594` | Type-checks RHS of monomorphic bindings | `InfSigCtxt mono_name`, `mono_name`, `mult`, `matches`, `[]`, `mono_ty` |

### Callers of `tcLambdaMatches`

| Caller | Location | Purpose | Arguments Passed |
|--------|----------|---------|------------------|
| **tcPolyExprCheck** | `Expr.hs:178-180` | Type-checks lambda in polymorphic context | `e`, `lam_variant`, `matches`, `pat_tys`, `res_ty` |
| **tcExpr (HsLam case)** | `Expr.hs:368` | Type-checks lambda expressions | `e`, `lam_variant`, `matches`, `[]`, `res_ty` |

### Ultimate Entry Points Hierarchy

```
Top-Level Type Checking (e.g., tcTopBinds, tcExpr)
    ↓
    ├─ Function Bindings Path:
    │   tcPolyCheck (for complete signatures)
    │       ↓ calls
    │   tcFunBindMatches
    │       ↓ calls with closure
    │   matchExpectedFunTys
    │       ↓ invokes closure
    │   tcMatches
    │
    ├─ Lambda Path:
    │   tcExpr (HsLam case)
    │       ↓ calls
    │   tcPolyExprCheck (if polymorphic)
    │       ↓ calls
    │   tcLambdaMatches
    │       ↓ calls with closure
    │   matchExpectedFunTys
    │       ↓ invokes closure
    │   tcMatches
    │
    └─ Let/Where Bindings Path:
        tcMonoBinds
            ↓
        ├─ Special case: direct tcFunBindMatches call
        └─ General case: tcLhs → tcRhs → tcFunBindMatches
```

---

## Closure Passing Architecture

### Pattern: The CPS-style Type Decomposition

The architecture follows a **continuation-passing style (CPS)** where:
- A driver function calls `matchExpectedFunTys` with a closure (callback)
- The closure receives decomposed types and performs the actual work
- Results flow back through the wrapper/coercion mechanism

```
Driver
  ↓ calls with closure
matchExpectedFunTys
  ↓ invokes closure with [ExpPatType] and ExpRhoType
Closure (thing_inside)
  ↓ calls
tcMatches / tcExpr / etc.
```

---

## Detailed Call Graph with Closure Passing

### 1. tcFunBindMatches (Main Driver)

**Location**: `GHC.Tc.Gen.Match:103-137`

**Purpose**: Type-checks function bindings (e.g., `f x y = rhs`)

**Signature**:
```haskell
tcFunBindMatches :: UserTypeCtxt
                 -> Name            -- Function name
                 -> Mult            -- Multiplicity of the binder
                 -> MatchGroup GhcRn (LHsExpr GhcRn)
                 -> [ExpPatType]    -- Scoped skolemised binders
                 -> ExpRhoType      -- Expected type of function
                 -> TcM (HsWrapper, MatchGroup GhcTc (LHsExpr GhcTc))
```

**Closure Passed to matchExpectedFunTys**:
```haskell
\ pat_tys rhs_ty ->
  tcScalingUsage mult $
    do { traceTc "tcFunBindMatches 2" $
         vcat [ text "ctxt:" <+> pprUserTypeCtxt ctxt
              , text "arity:" <+> ppr arity
              , text "invis_pat_tys:" <+> ppr invis_pat_tys
              , text "pat_tys:" <+> ppr pat_tys
              , text "rhs_ty:" <+> ppr rhs_ty ]
       ; tcMatches mctxt tcBody (invis_pat_tys ++ pat_tys) rhs_ty matches }
```

**Closure Captures**:
- `mult`: Multiplicity for linear types
- `invis_pat_tys`: Previously skolemised invisible binders
- `mctxt`: Match context (FunRhs)
- `matches`: The match group to type-check

**Flow**:
1. Gets arity from `checkArgCounts`
2. Calls `matchExpectedFunTys` with closure
3. Closure receives `pat_tys` (visible argument types) and `rhs_ty` (result type)
4. Combines `invis_pat_tys ++ pat_tys`
5. Calls `tcMatches` with combined pattern types

---

### 2. tcLambdaMatches (Lambda Driver)

**Location**: `GHC.Tc.Gen.Match:145-171`

**Purpose**: Type-checks lambda expressions (e.g., `\x y -> rhs`)

**Signature**:
```haskell
tcLambdaMatches :: HsExpr GhcRn -> HsLamVariant
                -> MatchGroup GhcRn (LHsExpr GhcRn)
                -> [ExpPatType]  -- Already skolemised
                -> ExpSigmaType  -- NB can be a sigma-type
                -> TcM (HsWrapper, MatchGroup GhcTc (LHsExpr GhcTc))
```

**Closure Passed to matchExpectedFunTys**:
```haskell
\ pat_tys rhs_ty ->
  tcMatches ctxt tc_body (invis_pat_tys ++ pat_tys) rhs_ty matches
```

**Closure Captures**:
- `ctxt`: Lambda alternative context
- `tc_body`: Body type-checker (tcBody or tcBodyNC)
- `invis_pat_tys`: Previously skolemised binders
- `matches`: The match group

**Flow**:
1. Gets arity from `checkArgCounts`
2. Calls `matchExpectedFunTys` with closure
3. Combines invisible and visible pattern types
4. Calls `tcMatches` to type-check the match group

---

### 3. matchExpectedFunTys (Core Decomposer)

**Location**: `GHC.Tc.Utils.Unify:792-822 (Infer), 824-945 (Check)`

**Purpose**: Decomposes expected function type, handling skolemisation

**Signature**:
```haskell
matchExpectedFunTys :: forall a.
                       ExpectedFunTyOrigin
                    -> UserTypeCtxt
                    -> VisArity
                    -> ExpSigmaType
                    -> ([ExpPatType] -> ExpRhoType -> TcM a)  -- THE CLOSURE
                    -> TcM (HsWrapper, a)
```

**Closure Contract**:
- **Input**: `[ExpPatType]` (argument types) and `ExpRhoType` (result type)
- **Output**: Result of type `a`
- **Side Effects**: Types are filled in (for Infer mode)

**Modes**:

#### Infer Mode (Line 809):
```haskell
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside = do
  arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]
  res_ty  <- newInferExpType (ir_inst inf_res)
  result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty  -- CALL CLOSURE
  -- ... fill inference result
```

#### Check Mode (Line 824):
```haskell
matchExpectedFunTys herald ctx arity (Check top_ty) thing_inside =
  check arity [] top_ty
  where
    check n_req rev_pat_tys ty = case analysis of
      -- ... skolemise, recurse, or handle function types
      -- Eventually calls:
      thing_inside pat_tys (mkCheckExpType rho_ty)  -- CALL CLOSURE
```

**Wrapper Construction**:
- Returns `HsWrapper` that coerces between the decomposed type and original type
- Wrapper composition: `wrap_gen <.> mkWpLet ev_binds <.> wrap_res`

---

### 4. tcMatches (Match Group Processor)

**Location**: `GHC.Tc.Gen.Match:222-258`

**Purpose**: Type-checks a group of matches (alternatives)

**Signature**:
```haskell
tcMatches :: (AnnoBody body, Outputable (body GhcTc))
          => HsMatchContextRn
          -> TcMatchAltChecker body
          -> [ExpPatType]             -- ^ Expected pattern types
          -> ExpRhoType               -- ^ Expected result-type
          -> MatchGroup GhcRn (LocatedA (body GhcRn))
          -> TcM (MatchGroup GhcTc (LocatedA (body GhcTc)))
```

**Parameters**:
- `pat_tys`: Expected types for patterns (from matchExpectedFunTys via closure)
- `rhs_ty`: Expected result type (from matchExpectedFunTys via closure)
- `tc_body`: Callback to type-check the RHS (not a closure, but a function reference)

**Flow**:
1. For each match, calls `tcMatch`
2. `tcMatch` calls `tcMatchPats` with patterns and types
3. `tcMatchPats` type-checks patterns, then calls `tcGRHSs`
4. `tcGRHSs` calls the `tc_body` callback for each RHS

---

### 5. tcPolyExprCheck (Polymorphic Expression Driver)

**Location**: `GHC.Tc.Gen.Expr:330-368`

**Purpose**: Type-checks expressions with polymorphic expected types

**Closure Usage**:
Calls `tcSkolemiseCompleteSig` which itself uses closure passing:

```haskell
tcSkolemiseCompleteSig sig $ \pat_tys rho_ty ->
  -- Then for lambdas:
  tcLambdaMatches e lam_variant matches pat_tys (mkCheckExpType rho_ty)
```

**Flow**:
1. Skolemises the expected type
2. If expression is a lambda, calls `tcLambdaMatches`
3. Otherwise, calls `tcExpr` with the skolemised type

---

## Closure Passing Chain Diagram

### Function Binding Path

```
tcFunBindMatches (driver)
    ↓
    [captures: mult, invis_pat_tys, mctxt, matches]
    ↓
matchExpectedFunTys
    ↓ skolemises types
    ↓ invokes closure with (pat_tys, rhs_ty)
    ↓
    Closure (thing_inside)
    ↓ combines invis_pat_tys ++ pat_tys
    ↓
    tcMatches
        ↓
        tcMatch (for each alternative)
            ↓
            tcMatchPats
                ↓
                tcGRHSs
                    ↓
                    tcBody (callback for RHS)
                        ↓
                        tcPolyLExpr / tcMonoExprNC
```

### Lambda Expression Path

```
tcPolyExprCheck (driver for polymorphic contexts)
    ↓
tcSkolemiseCompleteSig
    ↓ skolemises outer foralls
    ↓ invokes closure
    ↓
tcLambdaMatches
    ↓
matchExpectedFunTys
    ↓ invokes closure
    ↓
    Closure
    ↓
    tcMatches
        ↓
        ... (same as above)
```

---

## Key Design Patterns

### Pattern 1: Type Decomposition + Closure

```haskell
-- Decompose the type, then delegate to closure
matchExpectedFunTys herald ctxt arity exp_ty $ \arg_tys res_ty ->
  -- Use decomposed types here
  tcMatches ... arg_tys ... res_ty ...
```

**Benefits**:
- Separates type decomposition from type-checking logic
- Allows `matchExpectedFunTys` to handle skolemisation uniformly
- Enables wrapper/coercion construction

### Pattern 2: Accumulating Pattern Types

```haskell
-- In tcFunBindMatches
matchExpectedFunTys ... $ \pat_tys rhs_ty ->
  tcMatches ... (invis_pat_tys ++ pat_tys) rhs_ty ...
```

**Purpose**: Combines invisible binders (from type abstraction) with visible argument types

### Pattern 3: Wrapper Composition

```haskell
return (wrap_gen <.> mkWpLet ev_binds <.> wrap_res, result)
```

**Components**:
- `wrap_gen`: Skolemisation wrapper (type abstraction)
- `ev_binds`: Evidence bindings (constraints)
- `wrap_res`: Result from closure (inner coercions)

---

## Data Flow Summary

| Function | Input | Closure Receives | Closure Returns | Output |
|----------|-------|------------------|-----------------|--------|
| `tcFunBindMatches` | `exp_ty`, `matches` | `[ExpPatType]`, `ExpRhoType` | `MatchGroup GhcTc` | `(HsWrapper, MatchGroup GhcTc)` |
| `tcLambdaMatches` | `res_ty`, `matches` | `[ExpPatType]`, `ExpRhoType` | `MatchGroup GhcTc` | `(HsWrapper, MatchGroup GhcTc)` |
| `matchExpectedFunTys` | `exp_sigma` | `[ExpPatType]`, `ExpRhoType` | `a` | `(HsWrapper, a)` |
| `tcMatches` | `pat_tys`, `rhs_ty` | N/A (direct) | `MatchGroup GhcTc` | `MatchGroup GhcTc` |

---

## Critical Relationships

### 1. tcFunBindMatches ↔ matchExpectedFunTys

**Relationship**: Primary driver-callee relationship

**Closure Semantics**: 
```haskell
-- tcFunBindMatches builds this closure:
\pat_tys rhs_ty -> do
  let all_pat_tys = invis_pat_tys ++ pat_tys
  tcMatches mctxt tcBody all_pat_tys rhs_ty matches
```

**Key Point**: The closure extends the pattern types with invisible binders, then delegates to `tcMatches`

### 2. matchExpectedFunTys ↔ tcMatches

**Relationship**: Type provider ↔ Consumer

**Key Point**: `matchExpectedFunTys` guarantees that returned types have Fixed RuntimeRep (FRR)

### 3. tcMatches ↔ tcBody

**Relationship**: Pattern processor ↔ RHS type-checker

**Callback Pattern**: `tcMatches` receives `tc_body` as a function reference (not closure), calls it for each RHS

---

## Open Questions

1. **Why CPS?** Why is `matchExpectedFunTys` written in CPS style? 
   - Answer: It needs to fill in `ExpTypes` produced for arguments before filling in the `ExpType` passed in

2. **Wrapper Composition**: How do the wrappers from different levels compose?
   - `wrap_gen`: From skolemisation
   - `mkWpLet ev_binds`: From evidence bindings
   - `wrap_res`: From inner type-checking

3. **Error Context**: How does the herald propagate through the closure chain?
   - The herald is used in error messages for arity mismatches
