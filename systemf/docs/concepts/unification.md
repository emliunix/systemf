# Unification

**How the type checker solves constraints with meta-variables.**

---

## The Problem

When type checking polymorphic code, we often encounter situations where we know types must be equal, but we don't know what they are yet:

```haskell
id :: forall a. a -> a
id 3
```

Here:
- `id` has type `forall a. a -> a`
- `3` has type `Int`
- We need `a = Int`, but we don't know this immediately

**Solution**: Create a placeholder (meta-variable) and solve it later through **unification**.

## Meta-Variables (TMeta)

Meta-variables are **existential type variables** created during inference:

```python
@dataclass(frozen=True)
class TMeta(Type):
    id: int           # Unique identifier
    name: str | None  # Debug name (e.g., "_a")
```

**Key properties**:
- Existential: "There exists some type that goes here"
- Fresh: Each gets a unique ID
- Temporary: Solved during unification, replaced in final type
- **Different from TypeVar**: TypeVar is bound (has a binder), TMeta is unsolved

## The Substitution

A **substitution** maps meta-variables to their solutions:

```
Substitution = { TMeta(1) → Int, TMeta(2) → Bool }
```

**Example**:
```haskell
-- Before substitution
_fresh1 -> _fresh2

-- After unification: _fresh1 = Int, _fresh2 = Bool
Int -> Bool
```

## Robinson Unification

The standard algorithm for solving type equations (Robinson, 1965):

```python
def unify(t1, t2, subst):
    # Apply current substitution first
    t1 = subst.apply(t1)
    t2 = subst.apply(t2)
    
    match (t1, t2):
        case (TMeta(m), other):
            # Bind meta-variable
            if occurs_check(m, other):
                raise InfiniteTypeError
            return subst.extend(m, other)
        
        case (TypeArrow(a1, r1), TypeArrow(a2, r2)):
            # Unify components pairwise
            subst = unify(a1, a2, subst)
            subst = unify(r1, r2, subst)
            return subst
        
        case (TypeConstructor(n1, args1), TypeConstructor(n2, args2)):
            # Same constructor, unify arguments
            if n1 != n2: raise UnificationError
            for arg1, arg2 in zip(args1, args2):
                subst = unify(arg1, arg2, subst)
            return subst
```

## Occurs Check

Prevents infinite types (e.g., `a = a -> b`):

```python
def occurs_check(meta, ty, subst):
    """Check if meta occurs in ty (would create infinite type)"""
    ty = subst.apply(ty)  # Resolve first
    
    match ty:
        case TMeta(id) if id == meta.id:
            return True  # Found itself!
        case TypeArrow(arg, ret):
            return occurs_check(meta, arg) or occurs_check(meta, ret)
        case _:
            return False
```

**Example**:
```haskell
-- Try to unify: _a = _a -> Int
-- occurs_check(_a, _a -> Int) = True
-- REJECT - would create infinite type
```

## How It Works in Practice

### Example: Polymorphic Application

```haskell
id :: forall a. a -> a
id 3
```

**Step-by-step**:

```
1. Look up id: forall a. a -> a
   
2. Instantiate: Replace 'a' with fresh meta
   Type becomes: _t1 -> _t1
   
3. Infer 3: Int
   
4. Need to match: (_t1 -> _t1) arg with Int
   - Function domain _t1 must equal Int
   - unify(_t1, Int)
   
5. Substitution becomes: { _t1 → Int }
   
6. Apply substitution to return type: _t1 → Int
   
7. Result: Int
```

### Example: Multiple Constraints

```haskell
pair :: forall a b. a -> b -> Pair a b
pair (id 3) (id True)
```

**Unification steps**:

```
1. Instantiate pair: _t1 -> _t2 -> Pair _t1 _t2

2. First argument (id 3):
   - Instantiate id: _t3 -> _t3
   - unify(_t3, Int)  -- from 3
   - First arg type: Int
   - unify(_t1, Int)  -- match with pair's first param

3. Second argument (id True):
   - Instantiate id: _t4 -> _t4
   - unify(_t4, Bool)  -- from True
   - Second arg type: Bool
   - unify(_t2, Bool)  -- match with pair's second param

4. Final substitution: { _t1→Int, _t2→Bool, _t3→Int, _t4→Bool }

5. Result type: Pair Int Bool
```

## The Interleaving with Bidirectional Checking

**This is the key insight**: Unification and bidirectional checking are **not separate phases**. They **interleave** during the same traversal.

```python
def infer_app(func, arg, ctx):
    # 1. BIDIRECTIONAL: Infer function type
    func_type = infer(func, ctx)
    
    # 2. UNIFICATION: Apply substitutions
    func_type = subst.apply(func_type)
    
    # 3. IMPLICIT INSTANTIATION: Replace forall with meta
    if isinstance(func_type, TypeForall):
        func_type = instantiate(func_type)  # Creates TMetas
        func_type = subst.apply(func_type)
    
    # 4. BIDIRECTIONAL: Check argument against expected type
    match func_type:
        case TypeArrow(param_type, ret_type):
            check(arg, param_type, ctx)  # Uses expected type!
            
    # 5. UNIFICATION: Apply new substitutions
    ret_type = subst.apply(ret_type)
    
    return ret_type
```

**Pattern**: infer → apply_subst → maybe instantiate → check → apply_subst

This alternation happens **at every application**.

## TMeta vs TypeVar: Critical Distinction

| Aspect | TMeta | TypeVar |
|--------|-------|---------|
| **Represents** | Unknown type to be solved | Bound type parameter |
| **Has binder?** | No | Yes (in TypeForall) |
| **Lifetime** | Temporary (solved during elaboration) | Permanent (in Core AST) |
| **Example** | `_t1` (fresh meta) | `a` in `forall a. a -> a` |
| **Replaced by** | Substitution | Type application (TApp) |

**Visual distinction**:

```haskell
-- Surface: forall a. a -> a
-- After instantiation: _t1 -> _t1  (TMeta replaces TypeVar)
-- After unification with Int: Int -> Int  (TMeta solved)

-- Core: id[Int] 3
-- Here 'Int' replaces 'a' explicitly via TApp
```

## Summary

Unification solves the problem of **unknown types** during inference:

1. **Create** meta-variables (TMeta) for unknowns
2. **Collect** constraints by traversing the AST
3. **Solve** constraints via Robinson unification
4. **Apply** substitution to get concrete types
5. **Generate** Core AST with explicit type applications

**Key point**: Meta-variables are **not** part of the final Core language. They're elaboration-time tools that get completely resolved before producing Core.

## References

- **Robinson (1965)**: "A Machine-Oriented Logic Based on the Resolution Principle"
- **Martelli & Montanari (1982)**: "An Efficient Unification Algorithm"
- **Pierce (2002)**: "Types and Programming Languages" - Chapter 22
