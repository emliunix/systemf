"""Complex layout parsing tests.

Tests for nested layout scenarios that exercise the full parser stack.
These tests verify that layout constraints flow correctly through nested constructs.
"""

import pytest
from dataclasses import dataclass
from typing import List

from systemf.surface.parser import (
    TokenBase,
    IdentifierToken,
    KeywordToken,
    ConstructorToken,
    OperatorToken,
    DelimiterToken,
    AnyIndent,
    AtPos,
    AfterPos,
    EndOfBlock,
    lex,
)
from systemf.utils.location import Location
from systemf.surface.parser.helpers import (
    column,
    check_valid,
    block,
    block_entries,
    block_entry,
    terminator,
    must_continue,
)


# =============================================================================
# Complex Layout Scenario: Nested case + let
# =============================================================================
#
# Source:
#   case x of          -- parent indent = 0
#     True -> let      -- True at col 2, let at col 8 (> 2 ✓)
#       y = 1          -- y at col 4 (> 2 ✓, matches let's block)
#     in y + 1         -- in must be >= col 2 ✓
#     False -> 0       -- False at col 2 (matches True's column ✓)
#
# This tests:
# 1. Case branches at consistent column (2)
# 2. Nested let bindings at deeper column (4)
# 3. 'in' keyword validation relative to parent (>= 2)
# 4. Multiple branches maintaining layout


class TestNestedCaseLet:
    """Test nested case expressions with let bindings."""

    def test_case_branches_at_consistent_column(self):
        """Case branches must be at the same column."""
        source = """case x of
  True -> 1
  False -> 0"""

        tokens = lex(source)

        # Find 'True' and 'False' tokens
        true_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "True")
        false_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "False")

        # Both should be at same column (2 spaces indent = column 3)
        # Note: columns are 1-indexed, so 2 spaces = column 3
        assert true_tok.column == 3
        assert false_tok.column == 3

        # Check consistency with AtPos constraint
        assert check_valid(AtPos(3), true_tok.column)
        assert check_valid(AtPos(3), false_tok.column)

    def test_let_bindings_deeper_than_case(self):
        """Let bindings must be indented past the case branch."""
        source = """case x of
  True -> let
    y = 1
    z = 2
  in y + z"""

        tokens = lex(source)

        # Find column positions
        true_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "True")
        y_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "y")
        z_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "z")
        in_tok = next(t for t in tokens if hasattr(t, "value") and t.value == "in")

        # Case branch at col 3 (2 spaces indent, 1-indexed)
        assert true_tok.column == 3

        # Let bindings at col 5 (4 spaces indent, deeper than case)
        assert y_tok.column == 5
        assert z_tok.column == 5

        # 'in' at col 3 (>= case column, same as branch)
        assert in_tok.column == 3

    def test_in_keyword_must_be_at_or_after_parent_column(self):
        """'in' must not be dedented past the parent's reference column."""
        # This is a layout validation test
        # 'in' at col 2 when parent is at col 2 should pass
        assert check_valid(AfterPos(2), 2)  # At boundary
        assert check_valid(AfterPos(2), 4)  # Indented further

    def test_nested_constraint_validation(self):
        """Constraints flow correctly through nested blocks."""
        # Outer: case branches at AtPos(2)
        # Inner: let bindings at AtPos(4)

        # Branch at col 2 is valid
        assert check_valid(AtPos(2), 2)

        # Binding at col 4 is valid for let block
        assert check_valid(AtPos(4), 4)

        # But binding at col 4 is NOT at case branch column
        assert not check_valid(AtPos(2), 4)

    def test_terminator_detects_branch_end(self):
        """Terminator detects when we've left the case block."""
        # After parsing a branch, if we see a token at col <= branch_col,
        # that's a terminator

        # Token at same column as reference = new branch (not terminator in layout mode)
        # Actually in our design, same col means continue
        # Dedent means end
        pass  # TODO: Implement when we have full parser


class TestMixedExplicitAndLayout:
    """Test mixing explicit braces with layout."""

    def test_explicit_braces_override_layout(self):
        """Inside { }, layout rules don't apply."""
        # Note: No semicolons since lexer doesn't have SEMICOLON token
        source = """{
  x = 1
  y = 2
}"""
        tokens = lex(source)

        types = [t.type if hasattr(t, "type") else str(type(t).__name__) for t in tokens]

        # Check braces are present
        assert any("LBRACE" in str(t) or "{" in str(t) for t in types)
        assert any("RBRACE" in str(t) or "}" in str(t) for t in types)

    def test_mixed_case_with_explicit_branches(self):
        """Case can use explicit braces for branches."""
        # Note: Using newlines instead of semicolons since lexer doesn't have SEMICOLON
        source = """case x of {
  True -> 1
  False -> 0
}"""
        tokens = lex(source)

        # Should parse without layout constraints
        # AnyIndent mode inside braces
        pass  # TODO: Implement when we have full parser


class TestErrorCases:
    """Test layout error detection."""

    def test_inconsistent_branch_indentation(self):
        """Branches at different columns should fail."""
        # True at col 2, False at col 4 - should be error
        true_col = 2
        false_col = 4

        # False at col 4 does NOT satisfy AtPos(2)
        assert not check_valid(AtPos(2), false_col)

    def test_dedented_let_binding(self):
        """Let binding dedented past case branch should fail."""
        # Case branch at col 2
        # Binding at col 0 - violates constraint
        binding_col = 0

        # Does NOT satisfy AtPos(4) or even AfterPos(2)
        assert not check_valid(AtPos(4), binding_col)
        assert not check_valid(AfterPos(2), binding_col)

    def test_in_keyword_dedented(self):
        """'in' dedented past 'let' column should fail."""
        # 'let' at col 8 (for example)
        # 'in' at col 0 - definitely wrong
        in_col = 0

        assert not check_valid(AfterPos(8), in_col)


class TestParserShowcase:
    """Showcase complete programs demonstrating parser capabilities.

    These tests demonstrate the full range of System F syntax as defined
    in syntax.md, showcasing layout-sensitive parsing, expressions, and
    declarations working together.
    """

    def test_simple_function_definition(self):
        """Parse a simple function with type signature."""
        from systemf.surface.parser import parse_declaration

        source = "identity : forall a. a -> a = λx -> x"
        result = parse_declaration(source)

        # Should successfully parse as a term declaration
        assert result is not None

    def test_data_declaration(self):
        """Parse a data declaration with multiple constructors."""
        from systemf.surface.parser import parse_declaration

        source = """data Maybe a = Nothing | Just a"""
        result = parse_declaration(source)

        assert result is not None

    def test_nested_case_expression(self):
        """Parse nested case expressions with proper layout."""
        from systemf.surface.parser import parse_expression

        source = """case x of
  True -> case y of
    Just z -> z
    Nothing -> 0
  False -> 1"""

        result = parse_expression(source)
        assert result is not None

    def test_complex_let_expression(self):
        """Parse let with multiple bindings and nested expressions."""
        from systemf.surface.parser import parse_expression

        source = """let
  x = 1
  y = 2
  z = x + y
in z * 2"""

        result = parse_expression(source)
        assert result is not None

    def test_polymorphic_type_application(self):
        """Parse type application in expression."""
        from systemf.surface.parser import parse_expression

        source = "identity @Int 42"
        result = parse_expression(source)
        assert result is not None

    def test_type_abstraction(self):
        """Parse type abstraction (Λ)."""
        from systemf.surface.parser import parse_expression

        source = "Λa. λx:a -> x"
        result = parse_expression(source)
        assert result is not None

    def test_if_then_else_expression(self):
        """Parse if-then-else with layout."""
        from systemf.surface.parser import parse_expression

        source = """if x > 0 then
  x
else
  negate x"""

        result = parse_expression(source)
        assert result is not None

    def test_operator_expression(self):
        """Parse complex operator expressions."""
        from systemf.surface.parser import parse_expression

        source = "x + y * z == x + (y * z)"
        result = parse_expression(source)
        assert result is not None

    def test_primitive_declarations(self):
        """Parse primitive type and operation declarations."""
        from systemf.surface.parser import parse_declaration

        prim_type = "prim_type Int"
        prim_op = "prim_op int_plus : Int -> Int -> Int"

        result1 = parse_declaration(prim_type)
        result2 = parse_declaration(prim_op)

        assert result1 is not None
        assert result2 is not None

    def test_recursion_with_let(self):
        """Parse recursive function via let."""
        from systemf.surface.parser import parse_expression

        source = """let
  factorial n =
    if n == 0 then
      1
    else
      n * factorial (n - 1)
in factorial 5"""

        result = parse_expression(source)
        assert result is not None

    def test_list_data_type(self):
        """Parse list-like recursive data type."""
        from systemf.surface.parser import parse_declaration

        source = """data List a =
  Nil
  | Cons a (List a)"""

        result = parse_declaration(source)
        assert result is not None

    def test_pattern_matching_with_multiple_args(self):
        """Parse function with multiple pattern matches."""
        from systemf.surface.parser import parse_expression

        source = """case pair of
  Pair x y -> x + y
  Single z -> z"""

        result = parse_expression(source)
        assert result is not None

    def test_higher_order_function_type(self):
        """Parse type with higher-order function."""
        from systemf.surface.parser import parse_type

        source = "forall a b. (a -> b) -> List a -> List b"
        result = parse_type(source)
        assert result is not None

    def test_complex_forall_type(self):
        """Parse complex rank-1 polymorphic type."""
        from systemf.surface.parser import parse_type

        source = "forall a b c. a -> b -> c -> a"
        result = parse_type(source)
        assert result is not None
