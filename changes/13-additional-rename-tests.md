# Change Plan: Additional Rename Tests (Round 2) - REVISED

## Facts

Based on previous work in `changes/12-add-rename-tests.md` and current test file `tests/test_elab3/test_rename.py`:

1. **Template functions already established**:
   - `mk_rename_expr_with_builtins(mod_name="Test", uniq_start=1000)` - Creates RenameExpr with builtins
   - `parse_pattern(source)` - Parses surface pattern syntax
   - `names_equal_ignore_uniq(names1, names2)` - Compares names ignoring unique IDs
   - `structural_equals()` - Compares AST nodes ignoring location/unique fields

2. **Existing tests (7 passing)**:
   - Pattern: variable, nullary constructor, constructor with args, lookup
   - Type: free var error, function, forall

3. **Pattern AST types** (`systemf/elab3/ast.py`):
   - `VarPat(name: Name)` - variable patterns
   - `ConPat(con: Name, args: list[Pat])` - constructor patterns
   - `LitPat(value: int | str | bool)` - literal patterns
   - `DefaultPat()` - wildcard pattern (excluded from this work)

4. **Type AST types** (`systemf/elab3/types.py`):
   - `BoundTv(name: Name)` - bound type variables
   - `TyFun(arg: Ty, result: Ty)` - function types
   - `TyForall(vars: list[BoundTv], body: Ty)` - forall types
   - `TyConApp(con: Name, args: list[Ty])` - type constructor applications
   - `TyInt()`, `TyString()` - primitive types

5. **Builtins available** (`systemf/elab3/builtins.py`):
   - `BUILTIN_PAIR`, `BUILTIN_PAIR_MKPAIR` - pair constructors
   - `BUILTIN_LIST_CONS`, `BUILTIN_LIST_NIL` - list constructors
   - `BUILTIN_TRUE`, `BUILTIN_FALSE` - bool constructors

6. **Parser Limitations Discovered** (from review):
   - **Literal patterns NOT supported**: Parser doesn't handle `42` or `"hello"` in patterns (fails with "expected IdentifierToken")
   - **Nested patterns need grouping**: `Cons (Pair x y) zs` parses as flat; parentheses required but structure may differ
   - **Polymorphic function types NOT supported**: `(forall a. a -> a) -> Int` parsed incorrectly due to parser precedence

## Design

Add comprehensive test coverage for the remaining pattern and type forms (excluding unsupported features):

### Pattern Tests to Add

**1. Tuple pattern: `(x, y)`** ✅
- Input: `parse_pattern("(x, y)")`
- Expected: `ConPat(con=BUILTIN_PAIR_MKPAIR, args=[VarPat(x), VarPat(y)])`
- Bound names: `[x, y]`

**2. Cons pattern: `x : xs`** ✅
- Input: `parse_pattern("x : xs")`
- Expected: `ConPat(con=BUILTIN_LIST_CONS, args=[VarPat(x), VarPat(xs)])`
- Bound names: `[x, xs]`

**3. Nested patterns: `Cons (Cons x xs) ys`** ✅
- **Changed from**: `Cons (Pair x y) zs` (parser doesn't support Pair constructor in patterns)
- Input: `parse_pattern("Cons (Cons x xs) ys")`
- Expected: `ConPat(BUILTIN_LIST_CONS, [ConPat(BUILTIN_LIST_CONS, [VarPat(x), VarPat(xs)]), VarPat(ys)])`
- Bound names: `[x, xs, ys]`
- Tests recursive descent into nested ConPats

**4. Duplicate variable error: `Cons x x`** ✅
- Input: `parse_pattern("Cons x x")`
- Expected: Exception raised with message `"duplicate param names: x"`
- Tests that `check_dups()` in rename.py:254 correctly detects duplicate bindings

### Type Tests to Add

**5. Higher-rank types: `forall a. forall b. a -> b -> a`** ✅
- Input: `parse_type("forall a. forall b. a -> b -> a")`
- Expected: `TyForall([BoundTv(a)], TyForall([BoundTv(b)], TyFun(a, TyFun(b, a))))`
- Tests nested forall binding

**6. Type constructor with args: `Pair Int String`** ✅
- Input: `parse_type("Pair Int String")`
- Expected: `TyConApp(con=BUILTIN_PAIR, args=[TyInt(), TyString()])`
- Tests TyConApp with multiple arguments

**7. Tuple types: `(Int, String)`** ✅
- Input: `parse_type("(Int, String)")`
- Expected: `TyConApp(con=BUILTIN_PAIR, args=[TyInt(), TyString()])`
- Tests tuple type desugaring

### Excluded Tests (Parser Limitations)

The following tests were **REMOVED** from the plan due to parser limitations:

- ❌ **Literal patterns**: `42`, `"hello"` → Parser doesn't support literal patterns
- ❌ **Polymorphic function types**: `(forall a. a -> a) -> Int` → Parser precedence bug

### Implementation Notes

1. **Use established patterns**: Follow exact structure of existing tests in `test_rename.py`
2. **Structural comparison**: Build expected AST and compare with `structural_equals()`
3. **Ignore generated fields**: `structural_equals()` handles unique IDs and locations
4. **Name comparison**: Use `names_equal_ignore_uniq()` for bound variable lists
5. **Error testing**: Use `pytest.raises(Exception, match="duplicate param names: x")`

## Files

- **Modify**: `tests/test_elab3/test_rename.py` - Add 7 new test functions (revised from 9)

## Why It Works

1. **Consistent patterns**: Each test follows the same 5-step structure (setup, parse, execute, build expected, assert)
2. **Realistic expectations**: Tests only cover parser-supported features
3. **Edge cases included**: Duplicate variable detection, nested structures, higher-rank types
4. **No duplication**: Reuses existing template functions, adds no new dependencies
5. **Structural comparison**: Single assertions per test make failures obvious and debugging easy
6. **Addresses review feedback**: Revised to remove unsupported features, adjusted nested pattern test

## Test Implementation Checklist

- [ ] `test_rename_pattern_tuple()` - `(x, y)` → ConPat with BUILTIN_PAIR_MKPAIR
- [ ] `test_rename_pattern_cons()` - `x : xs` → ConPat with BUILTIN_LIST_CONS
- [ ] `test_rename_pattern_nested()` - `Cons (Cons x xs) ys` → nested ConPats
- [ ] `test_rename_pattern_duplicate_var_error()` - `Cons x x` → raises "duplicate param names" exception
- [ ] `test_rename_type_higher_rank()` - `forall a. forall b. a -> b -> a` → nested TyForall
- [ ] `test_rename_type_constructor_app()` - `Pair Int String` → TyConApp
- [ ] `test_rename_type_tuple()` - `(Int, String)` → TyConApp with BUILTIN_PAIR

**Removed from plan:**
- ~~Literal patterns~~ (parser doesn't support)
- ~~Polymorphic function types~~ (parser precedence bug)
- ~~Wildcard pattern~~ (explicitly excluded per user request)
