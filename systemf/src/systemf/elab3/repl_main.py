"""
REPL entry point - setup and argument parsing.

Usage:
    cd systemf && uv run python -m systemf.elab3.repl_main
    cd systemf && uv run python -m systemf.elab3.repl_main [search_paths...]
"""

import sys
from pathlib import Path

from systemf.elab3.repl import REPL
from systemf.elab3.repl_driver import REPLDriver


def make_session(search_paths: list[str] | None = None):
    """Create a REPL context and session."""
    if search_paths is None:
        search_paths = [str(Path(__file__).resolve().parent.parent)]
    ctx = REPL(search_paths=search_paths)
    session = ctx.new_session()
    return ctx, session


def main() -> None:
    search_paths = sys.argv[1:] if len(sys.argv) > 1 else None
    ctx, session = make_session(search_paths)
    driver = REPLDriver(session)
    driver.run()


if __name__ == "__main__":
    main()
