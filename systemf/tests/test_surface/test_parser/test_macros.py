"""Tests for source-level macro preprocessing.

These tests exercise `expand_comment_macros` directly and through the public
parse entry points.  They use temporary files so that relative-path resolution
can be checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systemf.surface.parser import parse_program
from systemf.surface.parser.macros import MacroError, expand_comment_macros


class TestExpandCommentMacros:
    """Direct tests for `expand_comment_macros`."""

    def test_no_macros_returns_unchanged_text(self, tmp_path: Path):
        text = "some comment text\n"
        assert expand_comment_macros(text, tmp_path / "main.sf") == text

    def test_include_replaces_directive_inside_comment_text(self, tmp_path: Path):
        included = tmp_path / "snippet.md"
        included.write_text("included body\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'some comment @include("{included.name}") more text\n'

        result = expand_comment_macros(text, source)
        assert result == "some comment included body\n more text\n"

    def test_include_inline_with_adjacent_text(self, tmp_path: Path):
        included = tmp_path / "prompt.md"
        included.write_text("prompt content", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'instruction @include("{included.name}") end'

        result = expand_comment_macros(text, source)
        assert result == "instruction prompt content end"

    def test_include_with_single_quotes(self, tmp_path: Path):
        included = tmp_path / "note.md"
        included.write_text("note body\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f"intro @include('{included.name}') outro\n"

        result = expand_comment_macros(text, source)
        assert result == "intro note body\n outro\n"

    def test_relative_path_resolution(self, tmp_path: Path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        included = subdir / "inner.md"
        included.write_text("inner content", encoding="utf-8")

        source = tmp_path / "main.sf"

        # expand_comment_macros operates on the stripped comment text
        result = expand_comment_macros('@include("subdir/inner.md")\n', source)
        assert result == "inner content\n"

    def test_nested_include(self, tmp_path: Path):
        inner = tmp_path / "inner.md"
        inner.write_text("deep value", encoding="utf-8")
        outer = tmp_path / "outer.md"
        outer.write_text(f'outer @include("{inner.name}")', encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'begin @include("{outer.name}") end'

        result = expand_comment_macros(text, source)
        assert result == "begin outer deep value end"

    def test_cyclic_include_raises(self, tmp_path: Path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text(f'@include("{b.name}")', encoding="utf-8")
        b.write_text(f'@include("{a.name}")', encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'@include("{a.name}")'

        with pytest.raises(MacroError, match="cyclic include detected"):
            expand_comment_macros(text, source)

    def test_missing_include_raises(self, tmp_path: Path):
        source = tmp_path / "main.sf"
        text = '@include("does-not-exist.md")'

        with pytest.raises(MacroError, match="include file not found"):
            expand_comment_macros(text, source)

    def test_include_in_plain_text_not_recognized(self, tmp_path: Path):
        """Only the @include(...) directive is expanded, not bare mentions."""
        source = tmp_path / "main.sf"
        text = "this mentions include but has no directive"
        assert expand_comment_macros(text, source) == text


class TestParseProgramWithMacros:
    """Integration tests: macro expansion runs inside the comment parser."""

    def test_parse_program_with_include_inserts_text_into_docstring(self, tmp_path: Path):
        """Includes inside comments become part of the docstring, not program code."""
        included = tmp_path / "decls.md"
        included.write_text(
            "x :: Int = 42\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = (
            f'-- | @include("{included.name}")\n'
            "y :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "y"
        assert decls[0].docstring == "x :: Int = 42\n"

    def test_parse_program_with_include_inserts_comments(self, tmp_path: Path):
        included = tmp_path / "comments.md"
        included.write_text(
            "included docs\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = (
            f'-- | before @include("{included.name}") after\n'
            "y :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "y"
        assert decls[0].docstring == "before included docs\n after"

    def test_parse_program_regular_comment_unchanged(self):
        imports, decls = parse_program("-- just a comment\nx :: Int = 1\n")
        assert len(decls) == 1
        assert decls[0].name == "x"

    def test_parse_program_with_include_docstring_attaches_to_decl(self, tmp_path: Path):
        included = tmp_path / "docs.md"
        included.write_text(
            "included docs",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = (
            f'-- | @include("{included.name}")\n'
            "x :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "x"
        assert decls[0].docstring == "included docs"

    def test_parse_program_include_on_its_own_line(self, tmp_path: Path):
        included = tmp_path / "part.md"
        included.write_text("part two", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = (
            "-- | part one\n"
            f'-- | @include("{included.name}")\n'
            "x :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].docstring == "part one\npart two"

    def test_parse_program_include_with_regular_comment_lines(self, tmp_path: Path):
        """Consecutive comment lines (marked and unmarked) are joined, then expanded."""
        included = tmp_path / "a.md"
        included.write_text("some hahaha", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = (
            f'-- | some comment @include("{included.name}")\n'
            "-- next line\n"
            "myfunc :: String -> String = id\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "myfunc"
        assert decls[0].docstring == "some comment some hahaha\nnext line"
