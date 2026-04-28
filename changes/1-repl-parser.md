# Change Plan: REPL Command Parser

## Facts

### Current State

The REPL currently uses inline string parsing in `repl_driver.py` (lines 42-59):

```python
@dataclass(frozen=True)
class Command:
    kind: str
    args: str

def parse_command(line: str) -> Command | None:
    stripped = line.strip()
    if not stripped.startswith(":"):
        return None
    rest = stripped[1:].strip()
    if not rest:
        return Command("", "")
    parts = rest.split(None, 1)
    kind = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    return Command(kind, args)
```

This is used in `REPLDriver._loop()` (lines 99-134) with a big `match` on `cmd.kind`:
- `"quit" | "q"` -> exit
- `"{"` -> read multiline
- `"import"` -> handle import
- `"browse"` -> list module exports  
- `"info"` -> show binding info

The parser is coupled to the driver and uses a generic `Command` type with string fields.

### Existing Parser Conventions

The surface language parser (`systemf/surface/parser/`) uses:
- `parsy` library for parser combinators
- Token-based parsing with layout sensitivity
- Re-exports in `__init__.py` with `__all__`

The REPL parser will be different by design: simple character-based parsing with no lexer.

### Import Parsing

Import commands reuse the surface parser's `import_decl_parser()`. This logic will move from `repl_driver.py` into `repl_parser.py`.

### Call Sites

`parse_command` is only used in `REPLDriver._loop()` in `repl_driver.py`.

## Design

### New Module: `systemf/elab3/repl_parser.py`

The parser is completely self-contained with its own types. It uses a **2-tier parsing strategy**:
1. **Tier 1 (string-based)**: Parse command name and raw args using simple string operations
2. **Tier 2 (thin wrapper)**: For `:import`, delegate to the surface parser to decode the import line

```python
from __future__ import annotations
from dataclasses import dataclass


# =============================================================================
# Command types (own types, no elab3 imports)
# =============================================================================

@dataclass(frozen=True)
class Eval:
    code: str

@dataclass(frozen=True)
class Browse:
    module_name: str

@dataclass(frozen=True)
class Info:
    name: str

@dataclass(frozen=True)
class Import:
    module: str
    qualified: bool
    alias: str | None

@dataclass(frozen=True)
class Help:
    pass

@dataclass(frozen=True)
class Exit:
    pass

@dataclass(frozen=True)
class MultilineStart:
    pass

type REPLCommand = Eval | Browse | Info | Import | Help | Exit | MultilineStart


class REPLParseError(Exception):
    pass


# =============================================================================
# Tier 1: String-based command parser
# =============================================================================

def parse_line(line: str) -> REPLCommand:
    """Parse a single REPL input line.
    
    Tier 1: Simple string-based dispatch on command name.
    """
    stripped = line.strip()
    if not stripped.startswith(":"):
        return Eval(stripped)
    
    rest = stripped[1:].strip()
    if not rest:
        raise REPLParseError("empty command")
    
    if rest == "{" or rest.startswith("{"):
        return MultilineStart()
    if rest in ("quit", "q", "exit"):
        return Exit()
    if rest == "help":
        return Help()
    
    parts = rest.split(None, 1)
    kind = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    
    if kind == "browse":
        if not args:
            raise REPLParseError(":browse requires a module name")
        return Browse(args)
    
    if kind == "info":
        if not args:
            raise REPLParseError(":info requires a name")
        return Info(args)
    
    if kind == "import":
        if not args:
            raise REPLParseError(":import requires a module name")
        # Tier 2: thin wrapper around surface parser
        return _parse_import(args)
    
    raise REPLParseError(f"unknown command: :{kind}")


# =============================================================================
# Tier 2: Thin wrapper for import parsing
# =============================================================================

def _parse_import(args: str) -> Import:
    """Parse import arguments using the surface parser.
    
    This is a thin wrapper: we prepend "import " and let the surface parser
    do the heavy lifting, then encode the result into our own Import type.
    """
    import_line = f"import {args}"
    raw = _parse_import_line(import_line)
    if raw is None:
        raise REPLParseError(f"invalid import: {args}")
    return Import(
        module=raw.module,
        qualified=raw.qualified,
        alias=raw.alias,
    )

def _parse_import_line(line: str):
    """Thin wrapper around surface parser's import_decl_parser."""
    from systemf.surface.parser import import_decl_parser, lex
    from parsy import eof
    try:
        tokens = list(lex(line, "<repl import>"))
        return (import_decl_parser() << eof).parse(tokens)
    except Exception:
        return None
```

### Update `repl_driver.py`

1. Remove `Command` dataclass and `parse_command()` function
2. Remove stale imports: `dataclass`, `import_decl_parser`, `lex`, `eof`, `Path`
3. Import from `repl_parser` instead
4. Update `_loop()` to wrap `parse_line()` in try/except `REPLParseError`
5. Match on `REPLCommand` types instead of string kinds

```python
from .repl_parser import REPLCommand, parse_line, REPLParseError

# In _loop():
try:
    cmd = parse_line(stripped)
except REPLParseError as e:
    self.output(f"*** {e}")
    continue

match cmd:
    case Exit():
        break
    case MultilineStart():
        text = self._read_multiline()
        if text.strip():
            self._handle_eval(text)
    case Import(module, qualified, alias):
        self._handle_import(module, qualified, alias)
    case Browse(mod_name):
        self._handle_browse(mod_name)
    case Info(name_str):
        self._handle_info(name_str)
    case Help():
        self._print_help()
    case Eval(code):
        self._handle_eval(code)
    case _:
        self.output(f"*** unhandled command: {cmd}")
```

6. Update `_handle_import` signature to accept raw fields:

```python
def _handle_import(
    self,
    module: str,
    qualified: bool,
    alias: str | None,
) -> None:
    try:
        self.session.cmd_import(ImportSpec(module, alias, qualified))
        self.output(f"imported {module}")
    except Exception as e:
        self.output(f"*** {e}")
```

7. Add `_print_help()` method:

```python
def _print_help(self) -> None:
    self.output("Commands:")
    self.output("  :browse <mod>     List exports from module")
    self.output("  :info <name>      Show type/info of a binding")
    self.output("  :import <mod>     Import a module")
    self.output("  :{ ... :}         Multi-line input")
    self.output("  :help             Show this help")
    self.output("  :quit, :q, :exit  Exit the REPL")
```

### New Feature: `:help` Command

Adding `:help` is a small new feature (not pure refactoring). It will print:

```
Commands:
  :browse <mod>     List exports from module
  :info <name>      Show type/info of a binding
  :import <mod>     Import a module
  :{ ... :}         Multi-line input
  :help             Show this help
  :quit, :q, :exit  Exit the REPL
```

## Why It Works

1. **Type safety**: Using ADT (algebraic data type) with `match` instead of stringly-typed commands prevents typos and makes exhaustiveness checking possible.
2. **Separation of concerns**: Parser is pure logic, driver handles I/O and side effects.
3. **Simplicity**: No lexer needed since REPL commands have simple, fixed syntax.
4. **Reuses existing import parsing**: Only import commands need the full surface parser.
5. **No __init__.py exports**: Module is imported directly, no re-export list needed.
6. **Error handling**: `REPLParseError` preserves friendly error messages instead of crashing.

## Files

### Create
- `systemf/src/systemf/elab3/repl_parser.py` — new REPL command parser module
- `systemf/tests/test_elab3/test_repl_parser.py` — tests for all command types

### Modify
- `systemf/src/systemf/elab3/repl_driver.py` — replace inline parsing with `repl_parser`

### Delete
- None (inline code in repl_driver.py will be removed, stale imports cleaned up)

## Test Cases

- `parse_line("1 + 2")` -> `Eval("1 + 2")`
- `parse_line(":quit")` -> `Exit()`
- `parse_line(":q")` -> `Exit()`
- `parse_line(":exit")` -> `Exit()`
- `parse_line(":{")` -> `MultilineStart()`
- `parse_line(":help")` -> `Help()`
- `parse_line(":browse builtins")` -> `Browse("builtins")`
- `parse_line(":browse")` -> raises `REPLParseError`
- `parse_line(":info id")` -> `Info("id")`
- `parse_line(":info")` -> raises `REPLParseError`
- `parse_line(":import builtins")` -> `Import(...)`
- `parse_line(":import")` -> raises `REPLParseError`
- `parse_line(":foo")` -> raises `REPLParseError`
- `parse_line(":")` -> raises `REPLParseError`
- `parse_line(": import builtins")` -> `Import(...)` (space after colon is normalized)

## Migration

All existing REPL commands continue to work identically. The change is primarily internal refactoring, with `:help` as a small new feature.
