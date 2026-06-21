"""Source-level macro preprocessing for the surface parser.

`expand_comment_macros` performs textual expansion of `@include` directives
inside stripped comment text.  It is called by the comment parser after
comment syntax (`--`, `|`, `^`) has been removed and consecutive comment lines
have been joined, but before the resulting docstring is attached to the AST.

Currently supported:

- `@include("path")` (or `@include('path')`) anywhere inside a comment
  string is replaced by the raw contents of the referenced file.
- Relative paths are resolved against the directory of the file being parsed.
- Included files may themselves contain `@include` directives; cycles are
  detected and rejected.
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


# Matches an @include directive inside stripped comment text.
_INCLUDE_RE = re.compile(r"@include\s*\(\s*([\"'])(.*?)\1\s*\)")


def expand_comment_macros(text: str, source_file: Path) -> str:
    """Expand @include directives inside a comment string.

    Args:
        text: Comment text after comment syntax has been stripped.
        source_file: Path to the file containing the comment. Used to
            resolve relative include paths and produce helpful errors.

    Returns:
        Comment text with @include directives expanded.

    Raises:
        MacroError: If an include cannot be resolved or a cycle is detected.
    """
    base_dir = source_file.parent if source_file else Path.cwd()
    return _expand(text, base_dir, source_file, set())


def _expand(text: str, base_dir: Path, source_file: Path, seen: set[Path]) -> str:
    result: list[str] = []
    pos = 0

    for match in _INCLUDE_RE.finditer(text):
        result.append(text[pos : match.start()])
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

        result.append(expanded)
        pos = match.end()

    result.append(text[pos:])
    return "".join(result)


def _resolve_include(raw_path: str, base_dir: Path) -> Path:
    """Resolve an include path relative to the current file's directory."""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
