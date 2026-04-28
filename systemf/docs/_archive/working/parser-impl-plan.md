# Parser Implementation: Context Closure & Execution Plan

## Status Summary

**Tests**: FROZEN - Do not modify test files
**Goal**: Make failing tests pass by implementing missing parser features
**Current**: 50/113 tests passing (63 tests failing legitimately)

## Architecture Overview

```
src/systemf/surface/parser/
├── helpers.py          ✅ FROZEN - Complete
├── types.py            ✅ FROZEN - Complete  
├── lexer.py            ✅ FROZEN - Complete
├── expressions.py      🔄 NEEDS WORK
├── declarations.py     🔄 NEEDS WORK
└── __init__.py         ✅ Complete
```

## Critical Files (READ-ONLY References)

1. **docs/syntax.md** - Grammar specification (Sections 3, 7)
2. **tests/test_surface/test_parser/test_expressions.py** - FROZEN
3. **tests/test_surface/test_parser/test_declarations.py** - FROZEN
4. **src/systemf/surface/parser/helpers.py** - FROZEN
5. **src/systemf/surface/types.py** - AST node definitions

## Implementation Phases

### Phase 1: Type Parser Fix (HIGH PRIORITY)
**Problem**: Data declarations fail on type params (`Maybe a`, `List a`)
**Error**: `AttributeError: 'NoneType' object has no attribute 'location'`
**Location**: declarations.py:221

**Root Cause**: 
- `type_atom_parser()` returns None for type variables in constructor position
- `constr_parser()` calls `type_atom_parser()` which fails on `a` in `Just a`

**Fix Required**:
```python
# In declarations.py, type_atom_parser needs to handle:
# - Type variables (IDENT)
# - Type constructors (CONSTRUCTOR)
# - Parenthesized types
# - Type applications (Cons a (List a))
```

**Tests Affected**:
- test_data_with_param (Maybe a)
- test_data_with_multiple_params (Either a b)
- test_recursive_data (List a)

---

### Phase 2: Operator Expressions (HIGH PRIORITY)
**Problem**: Operators not recognized in expressions
**Errors**: 
- `expected 'EOF' at 1` for `x + y`
- `expected keyword 'then', got GT` for `x > 0`

**Location**: expressions.py - `expr_parser()` missing `op_expr`

**Current State**:
```python
expr_parser = alt(
    lambda_parser(constraint),
    case_parser(constraint),
    let_parser(constraint),
    app_parser(constraint),  # Only handles application, not operators
)
```

**Fix Required**:
Add operator parsing between application and atom:
```python
# Operator precedence (high to low):
# 1. * /
# 2. + -
# 3. == /= < > <= >=
# 4. &&
# 5. ||

op_expr = chainl1(app_expr, operator)
```

**Tests Affected**:
- test_addition, test_arithmetic_precedence
- test_comparison, test_equality
- test_logical_operators
- test_if_with_layout (needs comparison)

---

### Phase 3: Multiple Let Bindings (HIGH PRIORITY)
**Problem**: Let only parses single binding
**Error**: `expected keyword 'in', got EQUALS at 5` for second binding

**Location**: expressions.py - `let_parser()` uses single `let_binding`, not `block_entries()`

**Current**:
```python
@generate
def let_parser(constraint):
    yield match_keyword("let")
    binding = yield let_binding(constraint)  # Only one!
    yield match_keyword("in")
    body = yield expr_parser(constraint)
    return SurfaceLet([binding], body)
```

**Fix Required**:
```python
@generate
def let_parser(constraint):
    yield match_keyword("let")
    col = yield column()  # Capture layout column
    bindings = yield block_entries(AtPos(col), let_binding)
    yield must_continue(constraint, "in")
    yield match_keyword("in")
    body = yield expr_parser(constraint)
    return SurfaceLet(bindings, body)
```

**Tests Affected**:
- test_let_multiple_bindings
- test_complex_let_expression
- test_let_recursive
- test_recursion_with_let

---

### Phase 4: If-Then-Else Parser (MEDIUM PRIORITY)
**Problem**: If expressions not implemented
**Error**: Parser expects atom but finds GT (>)

**Location**: expressions.py - missing `if_parser` in expr_parser chain

**Fix Required**:
```python
@generate
def if_parser(constraint):
    yield match_keyword("if")
    cond = yield expr_parser(constraint)
    yield match_keyword("then")
    then_branch = yield expr_parser(constraint)
    yield match_keyword("else")
    else_branch = yield expr_parser(constraint)
    return SurfaceIf(cond, then_branch, else_branch)
```

**Tests Affected**:
- test_simple_if
- test_if_with_layout
- test_recursive_function (inside let)

---

### Phase 5: Type Abstraction Λ (MEDIUM PRIORITY)
**Problem**: Type abstractions not in parser chain
**Error**: Parser expects atom at position 9 (the `.` in `Λa.`)

**Location**: expressions.py - `type_abs_parser` exists but not used in `expr_parser`

**Current**:
```python
# type_abs_parser defined but NOT in expr_parser!
expr_parser = alt(
    lambda_parser(constraint),
    case_parser(constraint),
    let_parser(constraint),
    app_parser(constraint),
)
```

**Fix Required**:
Add to expr_parser chain with proper priority (higher than lambda):
```python
expr_parser = alt(
    type_abs_parser(constraint),  # Add this
    lambda_parser(constraint),
    case_parser(constraint),
    let_parser(constraint),
    if_parser(constraint),        # Add this too
    op_parser(constraint),        # Add this
)
```

**Tests Affected**:
- test_simple_type_abs
- test_type_abs_with_lambda

---

### Phase 6: Multi-Argument Patterns (MEDIUM PRIORITY)
**Problem**: Pattern parser only handles single arg (`Just x`), not multi (`Pair x y`)
**Error**: Parser stops after first argument, leaves unconsumed tokens

**Location**: expressions.py - `pattern_parser()`

**Current**:
```python
@generate
def pattern_parser():
    name = yield match_constructor()
    # Only tries ONE optional arg!
    arg = yield match_ident().optional()
    if arg:
        return SurfacePattern(name, [arg])
    return SurfacePattern(name, [])
```

**Fix Required**:
```python
@generate
def pattern_parser():
    name = yield match_constructor()
    # Parse ZERO or MORE identifiers
    args = yield many(match_ident())
    return SurfacePattern(name, args)
```

**Tests Affected**:
- test_case_with_pattern (Just x, Nothing)
- test_pattern_matching_with_multiple_args (Pair x y)

---

## Implementation Constraints

1. **DO NOT modify tests** - Tests are the specification
2. **DO NOT modify helpers.py** - Already complete
3. **DO NOT modify types.py** - AST is correct
4. **DO modify**:
   - `expressions.py` - Add/fix parsers
   - `declarations.py` - Fix type parser
5. **Follow existing patterns**:
   - Use `@generate` decorator
   - Use `yield` for monadic parsing
   - Return proper AST nodes from systemf.surface.types

## Testing Each Phase

After each phase, run:
```bash
cd /home/liu/Documents/bub/systemf

# Phase 1
uv run pytest tests/test_surface/test_parser/test_declarations.py::TestDataDeclaration -v

# Phase 2  
uv run pytest tests/test_surface/test_parser/test_expressions.py::TestOperatorParser -v

# Phase 3
uv run pytest tests/test_surface/test_parser/test_expressions.py::TestLetParser -v

# Phase 4
uv run pytest tests/test_surface/test_parser/test_expressions.py::TestIfParser -v

# Phase 5
uv run pytest tests/test_surface/test_parser/test_expressions.py::TestTypeAbstractionParser -v

# Phase 6
uv run pytest tests/test_surface/test_parser/test_expressions.py::TestCaseParser -v

# Final verification
uv run pytest tests/test_surface/test_parser/ -v
```

## Success Criteria

- All 63 new unit tests pass
- All 50 existing tests still pass
- Total: 113/113 tests passing
- No modifications to test files
- No modifications to helpers.py or types.py

## Notes

- **Phase 1** (type parser) is blocking many declaration tests
- **Phase 2** (operators) is blocking many expression tests  
- **Phase 3** (multiple let) requires understanding block_entries pattern
- **Phase 4-6** are additive features
- **Idris2 reference**: `upstream/idris2/src/Idris/Parser.idr` for patterns
