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
    SurfaceList,
    SurfaceAbs,
    SurfaceApp,
    SurfaceCase,
    SurfaceBranch,
    SurfaceListPattern,
    SurfacePatternCons,
    SurfacePatternSeq,
    SurfacePatternTuple,
    SurfaceLitPattern,
    SurfaceLet,
    SurfaceTuple,
    SurfaceVarPattern,
    SurfaceUnitPattern,
    SurfaceWildcardPattern,
    SurfaceOp,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
    SurfaceUnit,
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

    def test_unit_literal(self):
        """Parse unit syntax: ()."""
        tokens = lex("()")
        result = atom_parser().parse(tokens)
        assert equals_ignore_location(result, SurfaceUnit())

    def test_unit_literal_with_spaces(self):
        """Parse unit syntax with spaces: (   )."""
        tokens = lex("(   )")
        result = atom_parser().parse(tokens)
        assert equals_ignore_location(result, SurfaceUnit())

    def test_empty_list_literal(self):
        """Parse empty list syntax: []."""
        tokens = lex("[]")
        result = atom_parser().parse(tokens)
        assert equals_ignore_location(result, SurfaceList(elements=[]))

    def test_list_literal(self):
        """Parse list syntax: [1, x, True]."""
        tokens = lex("[1, x, True]")
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceList(
            elements=[
                SurfaceLit(prim_type="Int", value=1),
                SurfaceVar(name="x"),
                SurfaceVar(name="True"),
            ]
        )
        assert equals_ignore_location(result, expected)

    def test_nested_list_literal(self):
        """Parse nested list syntax: [[1], []]."""
        tokens = lex("[[1], []]")
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceList(
            elements=[
                SurfaceList(elements=[SurfaceLit(prim_type="Int", value=1)]),
                SurfaceList(elements=[]),
            ]
        )
        assert equals_ignore_location(result, expected)

    def test_tuple_with_unit_and_list(self):
        """Parse tuple containing unit and list syntax."""
        tokens = lex("((), [1, 2])")
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceTuple(
            elements=[
                SurfaceUnit(),
                SurfaceList(elements=[
                    SurfaceLit(prim_type="Int", value=1),
                    SurfaceLit(prim_type="Int", value=2),
                ]),
            ]
        )
        assert equals_ignore_location(result, expected)


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
        source = """case p of
  (x, y) → x + y"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="p"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternTuple(
                        elements=[SurfaceVarPattern(name="x"), SurfaceVarPattern(name="y")]
                    ),
                    body=SurfaceOp(
                        left=SurfaceVar(name="x"),
                        op="+",
                        right=SurfaceVar(name="y"),
                    ),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_unit_pattern(self):
        """Parse case with unit pattern."""
        source = """case x of
  () → 1"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="x"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceUnitPattern(),
                    body=SurfaceLit(prim_type="Int", value=1),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_empty_list_pattern(self):
        """Parse case with empty list pattern."""
        source = """case xs of
  [] → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceListPattern(elements=[]),
                    body=SurfaceLit(prim_type="Int", value=0),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_list_pattern(self):
        """Parse case with list pattern."""
        source = """case xs of
  [a, b, c] → a"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceListPattern(elements=[
                        SurfaceVarPattern(name="a"),
                        SurfaceVarPattern(name="b"),
                        SurfaceVarPattern(name="c"),
                    ]),
                    body=SurfaceVar(name="a"),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_nested_list_pattern(self):
        """Parse case with nested list pattern."""
        source = """case xs of
  [[x], []] → x"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceListPattern(elements=[
                        SurfaceListPattern(elements=[
                            SurfaceVarPattern(name="x"),
                        ]),
                        SurfaceListPattern(elements=[]),
                    ]),
                    body=SurfaceVar(name="x"),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_tuple_of_unit_and_list_patterns(self):
        """Parse tuple pattern mixing unit and list syntax."""
        source = """case x of
  ((), [a, b]) → a"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="x"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternTuple(elements=[
                        SurfaceUnitPattern(),
                        SurfaceListPattern(elements=[
                            SurfaceVarPattern(name="a"),
                            SurfaceVarPattern(name="b"),
                        ]),
                    ]),
                    body=SurfaceVar(name="a"),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_list_head_cons_pattern(self):
        """Parse cons pattern whose head is a list pattern."""
        source = """case xss of
  [x] : xss -> x"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xss"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceListPattern(elements=[
                            SurfaceVarPattern(name="x"),
                        ]),
                        tail=SurfaceVarPattern(name="xss"),
                    ),
                    body=SurfaceVar(name="x"),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_unit_head_cons_pattern(self):
        """Parse cons pattern whose head is a unit pattern."""
        source = """case xs of
  () : rest -> 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceUnitPattern(),
                        tail=SurfaceVarPattern(name="rest"),
                    ),
                    body=SurfaceLit(prim_type="Int", value=0),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_unhappy_unit_literal_with_newline(self):
        """Unit token should not accept newlines between parens."""
        with pytest.raises(Exception):
            expr_parser(AnyIndent()).parse(lex("(\n)"))

    def test_unhappy_list_literal_trailing_comma(self):
        """Reject trailing comma in list literal."""
        with pytest.raises(Exception):
            expr_parser(AnyIndent()).parse(lex("[1,]"))

    def test_unhappy_list_pattern_trailing_comma(self):
        """Reject trailing comma in list pattern."""
        with pytest.raises(Exception):
            expr_parser(AnyIndent()).parse(lex("case xs of [x,] -> x"))

    def test_case_with_triple_pattern(self):
        """Parse case with triple pattern."""
        source = """case t of
  (a, b, c) → a"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="t"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternTuple(
                        elements=[
                            SurfaceVarPattern(name="a"),
                            SurfaceVarPattern(name="b"),
                            SurfaceVarPattern(name="c"),
                        ]
                    ),
                    body=SurfaceVar(name="a"),
                )
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_braces(self):
        """Parse case with explicit braces: case x of { True → 1 | False → 0 }."""
        source = "case x of { True → 1 | False → 0 }"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="x"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="True"),
                    body=SurfaceLit(prim_type="Int", value=1),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="False"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_braces_multiple_patterns(self):
        """Parse case with braces and multiple patterns."""
        source = "case mx of { Nothing → 0 | Just x → x }"
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="mx"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nothing"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
                SurfaceBranch(
                    pattern=SurfacePatternSeq(
                        patterns=[
                            SurfaceVarPattern(name="Just"),
                            SurfaceVarPattern(name="x"),
                        ]
                    ),
                    body=SurfaceVar(name="x"),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_cons_pattern(self):
        """Parse case with cons pattern: x : xs."""
        source = """case xs of
  x : xs → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceVarPattern(name="x"),
                        tail=SurfaceVarPattern(name="xs"),
                    ),
                    body=SurfaceVar(name="x"),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_nested_cons_pattern(self):
        """Parse case with nested cons pattern: x : y : zs."""
        source = """case xs of
  x : y : zs → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceVarPattern(name="x"),
                        tail=SurfacePatternCons(
                            head=SurfaceVarPattern(name="y"),
                            tail=SurfaceVarPattern(name="zs"),
                        ),
                    ),
                    body=SurfaceOp(
                        left=SurfaceVar(name="x"),
                        op="+",
                        right=SurfaceVar(name="y"),
                    ),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_grouped_pattern(self):
        """Parse case with grouped pattern: (x)."""
        source = """case xs of
  (x) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="x"),
                    body=SurfaceVar(name="x"),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_grouped_cons(self):
        """Parse case with grouped cons pattern: (x : xs)."""
        source = """case xs of
  (x : xs) → x
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceVarPattern(name="x"),
                        tail=SurfaceVarPattern(name="xs"),
                    ),
                    body=SurfaceVar(name="x"),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_nested_grouped_cons(self):
        """Parse case with nested grouped cons: (x : (y : zs))."""
        source = """case xs of
  (x : (y : zs)) → x + y
  Nil → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="xs"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternCons(
                        head=SurfaceVarPattern(name="x"),
                        tail=SurfacePatternCons(
                            head=SurfaceVarPattern(name="y"),
                            tail=SurfaceVarPattern(name="zs"),
                        ),
                    ),
                    body=SurfaceOp(
                        left=SurfaceVar(name="x"),
                        op="+",
                        right=SurfaceVar(name="y"),
                    ),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

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
                SurfaceBranch(pattern=SurfaceVarPattern(name="m"), body=SurfaceOp(left=SurfaceVar(name="m"), op="*", right=SurfaceLit(prim_type="Int", value=2))),
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
                SurfaceBranch(pattern=SurfaceVarPattern(name="msg"), body=SurfaceLit(prim_type="Int", value=0)),
            ],
        )
        assert equals_ignore_location(result, expected)

    def test_case_with_constructor_tuple_arg(self):
        """Parse case with constructor taking tuple: Pair (x, y) z."""
        source = """case p of
  Pair (x, y) z → x
  _ → 0"""
        tokens = lex(source)
        result = expr_parser(AnyIndent()).parse(tokens)
        expected = SurfaceCase(
            scrutinee=SurfaceVar(name="p"),
            branches=[
                SurfaceBranch(
                    pattern=SurfacePatternSeq(
                        patterns=[
                            SurfaceVarPattern(name="Pair"),
                            SurfacePatternTuple(
                                elements=[
                                    SurfaceVarPattern(name="x"),
                                    SurfaceVarPattern(name="y"),
                                ]
                            ),
                            SurfaceVarPattern(name="z"),
                        ]
                    ),
                    body=SurfaceVar(name="x"),
                ),
                SurfaceBranch(
                    pattern=SurfaceWildcardPattern(),
                    body=SurfaceLit(prim_type="Int", value=0),
                ),
            ],
        )
        assert equals_ignore_location(result, expected)

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

        assert equals_ignore_location(layout_result, braces_result)


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
                SurfaceBranch(pattern=SurfaceVarPattern(name="other"), body=SurfaceLit(prim_type="Int", value=1)),
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
                    pattern=SurfacePatternSeq(patterns=[
                        SurfaceVarPattern(name="Cons"),
                        SurfaceLitPattern(prim_type="Int", value=0),
                        SurfaceVarPattern(name="rest"),
                    ]),
                    body=SurfaceVar(name="rest"),
                ),
                SurfaceBranch(
                    pattern=SurfaceVarPattern(name="Nil"),
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
                SurfaceBranch(pattern=SurfaceVarPattern(name="other"), body=SurfaceLit(prim_type="Int", value=1)),
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
