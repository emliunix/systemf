"""Tests for RenameExpr.rename_expr method.

Tests expression renaming with structural comparison.
Uses the structural comparison style from docs/styles/testing-structural.md.

NOTE: Some tests are skipped due to parser limitations (not bugs):
- Unknown operators: lexer rejects $ and other unknown operators

The bugs that were previously blocking tests have been fixed:
✅ Literal types: parser produces "Int"/"String", renamer normalizes to lowercase
✅ Let expressions: parser returns ValBind objects, all downstream passes updated
"""

import pytest
from parsy import eof

from systemf.elab3.rename_expr import RenameExpr
from systemf.elab3.name_gen import NameGeneratorImpl
from systemf.elab3.builtins import (
    BUILTIN_TRUE, BUILTIN_FALSE, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
    BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR, BUILTIN_BIN_OPS
)
from systemf.elab3.reader_env import ReaderEnv, ImportRdrElt, ImportSpec, RdrElt
from systemf.elab3.types.ty import Name, TyInt, TyString, BoundTv, TyFun, TyForall, LitInt, LitString
from systemf.elab3.types.ast import (
    Var, Lam, App, Let, Ann, LitExpr, Case, CaseBranch, ConPat, VarPat,
    Binding, AnnotName
)
from systemf.utils.uniq import Uniq
from systemf.utils.location import Location
from systemf.utils.ast_utils import structural_equals
from systemf.surface.parser import parse_expression


def mk_rename_expr_with_builtins(mod_name: str = "Test", uniq_start: int = 1000) -> RenameExpr:
    """Create RenameExpr with builtins imported as unqualified.
    
    Args:
        mod_name: Module name for new names
        uniq_start: Starting unique ID to avoid conflicts with builtins
    
    Returns:
        RenameExpr configured with builtins in reader_env
    """
    uniq = Uniq(uniq_start)
    name_gen = NameGeneratorImpl(mod_name, uniq)
    spec = ImportSpec(module_name="builtins", alias=None, is_qual=False)
    
    # Import True, False for if-then-else tests, plus operators
    builtins = [BUILTIN_TRUE, BUILTIN_FALSE, BUILTIN_PAIR_MKPAIR]
    # Add binary operators that are Name objects
    for op_name in BUILTIN_BIN_OPS.values():
        if isinstance(op_name, Name) and op_name not in builtins:
            builtins.append(op_name)
    
    elts: list[RdrElt] = [ImportRdrElt.create(name, spec) for name in builtins]
    reader_env = ReaderEnv.from_elts(elts)
    return RenameExpr(reader_env, mod_name, name_gen)


def parse_expr(source: str):
    """Parse expression text to SurfaceTerm.
    
    Args:
        source: Expression source code (e.g., "\\x -> x")
    
    Returns:
        Parsed SurfaceTerm
    """
    return parse_expression(source)


# =============================================================================
# Variable and Literal Tests
# =============================================================================

def test_rename_expr_variable():
    """Variable reference becomes Var with looked-up Name."""
    renamer = mk_rename_expr_with_builtins()
    
    # Create a local binding for x
    x_name = renamer.name_gen.new_name("x", None)
    renamer.local_env.append(("x", x_name))
    
    expr = parse_expr("x")
    rn_expr = renamer.rename_expr(expr)
    
    expected = Var(name=x_name)
    assert structural_equals(rn_expr, expected)


def test_rename_expr_literal_int():
    """Integer literal becomes LitExpr with LitInt."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("42")
    rn_expr = renamer.rename_expr(expr)
    
    expected = LitExpr(lit=LitInt(value=42))
    assert structural_equals(rn_expr, expected)


def test_rename_expr_literal_string():
    """String literal becomes LitExpr with LitString."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr('"hello"')
    rn_expr = renamer.rename_expr(expr)
    
    expected = LitExpr(lit=LitString(value="hello"))
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Lambda Tests
# =============================================================================

def test_rename_expr_lambda_simple():
    """Lambda \\x -> x creates Lam with param and body referencing bound var."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\x -> x")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure - param and body reference same name
    expected_param = Name(mod="Test", surface="x", unique=-1)
    expected = Lam(
        args=[expected_param],
        body=Var(name=expected_param)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_lambda_annotated():
    """Lambda with type annotation \\(x :: Int) -> x."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\(x :: Int) -> x")
    rn_expr = renamer.rename_expr(expr)
    
    expected_param = AnnotName(
        name=Name(mod="Test", surface="x", unique=-1),
        type_ann=TyInt()
    )
    expected = Lam(
        args=[expected_param],
        body=Var(name=expected_param.name)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_lambda_multiple_params():
    """Lambda with multiple params \\x y -> x."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\x y -> x")
    rn_expr = renamer.rename_expr(expr)
    
    x_param = Name(mod="Test", surface="x", unique=-1)
    y_param = Name(mod="Test", surface="y", unique=-1)
    expected = Lam(
        args=[x_param, y_param],
        body=Var(name=x_param)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_lambda_nested():
    """Nested lambdas \\x -> \\y -> x with proper scoping."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("\\x -> \\y -> x")
    rn_expr = renamer.rename_expr(expr)
    
    x_param = Name(mod="Test", surface="x", unique=-1)
    y_param = Name(mod="Test", surface="y", unique=-1)
    expected = Lam(
        args=[x_param],
        body=Lam(
            args=[y_param],
            body=Var(name=x_param)
        )
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Application Tests
# =============================================================================

def test_rename_expr_application():
    """Application f x becomes App(Var(f), Var(x))."""
    renamer = mk_rename_expr_with_builtins()
    
    # Create local bindings
    f_name = renamer.name_gen.new_name("f", None)
    x_name = renamer.name_gen.new_name("x", None)
    renamer.local_env.extend([("f", f_name), ("x", x_name)])
    
    expr = parse_expr("f x")
    rn_expr = renamer.rename_expr(expr)
    
    expected = App(func=Var(name=f_name), arg=Var(name=x_name))
    assert structural_equals(rn_expr, expected)


def test_rename_expr_application_nested():
    """Nested application f x y becomes App(App(Var(f), Var(x)), Var(y))."""
    renamer = mk_rename_expr_with_builtins()
    
    f_name = Name(mod="Test", surface="f", unique=-1)
    x_name = Name(mod="Test", surface="x", unique=-1)
    y_name = Name(mod="Test", surface="y", unique=-1)
    renamer.local_env.extend([("f", f_name), ("x", x_name), ("y", y_name)])
    
    expr = parse_expr("f x y")
    rn_expr = renamer.rename_expr(expr)
    
    expected = App(
        func=App(
            func=Var(name=f_name),
            arg=Var(name=x_name)
        ),
        arg=Var(name=y_name)
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Let Tests (all skipped due to parser/renamer mismatch)
# =============================================================================

def test_rename_expr_let_simple():
    """Let binding let x = 1 in x."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("let x = 1 in x")
    rn_expr = renamer.rename_expr(expr)
    
    x_name = Name(mod="Test", surface="x", unique=-1)
    expected = Let(
        bindings=[Binding(name=x_name, expr=LitExpr(lit=LitInt(value=1)))],
        body=Var(name=x_name)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_let_annotated():
    """Let with type annotation let x :: Int = 1 in x."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("let x :: Int = 1 in x")
    rn_expr = renamer.rename_expr(expr)
    
    x_annot = AnnotName(
        name=Name(mod="Test", surface="x", unique=-1),
        type_ann=TyInt()
    )
    expected = Let(
        bindings=[Binding(name=x_annot, expr=LitExpr(lit=LitInt(value=1)))],
        body=Var(name=x_annot.name)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_let_multiple():
    """Multiple let bindings via layout."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("""let
  x = 1
  y = 2
in x + y""")
    rn_expr = renamer.rename_expr(expr)
    
    x_name = Name(mod="Test", surface="x", unique=-1)
    y_name = Name(mod="Test", surface="y", unique=-1)
    
    # The body is x + y which desugars to App(App(Var(+), Var(x)), Var(y))
    # We just check structure without full expansion
    expected = Let(
        bindings=[
            Binding(name=x_name, expr=LitExpr(lit=LitInt(value=1))),
            Binding(name=y_name, expr=LitExpr(lit=LitInt(value=2)))
        ],
        body=App(
            func=App(
                func=Var(name=BUILTIN_BIN_OPS["+"]),
                arg=Var(name=x_name)
            ),
            arg=Var(name=y_name)
        )
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_let_mutual():
    """Mutually recursive let bindings share environment."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("""let
  x = y
  y = 1
in x""")
    rn_expr = renamer.rename_expr(expr)
    
    x_name = Name(mod="Test", surface="x", unique=-1)
    y_name = Name(mod="Test", surface="y", unique=-1)
    
    expected = Let(
        bindings=[
            Binding(name=x_name, expr=Var(name=y_name)),
            Binding(name=y_name, expr=LitExpr(lit=LitInt(value=1)))
        ],
        body=Var(name=x_name)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_annotation():
    """Type annotation 1 :: Int becomes Ann(LitExpr(1), TyInt())."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("1 :: Int")
    rn_expr = renamer.rename_expr(expr)
    
    expected = Ann(
        expr=LitExpr(lit=LitInt(value=1)),
        ty=TyInt()
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# If-Then-Else Tests (Desugaring)
# =============================================================================

def test_rename_expr_if_then_else():
    """If-then-else desugars to case on True/False."""
    renamer = mk_rename_expr_with_builtins()
    
    # Create local bindings
    cond_name = Name(mod="Test", surface="cond", unique=-1)
    then_name = Name(mod="Test", surface="then_branch", unique=-1)
    else_name = Name(mod="Test", surface="else_branch", unique=-1)
    renamer.local_env.extend([
        ("cond", cond_name),
        ("then_branch", then_name),
        ("else_branch", else_name)
    ])
    
    expr = parse_expr("if cond then then_branch else else_branch")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected case structure
    expected = Case(
        scrutinee=Var(name=cond_name),
        branches=[
            CaseBranch(
                pattern=ConPat(con=BUILTIN_TRUE, args=[]),
                body=Var(name=then_name)
            ),
            CaseBranch(
                pattern=ConPat(con=BUILTIN_FALSE, args=[]),
                body=Var(name=else_name)
            )
        ]
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Binary Operator Tests
# =============================================================================

def test_rename_expr_binary_op():
    """Binary operator x + y desugars to App(App(Var(+), x), y)."""
    renamer = mk_rename_expr_with_builtins()
    
    # Check if + is available
    if "+" not in BUILTIN_BIN_OPS:
        pytest.skip("+ operator not in BUILTIN_BIN_OPS")
    
    x_name = Name(mod="Test", surface="x", unique=-1)
    y_name = Name(mod="Test", surface="y", unique=-1)
    renamer.local_env.extend([("x", x_name), ("y", y_name)])
    
    expr = parse_expr("x + y")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure: App(App(Var(+), Var(x)), Var(y))
    expected = App(
        func=App(
            func=Var(name=BUILTIN_BIN_OPS["+"]),
            arg=Var(name=x_name)
        ),
        arg=Var(name=y_name)
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Tuple Tests (Desugaring)
# =============================================================================

def test_rename_expr_tuple_pair():
    """Tuple (1, 2) desugars to nested pair constructor."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("(1, 2)")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure: App(App(Var(BUILTIN_PAIR_MKPAIR), LitExpr(1)), LitExpr(2))
    expected = App(
        func=App(
            func=Var(name=BUILTIN_PAIR_MKPAIR),
            arg=LitExpr(lit=LitInt(value=1))
        ),
        arg=LitExpr(lit=LitInt(value=2))
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_tuple_triple():
    """Triple (1, 2, 3) desugars to nested pair constructors."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("(1, 2, 3)")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure: App(App(Var(mkPair), 1), App(App(Var(mkPair), 2), 3))
    expected = App(
        func=App(
            func=Var(name=BUILTIN_PAIR_MKPAIR),
            arg=LitExpr(lit=LitInt(value=1))
        ),
        arg=App(
            func=App(
                func=Var(name=BUILTIN_PAIR_MKPAIR),
                arg=LitExpr(lit=LitInt(value=2))
            ),
            arg=LitExpr(lit=LitInt(value=3))
        )
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Case Expression Tests
# =============================================================================

def test_rename_expr_case_simple():
    """Simple case expression case x of with layout syntax."""
    renamer = mk_rename_expr_with_builtins()

    x_name = Name(mod="Test", surface="x", unique=-1)
    renamer.local_env.append(("x", x_name))

    expr = parse_expr("""case x of
  True -> 1
  False -> 0""")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected case structure
    expected = Case(
        scrutinee=Var(name=x_name),
        branches=[
            CaseBranch(
                pattern=ConPat(con=BUILTIN_TRUE, args=[]),
                body=LitExpr(lit=LitInt(value=1))
            ),
            CaseBranch(
                pattern=ConPat(con=BUILTIN_FALSE, args=[]),
                body=LitExpr(lit=LitInt(value=0))
            )
        ]
    )
    
    assert structural_equals(rn_expr, expected)


# =============================================================================
# Error Cases
# =============================================================================

def test_rename_expr_unresolved_variable():
    """Unresolved variable raises exception."""
    renamer = mk_rename_expr_with_builtins()
    expr = parse_expr("unknown_var")
    
    with pytest.raises(Exception, match="unresolved variable"):
        renamer.rename_expr(expr)


# =============================================================================
# Shadowing Tests
# =============================================================================

def test_rename_expr_lambda_shadowing():
    """Lambda param shadows outer binding."""
    renamer = mk_rename_expr_with_builtins()
    
    # Create outer binding for x
    outer_x = Name(mod="Test", surface="x", unique=-1)
    renamer.local_env.append(("x", outer_x))
    
    expr = parse_expr("\\x -> x")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure - lambda creates new binding for x
    # Body references the inner (lambda-bound) x, not outer_x
    expected_inner_x = Name(mod="Test", surface="x", unique=-1)
    expected = Lam(
        args=[expected_inner_x],
        body=Var(name=expected_inner_x)
    )
    
    assert structural_equals(rn_expr, expected)


def test_rename_expr_let_shadowing():
    """Let binding shadows outer binding."""
    renamer = mk_rename_expr_with_builtins()
    
    # Create outer binding for x
    outer_x = Name(mod="Test", surface="x", unique=-1)
    renamer.local_env.append(("x", outer_x))
    
    expr = parse_expr("let x = 1 in x")
    rn_expr = renamer.rename_expr(expr)
    
    # Build expected structure - let creates new binding for x
    expected_let_x = Name(mod="Test", surface="x", unique=-1)
    expected_binding = Binding(
        name=expected_let_x,
        expr=LitExpr(lit=LitInt(value=1))
    )
    expected = Let(
        bindings=[expected_binding],
        body=Var(name=expected_let_x)
    )
    
    assert structural_equals(rn_expr, expected)
