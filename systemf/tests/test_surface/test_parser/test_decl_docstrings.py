"""Tests for declaration-level docstrings.

Tests parsing of -- | style docstrings before declarations.
Follows syntax.md Section 7.1 (Documentation Comments).
"""

import pytest
from systemf.surface.parser import (
    decl_parser,
    data_parser,
    term_parser,
    prim_type_parser,
    prim_op_parser,
    lex,
    parse_program,
)
from systemf.surface.types import (
    SurfaceDataDeclaration,
    SurfaceTermDeclaration,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
)


class TestDataDeclarationDocstrings:
    """Test docstrings on data declarations."""

    def test_data_with_preceding_docstring(self):
        """Parse data declaration with -- | docstring before it."""
        source = """-- | A boolean type with two values
data Bool = True | False"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "Bool"
        assert result.docstring == "A boolean type with two values"

    def test_data_without_docstring(self):
        """Parse data declaration without docstring."""
        tokens = lex("data Bool = True | False")
        result = data_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.docstring is None

    def test_data_docstring_multiline(self):
        """Parse data with multiline docstring."""
        source = """-- | A list data type
-- | that can be empty or contain elements
data List a = Nil | Cons a (List a)"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.docstring == "A list data type\nthat can be empty or contain elements"

    def test_data_docstring_with_whitespace(self):
        """Parse docstring with extra whitespace after |."""
        source = """-- |   Natural numbers  
data Nat = Zero | Succ Nat"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        # Idris2-style: strip one leading space after marker, preserving rest
        assert result.docstring == "  Natural numbers"

    def test_data_docstring_inline_not_preceding(self):
        """Ensure -- ^ style is NOT captured as declaration docstring."""
        source = """data Maybe a =
  -- ^ Maybe doc
  Nothing
  | Just a"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        # -- ^ should not be captured as declaration docstring
        assert result.docstring is None


class TestTermDeclarationDocstrings:
    """Test docstrings on term declarations."""

    def test_term_with_preceding_docstring(self):
        """Parse term declaration with -- | docstring."""
        source = """-- | Add two integers
add :: Int -> Int -> Int = λx y -> x + y"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "add"
        assert result.docstring == "Add two integers"

    def test_term_without_docstring(self):
        """Parse term declaration without docstring."""
        tokens = lex("add :: Int -> Int -> Int = λx y -> x + y")
        result = term_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.docstring is None

    def test_term_multiline_docstring(self):
        """Parse term with multiline docstring."""
        source = """-- | Compute factorial
-- | of a natural number
factorial :: Nat -> Nat = λ n -> n"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.docstring == "Compute factorial\nof a natural number"

    def test_term_docstring_empty(self):
        """Parse empty docstring (just -- | with nothing after)."""
        source = """-- |
identity :: Int -> Int = λx -> x"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceTermDeclaration)
        assert result.docstring == ""


class TestPrimTypeDeclarationDocstrings:
    """Test docstrings on primitive type declarations."""

    def test_prim_type_with_docstring(self):
        """Parse prim_type with -- | docstring."""
        source = """-- | Primitive integer type
prim_type Int"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.name == "Int"
        assert result.docstring == "Primitive integer type"

    def test_prim_type_without_docstring(self):
        """Parse prim_type without docstring."""
        tokens = lex("prim_type Bool")
        result = prim_type_parser().parse(tokens)

        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.docstring is None


class TestPrimOpDeclarationDocstrings:
    """Test docstrings on primitive operation declarations."""

    def test_prim_op_with_docstring(self):
        """Parse prim_op with -- | docstring."""
        source = """-- | Integer addition
prim_op add :: Int -> Int -> Int"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfacePrimOpDecl)
        assert result.name == "add"
        assert result.docstring == "Integer addition"

    def test_prim_op_without_docstring(self):
        """Parse prim_op without docstring."""
        tokens = lex("prim_op sub :: Int -> Int -> Int")
        result = prim_op_parser().parse(tokens)

        assert isinstance(result, SurfacePrimOpDecl)
        assert result.docstring is None

    def test_prim_op_multiline_docstring(self):
        """Parse prim_op with multiline docstring."""
        source = """-- | Multiplication of
-- | two integers
prim_op mul :: Int -> Int -> Int"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfacePrimOpDecl)
        assert result.docstring == "Multiplication of\ntwo integers"


class TestDocstringEdgeCases:
    """Test edge cases and interactions."""

    def test_comment_not_docstring(self):
        """Regular comments -- (without |) should not be docstrings."""
        source = """-- This is just a comment
data Bool = True | False"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.docstring is None

    def test_docstring_with_special_chars(self):
        """Docstring can contain special characters."""
        source = """-- | Type with -> arrow and (parens)
data Fun a b = Fun (a -> b)"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.docstring == "Type with -> arrow and (parens)"

    def test_multiple_declarations_with_docstrings(self):
        """Multiple declarations, each with their own docstring."""
        source = """-- | First declaration
one :: Int = 1

-- | Second declaration
two :: Int = 2"""

        _, decls = parse_program(source)

        assert len(decls) == 2
        assert decls[0].docstring == "First declaration"
        assert decls[1].docstring == "Second declaration"

    def test_multiline_docstring_stops_at_pragma(self):
        """Docstring merging should stop at a pragma."""
        source = """-- | Line 1
-- Line 2
{-# INLINE foo #-}
data X = A"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        assert result.docstring == "Line 1\nLine 2"

    def test_multiline_docstring_stops_at_code(self):
        """Docstring merging should stop at code (non-comment)."""
        source = """-- | Line 1
-- Line 2

-- This is a separate comment
data X = A"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)

        assert isinstance(result, SurfaceDataDeclaration)
        # Should only include the consecutive lines
        assert result.docstring == "Line 1\nLine 2"
