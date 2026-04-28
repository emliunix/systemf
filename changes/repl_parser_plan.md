# REPL Parser Plan

## Conventions

- No `__init__.py` re-exports or `__all__` lists. Keep `__init__.py` empty or minimal.
- No lexer. Simple character-based / string-based parsing using `str.split()`, `str.startswith()`, etc.
- Follow existing project dataclass patterns for AST nodes.

## Module Layout

```
systemf/src/systemf/elab3/repl_parser.py
```

Single file module (simple enough, no package needed).

## Command Types

```python
from dataclasses import dataclass
from typing import Literal
from systemf.elab3.types.ast import ImportDecl

@dataclass(frozen=True)
class Eval:
    """Single line or multiline code to evaluate."""
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
    """:import <import_line> — reuses surface import parser."""
    decl: ImportDecl

@dataclass(frozen=True)
class Help:
    """:help"""
    pass

@dataclass(frozen=True)
class Exit:
    """:exit, :quit, :q"""
    pass

@dataclass(frozen=True)
class MultilineStart:
    """:{ — signals driver to read multiline input."""
    pass

type REPLCommand = Eval | Browse | Info | Import | Help | Exit | MultilineStart
```

## Parse Function

```python
def parse_line(line: str) -> REPLCommand:
    """Parse a single REPL input line.
    
    Returns:
        - MultilineStart for `:{`
        - Exit for `:quit`, `:q`, `:exit`
        - Help for `:help`
        - Browse for `:browse <mod>`
        - Info for `:info <name>`
        - Import for `:import <line>`
        - Eval for everything else (treats as code)
    """
```

Implementation strategy: simple string ops, no parsy needed.

```python
def parse_line(line: str) -> REPLCommand:
    stripped = line.strip()
    
    if not stripped.startswith(":"):
        return Eval(stripped)
    
    # It's a command
    rest = stripped[1:].strip()
    
    if rest == "{" or rest == "{}":
        return MultilineStart()
    
    if rest in ("quit", "q", "exit"):
        return Exit()
    
    if rest == "help":
        return Help()
    
    if rest.startswith("browse "):
        return Browse(rest[7:].strip())
    
    if rest.startswith("info "):
        return Info(rest[5:].strip())
    
    if rest.startswith("import "):
        import_line = "import " + rest[7:].strip()
        decl = _parse_import_line(import_line)
        if decl is None:
            raise REPLParseError(f"invalid import: {rest}")
        return Import(decl)
    
    # Unknown command — treat as eval? or error?
    # Decision: error, user can quote if they want colon at start
    raise REPLParseError(f"unknown command: :{rest.split()[0]}")
```

## Error Type

```python
class REPLParseError(Exception):
    """Error parsing a REPL command."""
    pass
```

## Multiline Handling

Driver responsibility (not parser). Driver reads lines until `:}` and concatenates.

```python
def parse_multiline(lines: list[str]) -> Eval:
    """Parse multiline input into Eval command."""
    return Eval("\n".join(lines))
```

## Reuse Surface Import Parser

Keep existing `_parse_import_line` logic that uses `systemf.surface.parser.lex` + `import_decl_parser`. It's already working.

## Migration Plan

1. Create `systemf/elab3/repl_parser.py` with types + `parse_line()` + `REPLParseError`
2. Update `repl_driver.py` to import from `repl_parser` instead of inline `parse_command()`
3. Remove `Command` dataclass from `repl_driver.py`
4. Update `repl_driver.py` `REPLDriver._loop()` to use `parse_line()`
5. Tests: add `systemf/tests/test_elab3/test_repl_parser.py`

## Files to Modify

- **New**: `systemf/src/systemf/elab3/repl_parser.py`
- **Update**: `systemf/src/systemf/elab3/repl_driver.py` — replace inline parsing with `repl_parser`
- **Update**: `systemf/tests/test_elab3/test_repl_parser.py` — test all command types

## Notes

- Surface parser uses parsy + token-based parsing with layout sensitivity.
- REPL parser is intentionally simpler: char-based, no layout, no tokens.
- `Import` command is the only one that reuses surface parser (for import declarations).
- Empty `__init__.py` in any new packages.
