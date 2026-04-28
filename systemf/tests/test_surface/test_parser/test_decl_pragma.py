"""Tests for declaration-level pragmas.

Tests parsing of {-# ... #-} style pragmas before declarations.
Follows syntax.md Section 7.2 (Pragmas).
"""

import pytest
from systemf.surface.parser import (
    decl_parser,
    data_parser,
    term_parser,
    prim_type_parser,
    prim_op_parser,
    lex,
)
from systemf.surface.types import (
    SurfaceDataDeclaration,
    SurfaceTermDeclaration,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
)


class TestTermDeclarationPragmas:
    """Test pragmas on term declarations."""

    def test_term_with_llm_pragma(self):
        """Parse term declaration with LLM pragma."""
        source = """{-# LLM model=gpt-4 temperature=0.7 #-}
translate :: String -> String = \\text -> text"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "translate"
        assert result.pragma is not None
        assert "LLM" in result.pragma
        assert "model=gpt-4" in result.pragma["LLM"]

    def test_term_without_pragma(self):
        """Parse term declaration without pragma."""
        tokens = lex("add :: Int -> Int -> Int = \\x y -> x + y")
        result = term_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is None

    def test_term_pragma_empty_content(self):
        """Parse pragma with empty content."""
        source = """{-# LLM #-}
identity :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma == {"LLM": ""}

    def test_term_pragma_whitespace_content(self):
        """Parse pragma with whitespace-only content."""
        source = """{-# LLM #-}
identity :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma == {"LLM": ""}


class TestPrimOpDeclarationPragmas:
    """Test pragmas on primitive operation declarations."""

    def test_prim_op_with_llm_pragma(self):
        """Parse prim_op with LLM pragma."""
        source = """{-# LLM model=claude-3-sonnet #-}
prim_op analyze :: String -> String"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfacePrimOpDecl)
        assert result.name == "analyze"
        assert result.pragma is not None
        assert "LLM" in result.pragma

    def test_prim_op_with_complex_pragma(self):
        """Parse prim_op with multi-parameter pragma."""
        source = """{-# LLM model=gpt-4o system="You are a helpful assistant" temperature=0.5 max_tokens=100 #-}
prim_op chat :: String -> String"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfacePrimOpDecl)
        assert result.pragma is not None
        assert "model=gpt-4o" in result.pragma["LLM"]
        assert "temperature=0.5" in result.pragma["LLM"]


class TestDataDeclarationPragmas:
    """Test pragmas on data declarations."""

    def test_data_with_pragma(self):
        """Parse data declaration with pragma."""
        source = """{-# DERIVING Show Eq #-}
data Maybe a = Nothing | Just a"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "Maybe"
        assert result.pragma is not None
        assert "DERIVING" in result.pragma
        assert "Show Eq" in result.pragma["DERIVING"]


class TestPragmaAndDocstringTogether:
    """Test pragma and docstring on same declaration."""

    def test_pragma_before_docstring(self):
        """Pragma appears before docstring."""
        source = """{-# LLM model=gpt-4 #-}
-- | Translate English to French
translate :: String -> String = \\text -> text"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        assert "LLM" in result.pragma
        assert result.docstring == "Translate English to French"

    def test_docstring_before_pragma(self):
        """Docstring appears before pragma."""
        source = """-- | Translate English to French
{-# LLM model=gpt-4 #-}
translate :: String -> String = \\text -> text"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.docstring == "Translate English to French"
        assert result.pragma is not None
        assert "LLM" in result.pragma

    def test_only_pragma_no_docstring(self):
        """Only pragma, no docstring."""
        source = """{-# LLM #-}
identity :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        assert result.docstring is None

    def test_only_docstring_no_pragma(self):
        """Only docstring, no pragma."""
        source = """-- | Identity function
identity :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.docstring == "Identity function"
        assert result.pragma is None


class TestPragmaEdgeCases:
    """Test edge cases for pragma parsing."""

    def test_pragma_with_newlines(self):
        """Pragma can span multiple lines."""
        source = """{-# LLM
  model=gpt-4
  temperature=0.7
#-}
translate :: String -> String = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        assert "LLM" in result.pragma
        assert "model=gpt-4" in result.pragma["LLM"]

    def test_multiple_pragmas(self):
        """Multiple pragmas before single declaration."""
        source = """{-# INLINE #-}
{-# LLM model=gpt-4 #-}
fastAdd :: Int -> Int -> Int = \\x y -> x + y"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        # Should have both pragmas
        assert "INLINE" in result.pragma
        assert "LLM" in result.pragma

    def test_pragma_special_chars(self):
        """Pragma content can have special characters."""
        source = """{-# LLM system="Use -> arrow and (parens)" #-}
test :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        assert 'system="Use -> arrow and (parens)"' in result.pragma["LLM"]

    def test_pragma_with_unicode(self):
        """Pragma can contain unicode characters."""
        source = """{-# LLM model=GPT-4 λ-enabled #-}
unicode :: Int -> Int = \\x -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None
        assert "GPT-4 λ-enabled" in result.pragma["LLM"]


class TestPragmaParsingErrors:
    """Test pragma parsing error cases."""

    def test_unclosed_pragma(self):
        """Unclosed pragma should raise lexer error."""
        from systemf.surface.parser.types import LexerError

        source = """{-# LLM model=gpt-4
test :: Int = 1"""
        # Lexer should fail on unclosed pragma
        with pytest.raises(LexerError):
            lex(source)

    def test_pragma_in_middle_of_declaration(self):
        """Pragma in middle of declaration should be parsed as separate token."""
        source = """{-# BEFORE #-}
test :: Int = 1"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        # Pragma before declaration works fine
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.pragma is not None

    def test_nested_pragma(self):
        """Nested pragmas cause lexer error (not supported)."""
        from systemf.surface.parser.types import LexerError

        source = """{-# OUTER {-# INNER #-} #-}
test :: Int = 1"""
        # Nested pragmas are not supported - lexer fails on unmatched #-
        with pytest.raises(LexerError):
            lex(source)
