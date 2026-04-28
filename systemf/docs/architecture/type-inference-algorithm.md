# System F Type Inference Algorithm

**Status**: Implemented with Known Limitations  
**Date**: 2026-03-02  
**File**: `systemf/surface/inference/elaborator.py`

---

## Overview

The System F elaborator implements **bidirectional type inference** with Robinson-style unification. It transforms Scoped AST (with de Bruijn indices) into typed Core AST.

### Bidirectional Type Checking

```
infer(term, ctx)  → (core_term, type)     # Synthesize type from term
check(term, type, ctx) → core_term       # Verify term matches type
```

**Key Insight**: Type inference is directed by the structure of terms and available type annotations.

---

## Core Algorithm

### 1. Type Synthesis (infer)

**Purpose**: Given a term, synthesize its type.

**Cases**:

#### Literals
```python
case SurfaceIntLit(_, _):
    return (core.IntLit(...), TypeConstructor("Int", []))

case SurfaceStringLit(_, _):
    return (core.StringLit(...), TypeConstructor("String", []))
```

#### Variables
```python
case ScopedVar(index, debug_name, location):
    var_type = ctx.lookup_term(index)  # Get type from context
    return (core.Var(location, index, debug_name), var_type)
```

#### Lambda Abstraction
```python
case ScopedAbs(var_name, var_type_annotation, body, location):
    if var_type_annotation is not None:
        var_type = surface_to_core(var_type_annotation)
    else:
        var_type = TMeta.fresh(var_name)  # Fresh meta-variable
    
    # Extend context and infer body
    new_ctx = ctx.extend_term(var_type)
    core_body, body_type = infer(body, new_ctx)
    
    # Apply substitution to resolve meta-variables
    var_type = subst.apply(var_type)
    body_type = subst.apply(body_type)  # CRITICAL FIX
    
    return (core.Abs(...), TypeArrow(var_type, body_type))
```

**Key Point**: Must apply substitution to `body_type` to resolve any unified meta-variables.

#### Application
```python
case SurfaceApp(func, arg, location):
    core_func, func_type = infer(func, ctx)
    func_type = subst.apply(func_type)
    
    match func_type:
        case TypeArrow(param_type, ret_type):
            core_arg = check(arg, param_type, ctx)
            ret_type = subst.apply(ret_type)  # CRITICAL FIX
            return (core.App(...), ret_type)
        
        case TMeta(meta_var):
            # Unknown function type - create fresh arrow
            param_type = TMeta.fresh("param")
            ret_type = TMeta.fresh("ret")
            unify(meta_var, TypeArrow(param_type, ret_type))
            
            core_arg = check(arg, param_type, ctx)
            return (core.App(...), ret_type)
```

### 2. Type Checking (check)

**Purpose**: Verify that a term has a specific type.

**Strategy**:
1. For annotated terms, check against annotation
2. For other terms, infer and unify

```python
def check(term, expected_type, ctx):
    match term:
        case SurfaceAnn(term_inner, type_ann, _):
            # Use annotation
            ann_type = surface_to_core(type_ann, ctx)
            core_term = check(term_inner, ann_type, ctx)
            return core_term  # Type already verified
        
        case _:
            # Infer and unify
            core_term, inferred_type = infer(term, ctx)
            inferred_type = subst.apply(inferred_type)
            expected_type = subst.apply(expected_type)
            
            try:
                unify(expected_type, inferred_type)
            except UnificationError as e:
                # Convert to TypeMismatchError
                raise TypeMismatchError(
                    expected=expected_type,
                    actual=inferred_type,
                    ...
                ) from e
            
            return core_term
```

---

## Unification (Robinson-style)

**File**: `systemf/surface/inference/unification.py`

### Algorithm

```python
def unify(t1, t2, subst):
    t1 = subst.apply(t1)
    t2 = subst.apply(t2)
    
    match (t1, t2):
        case (TMeta(id1), TMeta(id2)) if id1 == id2:
            return subst  # Same meta-variable
        
        case (TMeta(meta), other):
            if occurs_check(meta, other):
                raise InfiniteTypeError(...)
            return subst.extend(meta, other)
        
        case (other, TMeta(meta)):
            if occurs_check(meta, other):
                raise InfiniteTypeError(...)
            return subst.extend(meta, other)
        
        case (TypeVar(n1), TypeVar(n2)) if n1 == n2:
            return subst
        
        case (TypeArrow(a1, r1), TypeArrow(a2, r2)):
            subst = unify(a1, a2, subst)
            subst = unify(r1, r2, subst)
            return subst
        
        case (TypeConstructor(n1, a1), TypeConstructor(n2, a2)):
            if n1 != n2 or len(a1) != len(a2):
                raise UnificationError(...)
            for arg1, arg2 in zip(a1, a2):
                subst = unify(arg1, arg2, subst)
            return subst
        
        case _:
            raise UnificationError(...)
```

### Occurs Check

Prevents infinite types (e.g., `a = a -> b`):

```python
def occurs_check(meta, ty, subst):
    ty = subst.apply(ty)
    
    match ty:
        case TMeta(id) if id == meta.id:
            return True  # Found itself!
        case TypeArrow(arg, ret, _):
            return occurs_check(meta, arg) or occurs_check(meta, ret)
        case TypeConstructor(_, args):
            return any(occurs_check(meta, arg) for arg in args)
        case _:
            return False
```

---

## Extensions

### 1. Data Constructors

**Challenge**: Constructors have polymorphic types with free type variables.

**Example**:
```haskell
Pair : a -> b -> Pair a b
```

**Solution**: Instantiate free type variables with fresh meta-variables.

```python
def instantiate_free_vars(ty):
    """Replace TypeVars with fresh TMetas."""
    match ty:
        case TypeVar(name):
            return TMeta.fresh(name)
        case TypeArrow(arg, ret, doc):
            return TypeArrow(
                instantiate_free_vars(arg),
                instantiate_free_vars(ret),
                doc
            )
        case TypeConstructor(name, args):
            return TypeConstructor(
                name,
                [instantiate_free_vars(arg) for arg in args]
            )
        case _:
            return ty

# In constructor elaboration:
con_type = ctx.lookup_constructor("Pair")
# con_type = TypeArrow(TypeVar("a"), TypeArrow(TypeVar("b"), TypeConstructor("Pair", [TypeVar("a"), TypeVar("b")])))
con_type = instantiate_free_vars(con_type)
# con_type = TypeArrow(TMeta(1), TypeArrow(TMeta(2), TypeConstructor("Pair", [TMeta(1), TMeta(2)])))
```

### 2. Pattern Matching

**Challenge**: Pattern variables need types that match constructor fields.

**Example**:
```haskell
case pair of
  Pair a b -> a  -- a and b should have the types from Pair
```

**Algorithm**:
```python
def check_branch(branch, scrut_type, ctx):
    # Get constructor type
    constr_type = ctx.lookup_constructor(branch.pattern.constructor)
    constr_type = instantiate_free_vars(constr_type)
    
    # Extend context with pattern variable types
    branch_ctx = ctx
    for var_name in branch.pattern.vars:
        match constr_type:
            case TypeArrow(param_type, ret_type):
                branch_ctx = branch_ctx.extend_term(param_type)
                constr_type = ret_type
    
    # Infer body type
    core_body, body_type = infer(branch.body, branch_ctx)
    
    return (core.Branch(...), body_type)
```

### 3. Nominal Recursion

**Challenge**: Recursive data types need special handling.

**Example**:
```haskell
data Nat = Zero | Succ Nat

-- Nat appears in its own definition!
```

**Solution**: Use isorecursive types with explicit fold/unfold.

```python
# Recursive types are represented as:
TypeRec(name, body)  -- e.g., TypeRec("Nat", Sum([Unit, Var(0)]))

# When elaborating constructors:
# Zero : Nat becomes: Fold(Zero, Nat)
# Succ : Nat -> Nat becomes: \n -> Fold(Succ(n), Nat)

# When pattern matching:
case n of
  Zero -> ...
  Succ m -> ...  -- m is Unfold(n)
```

**Current Status**: Nominal recursion not fully implemented. Current system uses:
- Constructor-based approach (like Haskell)
- Type constructors with arguments
- No explicit fold/unfold

---

## Known Limitations

### 1. Forward References

**Issue**: Cannot reference a function defined later in the same module.

```python
# FAILS
def f():
    return g()  # g not in scope yet!

def g():
    return 42
```

**Root Cause**: Scope checking happens declaration-by-declaration.

**Solution**: Add name collection pass before scope checking.

### 2. Higher-Rank Polymorphism

**Issue**: Cannot infer types for higher-rank polymorphic functions.

```haskell
-- This works (rank-1)
id : forall a. a -> a

-- This doesn't (rank-2)
foo : (forall a. a -> a) -> Int
```

**Current**: Only rank-1 polymorphism via type annotations.

### 3. Let-Generalization

**Issue**: Local let bindings are monomorphic.

```haskell
-- Global: polymorphic
id x = x  -- id : forall a. a -> a

-- Local: monomorphic
f = let id = \x -> x  -- id : t -> t (not polymorphic!)
    in (id 5, id True)  -- Would fail!
```

**Status**: By design (like Idris 2).

---

## Testing Strategy

### Unit Tests
- Test each inference case in isolation
- Test unification separately
- Test substitution operations

### Integration Tests
- Full pipeline tests with real programs
- Test mutual recursion
- Test polymorphic functions

### Property-Based Tests
- Unification is symmetric: `unify(a, b) == unify(b, a)`
- Substitution is idempotent: `apply(apply(t)) == apply(t)`
- Occurs check rejects all cyclic types

---

## Performance Considerations

### Meta-Variable Storage
- Current: Dictionary mapping
- Optimization: Use array-based storage (like Idris 2)

### Substitution Application
- Current: Eager application at return sites
- Optimization: Lazy application with path compression

### Constraint Queue
- Current: Immediate unification
- Optimization: Postpone constraints and batch solve

---

## Future Enhancements

1. **SCC-Based Elaboration**: Dependency-sorted declarations
2. **Higher-Rank Types**: Explicit type application
3. **Let-Generalization**: Hindley-Milner style
4. **GADTs**: Generalized algebraic data types
5. **Type Classes**: Haskell-style overloading

---

## References

1. Pierce, B. C. (2002). *Types and Programming Languages*. MIT Press.
2. Dunfield, J., & Krishnaswami, N. R. (2013). Complete and Easy Bidirectional Typechecking for Higher-Rank Polymorphism.
3. Brady, E. (2013). Idris, a General-Purpose Dependently Typed Programming Language: Design and Implementation.
4. Norell, U. (2007). Towards a practical programming language based on dependent type theory.
