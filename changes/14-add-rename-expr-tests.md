# Change Plan: Add Tests for RenameExpr.rename_expr

## Status: Ready for Review

Created test file `tests/test_elab3/test_rename_expr.py` with comprehensive tests for the `RenameExpr.rename_expr` method.

## Facts

1. `RenameExpr.rename_expr(self, ast: SurfaceTerm) -> Expr` is defined at `systemf/elab3/rename.py:125` and handles expression renaming

2. Expression forms handled by rename_expr:
   - `SurfaceVar` → `Var` - variable references with reader env lookup
   - `SurfaceLit` → `LitExpr` - integer/string literals
   - `SurfaceAbs` → `Lam` - lambda abstraction with args (list[Name | AnnotName])
   - `SurfaceApp` → `App` - function application
   - `SurfaceLet` → `Let` - let bindings with recursive env extension
   - `SurfaceAnn` → `Ann` - type annotation (fields: `expr`, `ty`)
   - `SurfaceIf` → `Case` - if-then-else desugars to case on True/False
   - `SurfaceOp` → `App(App(Var(op), left), right)` - binary operators
   - `SurfaceTuple` → nested `App(App(Var(BUILTIN_PAIR_MKPAIR), ...))` - tuple construction
   - `SurfaceCase` → `Case` with branches - pattern matching

3. AST types in `systemf/elab3/ast.py`:
   - `Lam` has field `args: list[Name | AnnotName]` (not `params`)
   - `AnnotName` has fields `name: Name` and `type_ann: Ty` (not `type`)
   - `CaseBranch` has fields `pattern: Pat` and `body: Expr` (not `pat`)
   - `Ann` has fields `expr: Expr` and `ty: Ty` (not `term` and `type`)
   - `LitExpr` has field `lit: Lit` (use `LitInt`/`LitString` for `.value`)

4. Surface parsing via `systemf.surface.parser.parse_expression(source: str)`

5. Built-in operators in `systemf/elab3/builtins.BUILTIN_BIN_OPS`:
   - Maps operator strings (e.g., "+") to `Name` objects

6. Structural comparison via `systemf.utils.ast_utils.structural_equals()`
   - Ignores `location`, `source_loc`, `unique`, `loc` fields

## Design

Created comprehensive tests following the structural comparison style from `docs/styles/testing-structural.md`:

### Template Functions

- `mk_rename_expr_with_builtins()` - Creates RenameExpr with builtins imported
- `parse_expr()` - Wrapper for parse_expression()

### Test Coverage

**Variable and Literal Tests:**
- Variable reference (local env lookup)
- Integer literals
- String literals

**Lambda Tests:**
- Simple lambda `\x -> x`
- Annotated lambda `\(x: Int) -> x`
- Multiple params `\x y -> x`
- Nested lambdas `\x -> \y -> x`

**Application Tests:**
- Simple application `f x`
- Nested application `f x y` (left-associative)

**Let Tests:**
- Simple let `let x = 1 in x`
- Annotated let `let x: Int = 1 in x`
- Multiple bindings `let x = 1; y = 2 in x + y`
- Mutual recursion `let x = y; y = 1 in x`

**Type Annotation:**
- Annotation `1 :: Int`

**If-Then-Else (Desugaring):**
- If-then-else desugars to case on True/False

**Binary Operators:**
- Operator desugaring `x + y`

**Tuple (Desugaring):**
- Pair `(1, 2)` desugars to nested App with BUILTIN_PAIR_MKPAIR
- Triple `(1, 2, 3)`

**Case Expressions:**
- Simple case expression

**Error Cases:**
- Unresolved variable
- Unknown operator

**Shadowing Tests:**
- Lambda param shadows outer binding
- Let binding shadows outer binding

## Files

- **New file**: `tests/test_elab3/test_rename_expr.py` - 19 test functions

## Key Implementation Details

1. **Type narrowing required**: `Name | AnnotName` union types need explicit `isinstance()` checks
2. **Field names matter**: 
   - `Lam.args` not `Lam.params`
   - `AnnotName.type_ann` not `AnnotName.type`
   - `CaseBranch.pattern` not `CaseBranch.pat`
   - `Ann.expr/ty` not `Ann.term/type`
3. **Lit types**: `Lit` is abstract; narrow to `LitInt`/`LitString` to access `.value`
4. **Operator availability**: Some operators may not be in BUILTIN_BIN_OPS; tests check before using

## Test Execution

Run tests with:
```bash
cd /home/liu/Documents/bub/systemf
uv run pytest tests/test_elab3/test_rename_expr.py -v
```

## Why It Works

1. **Follows established patterns**: Reuses template functions and structural comparison from test_rename.py
2. **Comprehensive coverage**: Tests all expression forms handled by rename_expr
3. **Proper type narrowing**: Handles union types correctly with isinstance checks
4. **Desugaring verification**: Confirms if-then-else, tuples, and operators desugar correctly
5. **Environment testing**: Verifies local env extension and lookup work correctly
6. **Error cases**: Tests that invalid inputs raise appropriate errors
