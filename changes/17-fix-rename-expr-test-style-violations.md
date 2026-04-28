# Change Plan: Fix test_rename_expr.py Style Violations

**Status:** Draft  
**Date:** 2026-04-03  
**Target:** `systemf/tests/test_elab3/test_rename_expr.py`  
**Skill:** `docs/styles/testing-structural.md`

---

## Facts

1. **Current State:**
   - File created at `systemf/tests/test_elab3/test_rename_expr.py` (change 14)
   - Contains 19 test functions for `RenameExpr.rename_expr()`
   - Major style violations against structural comparison guidelines

2. **Violations Found (15+ instances of anti-patterns):**

| Lines | Current Code | Violation |
|-------|--------------|-----------|
| 123-131 | `isinstance(rn_expr, Lam)` chains checking fields | Using `isinstance` chains instead of structural comparison |
| 140-146 | `isinstance(param, AnnotName)` with field checks | Field-by-field assertions |
| 155-162 | `assert param0.surface == "x"` | Direct field assertions instead of structural comparison |
| 172-185 | Multiple `isinstance` checks for nested lambdas | Complex assertion chains |
| 221-229 | `isinstance(inner_app.arg, Var)` chains | Breaking down structure instead of comparing complete AST |
| 244-256 | `isinstance(binding.name, AnnotName)` | Field assertions on binding structure |
| 271-282 | Multiple `isinstance` assertions on Let | Not using structural comparison |
| 291-293 | `isinstance(rn_expr, Ann)` chain | Type introspection instead of structural comparison |
| 317-333 | True/False branch field assertions | Complex assertions on Case branches |
| 356-366 | `isinstance(rn_expr.func, App)` chains | Breaking down operator application structure |
| 380-383 | `isinstance(rn_expr.func.func, Var)` | Tuple desugaring assertions |
| 401-418 | `isinstance(rn_expr.scrutinee, Var)` | Case expression field checks |
| 449-457 | `assert rn_expr.body.name.unique == inner_x.unique` | Checking unique IDs instead of structural comparison |
| 471-479 | `isinstance(rn_expr.bindings[0].name, Name)` | Let binding field assertions |

3. **Required dataclass support:**
   - `Name` needs structural comparison (already supported via `structural_equals()`)
   - All AST types need proper `__eq__` for structural comparison

---

## Design

### Pattern: Build Expected AST, Compare with structural_equals()

**Example Fix for test_rename_expr_lambda_simple (lines 116-131):**

```python
# BEFORE (violation):
def test_rename_expr_lambda_simple():
    """Lambda \x -> x creates Lam with param and body referencing bound var."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\x -> x")
    rn_expr = renamer.rename_expr(expr)
    
    # Lambda binds x, body references the bound x
    assert isinstance(rn_expr, Lam)
    assert len(rn_expr.args) == 1
    param = rn_expr.args[0]
    assert isinstance(param, Name)
    assert param.surface == "x"
    
    # Body should be Var referencing the same name
    assert isinstance(rn_expr.body, Var)
    assert rn_expr.body.name.unique == param.unique

# AFTER (correct):
def test_rename_expr_lambda_simple():
    """Lambda \x -> x creates Lam with param and body referencing bound var."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\x -> x")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure completely
    expected_param = Name(mod="Test", surface="x", unique=-1)
    expected = Lam(
        args=[expected_param],
        body=Var(name=expected_param)
    )
    
    # Single structural comparison
    assert structural_equals(rn_expr, expected)
```

**Example Fix for test_rename_expr_application_nested (lines 208-229):**

```python
# BEFORE (violation):
def test_rename_expr_application_nested():
    """Nested application f x y becomes App(App(Var(f), Var(x)), Var(y))."""
    renamer = mk_rename_expr_with_builtins()
    
    f_name = renamer.name_gen.new_name("f", None)
    x_name = renamer.name_gen.new_name("x", None)
    y_name = renamer.name_gen.new_name("y", None)
    renamer.local_env.extend([("f", f_name), ("x", x_name), ("y", y_name)])
    
    expr = parse_expr("f x y")
    rn_expr = renamer.rename_expr(expr)
    
    # Should be left-associative: (f x) y
    assert isinstance(rn_expr, App)
    assert isinstance(rn_expr.arg, Var)
    assert rn_expr.arg.name.unique == y_name.unique
    assert isinstance(rn_expr.func, App)
    inner_app = rn_expr.func
    assert isinstance(inner_app.arg, Var)
    assert inner_app.arg.name.unique == x_name.unique
    assert isinstance(inner_app.func, Var)
    assert inner_app.func.name.unique == f_name.unique

# AFTER (correct):
def test_rename_expr_application_nested():
    """Nested application f x y becomes App(App(Var(f), Var(x)), Var(y))."""
    renamer = mk_rename_expr_with_builtins()
    
    f_name = Name(mod="Test", surface="f", unique=-1)
    x_name = Name(mod="Test", surface="x", unique=-1)
    y_name = Name(mod="Test", surface="y", unique=-1)
    renamer.local_env.extend([("f", f_name), ("x", x_name), ("y", y_name)])
    
    expr = parse_expr("f x y")
    rn_expr = renamer.rename_expr(expr)
    
    # Build complete expected AST
    expected = App(
        func=App(
            func=Var(name=f_name),
            arg=Var(name=x_name)
        ),
        arg=Var(name=y_name)
    )
    
    assert structural_equals(rn_expr, expected)
```

### Key Principles

1. **Build complete expected AST** - Construct the full expected structure
2. **Use `structural_equals()`** - Ignores `location`, `source_loc`, `unique`, `loc` fields
3. **Single assertion per test** - One `structural_equals()` call, not chains
4. **Use `unique=-1`** - Let structural comparison ignore unique IDs

---

## Files to Change

1. **`systemf/tests/test_elab3/test_rename_expr.py`** - Rewrite all tests to use structural comparison

---

## Validation Checklist

- [ ] No `isinstance()` assertions (except for error cases)
- [ ] No field-by-field assertions (`.surface`, `.unique`, etc.)
- [ ] All tests use `structural_equals()` for AST comparison
- [ ] Complete expected AST structures built in each test
- [ ] `unique=-1` used for expected Name objects
- [ ] Tests pass with `pytest tests/test_elab3/test_rename_expr.py -v`

---

## Why It Works

1. **Self-documenting**: Expected structure shows what the code should produce
2. **Maintainable**: Single assertion per test, easy to update when AST changes
3. **Robust**: Ignores generated fields (unique IDs, locations) that vary between runs
4. **Consistent**: Follows the structural comparison pattern established in other test files
