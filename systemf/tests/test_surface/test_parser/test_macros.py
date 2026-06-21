"""Tests for source-level macro preprocessing.

These tests exercise `render_macros` directly and through the public parse
entry points.  They use temporary files so that relative-path resolution can
be checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systemf.surface.parser import parse_program
from systemf.surface.parser.macros import MacroError, render_macros


class TestRenderMacros:
    """Direct tests for `render_macros`."""

    def test_no_macros_returns_unchanged_text(self, tmp_path: Path):
        text = "let x = 1\n"
        assert render_macros(tmp_path / "main.sf", text) == text

    def test_include_replaces_directive_line_with_raw_content(self, tmp_path: Path):
        included = tmp_path / "snippet.md"
        included.write_text("x = 42\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'-- @include "{included.name}"\nlet x = 1\n'

        result = render_macros(source, text)
        assert result == "x = 42\nlet x = 1\n"

    def test_include_of_commented_content_preserved(self, tmp_path: Path):
        included = tmp_path / "prompt.md"
        included.write_text(
            "-- | Prompt line 1\n"
            "-- | Prompt line 2\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = f'-- | @include "{included.name}"\nlet x = 1\n'

        result = render_macros(source, text)
        assert result == (
            "-- | Prompt line 1\n"
            "-- | Prompt line 2\n"
            "let x = 1\n"
        )

    def test_include_with_single_quotes(self, tmp_path: Path):
        included = tmp_path / "note.md"
        included.write_text("note body\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f"-- @include '{included.name}'\n"

        result = render_macros(source, text)
        assert result == "note body\n"

    def test_relative_path_resolution(self, tmp_path: Path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        included = subdir / "inner.md"
        included.write_text("inner content\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = '-- @include "subdir/inner.md"\n'

        result = render_macros(source, text)
        assert result == "inner content\n"

    def test_nested_include(self, tmp_path: Path):
        inner = tmp_path / "inner.md"
        inner.write_text("deep value\n", encoding="utf-8")
        outer = tmp_path / "outer.md"
        outer.write_text(f'-- @include "{inner.name}"\n', encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'-- @include "{outer.name}"\n'

        result = render_macros(source, text)
        assert result == "deep value\n"

    def test_cyclic_include_raises(self, tmp_path: Path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text(f'-- @include "{b.name}"\n', encoding="utf-8")
        b.write_text(f'-- @include "{a.name}"\n', encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'-- @include "{a.name}"\n'

        with pytest.raises(MacroError, match="cyclic include detected"):
            render_macros(source, text)

    def test_missing_include_raises(self, tmp_path: Path):
        source = tmp_path / "main.sf"
        text = '-- @include "does-not-exist.md"\n'

        with pytest.raises(MacroError, match="include file not found"):
            render_macros(source, text)

    def test_non_include_comment_is_preserved(self, tmp_path: Path):
        source = tmp_path / "main.sf"
        text = "-- this is just a comment\n"
        assert render_macros(source, text) == text

    def test_include_directive_with_extra_text_is_ignored(self, tmp_path: Path):
        """A comment line that is not *only* an include directive is left alone."""
        included = tmp_path / "note.md"
        included.write_text("note body\n", encoding="utf-8")

        source = tmp_path / "main.sf"
        text = f'-- also @include "{included.name}"\n'

        result = render_macros(source, text)
        assert result == text


class TestParseProgramWithMacros:
    """Integration tests: macro expansion runs during lexing."""

    def test_parse_program_with_include_inserts_code(self, tmp_path: Path):
        included = tmp_path / "decls.md"
        included.write_text(
            "x :: Int = 42\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = f'-- @include "{included.name}"\n'

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "x"

    def test_parse_program_with_include_inserts_comments(self, tmp_path: Path):
        included = tmp_path / "comments.md"
        included.write_text(
            "-- ignored comment\n"
            "-- another ignored comment\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = (
            f'-- @include "{included.name}"\n'
            "y :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "y"

    def test_parse_program_regular_comment_unchanged(self):
        imports, decls = parse_program("-- just a comment\nx :: Int = 1\n")
        assert len(decls) == 1
        assert decls[0].name == "x"

    def test_parse_program_with_include_docstring_attaches_to_decl(self, tmp_path: Path):
        included = tmp_path / "docs.md"
        included.write_text(
            "-- | included docs\n",
            encoding="utf-8",
        )

        source = tmp_path / "main.sf"
        text = (
            f'-- | @include "{included.name}"\n'
            "x :: Int = 1\n"
        )

        imports, decls = parse_program(text, str(source))
        assert len(decls) == 1
        assert decls[0].name == "x"
        assert decls[0].docstring == "included docs"
