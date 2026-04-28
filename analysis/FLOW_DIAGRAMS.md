# GHC Type Inference - Flow Diagrams

This document contains visual diagrams for GHC's type inference system.

**Related Documents**:
- `TYPE_INFERENCE.md` - Complete type inference system documentation
- `HSWRAPPER_ARCHITECTURE.md` - Evidence recording and Core translation

## 1. Overall Type Checking Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Haskell Source Code                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Parser (GHC/Parser/)                                        │
│  - Converts text to HsExpr (Haskell syntax tree)             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Renamer (GHC/Rename/)                                       │
│  - Resolves names and scopes                                 │
│  - Outputs: RenamedExpr (with Name references)               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Type Checker (GHC/Tc/) ◄──── THIS IS WHERE THE MAGIC IS    │
│  - Implements bidirectional type inference                   │
│  - Uses ExpType: Check | Infer                               │
│  - Outputs: TcExpr (with type information)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Desugarer (GHC/HsToCore/)                                   │
│  - Converts to Core (simpler intermediate language)          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
     ┌───────────────────┴───────────────────┐
     │                                       │
     ▼                                       ▼
┌──────────────────┐          ┌──────────────────────┐
│ STG Conversion   │          │ Core Optimizer       │
│ (to STG)         │          │ (optimizations)      │
└─────────┬────────┘          └──────────┬───────────┘
          │                              │
          └──────────────┬───────────────┘
                         │
                         ▼
        ┌────────────────┴─────────────────┐
        │                                  │
        ▼                                  ▼
   ┌─────────┐                      ┌──────────┐
   │ Backend │                      │ Backend  │
   │ Native  │                      │ LLVM     │
   │ Code    │                      │ Code     │
   └────┬────┘                      └──────┬───┘
        └───────────────┬────────────────┘
                        │
                        ▼
                   ┌──────────────┐
                   │  Executable  │
                   └──────────────┘
```

## 2. Bidirectional Type Inference Core

```
                    ┌──────────────────────┐
                    │   tcExpr entry       │
                    │ (HsExpr, ExpRhoType) │
                    └──────┬───────────────┘
                           │
                    ┌──────▼───────┐
                    │  ExpRhoType? │
                    └──┬───────┬───┘
                       │       │
        ┌──────────────┘       └──────────────┐
        │                                     │
        ▼                                     ▼
    ┌─────────────┐               ┌──────────────────┐
    │  Check ty   │               │  Infer inf_res   │
    │             │               │                  │
    │ CHECKING    │               │ INFERENCE MODE   │
    │ MODE        │               │                  │
    └──────┬──────┘               └────────┬─────────┘
           │                               │
           │ Unify against                 │ Fill hole
           │ expected type                 │ in IORef
           │                               │
           ▼                               ▼
    ┌─────────────┐               ┌──────────────────┐
    │ Generate    │               │ Infer type and   │
    │ constraints │               │ store in IORef   │
    │             │               │                  │
    │ Check that  │               │ Create meta var  │
    │ expr matches│               │ if still empty   │
    │ expected ty │               │                  │
    └──────┬──────┘               └────────┬─────────┘
           │                               │
           └───────────────┬───────────────┘
                           │
                    ┌──────▼──────────┐
                    │ Return TcExpr   │
                    │ with types      │
                    └─────────────────┘
```

## 3. ExpType Data Structure

```
┌────────────────────────────────────────────────────────────┐
│                       ExpType                              │
│  Represents "expected type" - can be in 2 modes:           │
└────────────┬────────────────────────────┬─────────────────┘
             │                            │
      ┌──────▼──────┐            ┌───────▼───────────┐
      │ Check TcType│            │ Infer InferResult │
      │             │            │                   │
      │ Immediate   │            │ Lazy evaluation   │
      │ type info   │            │ via IORef hole    │
      └─────────────┘            └─────────┬─────────┘
                                          │
                            ┌─────────────▼──────────────┐
                            │   InferResult (IR)         │
                            │                            │
                            │  ir_uniq :: Unique         │
                            │    ↳ For debugging         │
                            │                            │
                            │  ir_lvl :: TcLevel         │
                            │    ↳ Scope tracking        │
                            │                            │
                            │  ir_frr :: InferFRRFlag    │
                            │    ↳ Runtime rep check     │
                            │                            │
                            │  ir_inst :: InferInstFlag  │
                            │    ↳ Instantiation mode:   │
                            │       - IIF_Sigma          │
                            │       - IIF_ShallowRho     │
                            │       - IIF_DeepRho        │
                            │                            │
                            │  ir_ref :: IORef           │
                            │    ↳ THE HOLE!             │
                            │    ↳ Starts: Nothing       │
                            │    ↳ Filled: Just TcType   │
                            └────────────────────────────┘
```

## 4. Inference Hole Creation and Filling

```
┌──────────────────────────────────────────────────────────┐
│ Step 1: Create Inference Hole                            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  newInferExpType :: InferInstFlag -> TcM ExpType         │
│                                                          │
│    ┌─────────────────────────────────────────────────┐  │
│    │ 1. Generate unique ID (for debugging)           │  │
│    │ 2. Get current TcLevel                          │  │
│    │ 3. Create IORef Nothing                         │  │
│    │ 4. Create InferResult with all metadata         │  │
│    │ 5. Wrap in Infer constructor                    │  │
│    │ 6. Return ExpType                               │  │
│    └─────────────────────────────────────────────────┘  │
│                                                          │
│  Result: ExpType { Infer IR { ir_ref = ref } }         │
│                            where ref = IORef Nothing    │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│ Step 2: Type Check Expression with Hole                 │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  tcExpr :: HsExpr -> ExpType -> TcM (HsExpr)            │
│                                                          │
│    When encountering HsVar name:                        │
│    ┌─────────────────────────────────────────────────┐  │
│    │ 1. Look up type of name                         │  │
│    │ 2. Call unifyExpType                            │  │
│    │    - If Check ty: unify(ty, typeOf name)        │  │
│    │    - If Infer ir: fillInferResult               │  │
│    │ 3. fillInferResult writes to IORef              │  │
│    │    ├─ Read: IORef Nothing                       │  │
│    │    ├─ Write: IORef (Just typeOfName)            │  │
│    │    └─ Also applies instantiation                │  │
│    └─────────────────────────────────────────────────┘  │
│                                                          │
│  Result: IORef now contains Just (SomeType)            │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│ Step 3: Extract Inferred Type                           │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  inferResultToType :: InferResult -> TcM TcType         │
│                                                          │
│    ┌─────────────────────────────────────────────────┐  │
│    │ 1. Read IORef                                   │  │
│    │    ├─ If Just ty: return ty                     │  │
│    │    └─ If Nothing: create meta var               │  │
│    │ 2. Apply instantiation based on ir_inst         │  │
│    │    ├─ IIF_Sigma: return as-is                   │  │
│    │    ├─ IIF_ShallowRho: top-level instantiate     │  │
│    │    └─ IIF_DeepRho: deep instantiate             │  │
│    │ 3. Return final type                            │  │
│    └─────────────────────────────────────────────────┘  │
│                                                          │
│  Result: Final TcType with all types filled in         │
└──────────────────────────────────────────────────────────┘
```

## 5. Expression Type Checking Flow

```
                  tcExpr expr expType
                        │
                        ▼
           ┌────────────────────────────┐
           │   Dispatch on HsExpr       │
           └────┬──────────────────────┬┘
      Special   │                      │ General
      cases     │                      │ cases
      ─────────┼──────────────────────┼─────────
                │                      │
    ┌───────────┼──────────┬───────────┼────────────┐
    │           │          │           │            │
    ▼           ▼          ▼           ▼            ▼
  HsVar      HsApp    HsLam       HsOverLit    HsLet
    │           │          │           │            │
    │           │          │           │            │
    ├─→ tcVar   ├─→ tcApp  ├─→ tcLam   ├─→ tryShort ├─→ tcLet
    │           │  (Quick  │  (Check   │ Cut or     │
    │           │   Look!) │   poly    │ tcApp      │
    │           │          │   sigma)  │            │
    │           │          │           │            │
    └────┬──────┴──────┬───┴───────────┴────────────┘
         │             │
         ├─ Unify or   ├─ Generate
         │  Fill hole  │  constraints
         │             │
         └─────┬───────┘
               │
               ▼
         Return TcExpr
         (fully typed)
```

## 6. Quick Look Optimization in Application Checking

```
         tcApp (func_expr arg_expr...) expectedType
              │
              ▼
    ┌───────────────────────────────────────┐
    │  Phase 1: Analyze Application Head    │
    │  splitHsApps extracts:                │
    │  - Head expression                    │
    │  - List of arguments                  │
    └────┬────────────────────────────────┘
         │
         ▼
    ┌──────────────────────────────────────────┐
    │  Phase 2: Quick Look on Head             │
    │  tcInferAppHead_maybe with expectedType  │
    │  ✓ Uses expected type to guide:          │
    │    - Type variable instantiation         │
    │    - Overload resolution                 │
    │    - Impredicative instantiation         │
    └────┬───────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────────────────┐
    │  Phase 3: Check Arguments in Order          │
    │  For each (arg, arg_type) pair:             │
    │  ├─ Infer argument type                      │
    │  ├─ Unify with expected arg_type            │
    │  └─ Generate any needed constraints         │
    └────┬──────────────────────────────────────┘
         │
         ▼
    ┌────────────────────────────────────────┐
    │  Phase 4: Solve Constraints            │
    │  ├─ Apply constraint solver            │
    │  ├─ Resolve type class instances       │
    │  └─ Unify remaining variables          │
    └────┬───────────────────────────────────┘
         │
         ▼
    Return result with full type information
```

## 7. Checking vs Inference Mode Decision Tree

```
                      Start tcExpr
                            │
                            ▼
                    Is ExpRhoType in:
                    ┌─────────────┐
                    │   Check ty  │ → CHECKING MODE
                    │      or     │
                    │ Infer holes │ → INFERENCE MODE
                    └─────────────┘
                            │
            ┌───────────────┴──────────────┐
            │                              │
            ▼                              ▼
        CHECKING MODE                 INFERENCE MODE
        ──────────────                 ──────────────
        "I have an expected           "What's the type?"
         type, verify against it"
            │                              │
            ▼                              ▼
        unifyExpType                   fillInferResult
        (ty1 ~ ty2)                    (store in IORef)
            │                              │
            ├─ Generate constraints       ├─ No constraints
            ├─ May fail if mismatch       │  from the hole itself
            └─ Can't infer new types      └─ Type comes from expr
                                           structure
            │                              │
            ▼                              ▼
        Constraints passed          Hole filled with
        to solver                   inferred type
            │                              │
            ├─→ Solve & verify           ├─→ Instantiate if needed
            │   type matches             │   (based on InferInstFlag)
            └─→ Success or error         └─→ Return inferred type
```

## 8. Instantiation Modes: IIF_* Flags

```
InferInstFlag determines what gets returned from inference

┌─────────────────────────────────────────────────────────────┐
│ IIF_Sigma: Don't instantiate, preserve all foralls          │
├─────────────────────────────────────────────────────────────┤
│ Used for: Pattern type inference                            │
│                                                             │
│ Example:                                                    │
│   Expression: \x -> x                                      │
│   Result: forall a. a -> a  (preserves polymorphism)       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ IIF_ShallowRho: Top-level instantiation only                │
├─────────────────────────────────────────────────────────────┤
│ Used for: Expression type inference                         │
│                                                             │
│ Example:                                                    │
│   Expression: id                  (where id :: forall a...)│
│   Result: a -> a (top-level forall removed)                │
│           but nested foralls preserved                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ IIF_DeepRho: Deep instantiation (DeepSubsumption dependent) │
├─────────────────────────────────────────────────────────────┤
│ Used for: Expression type inference with flags              │
│                                                             │
│ Example (with DeepSubsumption ON):                         │
│   Expression: id                                            │
│   Result: a -> a (even nested foralls instantiated)         │
│                                                             │
│ Example (with DeepSubsumption OFF):                        │
│   Result: Same as IIF_ShallowRho                           │
└─────────────────────────────────────────────────────────────┘

        Choice affects:
        ├─ Polymorphism preservation
        ├─ Type inference quality
        ├─ Impredicative polymorphism support
        └─ Error messages
```

## 9. TcLevel Tracking for Scope

```
                     Module level (TcLevel 0)
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
    (TcLevel 1)        (TcLevel 1)         (TcLevel 1)
    Type decl           Function decl       Instance
        │                   │                   │
        └───────────┬───────┘───────┬──────────┘
                    │               │
                    │         ┌─────▼──────┐
                    │         │Lambda body │
                    │         │(TcLevel 2) │
                    │         └─────┬──────┘
                    │               │
                    │         ┌─────▼──────────┐
                    │         │Pattern match   │
                    │         │(TcLevel 3)     │
                    │         └────────────────┘

Why TcLevel matters:
├─ Variable created at TcLevel N can't escape to Level N-1
├─ Prevents untouchable variable violations
├─ Critical for GADT pattern matching
└─ Ensures type safety

Example (GADT):
    data T where
      MkT :: (forall a. a -> a) -> (x -> x) -> T
    
    f x = case x of
      MkT c w -> ???
      
    TcLevel for 'w':
    ├─ Created inside case at TcLevel > module level
    ├─ Type variable 'x' at that level
    └─ Can't use 'x' outside the case!
```

## 10. Complete Expression Type-Checking Example

```
Input: f = (\x -> x + 1) :: (Int -> Int)

Step 1: Create Inference Setup
├─ Create ExpType: Check (Int -> Int)
└─ Pass to tcExpr

Step 2: Match on Expression
├─ Recognize HsLam
└─ Call tcLam with expected type (Int -> Int)

Step 3: Lambda Type Checking
├─ Skolemise the expected type
│  ├─ Input: Int -> Int
│  └─ Output: [Int], Int (param types and return type)
├─ Type check pattern: x has type Int
├─ Type check body with expected type: Int
└─ Return lambda with full type

Step 4: Type Check Body (x + 1)
├─ Recognize HsOpApp (+)
├─ Go through tcApp (Quick Look!)
├─ Infer type of (+)
├─ Type check arguments:
│  ├─ x : Int (from pattern)
│  └─ 1 : Int (infer/check)
├─ Unify with expected type Int
└─ Return (+) x 1 : Int

Step 5: Final Result
├─ Expression type: Int -> Int
├─ Matches expected type
└─ Success! ✓
```

## 11. Error Path Example

```
Input: f = (\x -> "hello") :: (Int -> Bool)

Step 1: Expected Type
├─ Create ExpType: Check (Int -> Bool)
└─ Pass to tcExpr

Step 2: Lambda Analysis
├─ Expected: Int -> Bool
├─ Parameter x has type Int
├─ Body should have type Bool
└─ Proceed to type check body

Step 3: Type Check Body ("hello")
├─ Recognize HsOverLit
├─ Type is String (or [Char])
└─ Try to unify with expected Bool

Step 4: Unification Fails
├─ unifyExpType Check Bool String
├─ Types don't match!
├─ Generate error constraint
└─ Record: String doesn't match Bool

Step 5: Constraint Solving
├─ Solver tries to resolve constraint
├─ No way to make String ~ Bool
├─ Constraint remains unsolved

Step 6: Error Report
├─ Type error: Expected Bool, got String
├─ Point to the string literal
└─ Show expected type from annotation
```

## 12. Deep Subsumption with CheckExpType

```
With DeepSubsumption enabled:

When we have:  Check rho_type

The rho_type is DEEPLY SKOLEMISED:

Example:
  Expected type: (forall a. a -> a) -> Int
  
  Deeply skolemised:
  (forall a. a -> a) → remains forall
  But any nested constraints are skolemised
  
This enables:
├─ Impredicative polymorphism
├─ Higher-rank type handling
└─ Proper nested forall treatment

Without Deep Subsumption:
├─ Only top-level foralls skolemised
├─ Less flexible type inference
└─ Some higher-rank patterns won't work
```
