# Change Plan: Add elab3 Unit Tests for zonk_type and NameCache

**Status:** Draft  
**Date:** 2026-03-31  
**Files to Change:** `systemf/tests/test_elab3/test_zonk_and_cache.py` (new)

---

## Facts

1. **Existing Test Infrastructure:**
   - `tests/test_elab2/test_types.py` has comprehensive `zonk_type` tests
   - `tests/test_elab2/test_unify.py` has meta variable binding tests
   - elab3 has different type structure than elab2 but same concepts

2. **elab3 Type Structure:**
   - `MetaTv` has `ref: Ref[Ty] | None` field
   - `Ref` is a mutable cell with `inner: T | None`
   - `zonk_type()` in `types.py` does path compression
   - `NameCache.get()` in `mod.py` provides stable unique allocation

3. **Current State:**
   - `tests/test_elab3/test_types.py` exists but tests outdated signatures
   - No tests for `NameCache` behavior
   - No tests for meta variable chain resolution

---

## Design

Create focused test file covering:

1. **zonk_type() tests:**
   - Unsolved meta returns itself
   - Solved meta returns solution
   - Chain resolution (m1 -> m2 -> Int gives Int)
   - Path compression (updates ref cells)
   - Structural types (fun, forall) recursively zonk

2. **NameCache.get() tests:**
   - First call allocates new unique
   - Second call with same (module, surface) returns same Name
   - Different (module, surface) gets different unique
   - Builtin names get predefined uniques

---

## Why It Works

- Tests verify core infrastructure that other components depend on
- Follows same patterns as proven elab2 tests
- Isolated tests mean we catch regressions early
- No dependencies on incomplete components (rename, typecheck)

---

## Files

- **NEW:** `systemf/tests/test_elab3/test_zonk_and_cache.py`

---

## Test Cases

### zonk_type

```python
# Unbound meta returns itself
def test_zonk_unbound_meta():
    m = MetaTv(uniq=1, ref=Ref(None))
    assert zonk_type(m) is m

# Bound meta returns solution
def test_zonk_bound_meta():
    m = MetaTv(uniq=1, ref=Ref(TyInt()))
    assert zonk_type(m) == TyInt()

# Chain resolution
def test_zonk_meta_chain():
    m3 = MetaTv(uniq=3, ref=Ref(TyInt()))
    m2 = MetaTv(uniq=2, ref=Ref(m3))
    m1 = MetaTv(uniq=1, ref=Ref(m2))
    assert zonk_type(m1) == TyInt()
    # Verify path compression
    assert m1.ref.inner == TyInt()

# Function type recursively zonked
def test_zonk_function():
    m = MetaTv(uniq=1, ref=Ref(TyInt()))
    fun = TyFun(m, TyString())
    assert zonk_type(fun) == TyFun(TyInt(), TyString())
```

### NameCache

```python
# Stable allocation
def test_cache_stable():
    cache = NameCache(Uniq(1000))
    n1 = cache.get("M", "foo")
    n2 = cache.get("M", "foo")
    assert n1 is n2
    assert n1.unique == n2.unique

# Different keys get different uniques
def test_cache_different_keys():
    cache = NameCache(Uniq(1000))
    n1 = cache.get("M", "foo")
    n2 = cache.get("M", "bar")
    n3 = cache.get("N", "foo")
    assert n1.unique != n2.unique
    assert n1.unique != n3.unique

# Builtin uniques
def test_cache_builtin():
    cache = NameCache(Uniq(1000))
    n = cache.get("builtins", "Bool")
    assert n.unique == 1  # From BUILTIN_UNIQUES
```

---

## Open Questions

1. Should we fix `tests/test_elab3/test_types.py` in same PR or separate?
2. Do we need to add `__eq__` to Ty classes for test assertions?

---

## Validation Checklist

- [ ] All tests pass with `pytest tests/test_elab3/test_zonk_and_cache.py -v`
- [ ] Tests cover both success and edge cases
- [ ] No dependencies on incomplete modules (rename, typecheck)
