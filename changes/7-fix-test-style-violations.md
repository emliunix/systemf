# Change Plan: Fix elab3 Test Style Violations

**Status:** Draft  
**Date:** 2026-03-31  
**Target:** `systemf/tests/test_elab3/test_zonk_and_cache.py`  
**Skill:** `.agents/skills/python-ut/SKILL.md`

---

## Facts

1. **Current State:**
   - File created at `systemf/tests/test_elab3/test_zonk_and_cache.py`
   - Tests exist for `zonk_type()` and `NameCache.get()`
   - Multiple style violations against python-ut skill

2. **Violations Found (9 instances):**

| Line | Current Code | Violation |
|------|--------------|-----------|
| 22 | `assert result is m` | Uses `is` for value comparison |
| 53-54 | `assert m1.ref is not None`<br>`assert m1.ref.get() == TyInt()` | Internal state inspection |
| 114 | `assert name.unique >= 1000` | Magic number |
| 123 | `assert n1 is n2` | Uses `is` for value comparison |
| 133 | `assert n1.unique != n2.unique` | Negation assertion |
| 142 | `assert n1.unique != n2.unique` | Negation assertion |
| 151 | `assert n.unique == 1` | Magic number (builtin unique) |
| 160 | `assert n1 is n2` | Uses `is` for value comparison |
| 172 | `assert n1 is n3` | Uses `is` for value comparison |
| 173-174 | `assert n1.unique != n2.unique` | Negation assertions |
| 191 | `assert isinstance(result, TyConApp)` | Type introspection |

3. **Required dataclass support:**
   - `Name` needs `__eq__` comparing `unique` field
   - `Ty` subclasses need `__eq__` for structural comparison

---

## Design

### Changes Needed

**1. Fix Line 22: Identity → Explicit field comparison**
```python
# BEFORE:
assert result is m

# AFTER:
assert result.uniq == m.uniq  # Compare the unique field directly
```

**2. Fix Lines 53-54: Remove internal inspection**
```python
# BEFORE:
assert m1.ref is not None
assert m1.ref.get() == TyInt()

# AFTER:
# Just test the behavior - zonk returns correct result
# Internal state (path compression) is implementation detail
```

**3. Fix Line 114: Magic number → Named constant**
```python
# BEFORE:
assert name.unique >= 1000

# AFTER:
START_UNIQ = 1000
assert name.unique >= START_UNIQ
```

**4. Fix Lines 123, 160, 172: `is` → Explicit field comparison**
```python
# BEFORE:
assert n1 is n2

# AFTER:
assert n1.unique == n2.unique  # Compare unique field directly
```

**5. Fix Lines 133, 142, 173-174: Negation → Sequential comparison**
```python
# BEFORE:
assert n1.unique != n2.unique

# AFTER:
# Test that each new name gets a higher unique
assert n2.unique == n1.unique + 1  # Sequential allocation
```

**6. Fix Line 151: Magic number → Constant**
```python
# BEFORE:
assert n.unique == 1  # Builtin Bool unique

# AFTER:
# Import from builtins.py
from systemf.elab3.builtins import BUILTIN_BOOL
assert n.unique == BUILTIN_BOOL.unique
```

**7. Fix Line 191: isinstance → Structural comparison**
```python
# BEFORE:
assert isinstance(result, TyConApp)
assert result.args[0] == TyInt()

# AFTER:
expected = TyConApp(name=list_name, args=[TyInt()])
assert result == expected
```

### NO Dataclass Changes

Keep default dataclass behavior. Do NOT override `__eq__` or `__hash__` on `Name`.
Tests compare fields explicitly: `n1.unique == n2.unique`

---

## Why It Works

- Structural equality tests behavior, not implementation
- Named constants make intent clear
- Positive assertions are stronger than negations
- No brittle internal state dependencies

---

## Files to Change

1. **`systemf/tests/test_elab3/test_zonk_and_cache.py`** - Fix style violations ONLY

**NO changes to `systemf/src/systemf/elab3/types.py`** - Keep default dataclass `__eq__`

---

## Validation Checklist

- [ ] All `is` assertions converted to explicit field comparisons (`n1.unique == n2.unique`)
- [ ] No internal state inspection (`.ref`, `._field`)
- [ ] All magic numbers have named constants
- [ ] No `!=` assertions (use sequential comparison)
- [ ] No `isinstance()` type checks
- [ ] Tests pass with `pytest tests/test_elab3/test_zonk_and_cache.py -v`
- [ ] NO dataclass changes - keep default `__eq__` behavior

---

## Open Questions

None - all resolved.
