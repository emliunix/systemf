# Type Inference Bugs - Critical Issues

**Status**: Active investigation  
**Date**: 2026-03-02  
**Priority**: CRITICAL - Blocking full test suite passage  
**Files Affected**: `systemf/surface/inference/elaborator.py`

---

## Context: What We're Dealing With

The System F elaborator has **7 failing tests** (out of 182 total):
- 4 in type inference tests
- 3 in pipeline integration tests

The core functionality works (175 tests pass), but these edge cases reveal bugs in the type inference algorithm. We need to fix these before considering the refactor complete.

### The Type Inference Pipeline

```
SurfaceTerm (with type annotations or holes)
    ↓ infer()
TypeElaborator creates meta-variables for unknown types
    ↓ check()
Unification solves type constraints
    ↓
Core.Term (fully typed) + Type
```

**Key insight**: Type inference is **bidirectional**:
- `infer(term, ctx)` - Synthesize type from term (bottom-up)
- `check(term, expected_type, ctx)` - Verify term matches expected type (top-down)

---

## Bug A: Type Variable Resolution (2 tests failing)

### Tests Failing
1. `test_application_with_inference` - `tests/test_surface/test_inference.py:256`
2. `test_deeply_nested_application` - `tests/test_surface/test_inference.py:912`

### What Happens
```python
# Test: (\x -> x) 42  should return Int
body = ScopedVar(0, "x", DUMMY_LOC)
abs_term = ScopedAbs("x", None, body, DUMMY_LOC)  # No type annotation!
arg = SurfaceIntLit(42, DUMMY_LOC)
app = SurfaceApp(abs_term, arg, DUMMY_LOC)

core_term, ty = elab.infer(app, ctx)
# EXPECTED: ty.name == "Int"
# ACTUAL:   ty.name == "x"  (unresolved type variable!)
```

### Root Cause Analysis

When we have `ScopedAbs("x", None, body, loc)`:
1. `None` means no type annotation
2. TypeElaborator should create a **meta-variable** (TMeta) for `x`'s type
3. When we apply to `42` (Int), unification should bind the meta-variable to Int
4. **Bug**: The final type returned is the meta-variable itself, not the substituted type

**Code path**:
```python
# In elaborator.py, infer() for Abs:
case ScopedAbs(var_name, type_annotation, body, location):
    if type_annotation is None:
        # Creates fresh meta-variable
        arg_type = TMeta.fresh(var_name)  # e.g., TMeta(id=1, name="x")
    else:
        arg_type = self._surface_type_to_core(type_annotation)
    
    # Extends context with arg_type
    new_ctx = ctx.extend_term(arg_type)
    core_body, body_type = self.infer(body, new_ctx)
    
    # Returns function type, but body_type may still have unresolved meta-vars
    return core.Abs(...), TypeArrow(arg_type, body_type, ...)
```

The problem: `body_type` may contain meta-variables that were unified during inference, but we're returning the **original** type, not the **substitution-resolved** type.

### Detailed Bug Location

```python
# elaborator.py, infer() method for Abs (~line 383)
case ScopedAbs(var_name, type_annotation, body, location):
    # ... creates arg_type ...
    core_body, body_type = self.infer(body, new_ctx)
    # BUG: body_type hasn't had substitution applied!
    result_type = TypeArrow(arg_type, body_type, ...)
    return core.Abs(..., core_body, ...), result_type
```

**Fix needed**: Apply `self.subst.apply_to_type(body_type)` before returning.

---

## Bug B: Polymorphic Type Unification (3 tests failing)

### Tests Failing
1. `test_case_with_pattern_bindings` - `tests/test_surface/test_inference.py:593`
2. `test_flip_function` - `tests/test_pipeline.py:556`
3. `test_nested_lambda_application` - `tests/test_pipeline.py:323`

### What Happens - Case 1 (Pattern Bindings)

```python
# Constructor: Pair : a -> b -> Pair a b
ctx = TypeContext(
    constructors={
        "Pair": TypeArrow(
            TypeVar("a"),
            TypeArrow(TypeVar("b"), TypeConstructor("Pair", [TypeVar("a"), TypeVar("b")]))
    }
)

# scrut = Pair 1 2  (should be Pair Int Int)
scrut = SurfaceConstructor("Pair", [SurfaceIntLit(1), SurfaceIntLit(2)])

# case scrut of Pair a b -> a
branches = [SurfaceBranch(SurfacePattern("Pair", ["a", "b"]), ScopedVar(1, "a"))]
case_term = SurfaceCase(scrut, branches)

core_term, ty = elab.infer(case_term, ctx)
# ERROR: Cannot unify 'a' with 'Int'
```

### Root Cause Analysis

**The Issue**: When elaborating `SurfaceConstructor("Pair", [arg1, arg2])`:

1. We look up constructor type: `a -> b -> Pair a b`
2. We need to instantiate the type variables `a` and `b` with **fresh meta-variables**
3. Then unify those meta-variables with the actual argument types
4. **Bug**: The type variables `a` and `b` from the constructor signature are being used directly instead of being instantiated

**Code path**:
```python
# In elaborator.py, infer() for Constructor (~line 412):
case SurfaceConstructor(name, args, location):
    constr_type = ctx.constructors[name]  # TypeArrow(TypeVar("a"), ...)
    # BUG: Using TypeVar directly instead of instantiating!
    # Should be: fresh_meta_a, fresh_meta_b, then substitute
```

### What Happens - Case 2 (Flip Function)

```python
# flip : (a -> b -> c) -> b -> a -> c
flip_type = SurfaceTypeArrow(
    arrow_abc,  # a -> b -> c
    arrow_bac   # b -> a -> c
)

# When elaborating, type variables a, b, c should be distinct for each call
# BUG: They're being treated as the same variables across the type
# Error: Cannot unify 'a' with 'b'
```

**The Issue**: Type variables in polymorphic types need to be **instantiated** with fresh meta-variables at each use site. Currently they're being unified directly.

### Detailed Bug Location

```python
# elaborator.py, infer() for Constructor (~line 412):
case SurfaceConstructor(name, args, location):
    constr_type = ctx.constructors[name]
    # Need to instantiate polymorphic type here!
    # constr_type might be: forall a b. a -> b -> Pair a b
    # Should become: TMeta(fresh) -> TMeta(fresh) -> Pair TMeta TMeta
```

---

## Bug C: Wrong Exception Type (1 test failing)

### Test Failing
`test_type_mismatch_error_message` - `tests/test_surface/test_inference.py:794`

### What Happens
```python
# Trying to check Int as String
int_term = SurfaceIntLit(42)
str_type = TypeConstructor("String", [])

with pytest.raises(TypeMismatchError):
    elab.check(int_term, str_type, empty_ctx)
# EXPECTED: TypeMismatchError with expected=String, actual=Int
# ACTUAL:   UnificationError: Cannot unify 'String' with 'Int'
```

### Root Cause Analysis

The `check()` method calls `_unify()` which raises `UnificationError`. But for better error messages, we should catch that and raise `TypeMismatchError` with context.

**Code path**:
```python
# elaborator.py, check() (~line 749):
def check(self, term, expected_type, ctx):
    # ... infer actual type ...
    self._unify(expected_type, actual_type, location)  # Raises UnificationError
```

**Fix needed**: Wrap in try/except and convert to TypeMismatchError.

---

## Fix Plan

### Fix 1: Apply Substitution to Result Types (Bug A)
**File**: `systemf/surface/inference/elaborator.py`
**Lines**: ~383-395 (infer() for Abs)

```python
case ScopedAbs(var_name, type_annotation, body, location):
    # ... existing code ...
    core_body, body_type = self.infer(body, new_ctx)
    
    # FIX: Apply substitution to resolve any meta-variables
    body_type = self.subst.apply_to_type(body_type)
    
    result_type = TypeArrow(arg_type, body_type, ...)
    return core.Abs(...), result_type
```

### Fix 2: Instantiate Polymorphic Types (Bug B)
**File**: `systemf/surface/inference/elaborator.py`
**Lines**: ~412-433 (infer() for Constructor)

```python
def _instantiate_type(self, poly_type: Type) -> Type:
    """Instantiate polymorphic type with fresh meta-variables."""
    match poly_type:
        case TypeVar(name):
            return TMeta.fresh(name)
        case TypeArrow(arg, ret, loc):
            return TypeArrow(
                self._instantiate_type(arg),
                self._instantiate_type(ret),
                loc
            )
        case TypeForall(var, body):
            # Replace bound variable with fresh meta
            return self._instantiate_type(body)
        case _:
            return poly_type

# In infer() for Constructor:
case SurfaceConstructor(name, args, location):
    constr_type = ctx.constructors[name]
    # FIX: Instantiate before using
    constr_type = self._instantiate_type(constr_type)
    # ... rest of elaboration ...
```

### Fix 3: Convert Exception Types (Bug C)
**File**: `systemf/surface/inference/elaborator.py`
**Lines**: ~749 (check() method)

```python
def check(self, term, expected_type, ctx):
    # ... infer actual type ...
    try:
        self._unify(expected_type, actual_type, location)
    except UnificationError as e:
        # FIX: Convert to TypeMismatchError for better UX
        raise TypeMismatchError(
            expected=expected_type,
            actual=actual_type,
            location=location,
            diagnostic=e.diagnostic
        ) from e
```

### Fix 4: Mark Forward Reference Test as Expected Failure
**File**: `tests/test_pipeline.py`
**Test**: `test_forward_reference`

```python
@pytest.mark.xfail(reason="Forward references not yet implemented - see FORWARD_REFERENCES_RESEARCH.md")
def test_forward_reference(self):
    # ... existing test ...
```

---

## Testing After Fixes

Run these specific tests to verify fixes:
```bash
cd systemf
uv run pytest tests/test_surface/test_inference.py::TestApplication::test_application_with_inference -v
uv run pytest tests/test_surface/test_inference.py::TestComplexExpressions::test_deeply_nested_application -v
uv run pytest tests/test_surface/test_inference.py::TestConstructorsAndCases::test_case_with_pattern_bindings -v
uv run pytest tests/test_surface/test_inference.py::TestTypeErrors::test_type_mismatch_error_message -v
uv run pytest tests/test_pipeline.py::TestRealPrograms::test_flip_function -v
uv run pytest tests/test_pipeline.py::TestComplexExpressions::test_nested_lambda_application -v
```

Expected: All 6 should pass (test_forward_reference marked xfail)

---

## Forward References Research (Deferred)

See `FORWARD_REFERENCES_RESEARCH.md` for full analysis.

**Summary**: Forward references require collecting all names before scope-checking. Solution involves adding a "name collection pass" before the signature collection pass.

**Decision**: Fix type inference bugs first (blocking), implement forward references later (enhancement).

---

## Implementation Order

1. **Fix 3** (Exception type) - Easiest, builds confidence
2. **Fix 1** (Substitution application) - Core issue, affects many tests
3. **Fix 2** (Polymorphic instantiation) - Complex, affects advanced features
4. **Fix 4** (Mark xfail) - Housekeeping
5. **Verify all tests pass**

**Estimated time**: 1-2 hours of focused work
