"""REPL command parser — Tier 1 + Tier 2 parsing.

Takes an Iterable[str] of input lines and yields REPLCommands.
Handles multiline :{ ... :} internally.

Tier 1: command dispatch (:browse, :info, :import, :quit, :help, :{)
Tier 2: argument parsing (Import uses surface parser; Browse/Info extract identifier)
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Callable, TypeVar

from systemf.elab3.reader_env import ImportSpec


# =============================================================================
# Command types
# =============================================================================


@dataclass(frozen=True)
class CodeInput:
    """Single or multiline code to evaluate."""
    code: str


@dataclass(frozen=True)
class Browse:
    """:browse <module_name>"""
    module_name: str


@dataclass(frozen=True)
class Info:
    """:info <name>"""
    name: str


@dataclass(frozen=True)
class Import:
    """:import [qualified] <module> [as <alias>]"""
    spec: ImportSpec


@dataclass(frozen=True)
class Help:
    pass


@dataclass(frozen=True)
class Exit:
    pass


type REPLCommand = CodeInput | Browse | Info | Import | Help | Exit


class REPLParseError(Exception):
    pass


# =============================================================================
# Helpers
# =============================================================================


def _parse_import(raw: str) -> Import:
    """Parse ':import <raw>' using the surface parser. Raises REPLParseError on failure."""
    from systemf.surface.parser import import_decl_parser, lex  # type: ignore[import]
    from parsy import eof  # type: ignore[import]
    try:
        tokens = list(lex(f"import {raw}", "<repl import>"))
        decl = (import_decl_parser() << eof).parse(tokens)
        return Import(ImportSpec(module_name=decl.module, alias=decl.alias, is_qual=decl.qualified))
    except Exception:
        raise REPLParseError(f"invalid import: {raw}")


def _read_multiline(line_iter: Iterator[str], first_line: str) -> CodeInput:
    """Consume lines from iterator until a bare ':}' line, return CodeInput."""
    rest = itertools.takewhile(lambda l: l.strip() != ":}", line_iter)
    lines = ([first_line] if first_line.strip() else []) + list(rest)
    return CodeInput("\n".join(lines))


def _try_commands(cmd_parsers: list[Callable[[str], REPLCommand | None]], line: str) -> REPLCommand | None:
    """Try a list of command parsers on the line, return the first successful one."""
    for parser in cmd_parsers:
        res = parser(line)
        if res is not None:
            return res
    return None


def _line_cmd(cmd: str, constructor: Callable[[str], REPLCommand]) -> Callable[[str], REPLCommand | None]:
    """If line starts with ':prefix', parse it with constructor and return the command."""
    def parser(stripped: str) -> REPLCommand | None:
        prefix = f":{cmd}"
        if not stripped.startswith(prefix):
            return None
        after = stripped[len(prefix):].lstrip()
        return constructor(after)
    return parser


def _check_arg(cmd: str, constructor: Callable[[str], REPLCommand]) -> Callable[[str], REPLCommand]:
    def _go(arg: str) -> REPLCommand:
        if not arg:
           raise REPLParseError(f":{cmd} requires an argument")
        return constructor(arg)
    return _go


def _error_command(stripped: str) -> REPLCommand | None:
    if stripped.startswith(":"):
        raise REPLParseError(f"unknown command: {stripped}")
    return None


# =============================================================================
# Main API
# =============================================================================


def _parse_cmd(stripped: str, line_iter: Iterator[str]) -> REPLCommand:
    """Parse one non-empty stripped line into a command. Mutates line_iter for multiline."""

    if stripped.startswith(":{"):
        return _read_multiline(line_iter, stripped[2:].strip())

    res = _try_commands([
        _line_cmd("q",      lambda _: Exit()),
        _line_cmd("quit",   lambda _: Exit()),
        _line_cmd("exit",   lambda _: Exit()),
        _line_cmd("help",   lambda _: Help()),
        _line_cmd("browse", _check_arg("browse", Browse)),
        _line_cmd("info",   _check_arg("info",   Info)),
        _line_cmd("import", _check_arg("import", _parse_import)),
        _error_command,
        lambda line: CodeInput(line)  # default: treat as code input
    ], stripped)
    if res is not None:
        return res

    raise REPLParseError(f"invalid input")


def parse_lines(lines: Iterable[str]) -> Iterator[REPLCommand]:
    """Parse an iterable of input lines into REPL commands.

    Handles multiline :{ ... :} internally — consumes lines until :}
    and yields a single CodeInput with the concatenated content.

    Yields nothing for blank lines.
    Raises REPLParseError for unknown or malformed commands.
    """
    line_iter = iter(lines)
    for line in line_iter:
        stripped = line.strip()
        if stripped:
            yield _parse_cmd(stripped, line_iter)
