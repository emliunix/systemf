---
name: python-ut
description: Python unit testing style guide. Structural equality, behavioral testing, anti-patterns to avoid.
---

# Python Unit Testing Style Guide

## Core Principle: Structural Equality

Tests must verify **behavior** through **structural equality**, not inspect implementation details.

### Required: Use Structural Equality

```python
# GOOD: Full structural comparison
assert result == expected

# GOOD: Explicit field comparison when partial check needed
assert result.status == "success"
assert len(result.items) == 3

# GOOD: Named constants instead of magic numbers
MAX_RETRIES = 5
assert attempt_count <= MAX_RETRIES
```

### Forbidden: Implementation Inspection

```python
# BAD: Type introspection
assert isinstance(result, MyClass)

# BAD: Identity comparison for value objects
assert obj1 is obj2

# BAD: Negation assertions (weak)
assert a != b
assert x is not None

# BAD: Internal state inspection
assert obj._internal_field == value
assert obj.ref.inner is not None
assert len(obj._cache) == 2

# BAD: Magic numbers without context
assert value >= 1000
assert status_code == 404

# BAD: Arithmetic in assertions
assert len(items) * 2 == total
```

## Anti-Pattern Reference

| Anti-Pattern | Example | Why Bad | Better Alternative |
|--------------|---------|---------|-------------------|
| `is` for values | `assert n1 is n2` | Tests memory address, not equality | `assert n1 == n2` |
| `isinstance()` | `assert isinstance(x, T)` | Brittle to refactoring | `assert x == expected` or test behavior |
| `!=` assertions | `assert a != b` | Weak - many things are unequal | Test specific expected value |
| `is not None` | `assert obj is not None` | Just checks existence | Test the actual value/behavior |
| Magic numbers | `assert x >= 1000` | Unclear intent | Named constant + clear comparison |
| Internal access | `assert obj._field == v` | Tests implementation | Test public behavior/output |
| Type checking | `assert type(x) == int` | Too specific | `assert x == expected_value` |
| Boolean asserts | `assert result is True` | Minimal info | `assert result == expected_object` |
| Arithmetic in assert | `assert len(x) * 2 == y` | Complex, hard to debug | Calculate expected, then compare |

## Positive Patterns

### Pattern 1: Construct Expected, Compare

```python
def test_transform():
    input_data = {"a": 1, "b": 2}
    result = transform(input_data)
    
    expected = {"sum": 3, "product": 2}
    assert result == expected
```

### Pattern 2: Field Extraction for Clarity

```python
def test_complex_result():
    result = process(user_input)
    
    # Extract fields for readable assertions
    assert result.name == "processed_item"
    assert result.count == 42
    assert result.items == ["a", "b", "c"]
```

### Pattern 3: Named Constants

```python
DEFAULT_TIMEOUT = 30
MAX_ATTEMPTS = 3

def test_retry_logic():
    result = operation_with_retry()
    
    assert result.attempts <= MAX_ATTEMPTS
    assert result.timeout == DEFAULT_TIMEOUT
```

### Pattern 4: Helper Functions for Complex Objects

```python
def make_expected_tycon(name: str, args: list) -> TyConApp:
    return TyConApp(
        name=Name(mod="test", surface=name, unique=0),
        args=args
    )

def test_tycon_zonk():
    result = zonk_type(input_ty)
    expected = make_expected_tycon("List", [TyInt()])
    assert result == expected
```

## Exception Testing

When testing exceptions is necessary (should be rare):

```python
# Use pytest.raises with match for behavioral check
with pytest.raises(ValueError, match="invalid input"):
    parse("bad data")

# NOT: checking exception type alone
with pytest.raises(ValueError):  # Too broad
    parse("bad data")
```

## File Naming

- `test_<module>.py` - Tests for `module.py`
- `test_<feature>.py` - Tests for specific feature
- Group related tests in classes only when they share substantial setup

## Test Discovery

Use descriptive function names that explain the behavior being tested:

```python
# GOOD
def test_empty_list_returns_none():
def test_duplicate_names_raise_ambiguity_error():
def test_cache_returns_same_object_for_same_key():

# BAD
def test_list():
def test_names():
def test_cache():
```

## When to Break Rules

These are acceptable exceptions:

1. **Mock verification** - `assert mock.called` (infrastructure, not domain)
2. **None checks in setup** - `assert fixture is not None` (precondition, not test)
3. **Identity for singletons** - `assert logger is logging.root` (intentional identity)

## Checklist Before Committing Tests

- [ ] No `is` assertions except for None/singletons
- [ ] No `isinstance()` type checks
- [ ] No `!=` assertions (use specific expected value)
- [ ] No internal field access (`_private` or implementation details)
- [ ] No magic numbers (use named constants)
- [ ] Full structural equality preferred
- [ ] Test function names describe behavior
