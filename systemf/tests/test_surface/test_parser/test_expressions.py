"""Unit tests for expression parsers.

Tests for individual expression parsers from expressions.py.
These tests validate the grammar from syntax.md Section 3.
"""

import pytest
from systemf.surface.parser import (
    expr_parser,
    atom_parser,
    app_parser,
    lambda_parser,
    case_parser,
    let_parser,
    if_parser,
    AnyIndent,
    lex,
)
from systemf.surface.types import (
    SurfaceVar,
    SurfaceLit,
    SurfaceAbs,
    SurfaceApp,
    SurfaceCase,
    SurfaceBranch,
    SurfacePattern,
    SurfaceLitPattern,
    SurfaceLet,
    SurfaceVarPattern,
    SurfaceWildcardPattern,
    SurfaceOp,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
)
from systemf.utils.ast_utils import equals_ignore_location


class TestAtomParser:
    """Test atom parser for basic terms."""

    def test_variable(self):
        """Parse a variable."""
        tokens = lex("x")
        result = atom_parser().parse(tokens)
        assert isinstance(result, SurfaceVar)
        assert result.name == "x"

    def test_constructor(self):
        """Parse a constructor (now treated as variable)."""
        tokens = lex("True")
        result = atom_parser().parse(tokens)
        assert isinstance(result, SurfaceVar)
        assert result.name == "True"

    def test_integer_literal(self):
        """Parse an integer literal."""
        tokens = lex("42")
        result = atom_parser().parse(tokens)
        assert isinstance(result, SurfaceLit)
        assert result.value == 42

    def test_string_literal(self):
        """Parse a string literal."""
        tokens = lex('"hello"')
        result = atom_parser().parse(tokens)
        assert isinstance(result, SurfaceLit)
        assert result.value == "hello"

    def test_parenthesized_expression(self):
        """Parse a parenthesized expression."""
        tokens = lex("(x)")
        result = atom_parser().parse(tokens)
        assert isinstance(result, SurfaceVar)
        assert result.name == "x"


class TestLambdaParser:
    """Test lambda abstraction parser."""

    def test_simple_lambda(self):
        """Parse λx → x."""
        tokens = lex("λx → x")
        result = lambda_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAbs)
        assert result.var == "x"

    def test_lambda_with_type_annotation(self):
        """Parse λ(x :: Int) → x."""
        tokens = lex("λ(x :: Int) → x")
        result = lambda_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAbs)
        assert result.var == "x"

    def test_lambda_multiple_params(self):
        """Parse λx y → x."""
        tokens = lex("λx y → x")
        result = lambda_parser(AnyIndent()).parse(tokens)
        # Should parse as nested abs: λx. (λy. x)
        assert isinstance(result, SurfaceAbs)


class TestApplicationParser:
    """Test function application parser."""

    def test_simple_application(self):
        """Parse f x."""
        tokens = lex("f x")
        result = app_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceApp)

    def test_multiple_application(self):
        """Parse f x y z."""
        tokens = lex("f x y z")
        result = app_parser(AnyIndent()).parse(tokens)
        # Should be left-associated: ((f x) y) z
        assert isinstance(result, SurfaceApp)

    def test_type_application(self):
        """Parse identity @Int 42."""
        tokens = lex("identity @Int 42")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceApp)


class TestIfParser:
    """Test if-then-else parser."""

    def test_simple_if(self):
        """Parse if True then 1 else 0."""
        tokens = lex("if True then 1 else 0")
        result = if_parser(AnyIndent()).parse(tokens)
        assert result is not None

    def test_if_with_layout(self):
        """Parse if with multi-line layout."""
        source = """if x > 0 then
  x
else
  negate x"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None


class TestCaseParser:
    """Test case expression parser."""

    def test_simple_case(self):
        """Parse case x of True → 1 | False → 0."""
        tokens = lex("case x of True → 1")
        result = case_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)

    def test_case_with_layout(self):
        """Parse case with layout branches."""
        source = """case x of
  True → 1
  False → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2

    def test_case_with_pattern(self):
        """Parse case with constructor pattern."""
        source = """case mx of
  Just x → x
  Nothing → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)

    def test_nested_case(self):
        """Parse nested case expressions."""
        source = """case x of
  True → case y of
    Just z → z
    Nothing → 0
  False → 1"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)

    def test_case_with_tuple_pattern(self):
        """Parse case with tuple pattern."""
        from systemf.surface.types import SurfacePatternTuple

        source = """case p of
  (x, y) → x + y"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert isinstance(result.branches[0].pattern, SurfacePatternTuple)
        assert len(result.branches[0].pattern.elements) == 2

    def test_case_with_triple_pattern(self):
        """Parse case with triple pattern."""
        from systemf.surface.types import SurfacePatternTuple

        source = """case t of
  (a, b, c) → a"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert isinstance(result.branches[0].pattern, SurfacePatternTuple)
        assert len(result.branches[0].pattern.elements) == 3

    def test_case_with_braces(self):
        """Parse case with explicit braces: case x of { True → 1 | False → 0 }."""
        source = "case x of { True → 1 | False → 0 }"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2
        assert result.branches[0].pattern.patterns[0].name == "True"
        assert result.branches[1].pattern.patterns[0].name == "False"

    def test_case_with_braces_multiple_patterns(self):
        """Parse case with braces and multiple patterns."""
        source = "case mx of { Nothing → 0 | Just x → x }"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2

    def test_case_with_cons_pattern(self):
        """Parse case with cons pattern: x : xs."""
        from systemf.surface.types import SurfacePatternCons

        source = """case xs of
  x : xs → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2
        # First branch should have cons pattern
        assert isinstance(result.branches[0].pattern, SurfacePatternCons)
        assert result.branches[0].pattern.head is not None
        assert result.branches[0].pattern.tail is not None

    def test_case_with_nested_cons_pattern(self):
        """Parse case with nested cons pattern: x : y : zs."""
        from systemf.surface.types import SurfacePatternCons

        source = """case xs of
  x : y : zs → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2
        # First branch should have cons pattern
        cons_pattern = result.branches[0].pattern
        assert isinstance(cons_pattern, SurfacePatternCons)
        # Should be right-associative: x : (y : zs)
        assert isinstance(cons_pattern.tail, SurfacePatternCons)

    def test_case_with_grouped_pattern(self):
        """Parse case with grouped pattern: (x)."""
        source = """case xs of
  (x) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        # Grouped pattern should be equivalent to just 'x'
        assert result.branches[0].pattern.patterns[0].name == "x"

    def test_case_with_grouped_cons(self):
        """Parse case with grouped cons pattern: (x : xs)."""
        from systemf.surface.types import SurfacePatternCons

        source = """case xs of
  (x : xs) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert isinstance(result.branches[0].pattern, SurfacePatternCons)

    def test_case_with_nested_grouped_cons(self):
        """Parse case with nested grouped cons: (x : (y : zs))."""
        from systemf.surface.types import SurfacePatternCons

        source = """case xs of
  (x : (y : zs)) → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        cons_pattern = result.branches[0].pattern
        assert isinstance(cons_pattern, SurfacePatternCons)
        # Should be right-associative: x : (y : zs)
        assert isinstance(cons_pattern.tail, SurfacePatternCons)

    def test_case_with_int_literal_pattern(self):
        """Parse case with integer literal pattern."""
        source = """case n of
  0 → 1
  m → m * 2"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="n"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="Int", value=0), body=SurfaceLit(prim_type="Int", value=1)),
                SurfaceBranch(pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="m")]), body=SurfaceOp(left=SurfaceVar(name="m"), op="*", right=SurfaceLit(prim_type="Int", value=2))),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_string_literal_pattern(self):
        """Parse case with string literal pattern."""
        source = """case s of
  "hello" → 1
  msg → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="s"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="String", value="hello"), body=SurfaceLit(prim_type="Int", value=1)),
                SurfaceBranch(pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="msg")]), body=SurfaceLit(prim_type="Int", value=0)),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_constructor_tuple_arg(self):
        """Parse case with constructor taking tuple: Pair (x, y) z."""
        from systemf.surface.types import SurfacePatternTuple

        source = """case p of
  Pair (x, y) z → x
  _ → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        pattern = result.branches[0].pattern
        assert isinstance(pattern, SurfacePattern)
        # Should have 3 items: Pair constructor + 2 args (tuple and z)
        assert len(pattern.patterns) == 3
        # First item is the constructor name
        assert isinstance(pattern.patterns[0], SurfaceVarPattern)
        assert pattern.patterns[0].name == "Pair"

    def test_nested_case_with_braces(self):
        """Parse nested case with outer layout and inner braces."""
        source = """case x of
  True → case y of { Just z → z | Nothing → 0 }
  False → 1"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert len(result.branches) == 2

    def test_case_braces_vs_layout_equivalence(self):
        """Verify case produces same structure with braces or layout."""
        # Layout version
        layout_source = """case x of
  True → 1
  False → 0"""
        layout_tokens = lex(layout_source)
        layout_result = expr_parser(AnyIndent()).parse(layout_tokens)

        # Braces version
        braces_source = "case x of { True → 1 | False → 0 }"
        braces_tokens = lex(braces_source)
        braces_result = expr_parser(AnyIndent()).parse(braces_tokens)

        # Both should produce 2 branches
        assert len(layout_result.branches) == len(braces_result.branches) == 2
        # Branch patterns should be equivalent (check constructor name)
        assert (
            layout_result.branches[0].pattern.patterns[0].name
            == braces_result.branches[0].pattern.patterns[0].name
        )
        assert (
            layout_result.branches[1].pattern.patterns[0].name
            == braces_result.branches[1].pattern.patterns[0].name
        )


class TestLiteralPattern:
    """Test literal pattern parsing in case expressions."""

    def test_multiple_literal_branches(self):
        """Parse case with multiple int literal branches."""
        source = """case x of
  0 → 1
  1 → 2"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="x"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="Int", value=0), body=SurfaceLit(prim_type="Int", value=1)),
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="Int", value=1), body=SurfaceLit(prim_type="Int", value=2)),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_string_literal_pattern(self):
        """Parse case with string literal pattern."""
        source = """case s of
  "hello" → 0
  other → 1"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="s"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="String", value="hello"), body=SurfaceLit(prim_type="Int", value=0)),
                SurfaceBranch(pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="other")]), body=SurfaceLit(prim_type="Int", value=1)),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_constructor_with_literal_arg(self):
        """Parse case with constructor taking literal arg: Cons 0 xs."""
        source = """case xs of
  Cons 0 rest → rest
  Nil → Nil"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePattern(patterns=[
                        SurfaceVarPattern(name="Cons"),
                        SurfaceLitPattern(prim_type="Int", value=0),
                        SurfacePattern(patterns=[SurfaceVarPattern(name="rest")]),
                    ]),
                    body=SurfaceVar(name="rest"),
                ),
                SurfaceBranch(
                    pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="Nil")]),
                    body=SurfaceVar(name="Nil"),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_multiple_literal_braces(self):
        """Parse case with multiple int literal branches in braces."""
        source = "case x of { 0 → 1 | 1 → 2 }"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="x"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="Int", value=0), body=SurfaceLit(prim_type="Int", value=1)),
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="Int", value=1), body=SurfaceLit(prim_type="Int", value=2)),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_string_literal_braces(self):
        """Parse case with string literal pattern in braces."""
        source = 'case s of { "hello" → 0 | other → 1 }'
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="s"),
            branches=[
                SurfaceBranch(pattern=SurfaceLitPattern(prim_type="String", value="hello"), body=SurfaceLit(prim_type="Int", value=0)),
                SurfaceBranch(pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="other")]), body=SurfaceLit(prim_type="Int", value=1)),
            ],
        )
        assert equals_ignore_location(result, expected)


class TestLetParser:
    """Test let expression parser."""

    def test_simple_let(self):
        """Parse let x = 1 in x + 1."""
        tokens = lex("let x = 1 in x + 1")
        result = let_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)

    def test_let_single_binding(self):
        """Parse let with single binding."""
        tokens = lex("let x = 1 in x")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)
        assert len(result.bindings) == 1

    def test_let_multiple_bindings(self):
        """Parse let with multiple bindings."""
        source = """let
  x = 1
  y = 2
in x + y"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)
        assert len(result.bindings) == 2

    def test_let_with_type_annotation(self):
        """Parse let with type annotation."""
        tokens = lex("let x :: Int = 1 in x")
        result = let_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)

    def test_let_recursive(self):
        """Parse recursive let."""
        source = """let
  factorial n =
    if n == 0 then 1 else n * factorial (n - 1)
in factorial 5"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)


class TestOperatorParser:
    """Test operator expression parser."""

    def test_addition(self):
        """Parse x + y."""
        tokens = lex("x + y")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None

    def test_arithmetic_precedence(self):
        """Parse x + y * z."""
        tokens = lex("x + y * z")
        result = expr_parser(AnyIndent()).parse(tokens)
        # Should be x + (y * z)
        assert result is not None

    def test_comparison(self):
        """Parse x > 0."""
        tokens = lex("x > 0")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None

    def test_equality(self):
        """Parse x == y."""
        tokens = lex("x == y")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None

    def test_complex_operator_expression(self):
        """Parse x + y * z == x + (y * z)."""
        tokens = lex("x + y * z == x + (y * z)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None

    def test_logical_operators(self):
        """Parse x > 0 && y < 10."""
        tokens = lex("x > 0 && y < 10")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None


class TestComplexExpressions:
    """Test complex expression combinations."""

    def test_polymorphic_identity(self):
        """Parse identity function with type."""
        tokens = lex("λ(x :: a) → x")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAbs)

    def test_fold_definition(self):
        """Parse fold-like function."""
        source = """λf acc xs →
  case xs of
    Nil → acc
    Cons x rest → fold f (f acc x) rest"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAbs)

    def test_compose_function(self):
        """Parse compose function."""
        tokens = lex("λf g x → f (g x)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAbs)

    def test_let_with_case(self):
        """Parse let with case inside."""
        source = """let
  head xs = case xs of Cons x _ → x
in head mylist"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceLet)


class TestTupleParser:
    """Test tuple expression parser."""

    def test_tuple_pair(self):
        """Parse a pair tuple."""
        from systemf.surface.types import SurfaceTuple

        tokens = lex("(x, y)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceTuple)
        assert len(result.elements) == 2
        assert isinstance(result.elements[0], SurfaceVar)
        assert result.elements[0].name == "x"
        assert isinstance(result.elements[1], SurfaceVar)
        assert result.elements[1].name == "y"

    def test_tuple_triple(self):
        """Parse a triple tuple."""
        from systemf.surface.types import SurfaceTuple

        tokens = lex("(1, 2, 3)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceTuple)
        assert len(result.elements) == 3
        assert isinstance(result.elements[0], SurfaceLit)
        assert result.elements[0].value == 1

    def test_tuple_mixed(self):
        """Parse tuple with mixed elements."""
        from systemf.surface.types import SurfaceTuple, SurfaceLit

        tokens = lex("(1, True)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceTuple)
        assert isinstance(result.elements[0], SurfaceLit)
        assert isinstance(result.elements[1], SurfaceVar)
        assert result.elements[1].name == "True"

    def test_nested_tuple(self):
        """Parse nested tuples."""
        from systemf.surface.types import SurfaceTuple

        tokens = lex("((1, 2), 3)")
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceTuple)
        assert len(result.elements) == 2
        assert isinstance(result.elements[0], SurfaceTuple)
        assert isinstance(result.elements[1], SurfaceLit)


class TestPrimTypeParser:
    """Test primitive type declaration parser."""

    def test_prim_type_simple(self):
        """Parse simple prim_type declaration."""
        from systemf.surface.parser.declarations import prim_type_parser

        tokens = lex("prim_type Int")
        result = prim_type_parser().parse(tokens)
        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.name == "Int"
        assert result.params == []

    def test_prim_type_with_params(self):
        """Parse prim_type declaration with type parameters."""
        from systemf.surface.parser.declarations import prim_type_parser

        tokens = lex("prim_type Ref a")
        result = prim_type_parser().parse(tokens)
        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.name == "Ref"
        assert [p.name for p in result.params] == ["a"]

    def test_prim_type_multiple_params(self):
        """Parse prim_type declaration with multiple type parameters."""
        from systemf.surface.parser.declarations import prim_type_parser

        tokens = lex("prim_type Map k v")
        result = prim_type_parser().parse(tokens)
        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.name == "Map"
        assert [p.name for p in result.params] == ["k", "v"]


class TestPrimOpParser:
    """Test primitive operation declaration parser."""

    def test_prim_op_simple(self):
        """Parse simple prim_op declaration."""
        from systemf.surface.parser.declarations import prim_op_parser

        tokens = lex("prim_op int_plus :: Int -> Int -> Int")
        result = prim_op_parser().parse(tokens)
        assert isinstance(result, SurfacePrimOpDecl)
        assert result.name == "int_plus"
        assert result.type_annotation is not None

    def test_prim_op_with_forall(self):
        """Parse prim_op declaration with forall type."""
        from systemf.surface.parser.declarations import prim_op_parser

        tokens = lex("prim_op mk_ref :: forall a. Unit -> Ref a")
        result = prim_op_parser().parse(tokens)
        assert isinstance(result, SurfacePrimOpDecl)
        assert result.name == "mk_ref"
        assert result.type_annotation is not None
