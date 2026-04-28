# Implicit Instantiation

**How bidirectional checking and unification work together to eliminate explicit types.**

---

## The Problem

System F (polymorphic lambda calculus) requires **explicit type applications**:

```haskell
-- System F Core
id :: forall a. a -> a
id @Int 3               -- MUST write @Int
```

But programmers want to write:

```haskell
-- Surface Language
id :: forall a. a -> a
id 3                    -- Implicit! Compiler figures it out
```

**The challenge**: The compiler must infer `@Int` from context.

## The Solution: Extended Bidirectional Checking

The elaborator extends bidirectional type checking with **unification** to support implicit instantiation.

```
Surface:   id 3
           ↓
      Extended Bidirectional + Unification
           ↓
Core:      (id[Int] 3)          -- TApp inserted
```

## How It Works (Step by Step)

### Example: `id 3`

**Given**:
- `id :: forall a. a -> a` (polymorphic)
- `3 :: Int` (monomorphic)

**Step 1: Infer function type**

```python
# infer(id, ctx) 
func_type = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
```

**Step 2: Handle polymorphism (Instantiation)**

```python
# Function has forall type - need to instantiate
match func_type:
    case TypeForall(var, body):
        # Replace 'a' with fresh meta-variable
        meta = TMeta.fresh("a")           # _a
        instantiated = subst(body, var, meta)  # _a -> _a
```

**Step 3: Match against argument**

```python
# Function type is now _a -> _a
# Need to check 3 against _a
check(3, _a, ctx)

# 3 has type Int, so unification happens:
unify(_a, Int)  # Adds _a → Int to substitution
```

**Step 4: Apply substitution**

```python
# Apply current substitution everywhere
func_type = subst.apply(_a -> _a)  # Becomes Int -> Int
```

**Step 5: Generate Core**

```python
# Insert explicit type application
Core.App(
    func=Core.TApp(Core.Global("id"), TypeConstructor("Int")),
    arg=Core.Lit("Int", 3)
)
```

**Result type**: `Int`

## The Interleaving Pattern

Notice the **alternation** between bidirectional checking and unification:

```python
def infer_app(func, arg):
    # 1. BIDIRECTIONAL: Infer function type
    func_type = infer(func, ctx)
    
    # 2. UNIFICATION: Apply substitutions
    func_type = subst.apply(func_type)
    
    # 3. IMPLICIT INSTANTIATION: Handle polymorphism
    if isinstance(func_type, TypeForall):
        func_type = instantiate(func_type)  # Replace forall with TMeta
        func_type = subst.apply(func_type)
    
    match func_type:
        case TypeArrow(param_type, ret_type):
            # 4. BIDIRECTIONAL: Check argument against expected type
            core_arg = check(arg, param_type, ctx)
            
            # 5. UNIFICATION: Apply new substitutions
            ret_type = subst.apply(ret_type)
            
            return core.App(core_func, core_arg), ret_type
```

**Pattern**: `infer → apply_subst → instantiate → check → apply_subst`

This interleaving happens at **every function application** in the AST.

## Why This Works

### Bidirectional Alone Doesn't Work

Pure bidirectional checking (no unification):

```haskell
id :: forall a. a -> a
id 3

-- infer(id) = forall a. a -> a  (cannot use directly!)
-- Can't check 3 against 'forall a. a -> a' - not an arrow
```

### Unification Alone Doesn't Work

Pure unification (Algorithm W style):

```haskell
id 3

-- Create meta-variable: _t
-- id :: forall a. a -> a becomes _t -> _t
-- 3 :: Int
-- Unify: _t = Int
-- Works, but doesn't handle all cases well
```

### Combined They Work

Extended bidirectional with unification:

```haskell
id 3

-- Bidirectional: infer function type
-- Instantiation: forall a. a -> a → _a -> _a
-- Bidirectional: check arg against _a
-- Unification: _a = Int (from 3 :: Int)
-- Result: Core code with explicit type
```

## Visual: The Full Transformation

```
Surface Code:
    id :: forall a. a -> a
    id 3

Phase 1: Elaboration with Interleaving
    ┌──────────────────────────────────────┐
    │  infer(id)                           │
    │    → TypeForall("a", a → a)          │
    │                                      │
    │  instantiate                         │
    │    → _a → _a                         │
    │                                      │
    │  check(3, _a)                        │
    │    → infer(3) = Int                  │
    │    → unify(_a, Int)                  │
    │    → subst = { _a → Int }            │
    │                                      │
    │  apply_subst                         │
    │    → Int → Int                       │
    └──────────────────────────────────────┘

Phase 2: Core Generation
    App(
      func = TApp(Global("id"), Int),
      arg  = Lit(3)
    )
```

## Meta-Variables: The Bridge

**TMeta** (existential variables) enable the interleaving:

```haskell
-- Surface: forall a. a -> a
-- After instantiation: _a -> _a     (TMeta)
-- After unification: Int -> Int
-- In Core: explicit TApp
```

**Key point**: TMeta exists **only during elaboration**, not in Core.

## Limitations

### Works For (Rank-1)

```haskell
id :: forall a. a -> a
id 3                    -- ✓ Infers Int
id "hello"              -- ✓ Infers String

pair :: forall a b. a -> b -> Pair a b
pair 3 True             -- ✓ Infers Pair Int Bool
```

### Requires Annotations (Higher-Rank)

```haskell
-- Rank-2 type
applyToInt :: (forall a. a -> a) -> Int -> Int

-- This needs annotation
foo = applyToInt id 5   -- ✗ Can't infer

-- With annotation
foo :: Int
foo = applyToInt id 5   -- ✓ Works
```

**Why?** The function parameter has polymorphic type. Bidirectional checking needs the expected type to flow down.

## Relationship to Core Checker

The **Surface Elaborator** extends bidirectional checking:
- Has `infer` and `check` modes
- Adds unification with TMeta
- Handles implicit instantiation
- Generates Core with explicit types

The **Core Checker** is pure bidirectional:
- Has `infer` and `check` modes
- No unification (no TMeta)
- No implicit instantiation
- All types already explicit

```
Surface Elaborator          Core Checker
─────────────────           ────────────
infer + check               infer + check
+ unification               (no unification)
+ TMeta                     (no TMeta)
+ instantiation             (already explicit)
↓                           
Generates Core ──────────────→ Validates Core
```

## Summary

**Implicit instantiation** is achieved by:

1. **Bidirectional checking** - guides type information flow
2. **Meta-variables (TMeta)** - represent unknown types
3. **Unification** - solve constraints between types
4. **Instantiation** - replace `forall` with meta-variables
5. **Interleaving** - alternate between modes during traversal

The result: Surface code with implicit types → Core code with explicit types.

## References

- **[Bidirectional Checking](./bidirectional-checking.md)** - The foundation
- **[Unification](./unification.md)** - Solving type constraints
- **[Type System](./type-system.md)** - Surface vs Core distinction
