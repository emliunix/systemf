"""Regression tests for parser issues fixed during cons operator implementation.

These tests ensure that:
1. Type annotations use :: not :
2. Lambda parameters extract .name from tokens
3. Cons expressions work correctly
4. Cons patterns work in case expressions
5. Grouped patterns (parentheses) work
6. Constructor patterns accept complex args
"""

import pytest
from systemf.surface.parser import lex, expr_parser, parse_program
from systemf.surface.parser.types import AnyIndent
from systemf.surface.types import (
    SurfaceAnn,
    SurfaceCase,
    SurfaceOp,
    SurfacePattern,
    SurfacePatternCons,
    SurfacePatternTuple,
    SurfaceVarPattern,
)


class TestTypeAnnotationRegression:
    """Test that type annotations use :: not :"""

    def test_type_annotation_in_lambda(self):
        """Lambda with type annotation: λ(x :: Int) → x"""
        source = "λ(x :: Int) → x"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        # Should parse successfully (was failing when : was used instead of ::)
        assert result is not None

    def test_type_annotation_in_expression(self):
        """Expression with type annotation: (x :: Int)"""
        source = "(x :: Int)"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceAnn)

    def test_cons_not_confused_with_type_annotation(self):
        """Cons operator should not be parsed as type annotation.

        Regression: When atom_parser used ColonToken for type annotations,
        '1 : 2 : Nil' was parsed as '1 :: 2 :: Nil' (type annotations)
        instead of cons expressions.
        """
        source = "lst :: List Int = 1 : 2 : Nil"
        _, result = parse_program(source)
        assert len(result) == 1
        body = result[0].body
        # Should be cons expression, not type annotation
        assert isinstance(body, SurfaceOp)
        assert body.op == ":"


class TestLambdaParameterExtraction:
    """Test that lambda parameters correctly extract .name from tokens."""

    def test_simple_lambda_parameter(self):
        """Lambda with simple parameter: λx → x"""
        source = "λx → x"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None
        # Check var property is a string, not a token
        assert isinstance(result.var, str)
        assert result.var == "x"

    def test_annotated_lambda_parameter(self):
        """Lambda with annotated parameter: λ(x :: Int) → x"""
        source = "λ(x :: Int) → x"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert result is not None
        assert result.var == "x"


class TestConsExpressionRegression:
    """Test cons expressions: 1 : 2 : Nil"""

    def test_simple_cons(self):
        """Simple cons: 1 : Nil"""
        source = "lst :: List Int = 1 : Nil"
        _, result = parse_program(source)
        body = result[0].body
        assert isinstance(body, SurfaceOp)
        assert body.op == ":"

    def test_right_associative_cons(self):
        """Cons should be right-associative: 1 : 2 : Nil = 1 : (2 : Nil)"""
        from systemf.surface.types import SurfaceLit

        source = "lst :: List Int = 1 : 2 : Nil"
        _, result = parse_program(source)
        body = result[0].body
        # Should be 1 : (2 : Nil), not (1 : 2) : Nil
        assert isinstance(body, SurfaceOp)
        assert body.op == ":"
        # Left is literal 1
        assert isinstance(body.left, SurfaceLit)
        assert body.left.value == 1
        # Right is (2 : Nil)
        assert isinstance(body.right, SurfaceOp)
        assert body.right.op == ":"


class TestConsPatternRegression:
    """Test cons patterns in case expressions: case xs of x : xs → ..."""

    def test_simple_cons_pattern(self):
        """Simple cons pattern: x : xs"""
        source = """case xs of
  x : xs → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert isinstance(result.branches[0].pattern, SurfacePatternCons)

    def test_right_associative_cons_pattern(self):
        """Cons pattern should be right-associative: x : y : zs"""
        source = """case xs of
  x : y : zs → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        cons_pattern = result.branches[0].pattern
        assert isinstance(cons_pattern, SurfacePatternCons)
        # Should be x : (y : zs)
        assert isinstance(cons_pattern.tail, SurfacePatternCons)


class TestGroupedPatternRegression:
    """Test grouped patterns with parentheses: (x), (Cons x xs), (x : xs)"""

    def test_grouped_variable(self):
        """Grouped variable: (x)"""
        source = """case xs of
  (x) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        # Should be equivalent to just 'x'
        assert result.branches[0].pattern.patterns[0].name == "x"

    def test_grouped_constructor(self):
        """Grouped constructor: (Cons x xs)"""
        from systemf.surface.types import SurfacePattern

        source = """case xs of
  (Cons x xs) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        pattern = result.branches[0].pattern
        assert pattern.patterns[0].name == "Cons"
        var_constructors = [v.patterns[0].name for v in pattern.patterns[1:] if isinstance(v, SurfacePattern)]
        assert "x" in var_constructors
        assert "xs" in var_constructors

    def test_grouped_cons(self):
        """Grouped cons pattern: (x : xs)"""
        source = """case xs of
  (x : xs) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        assert isinstance(result.branches[0].pattern, SurfacePatternCons)

    def test_nested_grouped_cons(self):
        """Nested grouped cons: (x : (y : zs))"""
        source = """case xs of
  (x : (y : zs)) → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        cons_pattern = result.branches[0].pattern
        assert isinstance(cons_pattern, SurfacePatternCons)
        # Should be right-associative
        assert isinstance(cons_pattern.tail, SurfacePatternCons)


class TestConstructorPatternArgs:
    """Test constructor patterns with complex args: Pair (x, y) z"""

    def test_constructor_with_tuple_arg(self):
        """Constructor with tuple argument: Pair (x, y) z"""
        source = """case p of
  Pair (x, y) z → x
  _ → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        pattern = result.branches[0].pattern
        assert pattern.patterns[0].name == "Pair"
        # Should have 2 args
        assert len(pattern.patterns[1:]) == 2

    def test_constructor_with_grouped_cons_arg(self):
        """Constructor with grouped cons arg: Cons (x : xs) ys"""
        source = """case zs of
  Cons (x : xs) ys → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        assert isinstance(result, SurfaceCase)
        pattern = result.branches[0].pattern
        assert pattern.patterns[0].name == "Cons"


class TestDeclarationBoundaryRegression:
    """Test that expression parsers stop at declaration boundaries."""

    def test_cons_expression_does_not_consume_next_declaration(self):
        """Cons expression should not consume the next declaration.

        Regression: When parsing 'lst :: List Int = 1 : 2 : Nil\nnext :: Int = 42',
        the cons parser was consuming 'next' as part of the expression.
        """
        source = """lst :: List Int = 1 : 2 : Nil
next :: Int = 42"""
        _, result = parse_program(source)
        assert len(result) == 2
        assert result[0].name == "lst"
        assert result[1].name == "next"
