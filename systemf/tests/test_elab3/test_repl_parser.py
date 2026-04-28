"""Tests for REPL command parser."""

import pytest
from systemf.elab3.reader_env import ImportSpec
from systemf.elab3.repl_parser import (
    parse_lines,
    REPLParseError,
    CodeInput,
    Browse,
    Info,
    Import,
    Help,
    Exit,
)


def parse(lines: list[str]) -> list:
    return list(parse_lines(lines))


def parse_one(line: str):
    return next(parse_lines([line]))


class TestCodeInput:
    def test_expression(self):
        assert parse_one("1 + 2") == CodeInput("1 + 2")

    def test_strips_whitespace(self):
        assert parse_one("  let x = 1 in x  ") == CodeInput("let x = 1 in x")

    def test_blank_lines_skipped(self):
        assert parse(["", "  ", "1 + 2"]) == [CodeInput("1 + 2")]


class TestExit:
    def test_quit(self):   assert parse_one(":quit")  == Exit()
    def test_q(self):      assert parse_one(":q")     == Exit()
    def test_exit(self):   assert parse_one(":exit")  == Exit()


class TestHelp:
    def test_help(self):
        assert parse_one(":help") == Help()


class TestBrowse:
    def test_browse(self):
        assert parse_one(":browse builtins") == Browse("builtins")

    def test_no_args_raises(self):
        with pytest.raises(REPLParseError, match="requires an argument"):
            parse_one(":browse")


class TestInfo:
    def test_info(self):
        assert parse_one(":info id") == Info("id")

    def test_no_args_raises(self):
        with pytest.raises(REPLParseError, match="requires an argument"):
            parse_one(":info")


class TestImport:
    def test_simple(self):
        assert parse_one(":import builtins") == Import(ImportSpec("builtins", alias=None, is_qual=False))

    def test_qualified(self):
        assert parse_one(":import qualified builtins") == Import(ImportSpec("builtins", alias=None, is_qual=True))

    def test_aliased(self):
        assert parse_one(":import builtins as B") == Import(ImportSpec("builtins", alias="B", is_qual=False))

    def test_no_args_raises(self):
        with pytest.raises(REPLParseError, match="requires an argument"):
            parse_one(":import")

    def test_invalid_raises(self):
        with pytest.raises(REPLParseError, match="invalid import"):
            parse_one(":import @@@")


class TestMultiline:
    def test_basic(self):
        assert parse([":{", "line one", "line two", ":}"]) == [CodeInput("line one\nline two")]

    def test_inline_first_line(self):
        assert parse([":{first", "line two", ":}"]) == [CodeInput("first\nline two")]

    def test_empty_body(self):
        assert parse([":{", ":}"]) == [CodeInput("")]

    def test_sequencing(self):
        assert parse([":help", ":{", "x = 1", ":}", ":quit"]) == [Help(), CodeInput("x = 1"), Exit()]

    def test_command_after_multiline(self):
        # multiline consumes iterator directly — verify no lines are dropped after :}
        assert parse([":{", "body", ":}", ":help", "code"]) == [CodeInput("body"), Help(), CodeInput("code")]

    def test_two_multilines_in_sequence(self):
        assert parse([":{", "a", ":}", ":{", "b", ":}"]) == [CodeInput("a"), CodeInput("b")]

    def test_multiline_at_end_no_closing(self):
        # EOF before :} — consumes all remaining lines
        assert parse([":{", "a", "b"]) == [CodeInput("a\nb")]
