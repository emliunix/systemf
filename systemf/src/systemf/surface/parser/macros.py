"""Source-level macro preprocessing for the surface parser.

`render_macros` performs textual expansion of comment-level macros before
lexing.  Currently supported:

- A comment line containing only `@include "path"` (or `@include 'path'`)
  is replaced in-place by the raw contents of the referenced file.
  Relative paths are resolved against the directory of the file being parsed.

The expansion is intentionally "dumb": no comment syntax is added to or
removed from the included file content.  The directive line itself is replaced
entirely by the file content.  This pass runs before lexing, so it executes
before any comment/docstring concatenation performed by the lexer.
"""

from __future__ import annotations

import re
from pathlib import Path


class MacroError(Exception):
    """Error raised during macro expansion."""

    def __init__(self, message: str, path: Path | None = None):
        prefix = f"{path}: " if path else ""
        super().__init__(f"{prefix}{message}")
        self.path = path


# Matches a single-line comment whose only content is an include directive.
# Captures:
#   1. the quote character used (" or ')
#   2. the path inside the quotes
_INCLUDE_RE = re.compile(
    r"^[ \t]*--[ \t]*(?:\|[ \t]*|\^[ \t]*)?@include[ \t]+([\"'])(.*?)\1[ \t]*(?:\r?\n)?$"
)


def render_macros(file: Path, text: str) -> str:
    """Expand comment macros in source text.

    Args:
        file: Path to the file being parsed.  Used to resolve relative
            include paths and to produce helpful error messages.
        text: Raw source text.

    Returns:
        Source text with macros expanded.

    Raises:
        MacroError: If an include cannot be resolved or a cycle is detected.
    """
    base_dir = file.parent if file else Path.cwd()
    return _expand(text, base_dir, file, set())


def _expand(text: str, base_dir: Path, source_file: Path, seen: set[Path]) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []

    for line in lines:
        match = _INCLUDE_RE.match(line)
        if not match:
            out.append(line)
            continue

        raw_path = match.group(2)
        included_path = _resolve_include(raw_path, base_dir)

        if included_path in seen:
            chain = " -> ".join(str(p) for p in (*seen, included_path))
            raise MacroError(f"cyclic include detected: {chain}", source_file)

        try:
            included_text = included_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise MacroError(
                f"include file not found: {raw_path!r} (resolved to {included_path})",
                source_file,
            ) from exc
        except OSError as exc:
            raise MacroError(
                f"could not read include file {raw_path!r}: {exc}",
                source_file,
            ) from exc

        # Recursively expand macros inside the included file.  The base
        # directory for nested includes is the included file's parent dir.
        expanded = _expand(
            included_text,
            included_path.parent,
            included_path,
            seen | {included_path},
        )

        # Replace the directive line with the raw included content.
        out.append(expanded)

    return "".join(out)


def _resolve_include(raw_path: str, base_dir: Path) -> Path:
    """Resolve an include path relative to the current file's directory."""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
