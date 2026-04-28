# Core Language and System F - The Intermediate Representation

## Overview

After bidirectional type inference completes in the type-checking phase (Tc/), GHC's next step is to desugar the typed Haskell syntax into **Core**, which is GHC's intermediate representation language. Core is based on **System FC** (System F with type equality coercions), an extension of the classical **System F** lambda calculus.

This document explains:
1. What Core is and how it relates to System F
2. The 1-1 translation rules from Haskell source to Core
3. How the type information from bidirectional type inference is used
4. The Core data structures and their System F semantics

## Core as System FC

### Definition

From `GHC/Core.hs`:

```
This is the data type that represents GHC's core intermediate language. Currently
GHC uses System FC (https://www.microsoft.com/en-us/research/publication/system-f-with-type-equality-coercions/)
for this purpose, which is closely related to the simpler and better known System F
(http://en.wikipedia.org/wiki/System_F).
```

### Why System F?

System F is ideal for an intermediate representation because it:
- Has clean semantics for polymorphic types
- Can represent explicit type abstractions and applications
- Supports higher-rank types
- Has simple, mechanical compilation to machine code
- Is well-studied and understood

### System FC Extension

System FC extends System F by adding:
- **Type equality coercions** - For GADTs and type families
- **Representational roles** - Distinguishing between nominal and representational equality
- **Coercion terms** - First-class type equalities in expressions

## The Compilation Pipeline: Source → Core

### 1. Source Code (HsExpr)
```
f x = x + 1
```
Haskell syntax with full syntactic sugar.

### 2. Renamed (RdrName → Name)
```
f_1 x_2 = x_2 + 1
```
Names are disambiguated with Uniques.

### 3. Type Checked (TcExpr)
```
f_1 x_2 = (x_2 :: Int) + (1 :: Int)
```
- Type information is attached
- Type class constraints resolved
- Overloaded operations resolved to specific implementations
- Result: fully typed Haskell expression

### 4. Desugared (CoreExpr)
```
f_1 = \(x_2 :: Int) -> ((+) @Int $fNumInt x_2 1)
```
- Syntactic sugar removed
- Dictionary arguments made explicit
- Type abstractions and applications explicit
- Result: System FC expression

## Core Data Structure

From `GHC/Core.hs`, Core expressions are represented by the `Expr` type:

```haskell
data Expr b
  = Var   Id                      -- Variable occurrence
  | Lit   Literal                 -- Primitive literal
  | App   (Expr b) (Arg b)        -- Application (including type application)
  | Lam   b (Expr b)              -- Lambda abstraction
  | Let   (Bind b) (Expr b)       -- Let binding
  | Case  (Expr b) b Type [Alt b] -- Case expression
  | Cast  (Expr b) CoercionR      -- Cast with type coercion
  | Tick  CoreTickish (Expr b)    -- Profiling/debugging annotation
  | Type  Type                    -- Type (can appear as argument)
  | Coercion Coercion             -- Coercion (can appear as argument)
```

### System F Interpretation

| Core Constructor | System F Equivalent | Purpose |
|------------------|-------------------|---------|
| `Var x` | Variable reference | Variable occurrence |
| `Lam x e` | λx. e | Value or type abstraction |
| `App e₁ e₂` | e₁ e₂ | Application (value or type) |
| `Type ty` | τ (when in argument position) | Type argument |
| `Coercion co` | c (coercion proof) | Coercion argument |
| `Let b e` | let b in e | Local binding |
| `Case e x ty alts` | case e of ... | Pattern matching |
| `Cast e co` | e ▶ c | Type cast |

### Key Distinction: Explicit Type Application

In Haskell source:
```haskell
id x         -- Type is inferred
```

In Core:
```haskell
id @Int x    -- Type is explicit
```

This is the **key insight**: bidirectional type inference determines what `@Int` should be, and the desugarer makes it explicit in Core.

## Translation from Type-Checked Haskell to Core

The desugarer transforms `HsExpr GhcTc` to `CoreExpr`. This is conceptually a systematic translation, though the actual implementation handles many special cases. The type information from the type checker guides this translation.

**Important Timing Note**: `HsWrapper` values (type applications, dictionary arguments, coercions) are **created by the type checker** during unification/subsumption checking. The desugarer translates already-created wrappers into Core transformations - it does NOT create new wrappers.

### Rule 1: Variable References
```
Typed Haskell:  x
Core:           Var x

The variable's type from type checking is preserved in x's type information.
```

### Rule 2: Type-Annotated Expressions
```
Typed Haskell:  (e :: ty)
Core:           e    (type information already in e)

The type annotation doesn't need to appear in Core;
type checking has already verified it.
```

### Rule 3: Function Application
```
Typed Haskell:  f a b c
Core:           App (App (App (Var f) (Var a)) (Var b)) (Var c)

Multiple arguments are curried into nested Apps.
```

### Rule 4: Polymorphic Function Application
```
Typed Haskell:  id x                    -- where id :: forall a. a -> a
                -- With HsWrapper: WpTyApp Int
Core:           App (App (Var id) (Type Int)) (Var x)

Type arguments become explicit Type expressions.
The wrapper WpTyApp Int is created by the type checker
and translated to Core by the desugarer.
```

### Rule 5: Lambda Abstraction
```
Typed Haskell:  \x -> x + 1
Core:           Lam x (App (App (Var (+)) (Var x)) (Var 1))

Parameters are preserved; body is desugared recursively.
Type information on x is preserved.
```

### Rule 6: Explicit Type Abstractions
```
Typed Haskell:  \x -> x                 -- inferred as forall a. a -> a
Core:           Lam a (Lam x (Var x))   -- where a is a type variable

When the inferred type is polymorphic, we create explicit type lambdas.
```

### Rule 7: Type Classes (Dictionary Passing)
```
Typed Haskell:  x + y                   -- where x, y :: Int (Num Int needed)
                -- With wrappers from type checker:
                -- WpTyApp Int (type application)
                -- WpEvApp $fNumInt (dictionary)
Core:           App (App (App (Var (+)) (Type Int)) (Var $fNumInt)) (Var x) (Var y)

- Type checker creates wrappers for:
  - Type application: WpTyApp Int
  - Dictionary evidence: WpEvApp $fNumInt
- Desugarer translates wrappers to Core applications
- This is the **dictionary passing** translation
```

### Rule 8: Let Bindings
```
Typed Haskell:  let f x = x + 1 in f 5
Core:           Let (NonRec f (Lam x (App ...))) (App (Var f) (Lit 5))

Local definitions become Let bindings in Core.
Type information on f is preserved.
```

### Rule 9: Case Expressions
```
Typed Haskell:  case x of
                  Just y -> y
                  Nothing -> 0
Core:           Case (Var x) x (Type Int)
                  [Alt (DataAlt Just) [y] (Var y),
                   Alt DEFAULT [] (Lit 0)]

Pattern matching becomes case expressions.
The type of all alternatives must match (Int in this case).
```

### Rule 10: Cast (for GADTs and Newtypes)
```
Typed Haskell:  x                       -- where x :: Age, but Age ~# Int (GADT)
                -- With wrapper: WpCast co
Core:           Cast (Var x) co

- Type checker creates wrapper WpCast co
- Desugarer translates to Core Cast
- The coercion proves the type equality
```

## How HsWrapper Is Translated to Core

The type checker attaches `HsWrapper` values to expressions via `XExpr (WrapExpr wrapper expr)`. The desugarer translates these wrappers to Core transformations:

```haskell
-- From GHC.HsToCore.Binds
dsHsWrapper :: HsWrapper -> ((CoreExpr -> CoreExpr) -> DsM a) -> DsM a
dsHsWrapper WpHole              k = k $ \e -> e
dsHsWrapper (WpTyApp ty)        k = k $ \e -> App e (Type ty)
dsHsWrapper (WpEvApp tm)        k = do { core_tm <- dsEvTerm tm
                                       ; k $ \e -> e `App` core_tm }
dsHsWrapper (WpCast co)         k = k $ \e -> mkCastDs e co
dsHsWrapper (WpCompose w1 w2)   k = dsHsWrapper w1 $ \f1 ->
                                    dsHsWrapper w2 $ \f2 ->
                                    k (f1 . f2)
-- ... etc
```

**Key Point**: The wrapper is created by the type checker during type inference (when type information is available to compute coercions and evidence). The desugarer simply translates these already-created wrappers to Core.

## Desugaring Phase

The desugaring from typed Haskell to Core happens in `GHC/HsToCore/`:

### Main Entry Points

```haskell
-- Desugar expressions
dsExpr :: HsExpr GhcTc -> DsM CoreExpr

-- Desugar bindings
dsHsBinds :: LHsBinds GhcTc -> DsM (Bag CoreBind)

-- Desugar patterns
desugarPattern :: LPat GhcTc -> DsM (PatEnv, CoreExpr)
```

### What Happens During Desugaring

1. **Wrapper Translation** - HsWrapper values created by type checker are translated to Core:
   - `WpTyApp ty` → `App expr (Type ty)`
   - `WpEvApp dict` → `App expr dict`
   - `WpCast co` → `Cast expr co`
   
2. **Pattern Match Compilation** - Patterns are translated to case expressions

3. **Syntactic Sugar Removal** - List comprehensions, do-notation, etc. → Core equivalents

4. **Default Handling** - Default method uses, implicit parameters, etc.

5. **Lambda Lifting** - Top-level definitions extracted from nested scopes

### Example Desugaring

**Input (Typed Haskell)**:
```haskell
map f xs = case xs of
             [] -> []
             (y:ys) -> f y : map f ys
```

**Output (Core)**:
```
map = /\a b. \(f :: a -> b) (xs :: [a]) ->
  case xs of
    [] -> Nil @b
    (:) y ys -> Cons @b (f y) (map @a @b f ys)
```

Where:
- `/\a b.` = type abstractions (for `forall a b`)
- `\(f :: ...)` = value lambda
- `@b` = explicit type applications
- `Nil @b`, `Cons @b` = fully applied data constructors

## Connection to Bidirectional Type Inference

### How Type Information Flows

```
┌──────────────────────────────────────────────────────┐
│ Haskell Source Code                                  │
│ f x = x + 1                                          │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ Parser → HsExpr GhcPs                                │
│ (syntactic structure, RdrName, no type info)         │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ Renamer → HsExpr GhcRn                               │
│ (resolved Name, still no type info)                  │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ Type Checker (Tc/) - BIDIRECTIONAL INFERENCE         │
│                                                      │
│ tcExpr determines:                                   │
│ - f : Int → Int (inferred or checked)               │
│ - x : Int (inferred from f's type)                  │
│ - (+) : Int → Int → Int (resolved from Num Int)     │
│ - Dictionary $fNumInt : Num Int (evidence)          │
│                                                      │
│ ATTACHES to AST via:                                 │
│ - Id types (variable occurrences)                   │
│ - HsWrapper values (type apps, dicts, coercions)    │
│   Stored as: XExpr (WrapExpr wrapper expr)          │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ Desugarer (HsToCore/) - WRAPPER TRANSLATION          │
│                                                      │
│ Translates HsWrapper to Core:                       │
│ 1. WpTyApp ty → App expr (Type ty)                  │
│ 2. WpEvApp dict → App expr dict                     │
│ 3. WpCast co → Cast expr co                         │
│ 4. Compile patterns to case expressions             │
│ 5. Remove syntactic sugar                           │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ Core (System FC)                                     │
│ Lam f (Lam x (App (App (App (+) (Type Int))          │
│              ($fNumInt)) f) x) 1)                    │
└──────────────────────────────────────────────────────┘
```

### The Critical Connection

**Type Inference** → **Type Information** → **Desugaring** → **Core**

Specifically:
1. Bidirectional type inference produces a typed Haskell AST (`HsExpr GhcTc`)
2. This typing information is used to drive desugaring decisions
3. The desugarer translates to Core using 1-1 rules
4. Type information becomes explicit in Core (type applications, dictionary arguments)

## Key Differences: Source vs Core

### Implicit vs Explicit

| Aspect | Haskell Source | Core |
|--------|----------------|------|
| Type applications | Implicit (inferred) | Explicit (@Type) |
| Type class evidence | Implicit (resolved) | Explicit (dictionary args) |
| Type abstractions | Implicit (in signatures) | Explicit (/\a.) |
| Overloading resolution | Implicit (via class dispatch) | Explicit (specific functions) |

### Example: Overloaded Addition

**Haskell**:
```haskell
add :: Num a => a -> a -> a
add x y = x + y

use = add 3 5  -- type: Int
```

**Core**:
```
add = /\a. \($dNum :: Num a). \(x :: a). \(y :: a).
  (+) @a $dNum x y

use = add @Int $fNumInt 3 5
```

In Core, we see:
- Type abstraction `/\a.` for polymorphism
- Dictionary parameter `$dNum` for the constraint
- Explicit type application `@Int`
- Explicit dictionary application `$fNumInt`

## System FC Features

### 1. Coercions

Core expressions can include coercions (proofs of type equality):

```haskell
Cast (Var x) (co :: ty1 ~# ty2)
```

This is essential for:
- **GADTs** - Refining types in pattern matches
- **Type families** - Relating different types
- **Newtypes** - Distinguishing representation from abstract type

### 2. Roles

Coercions have roles that distinguish:
- **Nominal** - Can only be reflexivity (no coercion)
- **Representational** - Can use representational equality
- **Phantom** - Any coercion allowed (unused in the type)

Example:
```haskell
type Age = Int  -- newtype, representational role

x :: Age
-- Can cast to Int via representational coercion
Cast (Var x) (coerce :: Age ~R# Int)
```

### 3. Coercion Abstraction

Functions can be polymorphic in coercions:

```haskell
coerce :: forall a b. (a ~# b) => a -> b
coerce = /\a b. \(c :: a ~# b). \(x :: a). x |> sym c
```

Where `|>` is the cast operator.

## Summary: From Typing to Core

1. **Bidirectional Type Inference** (Tc/)
   - Determines types of all expressions
   - Resolves type classes and overloading
   - Produces fully-typed Haskell AST

2. **1-1 Translation Rules** (HsToCore/)
   - Systematic rules for each Haskell construct
   - Type information drives desugaring decisions
   - Syntactic sugar removed

3. **Core (System FC)**
   - Explicit representation of all types
   - Dictionary passing for type classes
   - Coercions for type equalities
   - Ready for optimization and code generation

The key insight: **Bidirectional type inference determines what should be explicit in Core.**

## Files to Explore

- `GHC/Core.hs` - Core language definition and System FC documentation
- `GHC/HsToCore/HsToCore.hs` - Main desugaring entry point
- `GHC/HsToCore/Expr.hs` - Expression desugaring (1-1 rules)
- `GHC/HsToCore/Binds.hs` - Binding desugaring
- `GHC/HsToCore/Match.hs` - Pattern match compilation
- `GHC/Core/Type.hs` - Type representation in Core
- `GHC/Core/Coercion.hs` - Coercion representation and manipulation

## Currying and Multi-Argument Functions

### The Core Representation

Core uses **single-arity lambdas**, even for multi-argument Haskell functions. The conversion from multi-binder Haskell syntax to curried Core happens in the desugarer.

#### Conversion Mechanics

**Source Haskell** (multi-binder):
```haskell
\x y z -> e          -- MatchGroup with 3 patterns in [LPat]
f x y z = e          -- FunBind with MatchGroup having 3 patterns
```

**Desugarer** (`GHC/Core/Make.hs:2199-2201`):
```haskell
mkLams :: [b] -> Expr b -> Expr b
mkLams binders body = foldr Lam body binders
```

**Resulting Core** (curried):
```haskell
Lam x (Lam y (Lam z e))  -- Nested single-arg lambdas
```

### Why Currying in Core?

**1. Simpler Semantics**
- Single constructor `Lam b (Expr b)` handles all abstractions
- No need for n-ary lambda constructor
- Uniform representation throughout compiler

**2. Natural Partial Application Support**
```haskell
-- Source: \x y z -> e
-- Partial: (\x y z -> e) 1  -- creates closure \y -> \z -> e
```

In Core, partial application is just applying fewer arguments than the nested lambda structure requires.

**3. Optimizer Can Reconstruct Multi-Arg Behavior**

While Core is curried, the **optimizer reconstructs multi-argument efficiency** through:

#### Worker/Wrapper Transformation
```haskell
-- Original (curried):
f = \x -> \y -> x + y

-- After worker/wrapper (GHC.Core.Opt.WorkWrap/Utils.hs:77-108):
-- Wrapper: Creates closures
f = \x -> let g = \y -> x + y in g
-- Worker: Gets unboxed arguments (if strict)
$f = \x# y# -> I# (x# +# y#)
```

#### Eta-Expansion/Eta-Reduction
```haskell
-- Before: \x -> f x  -- eta-reducible
-- After:  f          -- reduced
```

Computed by `exprArity` (GHC.Core.Opt.Arity.hs:1706):
```haskell
exprArity e = go e
  where
    go (Lam x e) | isId x = go e + 1      -- each lambda adds 1
    go (App f a) | exprIsTrivial a = (go f - 1) `max` 0
```

### The Full Pipeline

```
Source:      \x y z -> e        (MatchGroup [p1,p2,p3])
                ↓
Desugar:     foldr Lam          (GHC.Core.Make.mkLams)
                ↓
Core:        Lam x (Lam y (Lam z e))
                ↓
Simplify:    Eta reduction, float lets
                ↓
WorkWrap:    Strictness analysis → unbox strict args
                ↓
STG:         Closure conversion (GHC.Stg.Make.isPAP)
                ↓
Runtime:     Calling convention uses registers for args
```

### Partial Applications → Closures

In STG (the intermediate before Cmm), partial applications become **PAPs** (Partial Application closures):

```haskell
-- STG Level (GHC.Stg/Make.hs:127):
isPAP env (StgApp f args) = idArity f > length args
                             -- When arity > args, create PAP closure
```

### Multi-Arg at Runtime

Despite curried Core, the **backend compiles to efficient multi-argument functions**:

1. **Calling conventions** pass multiple args in registers
2. **Strictness analysis** unboxes arguments for workers
3. **Worker/wrapper** splits curried wrapper from multi-arg worker

### Trade-offs Validated

| Aspect | Multi-binder (HsExpr) | Curried (Core) |
|--------|----------------------|----------------|
| **Representation** | MatchGroup with [LPat] | Nested Lam |
| **Partial application** | Requires transformation | Natural |
| **Typechecking** | matchExpectedFunTys handles arity | Works with curried types |
| **Optimization** | - | Worker/wrapper reconstructs multi-arg |
| **Runtime** | - | Multi-arg calling conventions |

**Key files:**
- `GHC/Core/Make.hs:2199` - mkLams (currying function)
- `GHC/Core/Opt/WorkWrap/Utils.hs:77` - Worker/wrapper generation
- `GHC/Core/Opt/Arity.hs:1706` - exprArity computation
- `GHC/Stg/Make.hs:127` - PAP detection
- `GHC/Core/Opt/DmdAnal.hs` - Strictness analysis for unboxing

## References

- System FC Paper: "System F with Type Equality Coercions" (Sulzmann et al.)
- GHC Core Formalism: See notes in `GHC/Core/Lint.hs`
- Bidirectional Type Checking Papers: "Complete and Easy Bidirectional Typechecking for Higher-Rank Polymorphism" (Dunfield & Krishnaswami)