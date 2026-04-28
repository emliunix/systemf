# GHC Module-Level Type Inference Questions and Answers

**Generated:** 2026-03-19

This document contains technical questions about how GHC's module-level type inference works, focusing on global environment management, function definitions, datatypes, and pattern matching. Each question is followed by detailed answers based on source code analysis.

---

## Table of Contents

1. [Function Definitions](#function-definitions)
2. [Global Item References](#global-item-references)
3. [Datatypes, Type Constructors & Data Constructors](#datatypes-type-constructors--data-constructors)
4. [Pattern Matching Mechanism](#pattern-matching-mechanism)
5. [Cross-Cutting Concerns](#cross-cutting-concerns)

---

## Function Definitions

### Q1: Environment Population

**Question:** When type-checking `f x y = x + y` in a module, at what point does `f` get added to `tcg_type_env` vs remaining in a local environment? What's the difference between `tcg_type_env` and the local gamma context?

**Answer:**

The distinction between global (`tcg_type_env`) and local environments is crucial:

**Local Environment (Gamma Context)**
- Stored in `TcLclEnv` field `tcl_env :: NameEnv TcTyThing`
- Contains `ATcId` entries for identifiers being type-checked
- Used during inference of the RHS before generalization
- When checking `f x y = x + y`, initially `f` is added to the local env as an `ATcId` with a monomorphic type

**Global Environment (`tcg_type_env`)**
- Stored in `TcGblEnv` field `tcg_type_env :: TypeEnv`
- Contains fully type-checked, zonked `TyThing`s (Ids, TyCons, etc.)
- Populated AFTER generalization completes via `tcExtendGlobalEnv`

**The Flow:**

```haskell
-- Step 1: tcTopBinds calls tcValBinds
-- Step 2: For f x y = x + y, during RHS type checking:
--    - 'f' is in local env (tcl_env) as ATcId with monomorphic type
--    - 'x' and 'y' are also in local env
--    - Type inference produces: f :: Int -> Int -> Int (monomorphic)
--
-- Step 3: tcPolyInfer generalizes to: f :: forall a. Num a => a -> a -> a
--
-- Step 4: After generalization, AbsBinds is created and bindings are added
--    to tcg_type_env via addTypecheckedBinds (line 195 in Bind.hs)
```

**Key Insight:** The local environment is the "working set" during inference. The global environment (`tcg_type_env`) is the final, committed repository of type-checked entities for the module.

---

### Q2: Generalization Timing

**Question:** For a top-level function definition without an explicit type signature, when exactly does `tcPolyInfer` generalize `Int -> Int -> Int` to `forall a. Num a => a -> a -> a`? What prevents premature generalization for functions that reference local variables?

**Answer:**

**Generalization happens in `tcPolyInfer`** (GHC/Tc/Gen/Bind.hs, lines 714-766):

```haskell
tcPolyInfer top_lvl rec_tc prag_fn tc_sig_fn bind_list
  = do { -- Step 1: Type-check RHS in a new level with capture constraints
         (tclvl, wanted, (binds', mono_infos))
                <- pushLevelAndCaptureConstraints  $
                   tcMonoBinds rec_tc tc_sig_fn LetLclBndr bind_list

         -- Step 2: Check monomorphism restriction
       ; apply_mr <- checkMonomorphismRestriction mono_infos bind_list
       
         -- Step 3: Call simplifyInfer to quantify over free vars
       ; ((qtvs, givens, ev_binds, insoluble), residual)
             <- captureConstraints $
                simplifyInfer top_lvl tclvl infer_mode sigs name_taus wanted

         -- Step 4: Create AbsBinds with quantified type variables
       ; let abs_bind = AbsBinds { abs_tvs = qtvs
                                 , abs_ev_vars = givens
                                 , abs_exports = exports
                                 , ... }
       }
```

**Preventing Premature Generalization:**

The key mechanism is **`IdBindingInfo`** in `ATcId` (GHC/Tc/Types/BasicTypes.hs, lines 345-349):

```haskell
data IdBindingInfo
    = NotLetBound              -- Bound by lambda or case
    | LetBound ClosedTypeId    -- Bound by let, incl top level

type ClosedTypeId = Bool
```

**Rules:**

1. **For top-level bindings**: The function is `LetBound`, and `ClosedTypeId` is determined by `isTypeClosedLetBndr` (Env.hs line 677):
   - Checks if `noFreeVarsOfType (idType id)`
   - If the type has no free type variables, generalization proceeds

2. **For nested bindings referencing outer variables**: 
   - If `f` references an outer variable `x` that is `NotLetBound`, then `f` cannot generalize
   - See Note [Bindings with closed types: ClosedTypeId] (BasicTypes.hs lines 352-398)

3. **TcLevel mechanism**: Type variables from outer scopes have lower `TcLevel` and are marked as "untouchable" during inference of nested bindings, preventing them from being quantified over.

---

### Q3: Polymorphism Storage

**Question:** In `TcGblEnv`, how is the polymorphic type `forall a. a -> a` stored for a function? Is it stored as a `TyCon`, `Id`, or something else? How does `tcg_type_env` differentiate between type constructors and value identifiers?

**Answer:**

**Storage in `tcg_type_env`:**

`tcg_type_env :: TypeEnv` is a `NameEnv TyThing`, where:

```haskell
-- GHC.Types.TyThing
data TyThing
  = AnId     Id          -- Value identifiers (functions, variables)
  | ATyCon   TyCon       -- Type constructors
  | AConLike ConLike     -- Data constructors or pattern synonyms
  | ACoAxiom CoAxiom     -- Type family instances
```

**For a polymorphic function** `id :: forall a. a -> a`:
- Stored as `AnId id` where `id :: Id`
- The `Id` contains `idType id :: Type` which is the full polymorphic type
- Internally: `ForAllTy (Bndr a Specified) (FunTy a a)`

**Differentiation in TypeEnv:**

All entries are `TyThing`, pattern-matched to distinguish:

```haskell
-- Type constructors: data T a = MkT a
case lookupNameEnv type_env name of
  Just (ATyCon tc) -> ...  -- 'T' is a TyCon
  Just (AnId id)   -> ...  -- 'f' is an Id
  Just (AConLike (RealDataCon dc)) -> ...  -- 'MkT' is a DataCon
```

**Key Fields:**
- `tcg_type_env` holds both type and value-level entities
- Type constructors: `ATyCon` wrapper around `TyCon`
- Value identifiers: `AnId` wrapper around `Id` with full `Type` inside
- Data constructors: `AConLike (RealDataCon dc)` containing `DataCon` with its signature

---

### Q4: Export Collection

**Question:** When processing a module's export list, how does GHC correlate the `Name` from the export list with the `Id` that has the fully-inferred polymorphic type in `tcg_type_env`?

**Answer:**

**Export Processing Flow:**

```haskell
-- In GHC.Tc.Module, exports are processed after type checking completes
-- The tcg_rn_exports field holds renamed exports with their Avails
```

**Correlation Mechanism:**

1. **Names have Uniques**: Every `Name` has a `Unique` (Env.hs):
   ```haskell
   nameUnique :: Name -> Unique
   ```

2. **tcg_type_env is keyed by Name**: 
   ```haskell
   tcg_type_env :: TypeEnv  -- NameEnv TyThing
   ```

3. **Lookup by Name**: In `tcRnExports` (Module.hs):
   ```haskell
   -- Export list processing uses the fully zonked type environment
   env <- getGblEnv
   let type_env = tcg_type_env env
   -- For each export name, lookup in type_env
   case lookupNameEnv type_env name of
     Just thing -> ... -- Found with final type
   ```

4. **Export Representation**: `AvailInfo` contains:
   ```haskell
   data AvailInfo
     = Avail Name                    -- Simple export
     | AvailTC Name [Name] [FieldLabel]  -- Type with constructors/fields
   ```

**Key Point:** The `Name` used in the export list is the SAME `Name` (same `Unique`) that was used when adding the `Id` to `tcg_type_env`. This identity ensures correlation.

---

## Global Item References

### Q5: Variable Lookup Chain

**Question:** When the type checker encounters a variable reference `x` in an expression, what's the exact lookup chain? Does it check `tcg_type_env` first, then imports, or does it use a merged environment?

**Answer:**

**The Lookup Chain** (GHC/Tc/Utils/Env.hs, lines 579-584):

```haskell
tcLookup :: Name -> TcM TcTyThing
tcLookup name = do
    local_env <- getLclEnv
    case lookupNameEnv local_env name of
        Just thing -> return thing           -- Step 1: Check local env
        Nothing    -> AGlobal <$> tcLookupGlobal name  -- Step 2: Check global
```

**tcLookupGlobal** (Env.hs, lines 246-269):

```haskell
tcLookupGlobal name
  = do  { env <- getGblEnv
        ; case lookupNameEnv (tcg_type_env env) name of
                Just thing -> return thing              -- Step 2a: Current module
                Nothing    ->
          if nameIsLocalOrFrom (tcg_semantic_mod env) name
          then notFound name                            -- Step 2b: Should be local but isn't
          else do
            -- Step 3: Look in imports (home/external package tables)
            mb_thing <- tcLookupImported_maybe name
            ...
        }
```

**The Chain:**

1. **Local Environment** (`tcl_env`): Lexically-scoped variables (lambda-bound, pattern-bound)
2. **Module Global** (`tcg_type_env`): Top-level definitions in current module
3. **Imported Names**: 
   - Home package table (other modules being compiled)
   - External package table (installed packages)
   - May trigger interface file loading

**No Merged Environment**: The lookup is hierarchical - it doesn't merge environments upfront. It searches in order of scope: local → module-global → imported.

---

### Q6: Imported vs Local

**Question:** How does `tcLookupId` distinguish between a variable defined in the current module (which should be in `tcg_type_env`) versus an imported variable (which might need interface file loading)?

**Answer:**

**tcLookupIdMaybe** (Env.hs, lines 604-610):

```haskell
tcLookupIdMaybe :: Name -> TcM (Maybe Id)
tcLookupIdMaybe name
  = do { thing <- tcLookup name
       ; case thing of
          ATcId { tct_id = id} -> return $ Just id    -- Local: from tcl_env
          AGlobal (AnId id)    -> return $ Just id    -- Global: from tcg_type_env or imports
          _                    -> return Nothing }
```

**The Distinction is Transparent After Lookup:**

After `tcLookup` returns, the distinction between local (`ATcId`) and global (`AGlobal`) is known:

**For Local Variables:**
- Found in `tcl_env` as `ATcId`
- Has `IdBindingInfo` indicating whether generalization is possible
- Type may contain unfilled meta-variables during inference

**For Imported Variables:**
- Found via `tcLookupGlobal` which checks:
  1. Current module's `tcg_type_env` (already type-checked top-levels)
  2. If not found there, checks `nameIsLocalOrFrom`:
     ```haskell
     if nameIsLocalOrFrom (tcg_semantic_mod env) name
     then notFound name  -- Should be in current module but isn't
     else tcLookupImported_maybe name
     ```
  3. `tcLookupImported_maybe` consults:
     - Home package table
     - External package table (may load interface files)

**Key Insight:** The `Name` itself carries the module information (`nameModule_maybe`), so GHC knows whether to look locally or load from an interface file.

---

### Q7: IdBindingInfo

**Question:** For a function reference like `map` used inside a let-binding, how does `IdBindingInfo` (`NotLetBound` vs `LetBound`) influence whether the type can be generalized or must remain monomorphic?

**Answer:**

**IdBindingInfo Definition** (BasicTypes.hs, lines 345-349):

```haskell
data IdBindingInfo
    = NotLetBound              -- Bound by lambda or case
    | LetBound ClosedTypeId    -- Bound by let, incl top level

type ClosedTypeId = Bool
```

**Usage in Generalization Decision** (Bind.hs, `decideGeneralisationPlan`):

```haskell
-- Can generalize if:
-- 1. The Id is LetBound (not NotLetBound)
-- 2. AND the type is closed (no free type variables)
-- 3. AND all free variables are either:
--    - Global (imported)
--    - OR also LetBound with ClosedTypeId=True
```

**Examples:**

```haskell
-- Example 1: Can generalize
let g ys = map not ys    -- g :: forall a. [Bool] -> [Bool]
-- g is LetBound
-- 'map' is imported (global)
-- 'not' is imported (global)
-- ClosedTypeId = True

-- Example 2: Cannot generalize (references NotLetBound var)
\x -> let g y = x + y    -- g :: Int -> Int (monomorphic)
-- 'x' is NotLetBound (lambda-bound)
-- So g cannot generalize over 'x'

-- Example 3: Nested let, inner can generalize
let f x = let g y = x + y
              h z = map (g z)  
          in ...
-- g is monomorphic (references x which is NotLetBound)
-- h CAN generalize (references g which is LetBound, even though monomorphic)
```

**The Rule:**
- `NotLetBound`: Never generalize (lambda/case-bound)
- `LetBound False`: Don't generalize this binding, but it can be referenced by nested bindings
- `LetBound True`: Can generalize (closed type, no problematic free vars)

See Note [Bindings with closed types: ClosedTypeId] (BasicTypes.hs lines 352-398).

---

### Q8: Cross-Module References

**Question:** When referencing a function from an imported module, how does the interface file mechanism ensure the `Unique` in the current module matches the `Unique` from the imported module's interface file?

**Answer:**

**Interface File Uniques:**

Interface files (.hi) store `Name`s with their `Unique`s directly:

```haskell
-- In GHC.Iface.Syntax
-- Names are serialized with their Unique
-- When loading an interface file, the Unique is read and used directly
```

**The Process** (Env.hs, `tcLookupImported_maybe`):

```haskell
-- Step 1: Try lookup in already-loaded tables
mb_thing <- lookupType hsc_env name  -- Check ExternalPackageTable

-- Step 2: If not found, load interface file
importDecl_maybe hsc_env name
  -- Parses the .hi file
  -- Reconstructs TyThings with the stored Uniques
```

**Unique Consistency:**

1. **Deterministic Name Generation**: GHC uses deterministic name generation for interface files, so the same source code produces the same `Unique`

2. **Serialized in Interface**: The `Unique` is part of the interface file format:
   ```
   Name: package:Module.name _unique_123
   ```

3. **No Reassignment**: When loading, GHC uses the `Unique` from the interface file directly - it doesn't generate new ones for imported names

**Verification**:
```haskell
-- When compiling module B that imports A.f:
-- 1. Load A.hi
-- 2. Find Name for 'f' with Unique U
-- 3. In module B, references to 'f' use the same Unique U
-- 4. This allows the compiler to know they refer to the same entity
```

**Key Point:** Uniques are globally unique across modules because they're based on the name string and module, not assigned sequentially per-module.

---

## Datatypes, Type Constructors & Data Constructors

### Q9: TyCon Population

**Question:** When processing `data T a = MkT a`, at what point do both the type constructor `T` and the data constructor `MkT` get added to `tcg_type_env`? Are they added simultaneously or in separate passes?

**Answer:**

**Multi-Pass Processing** (GHC/Tc/TyCl.hs):

**Pass 1: Kind Checking (Knot-Tying)**
```haskell
-- Create TcTyCon placeholders for T
-- T is added to local env as ATcTyCon (not yet in tcg_type_env)
```

**Pass 2: Type Checking**
```haskell
-- Process data constructors
-- MkT gets its type: forall a. a -> T a
```

**Pass 3: Finalization** (`tcExtendGlobalEnv`):
```haskell
-- Both T and MkT added to tcg_type_env simultaneously
-- This happens after the entire declaration group is checked
```

**The Process**:

1. **Initial Registration** (TyCl.hs):
   ```haskell
   tcTyClDecl ...
     -- Creates TyCon for T
     -- Creates DataCon for MkT
     -- Links them: dataConTyCon MkT = T
   ```

2. **Population to tcg_type_env** (Env.hs, `tcExtendGlobalEnv`):
   ```haskell
   tcExtendGlobalEnv things thing_inside
     = do { env <- getGblEnv
          ; let env' = env { tcg_type_env = extendTypeEnvList (tcg_type_env env) things }
          ; setGblEnv env' thing_inside }
   ```

**Simultaneous Addition:**

Both are added together as a list of `TyThing`s:
```haskell
things = [ ATyCon t            -- Type constructor
         , AConLike (RealDataCon mkT)  -- Data constructor
         ]
```

This ensures atomicity - you can't have `T` in the environment without `MkT` or vice versa.

---

### Q10: Constructor Representation

**Question:** How is the relationship between type constructor `T` and data constructor `MkT` represented? Does `MkT` store a reference to `T` via `dataConTyCon`? How does pattern matching use this relationship?

**Answer:**

**DataCon Fields** (DataCon.hs, lines 382-529):

```haskell
data DataCon = MkData {
    dcName    :: Name,           -- Name (e.g., MkT)
    dcUnique  :: Unique,         -- Cached unique
    dcTag     :: ConTag,         -- Constructor tag (for enumeration)
    
    dcUnivTyVars     :: [TyVar],  -- Universal tyvars [a]
    dcExTyCoVars     :: [TyCoVar], -- Existentials (empty for simple ADT)
    dcEqSpec         :: [EqSpec],  -- GADT equalities (empty for ADT)
    dcOtherTheta     :: ThetaType, -- Constraints
    dcOrigArgTys     :: [Scaled Type], -- Argument types [a]
    dcOrigResTy      :: Type,      -- Result type T a
    
    -- Reference to parent type constructor
    dcRepTyCon       :: TyCon,     -- The TyCon T
    ...
}
```

**The Relationship:**

```haskell
-- MkT stores reference to T via dcRepTyCon
dataConTyCon :: DataCon -> TyCon
dataConTyCon = dcRepTyCon

-- Pattern matching uses this to:
-- 1. Verify the scrutinee has type T a
-- 2. Extract the type arguments for instantiation
```

**Pattern Matching Usage** (Pat.hs, `tcConPat`):

```haskell
tcConPat penv con pat_ty arg_pats thing_inside
  = do { -- Get the TyCon from the DataCon
         let tycon = dataConTyCon con
         
         -- Unify pattern type with constructor result type
         -- pat_ty should be T ty_args
         ; unifyType pat_ty (mkTyConApp tycon univ_ty_args)
         
         -- Type-check arguments using constructor's field types
         ; tcConArgs con arg_pats ...
       }
```

**Key Points:**
- `dcRepTyCon` links `MkT` back to `T`
- The result type `dcOrigResTy` is `T a` (with appropriate type args)
- Pattern matching uses this to deconstruct values and extract fields

---

### Q11: Polymorphic Constructor Types

**Question:** For `data T a = MkT (a -> a)`, how is the polymorphic type of `MkT` stored? Is it `forall a. (a -> a) -> T a` in the `DataCon` representation?

**Answer:**

**Yes, exactly.** The type is stored in pieces in the `DataCon`:

```haskell
-- For: data T a = MkT (a -> a)
-- User view: MkT :: forall a. (a -> a) -> T a

MkData {
  dcUnivTyVars = [a],           -- Universal tyvars (from data decl)
  dcExTyCoVars = [],            -- No existentials
  dcUserTyVarBinders = [a],     -- As written by user
  
  dcEqSpec = [],                -- No GADT equalities
  dcOtherTheta = [],            -- No constraints
  
  dcOrigArgTys = [a -> a],      -- Argument types (scaled)
  dcOrigResTy = T a,            -- Result type
  
  dcRepTyCon = T,               -- Parent TyCon
  ...
}
```

**Reconstructing the Full Type:**

```haskell
dataConFullSig :: DataCon -> ([TyVar], [TyCoVar], [EqSpec], ThetaType, [Scaled Type], Type)
dataConFullSig dc
  = ( dcUnivTyVars dc
    , dcExTyCoVars dc
    , dcEqSpec dc
    , dcOtherTheta dc
    , dcOrigArgTys dc
    , dcOrigResTy dc )

-- Full signature: forall a. (a -> a) -> T a
```

**The dcUserTyVarBinders Field:**

For `data T a b where MkT :: forall b a. b -> a -> T a b`:
```haskell
dcUnivTyVars = [a, b]        -- Alphabetical (internal)
dcUserTyVarBinders = [b, a]  -- As written (user-specified order)
```

This allows preserving user-written order while having canonical internal representation.

---

### Q12: GADT Representation

**Question:** For `data T a where MkT :: Int -> T Bool`, how does the `DataCon` store the type coercion that `a ~ Bool`? How does this differ from a regular ADT constructor?

**Answer:**

**GADT Storage** (DataCon.hs):

```haskell
-- data T a where MkT :: Int -> T Bool

MkData {
  dcUnivTyVars = [a],           -- The tyvar from data decl head
  dcExTyCoVars = [],            -- No existentials (for this example)
  
  dcEqSpec = [a ~ Bool],        -- THE KEY: GADT equality
  -- Stores: a (from univ) ~ Bool (the actual result type arg)
  
  dcOtherTheta = [],            -- No other constraints
  dcOrigArgTys = [Int],         -- Arguments
  dcOrigResTy = T a,            -- Result (with univ tyvar)
  
  dcRepTyCon = T,
  dcVanilla = False,            -- NOT a vanilla constructor
  ...
}
```

**dcEqSpec Field** (lines 465-478):

```haskell
dcEqSpec :: [EqSpec]   -- Equalities derived from result type

-- Each EqSpec: (tyvar ~ type)
-- Invariant: tyvar is from dcUnivTyVars
-- Invariant: tyvar appears only in dcUnivTyVars (nowhere else in DataCon)
```

**Difference from Regular ADT:**

| Aspect | Regular ADT | GADT |
|--------|-------------|------|
| `dcEqSpec` | `[]` (empty) | `[a ~ Bool]` |
| `dcVanilla` | `True` | `False` |
| Univ tyvars | Match TyCon exactly | May differ from TyCon tyvars |
| Result type | Always `T a b...` | Can be `T Bool`, `T Int`, etc. |

**Pattern Matching with GADTs** (Pat.hs):

```haskell
-- case x of MkT n -> ...
-- x :: T a
-- Inside branch: a ~ Bool

tcConPat ... = do
  -- Generate equality constraint from dcEqSpec
  -- a ~ Bool becomes a coercion
  let gadt_co = mkEqSpecCoercion (dcEqSpec con) univ_tys
  
  -- Wrap pattern binder with coercion
  -- n :: Int (from dcOrigArgTys)
  -- But we might need evidence that a ~ Bool
```

**Key Difference:**
- Regular ADT: Pattern matching just extracts fields
- GADT: Pattern matching also generates equality constraints/coercions that refine types in the branch

---

## Pattern Matching Mechanism

### Q13: Pattern Type Checking

**Question:** When type-checking `case x of MkT y -> ...`, how does the type checker ensure `x` has type `T a` and `y` has type `a`? What role does `tcMatchPats` play in setting up the expected types for pattern variables?

**Answer:**

**tcMatchPats Function** (Pat.hs, lines 116-145):

```haskell
tcMatchPats :: forall a.
               HsMatchContext GhcTc   -- Context (case, function, etc.)
            -> [LPat GhcRn]           -- Patterns
            -> [Scaled ExpSigmaTypeFRR]  -- Expected types for patterns
            -> TcM a                  -- Thing inside (RHS)
            -> TcM ([LPat GhcTc], a)  -- Type-checked patterns + result
```

**The Process:**

```haskell
-- case x of MkT y -> rhs
-- Step 1: Infer type of scrutinee x
(scrut_expr, scrut_ty) <- tcInferRho x  -- scrut_ty = T alpha

-- Step 2: Lookup MkT DataCon
con <- tcLookupDataCon (mkDataCon "MkT")

-- Step 3: Get constructor signature
-- MkT :: forall a. a -> T a

-- Step 4: Unify scrut_ty with constructor result
-- T alpha ~ T a
-- => alpha ~ a

-- Step 5: Get field type
-- Field type: a (now unified with alpha)
-- So y :: alpha (which is the same as 'a')
```

**Expected Type Setup:**

```haskell
tcMatchPats ctxt pats exp_tys thing_inside
  = do { -- Each pattern gets its expected type
         tcMultiple tc_lpat exp_tys pats $
         thing_inside }
```

For constructor patterns:
- Pattern `MkT y` gets expected type `T a`
- Sub-pattern `y` gets expected type from `dcOrigArgTys`
- The unification of scrutinee type with constructor result determines type arguments

---

### Q14: GADT Refinement

**Question:** In `case x of { MkT y -> ... }` where `MkT :: Int -> T Bool`, how does the type checker learn that `x`'s type `T a` means `a ~ Bool` in the branch? How is this equality constraint propagated?

**Answer:**

**GADT Pattern Checking** (tcConPat in Pat.hs, lines 1127+):

```haskell
tcConPat penv (L loc qcon) pat_ty arg_pats thing_inside
  = do { -- Step 1: Lookup the constructor
         con <- tcLookupDataCon con_name
         
         -- Step 2: Instantiate constructor type
         -- con_ty :: forall a. Int -> T Bool
         -- Wait: MkT :: Int -> T Bool (no forall, specific Bool)
         -- So we have:
         --   dcUnivTyVars = [a]
         --   dcEqSpec = [a ~ Bool]
         --   dcOrigArgTys = [Int]
         
         -- Step 3: Unify pattern type with result
         -- pat_ty = T alpha (from scrutinee)
         -- con_res = T a
         -- => alpha ~ a
         
         -- Step 4: Process dcEqSpec
         -- a ~ Bool (from dcEqSpec)
         -- Combined with alpha ~ a, we get alpha ~ Bool
         
         -- Step 5: Add equality constraint to solver
         co <- unifyType (mkTyVarTy alpha) boolTy
         
         -- Step 6: Coerce pattern binders
         -- y :: Int (from dcOrigArgTys)
         -- Available evidence: alpha ~ Bool
       }
```

**Equality Propagation via Constraints:**

1. **Pattern Match Coercion**: The `CoPat` wrapper stores the coercion:
   ```haskell
   CoPat { co_cpt_wrap :: HsWrapper  -- Evidence that a ~ Bool
         , co_pat_inner :: Pat GhcTc  -- The actual pattern
         , co_pat_ty :: Type }        -- Type in inner pattern
   ```

2. **In the RHS**: The equality `a ~ Bool` is available to the constraint solver

3. **Type Refinement**: Any occurrence of `a` in the RHS is treated as `Bool`

**Example:**
```haskell
case x of
  MkT y -> (y, True :: a)
  -- y :: Int (from MkT's field)
  -- a ~ Bool, so (True :: a) is valid
```

---

### Q15: Constructor Lookup

**Question:** When seeing a pattern `MkT y`, how does the type checker resolve `MkT` to the correct `DataCon`? Does it look in `tcg_type_env` or a separate constructor environment?

**Answer:**

**Lookup via tcg_type_env** (Env.hs, `tcLookupDataCon`, lines 280-285):

```haskell
tcLookupDataCon :: Name -> TcM DataCon
tcLookupDataCon name = do
    thing <- tcLookupGlobal name  -- Uses tcg_type_env + imports
    case thing of
        AConLike (RealDataCon con) -> return con
        _ -> wrongThingErr WrongThingDataCon (AGlobal thing) name
```

**The Chain:**

1. **Pattern Analysis**: Pattern `MkT y` has `MkT` as a `Name`

2. **tcLookupGlobal**:
   - Check `tcg_type_env` for current module
   - If not found, check imports (home/external package tables)
   - May load interface file

3. **Result Pattern Matching**:
   ```haskell
   case thing of
     AConLike (RealDataCon con) -> ... -- Success: got DataCon
     AConLike (PatSynCon ps)    -> ... -- Pattern synonym (different path)
     ATyCon tc                  -> ... -- Wrong: type constructor used as value
     AnId id                    -> ... -- Wrong: value used as constructor
   ```

**No Separate Constructor Environment:**

Constructors are stored alongside other `TyThing`s in `tcg_type_env`. The distinction is made by pattern matching on the `TyThing` constructor (`AConLike` vs `ATyCon` vs `AnId`).

**Key Point:** After renaming, `MkT` is just a `Name`. Type checking resolves it to the appropriate entity kind (DataCon, TyCon, Id) via environment lookup.

---

### Q16: Pattern Wrapper Generation

**Question:** How does pattern matching generate `HsWrapper` evidence? Specifically, for a GADT pattern match, when is `WpCast` created and attached to the pattern-bound variables?

**Answer:**

**Wrapper Generation in tcPatBndr** (Pat.hs, lines 315-346):

```haskell
tcPatBndr penv bndr_name exp_pat_ty
  -- Case with signature
  | Just bndr_id <- sig_fn bndr_name
  = do { wrap <- tcSubTypePat_GenSigCtxt penv (scaledThing exp_pat_ty) (idType bndr_id)
       ; return (wrap, bndr_id) }
  
  -- Case without signature
  | otherwise
  = do { (co, bndr_ty) <- case scaledThing exp_pat_ty of
              Check pat_ty    -> promoteTcType bind_lvl pat_ty
              Infer infer_res -> ... inferResultToType ...
       
       ; bndr_id <- newLetBndr no_gen bndr_name bndr_mult bndr_ty
       ; return (mkWpCastN co, bndr_id)   -- WpCast created here!
       }
```

**GADT Pattern Wrapper** (tcConPat):

```haskell
tcConPat penv con scaled_exp_pat_ty arg_pats thing_inside
  = do { -- ... type checking ...
         
         -- Build coercion from GADT equalities
         let gadt_cos = ... -- from dcEqSpec
         
         -- Attach wrapper to pattern
         ; wrapped_pat <- mkHsWrapPat gadt_co inner_pat pat_ty
         
         -- For each field binder
         ; (wraps, field_ids) <- ...
         
         -- Return pattern with CoPat wrapper
       }
```

**CoPat Creation:**

```haskell
-- For: case x :: T a of MkT (y :: Int)
-- where MkT :: Int -> T Bool
-- We have: a ~ Bool

CoPat {
  co_cpt_wrap = WpCast (a ~ Bool),  -- The GADT equality coercion
  co_pat_inner = ConPat MkT [y],    -- The actual constructor pattern
  co_pat_ty = T Bool                -- Inner pattern type
}
```

**When WpCast is Created:**

1. **Type-level mismatch**: Expected type differs from actual type
2. **GADT match**: Pattern refines type variables (creates equality proof)
3. **View patterns**: View function changes type

The wrapper is used during desugaring to insert the appropriate cast.

---

### Q17: Exhaustiveness Checking

**Question:** How does GHC verify pattern exhaustiveness using the `tcg_complete_match_env` field of `TcGblEnv`? How does it track which patterns have been matched?

**Answer:**

**tcg_complete_match_env** (Types.hs, line 504):

```haskell
tcg_complete_match_env :: CompleteMatches,
-- ^ The complete matches for all /home-package/ modules;
-- Includes the complete matches in tcg_complete_matches
```

**COMPLETE Pragmas:**

Users can specify exhaustiveness information:
```haskell
{-# COMPLETE Just, Nothing #-}
-- Tells GHC that Just + Nothing covers all cases for Maybe
```

**Checking Exhaustiveness** (Pmc.hs - Pattern Match Compiler):

```haskell
-- After type checking patterns, check exhaustiveness
-- 1. Build pattern matrix from all clauses
-- 2. Use auxiliary functions to detect uncovered cases
-- 3. Report warnings for non-exhaustive patterns
```

**Tracking Matched Patterns:**

```haskell
-- For: 
-- f Nothing = 0
-- f (Just x) = x

-- Pattern matrix:
-- [Nothing]
-- [Just x]

-- Exhaustiveness check:
-- - Can any value fail to match? 
-- - With COMPLETE Just, Nothing: No
-- - Without pragma: Check if all constructors covered
```

**The Process:**

1. **Pattern Matrix Construction**: Each match clause adds a row
2. **Covered Set Tracking**: Which constructors are handled
3. **Incomplete Check**: If not all constructors covered → warning
4. **Redundancy Check**: If a clause is subsumed by previous ones → warning

**Integration:**

The `tcg_complete_match_env` accumulates `COMPLETE` pragmas from:
- Current module
- Imported modules
- Built-in instances (e.g., for tuples)

These inform the exhaustiveness checker about valid coverage sets.

---

### Q18: Pattern Desugaring Connection

**Question:** When the desugarer processes a pattern match, how does it use the `CoPat` wrapper that was generated during type checking? What's the relationship between `co_cpt_wrap` and the actual runtime coercion?

**Answer:**

**CoPat Definition** (Hs/Pat.hs):

```haskell
data XXPatGhcTc
  = CoPat
      { co_cpt_wrap :: HsWrapper    -- Type-checker evidence
      , co_pat_inner :: Pat GhcTc   -- Inner pattern
      , co_pat_ty :: Type           -- Type of inner pattern
      }
```

**Desugaring Process** (HsToCore/Match.hs):

```haskell
-- During match desugaring
dsPat :: Pat GhcTc -> DsM (CoreExpr -> CoreExpr, [Id])
-- Returns: (wrapper, binders)

dsPat (CoPat wrap inner_pat ty)
  = do { (inner_wrapper, binders) <- dsPat inner_pat
       
         -- dsHsWrapper translates HsWrapper to Core transformation
       ; return (dsHsWrapper wrap . inner_wrapper, binders) }
```

**dsHsWrapper** (HsToCore/Binds.hs):

```haskell
dsHsWrapper :: HsWrapper -> (CoreExpr -> CoreExpr) -> DsM a
dsHsWrapper wrap k = go wrap
  where
    go WpHole k = k (\e -> e)
    go (WpCast co) k = k (\e -> Cast e co)  -- Runtime coercion!
    go (WpCompose w1 w2) k = go w1 $ \f1 ->
                              go w2 $ \f2 ->
                              k (f1 . f2)
    ...
```

**The Relationship:**

| Type Checker | Desugarer | Runtime |
|--------------|-----------|---------|
| `HsWrapper` | `dsHsWrapper` | Core cast |
| `WpCast co` | `\e -> Cast e co` | Actual coercion instruction |
| `CoPat` | Wrapper applied to pattern binder | Value cast at runtime |

**Example:**

```haskell
-- Source:
case x :: T a of
  MkT y -> ...y...
  -- MkT :: Int -> T Bool
  -- In branch: a ~ Bool

-- After type checking:
CoPat (WpCast (a ~ Bool)) (ConPat MkT [y]) (T Bool)

-- After desugaring:
case x of
  MkT y -> let y' = y |> (a ~ Bool) in ...y'...
  -- The cast is applied to uses of y in the RHS
```

**Key Point:** `co_cpt_wrap` contains the coercion evidence. The desugarer converts this to actual Core `Cast` operations that are preserved through optimization and become runtime type coercions (or compile-time no-ops if the coercion is reflexive).

---

## Cross-Cutting Concerns

### Q19: Zonking

**Question:** How does `zonkTcGblEnv` ensure that all meta-variables in `tcg_type_env` are resolved before the module is handed to the desugarer? What happens to unfilled metavariables?

**Answer:**

**zonkTcGblEnv** (Module.hs, lines 653-665):

```haskell
zonkTcGblEnv :: TcGblEnv
             -> TcM (TypeEnv, Bag EvBind, LHsBinds GhcTc,
                       [LForeignDecl GhcTc], [LTcSpecPrag], [LRuleDecl GhcTc], [PatSyn])
zonkTcGblEnv tcg_env@(TcGblEnv { tcg_binds     = binds
                               , tcg_ev_binds  = ev_binds
                               , ... })
  = setGblEnv tcg_env $
    zonkTopDecls ev_binds binds rules imp_specs fords pat_syns
```

**Zonking Process** (Zonk/Env.hs and Zonk/TcType.hs):

```haskell
-- Zonking replaces TcTyVars (meta-variables) with their final types
zonkType :: Type -> TcM Type
zonkType ty = go ty
  where
    go (TyVarTy tv) = case tcTyVarDetails tv of
      MetaTv { mtv_ref = ref } -> do
        contents <- readTcRef ref
        case contents of
          Flexi -> return (TyVarTy tv)  -- Unfilled: keep as is
          Indirect ty' -> go ty'        -- Filled: follow indirection
      _ -> return (TyVarTy tv)
    ...
```

**What Happens to Unfilled Meta-Variables:**

1. **During Type Checking**: Meta-vars are "flexible" (can be unified)

2. **After Constraint Solving**: Most should be filled

3. **Final Zonk** (before desugaring):
   - **Filled meta-vars**: Replaced with their type
   - **Unfilled meta-vars**: 
     - If constrained: Report error (ambiguous type)
     - If truly unconstrained: Default to `()` or report error (depending on MonomorphismRestriction)

4. **TcLevel Check**: Meta-vars with level higher than current should never escape - if they do, it's a compiler bug

**zonkTopDecls**:

```haskell
zonkTopDecls ev_binds binds rules ...
  = do { -- Zonk type environment
         type_env' <- zonkTypeEnv (tcg_type_env tcg_env)
         
         -- Zonk bindings
         binds' <- zonkLHsBinds binds
         
         -- Zonk evidence bindings
         ev_binds' <- zonkEvBinds ev_binds
         
         ; return (type_env', ev_binds', binds', ...) }
```

**Result**: After zonking, `tcg_type_env` contains fully resolved types with no meta-variables.

---

### Q20: Interface File Generation

**Question:** When generating `.hi` files from `TcGblEnv`, how are the polymorphic types from `tcg_type_env` serialized? Are they fully zonked first?

**Answer:**

**Interface Generation** (GHC/Iface/Make.hs):

```haskell
-- From tcg_type_env, extract exported entities
-- Serialize as IfaceDecl

mkIfaceDecl :: TyThing -> IfaceDecl
mkIfaceDecl (AnId id)
  = IfaceId { ifName = idName id
            , ifType = toIfaceType (idType id)
            , ... }
```

**Serialization Process:**

```haskell
-- Step 1: After type checking, call mkIfaceTc
tcRnModule ... = do
  ...
  -- Type checking complete, tcg_env has zonked types
  ; tcg_env <- zonkTcGblEnv tcg_env
  
  -- Step 2: Generate interface
  ; iface <- mkIfaceTc hsc_env ... tcg_env
  
  -- Step 3: Write to .hi file
  ; writeIfaceFile iface
```

**Yes, Fully Zonked First:**

The sequence in `tcRnModule` (Module.hs):
1. Type check the module → `TcGblEnv` with potentially unfilled meta-vars
2. Call `zonkTcGblEnv` → All types fully resolved
3. Generate interface from zonked environment

**Type Serialization** (Iface/Type.hs):

```haskell
toIfaceType :: Type -> IfaceType
toIfaceType ty = case ty of
  TyVarTy tv      -> IfaceTyVar (toIfaceTyVar tv)
  AppTy t1 t2     -> IfaceAppTy (toIfaceType t1) (toIfaceType t2)
  FunTy _ w t1 t2 -> IfaceFunTy (toIfaceType t1) (toIfaceType t2)
  ForAllTy tv ty  -> IfaceForAllTy (toIfaceForAllBndr tv) (toIfaceType ty)
  TyConApp tc tys -> IfaceTyConApp (toIfaceTyCon tc) (map toIfaceType tys)
  ...
```

**Key Point:** Interface files contain fully zonked, resolved types. They never contain meta-variables. This ensures that importing modules see concrete, monomorphic or fully polymorphic types.

---

### Q21: Recursive Bindings

**Question:** For mutually recursive functions `f` and `g`, how does the type checker handle the forward references? Does it use a two-pass approach or knot-tying through `tcg_type_env_var`?

**Answer:**

**Knot-Tying Approach** (Tc/Types.hs, line 491):

```haskell
tcg_type_env_var :: KnotVars (IORef TypeEnv),
-- Used only to initialise the interface-file typechecker in initIfaceTcRn,
-- so that it can see stuff bound in this module when dealing with hi-boot recursions
```

**The Process** (Bind.hs, `tcValBinds`):

```haskell
-- For: f x = ...g...; g y = ...f...

-- Step 1: Create monomorphic Ids for all binders
-- These go in local env, NOT tcg_type_env yet
let rec_ids = [(f_name, f_mono_id), (g_name, g_mono_id)]

-- Step 2: Extend local env with recursive Ids
tcExtendRecIds rec_ids $ do
  -- Step 3: Type check RHSs
  -- Both f and g can see each other's monomorphic Ids
  f_rhs <- tcMonoExpr f_body ...
  g_rhs <- tcMonoExpr g_body ...
  ...
```

**Two-Phase Approach for Top-Level:**

1. **Phase 1: Inference**:
   - Create monomorphic Ids
   - Type check RHSs with these Ids in scope
   - Collect constraints

2. **Phase 2: Generalization** (if applicable):
   - Solve constraints
   - Generalize types
   - Create AbsBinds
   - Add to `tcg_type_env`

**For Type/Class Declarations** (More Complex):

```haskell
-- Uses tcg_type_env_var for true knot-tying
tcExtendRecEnv :: [(Name, TcTyThing)] -> TcM a -> TcM a
-- Temporarily add TyCons to local env during kind checking
-- Allows recursive references
```

**The Difference:**

- **Value bindings**: Monomorphic Ids in local env (tcExtendRecIds)
- **Type bindings**: Placeholder TyCons via tcg_type_env_var knot-tying

---

### Q22: Evidence Accumulation

**Question:** How do evidence bindings (dictionaries, coercions) accumulate in `tcg_ev_binds` during type checking of a function definition with type class constraints?

**Answer:**

**Evidence Accumulation Sites** (Types.hs):

```haskell
tcg_binds     :: TcRef (LHsBinds GhcTc),     -- Value bindings
tcg_ev_binds  :: TcRef (LHsBinds GhcTc),     -- Evidence bindings (separate!)
tcg_sigs      :: TcRef [LSig GhcTc],         -- Type signatures
```

**The Process** (Tc/Gen/Bind.hs):

```haskell
-- For: f x = x + 1
-- Constraint: Num a (from (+))

tcPolyInfer ... = do
  -- Step 1: Type check RHS, collecting constraints
  (tclvl, wanted, (binds', mono_infos))
         <- pushLevelAndCaptureConstraints  $
            tcMonoBinds ...
  -- 'wanted' contains: Num alpha (where alpha is x's type)
  
  -- Step 2: Solve constraints
  ((qtvs, givens, ev_binds, insoluble), residual)
      <- captureConstraints $
         simplifyInfer top_lvl tclvl infer_mode sigs name_taus wanted
  
  -- Step 3: ev_binds contains dictionary bindings
  -- ev_binds :: TcEvBinds with dictionary construction
  -- e.g., $dNum :: Num Int = $fNumInt
```

**Evidence Binding Structure** (Types/Evidence.hs):

```haskell
data TcEvBinds
  = TcEvBinds { ev_binds_var :: TcRef [EvBind] }

data EvBind
  = EvBind { eb_lhs :: EvVar    -- Dictionary variable
           , eb_rhs :: EvTerm    -- How to construct it
           , ... }

data EvTerm
  = EvExpr EvExpr
  | EvTypeable Type TypeableEvidence
  
type EvExpr = CoreExpr  -- But built during type checking
```

**How They Accumulate:**

1. **Constraint Solving** (Solver/Solve.hs):
   ```haskell
   -- When solver finds a solution:
   -- Num Int => use $fNumInt
   -- Emit evidence binding: $dNum = $fNumInt
   ```

2. **Evidence Collection**:
   ```haskell
   -- During tcMonoBinds, evidence accumulates in ambient constraints
   -- After solve, evidence bindings extracted
   ```

3. **Storage**:
   ```haskell
   -- AbsBinds contains the evidence bindings
   abs_bind = AbsBinds { abs_ev_binds = [ev_binds], ... }
   
   -- Later added to tcg_ev_binds
   tcg_env { tcg_ev_binds = ... }
   ```

**Example:**

```haskell
f x = x + 1  -- f :: Num a => a -> a

-- After type checking:
AbsBinds {
  abs_tvs = [a],
  abs_ev_vars = [$dNum :: Num a],  -- Abstract over dictionary
  abs_ev_binds = [let $dNum = ... in ...],  -- Evidence bindings
  abs_exports = [ABE { abe_poly = f, abe_mono = f_mono }],
  abs_binds = [f_mono x = (+) $dNum x 1]  -- Monomorphic version
}
```

**Key Point:** Evidence bindings are collected during constraint solving, stored in `AbsBinds`, and eventually added to `tcg_ev_binds` (though in practice, they're often part of the main bindings structure for top-level definitions).

---

## Source File Summary

All answers derived from analysis of:

| Concept | File | Key Functions/Types |
|---------|------|---------------------|
| Environment lookup | GHC/Tc/Utils/Env.hs | tcLookup, tcLookupGlobal, tcLookupId |
| Binding type checking | GHC/Tc/Gen/Bind.hs | tcPolyInfer, tcTopBinds, tcValBinds |
| Pattern matching | GHC/Tc/Gen/Pat.hs | tcConPat, tcPatBndr, tcMatchPats |
| Data constructors | GHC/Core/DataCon.hs | DataCon, mkDataCon |
| Type checker types | GHC/Tc/Types/BasicTypes.hs | TcTyThing, IdBindingInfo |
| Type environment | GHC/Tc/Types.hs | TcGblEnv, tcg_type_env |
| Module orchestration | GHC/Tc/Module.hs | tcRnModule, zonkTcGblEnv |
| Interface generation | GHC/Iface/Make.hs | mkIfaceTc |

---

*Document Status: All questions answered based on GHC source code analysis (March 2026)*
