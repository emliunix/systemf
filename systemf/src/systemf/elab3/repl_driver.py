"""
REPL driver - string I/O focused wrapper around REPLSession.

Handles command parsing, dispatch, and user interaction.
Commands:
  :browse <mod>     - List exported names from a module
  :info <name>      - Show type/info of a binding
  :import <mod>     - Import a module
  :{ ... :}          - Multi-line input
  :help             - Show help
  :quit, :q          - Exit
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable, Iterator
from pathlib import Path
from typing import Callable

from systemf.elab3.reader_env import ImportSpec, UnqualName
from systemf.elab3.pp_tything import pp_tything
from systemf.elab3.repl_session import REPLSession
from systemf.elab3.types.protocols import REPLSessionProto
from systemf.elab3.types.tything import ACon
from systemf.elab3.val_pp import pp_val
from systemf.elab3.repl_parser import (
    REPLCommand, parse_lines, REPLParseError,
    CodeInput, Browse, Info, Import, Help, Exit,
)
from systemf.utils.location import Location


PROMPT = ">> "
CONTINUE_PROMPT = ".. "


# =============================================================================
# REPL Driver
# =============================================================================

class REPLDriver:
    """String I/O focused REPL driver.

    Wraps a REPLSession and handles interactive command processing.
    Accepts an iterable of lines for testing, or uses input() interactively.
    """
    session: REPLSession
    _lines: Iterable[str] | None
    output: Callable[[str], None]

    def __init__(
        self,
        session: REPLSession,
        lines: Iterable[str] | None = None,
        output: Callable[[str], None] = print,
    ):
        self.session = session
        self._lines = lines
        self.output = output

    def _line_source(self) -> Iterator[str]:
        """Yield lines from iterable or interactive input."""
        if self._lines is not None:
            yield from self._lines
            return
        while True:
            try:
                line = input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                break
            yield line

    async def run(self) -> None:
        """Run the interactive REPL loop."""
        async for out in self._run_iter():
            self.output(out)

    async def _run_iter(self) -> AsyncGenerator[str, None]:
        """Yield output lines. Callers can capture or print them."""
        cmd_iter = parse_lines(self._line_source())
        while True:
            try:
                cmd = next(cmd_iter)
            except StopIteration:
                break
            except REPLParseError as e:
                yield f"*** {e}"
                continue
            match cmd:
                case Exit():
                    break
                case Import() as imp:
                    async for line in self._handle_import_iter(imp):
                        yield line
                case Browse() as br:
                    async for line in self._handle_browse_iter(br.module_name):
                        yield line
                case Info() as info:
                    async for line in self._handle_info_iter(info.name):
                        yield line
                case Help():
                    async for line in self._print_help_iter():
                        yield line
                case CodeInput(code):
                    async for line in self._handle_eval_iter(code):
                        yield line
                case _:
                    yield f"*** unhandled command: {cmd}"

    async def _handle_eval_iter(self, input_text: str) -> AsyncGenerator[str, None]:
        try:
            result = await self.session.eval(input_text)
            if result is not None:
                val, ty = result
                yield pp_val(self.session, val, ty)
        except Exception as e:
            yield f"*** {e}"

    async def _handle_import_iter(self, imp: Import) -> AsyncGenerator[str, None]:
        try:
            self.session.add_import(imp.imp)
            yield f"imported {imp.imp.module}"
        except Exception as e:
            yield f"*** {e}"

    async def _handle_browse_iter(self, mod_name: str) -> AsyncGenerator[str, None]:
        try:
            mod = self.session.ctx.load(mod_name)
            yield f"module {mod.name}"
            if mod.tythings:
                # yield "  bindings:"
                for _, thing in mod.tythings:
                    if isinstance(thing, ACon):
                        continue  # skip data constructors, covered in tycon
                    for line in pp_tything(thing).strip().split("\n"):
                        yield f"    {line}"
        except Exception as e:
            yield f"*** {e}"

    async def _handle_info_iter(self, name_str: str) -> AsyncGenerator[str, None]:
        try:
            results = self.session.reader_env.lookup(UnqualName(name_str))
            if not results:
                yield f"*** name not in scope: {name_str}"
                return

            for elt in results:
                name = elt.name
                thing = self.session.lookup(name)
                yield _pp_info_name(name.mod, name.surface, name.loc)
                for line in pp_tything(thing).strip().split("\n"):
                    yield f"  {line}"
        except Exception as e:
            yield f"*** {e}"

    async def _print_help_iter(self) -> AsyncGenerator[str, None]:
        yield "Commands:"
        yield "  :browse <mod>     List exports from module"
        yield "  :info <name>      Show type/info of a binding"
        yield "  :import <mod>     Import a module"
        yield "  :{ ... :}         Multi-line input"
        yield "  :help             Show this help"
        yield "  :quit, :q, :exit  Exit the REPL"


def _pp_info_name(mod: str, surface: str, loc: Location | None) -> str:
    header = f"{mod}.{surface}"
    if loc is None:
        return header
    return f"{header}  -- defined at {_pp_loc(loc.file, loc.line, loc.column)}"


def _pp_loc(file: str | None, line: int, column: int) -> str:
    if file is None:
        return f"line {line}:{column}"
    try:
        path = Path(file)
        if path.is_absolute():
            file = str(path.relative_to(Path.cwd()))
    except ValueError:
        pass
    return f"{file}:{line}:{column}"
