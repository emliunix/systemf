"""Tests for System F lexer.

Tests basic tokenization without virtual indentation tokens.
The lexer now just emits raw tokens with location information.
Layout handling is done by the stateful parser using column tracking.
"""

import pytest

from systemf.surface.parser import Lexer, lex, LexerError
from systemf.surface.parser.types import (
    ArrowToken,
    CaseToken,
    DataToken,
    DocstringToken,
    DotToken,
    ForallToken,
    IdentifierToken,
    InToken,
    LambdaToken,
    LetToken,
    NumberToken,
    OfToken,
)


# =============================================================================
# Basic Token Tests
# =============================================================================


class TestBasicTokens:
    """Tests for basic token recognition."""

    def test_empty_source(self):
        """Empty source should return empty list (no EOF token)."""
        tokens = lex("")
        assert len(tokens) == 0

    def test_simple_tokens(self):
        """Tokenize simple identifiers."""
        tokens = lex("x y z")
        types = [type(t).__name__ for t in tokens]
        assert types == ["IdentifierToken", "IdentifierToken", "IdentifierToken"]

    def test_keywords(self):
        """Tokenize keywords."""
        source = "data let in case of forall type if then else"
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]
        assert types == [
            "DataToken",
            "LetToken",
            "InToken",
            "CaseToken",
            "OfToken",
            "ForallToken",
            "TypeToken",
            "IfToken",
            "ThenToken",
            "ElseToken",
        ]

    def test_operators(self):
        """Tokenize operators."""
        source = "-> => = : | @ . ++ && || /="
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]
        assert types == [
            "ArrowToken",
            "DarrowToken",
            "EqualsToken",
            "ColonToken",
            "BarToken",
            "AtToken",
            "DotToken",
            "AppendToken",
            "AndToken",
            "OrToken",
            "NeToken",
        ]

    def test_arithmetic_operators(self):
        """Tokenize arithmetic operators."""
        source = "+ - * /"
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]
        assert types == ["PlusToken", "MinusToken", "StarToken", "SlashToken"]

    def test_comparison_operators(self):
        """Tokenize comparison operators."""
        source = "== < > <= >="
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]
        assert types == ["EqToken", "LtToken", "GtToken", "LeToken", "GeToken"]

    def test_delimiters(self):
        """Tokenize delimiters."""
        source = "( ) [ ] { }"
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]
        assert types == [
            "LeftParenToken",
            "RightParenToken",
            "LeftBracketToken",
            "RightBracketToken",
            "LeftBraceToken",
            "RightBraceToken",
        ]


# =============================================================================
# Location Tests
# =============================================================================


class TestTokenLocations:
    """Tests for token location tracking (column info)."""

    def test_token_columns(self):
        """Each token should have column information."""
        tokens = lex("x y")
        # x at col 1, y at col 3
        assert tokens[0].column == 1
        assert tokens[1].column == 3

    def test_multiline_columns(self):
        """Column tracking works across lines."""
        source = """case x of
  A -> 1"""
        tokens = lex(source)

        # Find case keyword at col 1
        case_tok = next(t for t in tokens if isinstance(t, CaseToken))
        assert case_tok.column == 1

        # Find A identifier at col 3 (indented)
        a_tok = next(t for t in tokens if isinstance(t, IdentifierToken) and t.value == "A")
        assert a_tok.column == 3


# =============================================================================
# Complex Examples
# =============================================================================


class TestComplexExamples:
    """Tests for complete code examples."""

    def test_simple_case_expression(self):
        """Case expression with indentation."""
        source = """case x of
  True -> 1
  False -> 0"""
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]

        # No virtual tokens - just raw tokens
        expected = [
            "CaseToken",
            "IdentifierToken",
            "OfToken",
            "IdentifierToken",
            "ArrowToken",
            "NumberToken",
            "IdentifierToken",
            "ArrowToken",
            "NumberToken",
        ]
        assert types == expected

    def test_let_expression(self):
        """Let expression with indentation."""
        source = """let
  x = 1
  y = 2
in x + y"""
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]

        # No virtual tokens
        assert "LetToken" in types
        assert "InToken" in types
        # Check columns
        let_tok = next(t for t in tokens if isinstance(t, LetToken))
        assert let_tok.column == 1

    def test_data_declaration(self):
        """Data declaration with constructors."""
        source = """data Bool = True | False"""
        tokens = lex(source)
        types = [type(t).__name__ for t in tokens]

        expected = [
            "DataToken",
            "IdentifierToken",
            "EqualsToken",
            "IdentifierToken",
            "BarToken",
            "IdentifierToken",
        ]
        assert types == expected


# =============================================================================
# Error Handling
# =============================================================================


class TestLexerErrors:
    """Tests for lexer error handling."""

    def test_unexpected_character(self):
        """Lexer should raise error for unexpected characters."""
        with pytest.raises(LexerError):
            lex("x $ y")


# =============================================================================
# Helper Functions
# =============================================================================


def get_token_columns(source: str) -> list[tuple[str, int]]:
    """Get (type, column) pairs for all tokens."""
    tokens = lex(source)
    return [(type(t).__name__, t.column) for t in tokens]


def test_column_tracking():
    """Verify column tracking in lexer."""
    source = """let x = 1
    y = 2"""
    cols = get_token_columns(source)

    # let at col 1, x at col 5, = at col 7, 1 at col 9
    assert cols[0] == ("LetToken", 1)
    assert cols[1] == ("IdentifierToken", 5)
    assert cols[2] == ("EqualsToken", 7)
    assert cols[3] == ("NumberToken", 9)

    # y at col 5 (second line)
    assert cols[4] == ("IdentifierToken", 5)


# =============================================================================
# Unicode Token Tests
# =============================================================================


class TestUnicodeTokens:
    """Tests for unicode token recognition (LAMBDA, ARROW)."""

    def test_lambda_ascii(self):
        """Tokenize \\ as LambdaToken."""
        tokens = lex("\\")
        assert len(tokens) == 1  # LambdaToken only (no EOF)
        assert isinstance(tokens[0], LambdaToken)
        assert tokens[0].value == "\\"

    def test_lambda_unicode(self):
        """Tokenize λ as LambdaToken."""
        tokens = lex("λ")
        assert len(tokens) == 1  # LambdaToken only (no EOF)
        assert isinstance(tokens[0], LambdaToken)
        assert tokens[0].value == "λ"

    def test_arrow_ascii(self):
        """Tokenize -> as ArrowToken."""
        tokens = lex("->")
        assert len(tokens) == 1  # ArrowToken only (no EOF)
        assert isinstance(tokens[0], ArrowToken)
        assert tokens[0].value == "->"

    def test_arrow_unicode(self):
        """Tokenize → as ArrowToken."""
        tokens = lex("→")
        assert len(tokens) == 1  # ArrowToken only (no EOF)
        assert isinstance(tokens[0], ArrowToken)
        assert tokens[0].value == "→"

    def test_forall_unicode(self):
        """Tokenize ∀ as FORALL (preserves unicode in keyword field)."""
        tokens = lex("∀")
        assert len(tokens) == 1  # FORALL only (no EOF)
        assert isinstance(tokens[0], ForallToken)
        assert tokens[0].value == "∀"  # Preserves original unicode

    def test_type_abstraction_tokens(self):
        """Tokenize complete type abstraction."""

    def test_lambda_with_type_annotation_tokens(self):
        """Tokenize lambda with type annotation."""
        tokens = lex("λx:Int -> x")
        types = [type(t).__name__ for t in tokens]
        assert types == [
            "LambdaToken",
            "IdentifierToken",
            "ColonToken",
            "IdentifierToken",
            "ArrowToken",
            "IdentifierToken",
        ]

    def test_mixed_unicode_ascii(self):
        """Tokenize mix of unicode and ASCII symbols."""
        # Using unicode lambda but ASCII arrow
        tokens = lex("λx -> x")
        types = [type(t).__name__ for t in tokens]
        assert types == ["LambdaToken", "IdentifierToken", "ArrowToken", "IdentifierToken"]

        # Using ASCII lambda but unicode arrow
        tokens = lex("\\x → x")
        types = [type(t).__name__ for t in tokens]
        assert types == ["LambdaToken", "IdentifierToken", "ArrowToken", "IdentifierToken"]


class TestTokenIdentity:
    """Tests to ensure token types are correctly identified."""

    def test_token_types_are_not_generic_operators(self):
        """Critical tokens should have specific types, not generic OPERATOR."""
        # These should NOT be tokenized as generic OPERATOR
        critical_tokens = [
            ("λ", LambdaToken),
            ("\\", LambdaToken),
            ("->", ArrowToken),
            ("→", ArrowToken),
            ("∀", ForallToken),
        ]

        for source, expected_type in critical_tokens:
            tokens = lex(source)
            assert isinstance(tokens[0], expected_type), (
                f"Expected {expected_type.__name__} for '{source}', got {type(tokens[0]).__name__}"
            )

    def test_arrow_variants_equivalent(self):
        """-> and → should both be ARROW type."""
        ascii_arrow = lex("->")[0]
        unicode_arrow = lex("→")[0]

        assert isinstance(ascii_arrow, ArrowToken)
        assert isinstance(unicode_arrow, ArrowToken)
        assert type(ascii_arrow) == type(unicode_arrow)


# =============================================================================
# Docstring Tests (Whitespace Tolerance)
# =============================================================================


class TestDocstringWhitespaceTolerance:
    """Tests for docstring whitespace tolerance edge cases."""

    def test_docstring_no_space_after_dashes(self):
        """Docstring --| should be recognized without space."""
        from systemf.surface.parser.types import DocstringToken

        tokens = lex("--| This is a docstring")
        assert len(tokens) == 1
        assert isinstance(tokens[0], DocstringToken)
        assert tokens[0].content == "This is a docstring"

    def test_docstring_with_space_after_dashes(self):
        """Docstring -- | should be recognized with space."""
        from systemf.surface.parser.types import DocstringToken

        tokens = lex("-- | This is a docstring")
        assert len(tokens) == 1
        assert isinstance(tokens[0], DocstringToken)
        assert tokens[0].content == "This is a docstring"

    def test_inline_docstring_no_space_after_dashes(self):
        """Inline docstring --^ should be recognized without space."""
        from systemf.surface.parser.types import DocstringToken

        tokens = lex("x --^ inline doc")
        assert len(tokens) == 2  # IDENT and DOCSTRING
        assert isinstance(tokens[1], DocstringToken)
        assert tokens[1].content == "inline doc"

    def test_inline_docstring_with_space_after_dashes(self):
        """Inline docstring -- ^ should be recognized with space."""
        from systemf.surface.parser.types import DocstringToken

        tokens = lex("x -- ^ inline doc")
        assert len(tokens) == 2  # IDENT and DOCSTRING
        assert isinstance(tokens[1], DocstringToken)
        assert tokens[1].content == "inline doc"

    def test_docstring_merging_with_mixed_whitespace(self):
        """Docstring merging should work with mixed whitespace patterns."""
        from systemf.surface.parser.types import DocstringToken

        # First line has space, continuation doesn't
        source = """-- | First line
-- continuation"""
        tokens = lex(source)
        assert len(tokens) == 1
        assert isinstance(tokens[0], DocstringToken)
        assert "First line" in tokens[0].content
        assert "continuation" in tokens[0].content

    def test_regular_comment_not_docstring(self):
        """Regular comments should not be tokenized."""
        tokens = lex("x -- regular comment")
        assert len(tokens) == 1
        assert isinstance(tokens[0], IdentifierToken)
