# Forward References and Mutual Recursion Research

**Status**: Documented, implementation deferred  
**Date**: 2026-03-02  
**Priority**: Type inference bugs are more critical - fix those first

---

## Current Limitation

Forward references fail when function `f` references `g` but `g` is defined later in the same declaration list:

```python
# FAILS: g not in scope when f is elaborated
f x = g x   # Undefined variable: 'g'
g y = y
```

But mutual recursion **does work** when functions are in the same scope:
```python
# WORKS: both visible to each other via globals
even Z = True
even (S n) = odd n
odd Z = False  
odd (S n) = even n
```

## Root Cause

Our current pipeline:
1. **Phase 1**: Collect type signatures → add to TypeContext
2. **Phase 2**: Scope-check each body (Surface → Scoped AST)  
   - **Problem**: ScopeContext doesn't have the names yet!
3. **Phase 3**: Elaborate each body (Scoped → Core AST)

The scope checker needs the **names** (not just type signatures) to be in scope.

## How Other Languages Solve This

### Idris 2 (Lines 313-316 in elaboration-comparison.md)
```
**Top-level declarations:**
1. Collect all names first
2. Elaborate type signatures  
3. Elaborate definitions (with names in scope)
4. **Mutual recursion:** All definitions see each other
```

### Agda (Line 214)
- Uses **mutual blocks** explicitly
- Forward references allowed within a mutual block

### GHC Haskell (Lines 398-399)
- Uses **SCCs (Strongly Connected Components)**
- Dependency-sorted elaboration

## Solution Strategy

**Fix: Add Name Collection Pass**

Change pipeline from:
```
Signatures → Scope Check → Elaborate
```

To:
```
Collect Names → Add to ScopeContext → Signatures → Scope Check → Elaborate
```

**Implementation**:
```python
def elaborate_declarations(decls):
    # NEW: Pass 0 - Collect all names
    all_names = {decl.name for decl in decls}
    
    # Pass 1: Collect signatures
    global_types = {}
    for decl in decls:
        if isinstance(decl, SurfaceTermDeclaration):
            global_types[decl.name] = surface_to_core_type(decl.type_annotation)
    
    # Pass 2: Scope check with names in scope  
    scope_ctx = ScopeContext(globals=all_names)  # NOW has names!
    for decl in decls:
        scoped_body = scope_checker.check_term(decl.body, scope_ctx)
        # ...
    
    # Pass 3: Elaborate
    ...
```

## Test Failures Related to This

- `test_forward_reference` (Pipeline) - Forward reference limitation
- `test_case_with_pattern_bindings` (Inference) - May be related to scope issues
- `test_flip_function` (Pipeline) - Polymorphic unification

## Next Steps

1. **FIRST**: Fix type inference bugs (application inference, error types)
2. **THEN**: Implement name collection pass for forward references
3. **LATER**: Consider full SCC-based dependency sorting if needed

---

## Type Inference Bugs (Critical - Fix Now)

### Issue A: Type Variable Resolution (2 tests failing)
**Tests**: `test_application_with_inference`, `test_deeply_nested_application`

**Problem**: Type variable `'x'` not resolved to `'Int'`
```python
(\x -> x) 42  # Should return Int, returns type var 'x'
```

**Likely cause**: Substitution not applied to final result type

### Issue B: Polymorphic Type Unification (3 tests failing)  
**Tests**: `test_case_with_pattern_bindings`, `test_flip_function`

**Problem**: Type variables from different scopes treated as same
```python
# Pair : a -> b -> Pair a b
# Pair 1 2  # Should unify a=Int, b=Int
# Error: Cannot unify 'a' with 'Int'
```

**Likely cause**: Pattern matching doesn't properly introduce fresh type variables

### Issue C: Exception Type (1 test failing)
**Test**: `test_type_mismatch_error_message`

**Problem**: `UnificationError` raised instead of `TypeMismatchError`

**Fix**: Catch unification failures in elaborator, re-raise as TypeMismatchError

## Files to Modify

1. `systemf/surface/inference/elaborator.py` - Fix type variable resolution
2. `systemf/surface/inference/elaborator.py` - Fix exception type  
3. Tests - Mark forward reference as expected failure for now

---

**Decision**: Fix type inference bugs first (critical), implement forward references later (feature enhancement).
