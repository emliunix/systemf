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

import readline  # noqa: F401 — hooks into input() for line editing + history
from collections.abc import Iterable, Iterator
from typing import Callable

from systemf.elab3.reader_env import ImportSpec, UnqualName
from systemf.elab3.pp_tything import pp_tything
from systemf.elab3.types.tything import ACon
from systemf.elab3.val_pp import pp_val
from systemf.elab3.repl_parser import (
    REPLCommand, parse_lines, REPLParseError,
    CodeInput, Browse, Info, Import, Help, Exit,
)


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

    def __init__(
        self,
        session,
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

    def run(self) -> None:
        """Run the interactive REPL loop."""
        self.output("elab3 repl  (:browse <mod>  :info <name>  :import <mod>  :{ .. :}  :help  :quit)")
        for out in self._run_iter():
            self.output(out)

    def _run_iter(self) -> Iterator[str]:
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
                    yield from self._handle_import_iter(imp)
                case Browse() as br:
                    yield from self._handle_browse_iter(br.module_name)
                case Info() as info:
                    yield from self._handle_info_iter(info.name)
                case Help():
                    yield from self._print_help_iter()
                case CodeInput(code):
                    yield from self._handle_eval_iter(code)
                case _:
                    yield f"*** unhandled command: {cmd}"

    def _handle_eval_iter(self, input_text: str) -> Iterator[str]:
        try:
            result = self.session.eval(input_text)
            if result is not None:
                val, ty = result
                yield pp_val(self.session, val, ty)
        except Exception as e:
            yield f"*** {e}"

    def _handle_import_iter(self, imp: Import) -> Iterator[str]:
        try:
            self.session.cmd_import(imp.spec)
            yield f"imported {imp.spec.module_name}"
        except Exception as e:
            yield f"*** {e}"

    def _handle_browse_iter(self, mod_name: str) -> Iterator[str]:
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

    def _handle_info_iter(self, name_str: str) -> Iterator[str]:
        try:
            results = self.session.reader_env.lookup(UnqualName(name_str))
            if not results:
                yield f"*** name not in scope: {name_str}"
                return

            for elt in results:
                name = elt.name
                thing = self.session.lookup(name)
                yield f"{name}"
                for line in pp_tything(thing).strip().split("\n"):
                    yield f"  {line}"
        except Exception as e:
            yield f"*** {e}"

    def _print_help_iter(self) -> Iterator[str]:
        yield "Commands:"
        yield "  :browse <mod>     List exports from module"
        yield "  :info <name>      Show type/info of a binding"
        yield "  :import <mod>     Import a module"
        yield "  :{ ... :}         Multi-line input"
        yield "  :help             Show this help"
        yield "  :quit, :q, :exit  Exit the REPL"
