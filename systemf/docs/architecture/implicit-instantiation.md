# Implicit Type Instantiation in System F

## The Core Problem

**System F** (Girard-Reynolds polymorphic lambda calculus) requires **explicit type application**:

```haskell
-- System F Core
id = Λa. λx:a. x        -- type abstraction
id @Int 3               -- type application (MUST write @Int)
```

But **practical languages** (Haskell, OCaml, Idris) let you write:

```haskell
-- Surface Language
id :: forall a. a -> a  -- polymorphic type
id 3                    -- implicit instantiation
-- Compiler inserts: id @Int 3
```

## The Relationship

Surface Language (with implicit types) compiles to System F Core (explicit):

```
Surface:   id 3
           ↓ elaboration/inference
Core:      id @Int 3
```

**Key insight**: The elaborator adds the explicit type applications that System F requires.

## How It Works

### Step 1: Type Inference (HM-Style)

When you write `id 3`:

1. Look up `id` type: `forall a. a -> a`
2. Infer argument type: `3 : Int`
3. **Unification**: `a ~ Int`
4. **Instantiation**: Replace `a` with `Int`
5. Result: `id @Int 3 : Int`

### Step 2: Insert Explicit Applications

```python
# In elaborator
match term:
    case SurfaceApp(func, arg):
        func_type = infer(func)
        
        match func_type:
            case TypeForall(var, body_type):
                # Implicit instantiation!
                arg_type = infer(arg)
                # Create fresh meta or use arg_type
                instantiated = subst(var, arg_type, body_type)
                return elaborate_application(instantiated, arg)
```

## Approaches

### 1. HM-Style (Rank-1 Only)

**Works for**: `forall a. a -> a`

```haskell
id 3        -- OK, infers Int
id "hello"  -- OK, infers String
```

**Doesn't work for**: Higher-rank types

```haskell
foo f = f 42  -- f : (forall a. a -> a) -> ???
              -- Can't infer f's type without annotation
```

### 2. Bidirectional with Propagation

Use expected type from context:

```haskell
(id :: Int -> Int) 3   -- Expected type flows down
```

### 3. Dummy Type Variables (Existential)

Insert fresh variables, solve later:

```haskell
id 3  --→  id @__t1 3
       --  __t1 gets solved to Int
```

## What We Should Do

For **System F surface language**:

1. **Support implicit instantiation for rank-1** (HM-style)
   - Most common case
   - Complete inference
   - Good error messages

2. **Require explicit for higher-rank**
   - `foo (\x -> x)` needs annotation
   - Or: `foo @(forall a. a -> a) (\x -> x)`

3. **Bidirectional checking helps**
   - When expected type is known, use it
   - `(id : Int -> Int) 3` works without unification

## Implementation Sketch

```python
def elaborate_app(func, arg, ctx):
    func_core, func_type = infer(func, ctx)
    
    # Handle implicit instantiation
    match func_type:
        case TypeForall(var, body_type):
            # Try to infer from argument
            arg_type = try_infer_type(arg, ctx)
            if arg_type:
                # Instantiate with inferred type
                instantiated = subst(var, arg_type, body_type)
                arg_core = check(arg, arg_type, ctx)
                
                # Insert explicit type application in core
                return TApp(func_core, arg_type), instantiated
            else:
                # Can't infer - create fresh meta-variable
                meta = fresh_meta()
                instantiated = subst(var, meta, body_type)
                # Let unification solve it later
                arg_core = check(arg, meta, ctx)
                return TApp(func_core, meta), instantiated
```

## Summary

- **System F Core**: Explicit type application (`@Int`)
- **Surface Language**: Implicit (`id 3`)
- **Elaboration**: Adds explicit applications
- **Method**: HM-style unification for rank-1
- **Result**: Best of both worlds - convenient surface, rigorous core

**Key Paper**: "Local Type Inference" (Pierce & Turner, 1998) - how to do implicit instantiation while keeping System F as the core.
