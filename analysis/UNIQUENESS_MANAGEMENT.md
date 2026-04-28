# Uniqueness Management in GHC

## Overview

GHC uses a **global uniqueness system** to ensure that every identifier (variables, names, type variables) across all compiler phases has a distinct identity. This is fundamental to:

- **Alpha equivalence**: Distinguishing `x` in different scopes
- **Shadowing**: Proper handling of nested bindings
- **Inlining**: Safe substitution of variables
- **Desugaring**: Creating fresh variables without collisions

---

## The Core Mechanism: Global Atomic Counter

### The genSym Function

**Location**: `GHC/Types/Unique/Supply.hs:263-278`

```haskell
genSym :: IO Word64
genSym = do
    let !mask = (1 `unsafeShiftL` uNIQUE_BITS) - 1
    let !(Ptr counter) = ghc_unique_counter64
    I# inc# <- peek ghc_unique_inc
    let !inc = wordToWord64# (int2Word# inc#)
    u <- IO $ \s1 -> case fetchAddWord64Addr# counter inc s1 of
            (# s2, val #) ->
                let !u = W64# (val `plusWord64#` inc) .&. mask
                in (# s2, u #)
    return u
```

This is a **thread-safe atomic increment** operation:
- Single global counter shared by ALL compiler phases
- Atomic `fetchAddWord64Addr#` ensures no race conditions
- Every `Unique` gets a distinct number

### Global State

**Location**: `GHC/Types/Unique/Supply.hs:280-281`

```haskell
foreign import ccall unsafe "&ghc_unique_counter64" ghc_unique_counter64 :: Ptr Word64
foreign import ccall unsafe "&ghc_unique_inc"       ghc_unique_inc       :: Ptr Int
```

These C-level global variables hold:
- `ghc_unique_counter64`: The actual counter
- `ghc_unique_inc`: Increment value (usually 1)

---

## The Unique Data Type

### Representation

**Location**: `GHC/Types/Unique.hs:130`

```haskell
newtype Unique = MkUnique Word64
```

A `Unique` is just a 64-bit word combining:
- **Tag** (8 bits): Identifies the source/compiler phase
- **Number** (56 bits): The actual unique value from `genSym`

### Uniquable Typeclass

**Location**: `GHC/Types/Unique.hs:405-408`

```haskell
class Uniquable a where
    getUnique :: a -> Unique

x `hasKey` k = getUnique x == k
```

All named entities implement this:
- `Name` → `nameUnique :: Unique`
- `Var` → `realUnique :: Unique`
- `Id` → inherits from `Var`

---

## Tags: Cosmetic but Useful

Tags help identify where a unique was created:

| Tag | Phase | Description |
|-----|-------|-------------|
| `'t'` | TcM | Type checker |
| `'r'` | RnM | Renamer |
| `'d'` | DsM | Desugarer |
| `'s'` | SimplM | Simplifier |
| `'g'` | DsM | Pattern matcher |
| `'x'` | Various | Internal/system names |

**Location**: `GHC/Types/Unique.hs:132-179`

```haskell
data UniqueTag
  = AlphaTyVarTag
  | BcoTag
  | BlockIdTag
  | BoxedTupleDataTag
  | TcTag          -- ^ Type checker
  | DsTag          -- ^ Desugarer
  | SkolemTag      -- ^ Skolem variables
  | ...
```

### Important Note

From `Note [How unique supplies are used]`:
> *Different parts of the compiler will use a UniqSupply or MonadUnique instance with a specific tag. This way the different parts of the compiler will generate uniques with different tags.*

**The tag is cosmetic** - distinct numbers come from the global counter.

---

## MonadUnique: The Universal Interface

### Typeclass Definition

**Location**: `GHC/Types/Unique/Supply.hs:366-379`

```haskell
class Monad m => MonadUnique m where
    getUniqueSupplyM :: m UniqSupply
    getUniqueM  :: m Unique
    getUniquesM :: m [Unique]
    
    -- Default implementations
    getUniqueM  = liftM uniqFromSupply  getUniqueSupplyM
    getUniquesM = liftM uniqsFromSupply getUniqueSupplyM
```

### Implementations Across GHC

#### Type Checker (TcM)

**Location**: `GHC/Tc/Utils/Monad.hs:816-859`

```haskell
newUnique :: TcRnIf gbl lcl Unique
newUnique = do { env <- getEnv
               ; let tag = env_ut env  -- 't' for TcM
               ; liftIO $! uniqFromTagGrimly tag }

instance MonadUnique (IOEnv (Env gbl lcl)) where
    getUniqueM = newUnique
    getUniqueSupplyM = newUniqueSupply
```

#### Desugarer (DsM)

**Location**: `GHC/HsToCore/Types.hs:127`

```haskell
type DsM = TcRnIf DsGblEnv DsLclEnv
```

DsM reuses the same infrastructure as TcM, just with different environment types.

#### UniqSM (Pure Code)

**Location**: `GHC/Types/Unique/Supply.hs:381-388`

```haskell
instance MonadUnique UniqSM where
    getUniqueSupplyM = getUs
    getUniqueM = getUniqueUs
    getUniquesM = getUniquesUs
```

Used in pure code that threads a `UniqSupply` explicitly.

---

## The UniqSupply Tree

### Lazy Infinite Tree Structure

**Location**: `GHC/Types/Unique/Supply.hs:200-202`

```haskell
data UniqSupply
  = MkSplitUniqSupply {-# UNPACK #-} !Word64
                   UniqSupply UniqSupply
```

A binary tree where each node:
- Contains a unique value
- Has two lazy subtrees

### Operations

```haskell
takeUniqFromSupply :: UniqSupply -> (Unique, UniqSupply)
-- Returns current unique + one subtree

splitUniqSupply :: UniqSupply -> (UniqSupply, UniqSupply)
-- Returns both subtrees
```

### Lazy Creation

**Location**: `GHC/Types/Unique/Supply.hs:232-239`

```haskell
mk_supply s0 =
   case noDuplicate# s0 of { s1 ->
   case unIO genSym s1 of { (# s2, u #) ->
   case unIO (unsafeDupableInterleaveIO (IO mk_supply)) s2 of { (# s3, x #) ->
   case unIO (unsafeDupableInterleaveIO (IO mk_supply)) s3 of { (# s4, y #) ->
   (# s4, MkSplitUniqSupply (tag .|. u) x y #)
   }}}}
```

Subtrees are created lazily using `unsafeDupableInterleaveIO`.

---

## Creating Variables: Examples

### In Type Checker

**Location**: `GHC/Tc/Utils/Monad.hs:838-855`

```haskell
newNameAt :: OccName -> SrcSpan -> TcM Name
newNameAt occ span = do
  { uniq <- newUnique
  ; return (mkInternalName uniq occ span) }

newSysLocalId :: FastString -> Mult -> TcType -> TcRnIf gbl lcl TcId
newSysLocalId fs w ty = do
  { u <- newUnique
  ; return (mkSysLocal fs u w ty) }
```

### In Desugarer

**Location**: `GHC/HsToCore/Monad.hs:440-453`

```haskell
newUniqueId :: Id -> Mult -> Type -> DsM Id
newUniqueId id = mkSysLocalOrCoVarM (occNameFS (nameOccName (idName id)))

duplicateLocalDs :: Id -> DsM Id
duplicateLocalDs old_local = do
  { uniq <- newUnique
  ; return (setIdUnique old_local uniq) }
```

### Key Pattern

```haskell
-- Always the same pattern:
do { uniq <- newUnique   -- Get fresh unique from global counter
   ; return (mk... uniq ...) }
```

---

## Use Case: AABS2 Variable Creation

### The Scenario

In `matchCoercion` (AABS2 desugaring):

**Location**: `GHC/HsToCore/Match.hs:277-285`

```haskell
matchCoercion (var :| vars) ty eqns@(eqn1 :| _)
  = do  { let XPat (CoPat co pat _) = firstPat eqn1
        ; let pat_ty' = hsPatType pat
        ; var' <- newUniqueId var (idMult var) pat_ty'   -- NEW unique!
        ; ... }
```

### Why Different Uniques Matter

```haskell
-- Type checker creates:
id_x :: Id          -- unique = u1 (from TcM)

-- Desugarer creates:
var' :: Id          -- unique = u2 (from DsM)

-- They are distinct because both use the global counter
-- u1 ≠ u2 guaranteed by atomic increment
```

### The Connection

```haskell
-- In Core:
let var' = f var in ...

-- Two distinct variables:
-- var : σₐ (incoming parameter, from pattern match)
-- var' : σₓ (coerced value, fresh unique)
```

---

## Why Global Uniqueness Matters

### 1. Cross-Phase Safety

Variables created in different phases never collide:
- Type checker variable `x_123`
- Desugarer variable `x_456`
- Both valid, distinct

### 2. Simplifier Inlining

When the simplifier substitutes:
```haskell
let x = e in ...x...
```

It knows `x` is unique - no risk of capturing other variables named `x`.

### 3. Hash Maps and Sets

**Location**: `GHC/Types/Unique/FM.hs`

```haskell
unitUFM k v = UFM (M.singleton (getKey $ getUnique k) v)
```

Uses `Unique` as key for O(1) lookup.

### 4. Debuggability

Tags make it easy to trace where a variable came from:
```
x_123_t   -- Created by type checker (tag 't')
x_456_d   -- Created by desugarer (tag 'd')
```

---

## Summary

| Aspect | Implementation |
|--------|---------------|
| **Source** | Single global atomic counter (`genSym`) |
| **Storage** | `newtype Unique = MkUnique Word64` |
| **Interface** | `MonadUnique` typeclass |
| **Phases** | TcM, RnM, DsM all share same counter |
| **Tags** | Cosmetic (8 bits), identify source |
| **Numbers** | Global (56 bits), guarantee distinctness |
| **Trees** | `UniqSupply` for pure code |

The key insight: **All compiler phases share one atomic counter**, ensuring global uniqueness while using tags for debugging. This enables safe variable creation across type checking, renaming, desugaring, and optimization phases.

---

## Key Source References

| Concept | File | Line | Purpose |
|---------|------|------|---------|
| `genSym` | `GHC/Types/Unique/Supply.hs` | 263-278 | Global atomic counter |
| `Unique` type | `GHC/Types/Unique.hs` | 130 | 64-bit unique representation |
| `MonadUnique` | `GHC/Types/Unique/Supply.hs` | 366-379 | Universal interface |
| `newUnique` | `GHC/Tc/Utils/Monad.hs` | 816-820 | TcM implementation |
| `UniqSupply` | `GHC/Types/Unique/Supply.hs` | 200-202 | Lazy tree structure |
| `newUniqueId` | `GHC/HsToCore/Monad.hs` | 440-441 | DsM variable creation |
| `Uniquable` | `GHC/Types/Unique.hs` | 405-408 | Typeclass for named entities |

---

**Related Documents**:
- `DESUGARING_PATTERNS.md` - How fresh variables are used in desugaring
- `HSWRAPPER_ARCHITECTURE.md` - Wrapper and evidence handling
- `TYPE_INFERENCE.md` - Type checking and variable creation
