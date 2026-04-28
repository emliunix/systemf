# Change Plan: Add Unit Tests for elab3 rename module

## Facts

1. The rename module (`systemf/elab3/rename.py`) contains the `RenameExpr` class with methods:
   - `rename_pattern(pat: SurfacePatternBase) -> tuple[list[Name], Pat]` - renames patterns and returns bound names + renamed pattern
   - `rename_type(ty: SurfaceType) -> Ty` - renames surface types to internal Ty types

2. `RenameExpr` requires:
   - `reader_env: ReaderEnv` - for looking up global names
   - `mod_name: str` - module name for creating new names
   - `uniq: Uniq` - for generating unique IDs

3. Pattern parsing is available via:
   - `systemf.surface.parser.expressions.pattern_parser()` - returns parser object; use `pattern_parser().parse(tokens)`
   - `systemf.surface.parser.parse_expression()` - convenience function for parsing expressions
   - `systemf.surface.parser.parse_type()` - convenience function for parsing types

4. Test utilities available:
   - `systemf.utils.ast_utils.equals_ignore_location()` - compare AST nodes ignoring location
   - Existing test patterns in `tests/test_elab3/test_reader_env.py` show how to construct ReaderEnv and Names

5. Built-in names are defined in `systemf/elab3/builtins.py`:
   - `BUILTIN_TRUE`, `BUILTIN_FALSE` - boolean constructors
   - `BUILTIN_LIST_CONS`, `BUILTIN_LIST_NIL` - list constructors
   - `BUILTIN_PAIR`, `BUILTIN_PAIR_MKPAIR` - pair constructors

6. The AST types are in `systemf/elab3/ast.py`:
   - `Pat` hierarchy: `VarPat`, `ConPat`, `LitPat`
   - `Expr` hierarchy: `Var`, `Lam`, `App`, `Let`, `Ann`, `Case`, `LitExpr`

7. The types are in `systemf/elab3/types.py`:
   - `Ty` hierarchy: `TyVar`, `TyFun`, `TyForall`, `TyConApp`, `TyInt`, `TyString`
   - `Name` - unique identifier with mod, surface, unique fields

## Design

Create comprehensive unit tests for `rename_pattern` and `rename_type` methods:

### Test Structure

1. **Helper Functions**:
   - `mk_rename_expr_with_builtins(mod_name="Test", uniq_start=1000)` - factory that creates RenameExpr with ReaderEnv containing builtins imported as unqualified
   - `parse_pattern(source)` - wrapper that lexes source and parses with pattern_parser()
   - `parse_type(source)` - wrapper using parse_type() convenience function
   - `names_equal_ignore_uniq(names1, names2)` - compare name lists comparing (mod, surface) tuples, ignoring unique IDs

2. **Test Categories for `rename_pattern`**:
   - **Variable patterns**: Single identifier not in env → should create fresh Name, return VarPat
   - **Nullary constructor patterns**: Single identifier that IS in env (e.g., `True`, `False`) → should return ConPat with no args
   - **Constructor patterns with args**: Multi-item pattern (e.g., `Cons x xs`) → should return ConPat with arg patterns
   - **Tuple patterns**: `(x, y)` → should desugar to nested ConPat with BUILTIN_PAIR_MKPAIR
   - **Empty tuple pattern `()`**: Edge case for tuple patterns
   - **Single-element tuple `(x,)`**: Desugaring edge case
   - **Cons patterns**: `x : xs` → should desugar to ConPat with BUILTIN_LIST_CONS
   - **Literal patterns**: `42`, `"hello"` → should return LitPat
   - **Wildcard pattern `_`**: Should return DefaultPat (exists in ast.py)
   - **Nested patterns**: `Cons (Pair x y) zs`, `Cons (Cons x xs) ys` → should handle nested structure correctly
   - **Local name shadowing**: Variable pattern can shadow global constructor name
   - **Error cases**: Duplicate variable names, unresolved constructors

3. **Test Categories for `rename_type`**:
   - **Type variables**: `a`, `b` → should return BoundTv with Name
   - **Function types**: `Int -> String` → should return TyFun
   - **Forall types**: `forall a. a -> a` → should return TyForall with bound var
   - **Nested forall**: `forall a. forall b. a -> b -> a` (higher-rank types)
   - **Constructor types**: `Bool`, `List Int` → should return TyConApp
   - **Type constructor with multiple args**: `Pair Int String`
   - **Builtin types**: `Int`, `String` → should return TyInt, TyString
   - **Tuple types**: `(Int, String)` → should desugar to nested TyConApp with BUILTIN_PAIR
   - **Polymorphic function types**: `(forall a. a -> a) -> Int`

4. **Test Environment Setup**:
   - Create ReaderEnv with builtins imported (is_qual=False)
   - Import builtins as unqualified so `True`, `False`, `Cons` are accessible
   - Use `Uniq(start=1000)` to avoid conflicts with builtin uniques (which go up to 1000)
   - RenameExpr manages its own Uniq reference - tests use the same instance passed to constructor

### Comparison Strategy

- For AST comparison: use `equals_ignore_location()` to ignore location differences
- For Name comparison in patterns: compare (mod, surface) tuples, ignore unique IDs
- For bound variable lists: verify the right number of names are returned with correct surface names

## Files

- **New file**: `tests/test_elab3/test_rename.py` - main test file with all test cases

## Why It Works

1. **Isolated testing**: Each test creates its own RenameExpr with controlled environment, avoiding interference between tests.

2. **Realistic environment**: Using actual builtins module means tests verify real-world rename behavior with known constructors.

3. **Comprehensive coverage**: Tests cover all pattern and type forms, including edge cases like nested patterns, wildcards, higher-rank types.

4. **Clear assertions**: Using structural comparison helpers makes tests readable and focused on semantics not syntax.

5. **Maintainable structure**: Template functions allow easy addition of new test cases following established patterns.

## Test Examples

```python
"""Tests for elab3 rename module.

Tests rename_pattern and rename_type methods of RenameExpr class.
"""

import pytest
from parsy import eof

from systemf.elab3.rename import RenameExpr
from systemf.elab3.builtins import (
    BUILTIN_TRUE, BUILTIN_FALSE, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
    BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR
)
from systemf.elab3.reader_env import ReaderEnv, ImportRdrElt, ImportSpec
from systemf.elab3.types import Name, BoundTv, TyFun, TyForall, TyInt, TyString, TyConApp, TyVar
from systemf.elab3.ast import VarPat, ConPat, LitPat, DefaultPat
from systemf.utils.uniq import Uniq
from systemf.utils.location import Location
from systemf.utils.ast_utils import equals_ignore_location
from systemf.surface.parser import lex, parse_type
from systemf.surface.parser.expressions import pattern_parser


def mk_rename_expr_with_builtins(mod_name: str = "Test", uniq_start: int = 1000) -> RenameExpr:
    """Create RenameExpr with builtins imported as unqualified.
    
    Args:
        mod_name: Module name for new names
        uniq_start: Starting unique ID to avoid conflicts with builtins (which go up to 1000)
    
    Returns:
        RenameExpr configured with builtins in reader_env
    """
    uniq = Uniq(uniq_start)
    
    # Create import specs for builtins (unqualified import)
    spec = ImportSpec(module_name="builtins", alias=None, is_qual=False)
    
    # Add builtin constructors to reader env
    builtins = [
        BUILTIN_TRUE, BUILTIN_FALSE,
        BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
        BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR,
    ]
    
    elts = [ImportRdrElt.create(name, spec) for name in builtins]
    reader_env = ReaderEnv.from_elts(elts)
    
    return RenameExpr(reader_env, mod_name, uniq)


def parse_pattern(source: str):
    """Parse pattern text to SurfacePatternBase.
    
    Args:
        source: Pattern source code (e.g., "Cons x xs")
    
    Returns:
        Parsed SurfacePatternBase (SurfacePattern, SurfacePatternTuple, or SurfacePatternCons)
    """
    tokens = list(lex(source))
    return (pattern_parser() << eof).parse(tokens)


def names_equal_ignore_uniq(names1: list[Name], names2: list[Name]) -> bool:
    """Compare two lists of names ignoring unique IDs.
    
    Compares (mod, surface) tuples since unique IDs are generated fresh.
    """
    if len(names1) != len(names2):
        return False
    for n1, n2 in zip(names1, names2):
        if (n1.mod, n1.surface) != (n2.mod, n2.surface):
            return False
    return True


# =============================================================================
# Pattern Tests (Structural Comparison Style)
# =============================================================================

def test_rename_pattern_variable_not_in_env():
    """Variable not in reader env becomes VarPat with fresh Name."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("x")
    names, rn_pat = renamer.rename_pattern(pat)
    
    # Build expected names list (mod and surface, ignoring unique)
    expected_names = [Name(mod="Test", surface="x", unique=-1)]
    assert names_equal_ignore_uniq(names, expected_names)
    
    # Build expected pattern and compare
    expected_pat = VarPat(name=Name(mod="Test", surface="x", unique=-1))
    assert equals_ignore_location(rn_pat, expected_pat)


def test_rename_pattern_nullary_constructor():
    """Single identifier that IS in env (True) becomes ConPat."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("True")
    names, rn_pat = renamer.rename_pattern(pat)
    
    # Build expected names list (empty - no variables bound)
    expected_names = []
    assert names_equal_ignore_uniq(names, expected_names)
    
    # Build expected pattern and compare
    expected_pat = ConPat(con=BUILTIN_TRUE, args=[])
    assert equals_ignore_location(rn_pat, expected_pat)


def test_rename_pattern_constructor_with_args():
    """Multi-item pattern becomes ConPat with arg patterns."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("Cons x xs")
    names, rn_pat = renamer.rename_pattern(pat)
    
    # Build expected names list (bound variables: x, xs)
    expected_names = [
        Name(mod="Test", surface="x", unique=-1),
        Name(mod="Test", surface="xs", unique=-1),
    ]
    assert names_equal_ignore_uniq(names, expected_names)
    
    # Build expected pattern structure
    expected_pat = ConPat(
        con=BUILTIN_LIST_CONS,
        args=[
            VarPat(name=Name(mod="Test", surface="x", unique=-1)),
            VarPat(name=Name(mod="Test", surface="xs", unique=-1)),
        ]
    )
    assert equals_ignore_location(rn_pat, expected_pat)


def test_rename_pattern_nullary_constructor_lookup():
    """Single identifier in env becomes ConPat (disambiguation via env lookup).
    
    Tests that the rename phase correctly distinguishes between variables
    and constructors by checking the reader environment.
    """
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("True")
    
    names, rn_pat = renamer.rename_pattern(pat)
    
    # Build expected names list (empty - constructor, not variable)
    expected_names = []
    assert names_equal_ignore_uniq(names, expected_names)
    
    # Build expected pattern and compare
    expected_pat = ConPat(con=BUILTIN_TRUE, args=[])
    assert equals_ignore_location(rn_pat, expected_pat)


# =============================================================================
# Type Tests (Structural Comparison Style)
# =============================================================================

def test_rename_type_variable():
    """Type variable becomes BoundTv with Name."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("a")
    rn_ty = renamer.rename_type(ty)
    
    # Build expected type: BoundTv with Name for 'a'
    # Note: type variables get fresh names during rename
    expected_ty = BoundTv(name=Name(mod="Test", surface="a", unique=-1))
    assert equals_ignore_location(rn_ty, expected_ty)


def test_rename_type_function():
    """Function type becomes TyFun."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("Int -> String")
    rn_ty = renamer.rename_type(ty)
    
    # Build expected type structure
    expected_ty = TyFun(arg=TyInt(), ret=TyString())
    assert equals_ignore_location(rn_ty, expected_ty)


def test_rename_type_forall():
    """Forall type binds variable and returns TyForall."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("forall a. a -> a")
    rn_ty = renamer.rename_type(ty)
    
    assert isinstance(rn_ty, TyForall)
    assert len(rn_ty.bound) == 1
    assert isinstance(rn_ty.bound[0], BoundTv)
    assert isinstance(rn_ty.body, TyFun)
```

## Additional Tests to Add

The examples above show the pattern. Additional tests should follow the same structure:

### Pattern Tests (following the examples):
- **Tuple pattern**: `(x, y)` → desugars to nested ConPat with BUILTIN_PAIR_MKPAIR
- **Cons pattern**: `x : xs` → ConPat with BUILTIN_LIST_CONS
- **Literal patterns**: `42`, `"hello"` → LitPat
- **Wildcard pattern**: `_` → DefaultPat (from ast.py)
- **Nested patterns**: `Cons (Pair x y) zs`, `Cons (Cons x xs) ys` → verify recursion
- **Duplicate variable error**: `Cons x x` → should raise exception

### Type Tests (following the examples):
- **Nested forall**: `forall a. forall b. a -> b -> a` → higher-rank types
- **Type constructor with args**: `Pair Int String` → TyConApp
- **Tuple types**: `(Int, String)` → nested TyConApp with BUILTIN_PAIR
- **Polymorphic function types**: `(forall a. a -> a) -> Int`
