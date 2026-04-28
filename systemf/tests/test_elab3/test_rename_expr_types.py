"""Tests for elab3 rename module.

Tests rename_pattern and rename_type methods of RenameExpr class.
Uses structural comparison with structural_equals for AST nodes.
"""

import pytest
from parsy import eof

from systemf.elab3.rename_expr import RenameExpr
from systemf.elab3.name_gen import NameGeneratorImpl
from systemf.elab3.builtins import (
    BUILTIN_TRUE, BUILTIN_FALSE, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
    BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR
)
from systemf.elab3.reader_env import ReaderEnv, ImportRdrElt, ImportSpec
from systemf.elab3.types.ty import Name, BoundTv, TyFun, TyForall, TyInt, TyString, TyConApp
from systemf.elab3.types.ast import VarPat, ConPat, LitPat
from systemf.utils.uniq import Uniq
from systemf.utils.location import Location
from systemf.utils.ast_utils import structural_equals
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
    name_gen = NameGeneratorImpl(mod_name, uniq)
    
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
    
    return RenameExpr(reader_env, mod_name, name_gen)


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
    assert structural_equals(rn_pat, expected_pat)


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
    assert structural_equals(rn_pat, expected_pat)


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
    assert structural_equals(rn_pat, expected_pat)


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
    assert structural_equals(rn_pat, expected_pat)


# =============================================================================
# Type Tests (Structural Comparison Style)
# =============================================================================

def test_rename_type_variable_fails_for_free_var():
    """Free type variable (not bound by forall) correctly raises error.
    
    In System F, type variables must be bound by forall. A bare type variable
    like 'a' is invalid and should fail during rename.
    """
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("a")
    
    with pytest.raises(Exception) as exc_info:
        renamer.rename_type(ty)
    
    assert "unresolved variable" in str(exc_info.value)
    assert "a" in str(exc_info.value)


def test_rename_type_function():
    """Function type becomes TyFun."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("Int -> String")
    rn_ty = renamer.rename_type(ty)
    
    # Build expected type structure
    expected_ty = TyFun(arg=TyInt(), result=TyString())
    assert structural_equals(rn_ty, expected_ty)


def test_rename_type_forall():
    """Forall type binds variable and returns TyForall."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("forall a. a -> a")
    rn_ty = renamer.rename_type(ty)

    assert isinstance(rn_ty, TyForall)
    assert len(rn_ty.vars) == 1
    assert isinstance(rn_ty.vars[0], BoundTv)

    # Check that both occurrences of 'a' have the same unique ID
    bound_a = rn_ty.vars[0]
    assert isinstance(rn_ty.body, TyFun)
    arg_a = rn_ty.body.arg
    result_a = rn_ty.body.result
    assert isinstance(arg_a, BoundTv)
    assert isinstance(result_a, BoundTv)
    assert arg_a.name.unique == bound_a.name.unique
    assert result_a.name.unique == bound_a.name.unique


# =============================================================================
# Additional Pattern Tests (Round 2)
# =============================================================================

def test_rename_pattern_tuple():
    """Tuple pattern (x, y) desugars to ConPat with BUILTIN_PAIR_MKPAIR."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("(x, y)")
    names, rn_pat = renamer.rename_pattern(pat)
    
    # Build expected names list (bound variables: x, y)
    expected_names = [
        Name(mod="Test", surface="x", unique=-1),
        Name(mod="Test", surface="y", unique=-1),
    ]
    assert names_equal_ignore_uniq(names, expected_names)
    
    # Build expected pattern structure
    expected_pat = ConPat(
        con=BUILTIN_PAIR_MKPAIR,
        args=[
            VarPat(name=Name(mod="Test", surface="x", unique=-1)),
            VarPat(name=Name(mod="Test", surface="y", unique=-1)),
        ]
    )
    assert structural_equals(rn_pat, expected_pat)


def test_rename_pattern_cons():
    """Cons pattern x : xs becomes ConPat with BUILTIN_LIST_CONS."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("x : xs")
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
    assert structural_equals(rn_pat, expected_pat)


def test_rename_pattern_nested():
    """Nested pattern Cons (Cons x xs) ys tests recursive descent."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("Cons (Cons x xs) ys")
    names, rn_pat = renamer.rename_pattern(pat)

    # Build expected names list (bound variables: x, xs, ys)
    expected_names = [
        Name(mod="Test", surface="x", unique=-1),
        Name(mod="Test", surface="xs", unique=-1),
        Name(mod="Test", surface="ys", unique=-1),
    ]
    assert names_equal_ignore_uniq(names, expected_names)

    # Build expected nested pattern structure
    expected_pat = ConPat(
        con=BUILTIN_LIST_CONS,
        args=[
            ConPat(
                con=BUILTIN_LIST_CONS,
                args=[
                    VarPat(name=Name(mod="Test", surface="x", unique=-1)),
                    VarPat(name=Name(mod="Test", surface="xs", unique=-1)),
                ]
            ),
            VarPat(name=Name(mod="Test", surface="ys", unique=-1)),
        ]
    )
    assert structural_equals(rn_pat, expected_pat)

    # Check that VarPat unique IDs match the names list
    # rn_pat is ConPat(Cons, [inner_ConPat, VarPat(ys)])
    inner_conpat = rn_pat.args[0]  # ConPat(Cons, [VarPat(x), VarPat(xs)])
    varpat_x = inner_conpat.args[0]  # VarPat(x)
    varpat_xs = inner_conpat.args[1]  # VarPat(xs)
    varpat_ys = rn_pat.args[1]  # VarPat(ys)

    assert varpat_x.name.unique == names[0].unique  # x
    assert varpat_xs.name.unique == names[1].unique  # xs
    assert varpat_ys.name.unique == names[2].unique  # ys


def test_rename_pattern_duplicate_var_error():
    """Duplicate variable names in pattern should raise exception."""
    renamer = mk_rename_expr_with_builtins()
    pat = parse_pattern("Cons x x")
    
    with pytest.raises(Exception, match="duplicate param names: x"):
        renamer.rename_pattern(pat)


# =============================================================================
# Additional Type Tests (Round 2)
# =============================================================================

def test_rename_type_higher_rank():
    """Higher-rank type forall a. forall b. a -> b -> a nests TyForall."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("forall a. forall b. a -> b -> a")
    rn_ty = renamer.rename_type(ty)

    assert isinstance(rn_ty, TyForall)
    assert len(rn_ty.vars) == 1
    assert isinstance(rn_ty.vars[0], BoundTv)
    outer_a = rn_ty.vars[0]

    # Inner forall
    inner = rn_ty.body
    assert isinstance(inner, TyForall)
    assert len(inner.vars) == 1
    assert isinstance(inner.vars[0], BoundTv)
    inner_b = inner.vars[0]

    # Function type inside: a -> b -> a
    assert isinstance(inner.body, TyFun)
    arg_a = inner.body.arg
    rest = inner.body.result
    assert isinstance(arg_a, BoundTv)
    assert isinstance(rest, TyFun)
    arg_b = rest.arg
    result_a = rest.result
    assert isinstance(arg_b, BoundTv)
    assert isinstance(result_a, BoundTv)

    # Check that all 'a' occurrences have the same unique ID
    assert arg_a.name.unique == outer_a.name.unique
    assert result_a.name.unique == outer_a.name.unique

    # Check that 'b' has consistent unique ID
    assert arg_b.name.unique == inner_b.name.unique


def test_rename_type_constructor_app():
    """Type constructor application Pair Int String becomes TyConApp."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("Pair Int String")
    rn_ty = renamer.rename_type(ty)
    
    # Build expected type structure
    expected_ty = TyConApp(
        name=BUILTIN_PAIR,
        args=[TyInt(), TyString()]
    )
    assert structural_equals(rn_ty, expected_ty)


def test_rename_type_tuple():
    """Tuple type (Int, String) desugars to TyConApp with BUILTIN_PAIR."""
    renamer = mk_rename_expr_with_builtins()
    ty = parse_type("(Int, String)")
    rn_ty = renamer.rename_type(ty)
    
    # Build expected type structure
    expected_ty = TyConApp(
        name=BUILTIN_PAIR,
        args=[TyInt(), TyString()]
    )
    assert structural_equals(rn_ty, expected_ty)
