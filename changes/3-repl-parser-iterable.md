# Change Plan: repl_parser iterable redesign

## Facts

### Current state

`repl_parser.py` (104 lines):
- Exports: `Eval(code)`, `Browse(raw)`, `Info(raw)`, `Import(raw)`, `Help`, `Exit`, `MultilineStart`
- `parse_line(line: str) -> REPLCommand` — single-line dispatch only
- No multiline handling; driver does multiline in `_read_multiline()`
- Import parsing (surface parser) lives in `repl_driver.py._parse_import_line()`

`repl_driver.py` (265 lines):
- `REPLDriver.__init__(session, lines, output)` — accepts optional iterable
- `_run_iter()` calls `parse_line()`, then dispatches; handles `MultilineStart` → `_read_multiline()`
- `_handle_import_iter()` calls `_parse_import_line()` (surface parser)
- Has duplicate `_handle_*` methods (non-iter versions, dead code)

`test_repl_parser.py`:
- Tests `parse_line()` API
- Expects `Browse.module_name`, `Info.name`, `Import.module/qualified/alias` — **currently broken** (Browse has `raw`, Import has `raw`)

### Call sites of `parse_line`
- `repl_driver.py:84` — only call site

### Call sites of `MultilineStart`
- `repl_driver.py:92` — only call site

## Design

### New `repl_parser.py`

**Command dataclasses** (field names match test expectations):

```python
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
    """:import ..."""
    module: str
    qualified: bool
    alias: str | None

@dataclass(frozen=True)
class Help:
    pass

@dataclass(frozen=True)
class Exit:
    pass

type REPLCommand = CodeInput | Browse | Info | Import | Help | Exit
```

Note: `Eval` renamed to `CodeInput`. `MultilineStart` removed (handled internally).

**Helper**:

```python
def parse_line_cmd(line: str, prefix: str, constructor) -> REPLCommand | None:
    """If line starts with :prefix, extract args and call constructor(args).
    Returns None if line doesn't match prefix."""
```

**Import parsing** moves into `repl_parser.py`:

```python
def _parse_import(raw: str) -> Import:
    """Parse ':import <raw>' using surface parser. Raises REPLParseError on failure."""
    from systemf.surface.parser import import_decl_parser, lex
    from parsy import eof
    try:
        tokens = list(lex(f"import {raw}", "<repl import>"))
        decl = (import_decl_parser() << eof).parse(tokens)
        return Import(module=decl.module, qualified=decl.qualified, alias=decl.alias)
    except Exception:
        raise REPLParseError(f"invalid import: {raw}")
```

**Main API**:

```python
def parse_lines(lines: Iterable[str]) -> Iterator[REPLCommand]:
    """Parse an iterable of input lines into REPL commands.
    
    Handles multiline :{ ... :} internally — consumes lines until :}
    and yields a single CodeInput with the concatenated content.
    """
```

**Multiline** consumed inside `parse_lines`:

```python
def _read_multiline(line_iter: Iterator[str], first_line: str) -> CodeInput:
    """Consume lines from iterator until :} and return CodeInput."""
    # first_line is the content after :{ on the opening line (may be empty)
    content_lines: list[str] = []
    if first_line.strip():
        content_lines.append(first_line)
    for line in line_iter:
        if line.strip() == ":}":
            break
        content_lines.append(line)
    return CodeInput("\n".join(content_lines))
```

### Updated `repl_driver.py`

- Import `CodeInput, Browse, Info, Import, Help, Exit` from `repl_parser`
- Remove `MultilineStart` usage
- Replace `parse_line()` call with `parse_lines()` iterated over
- Remove `_read_multiline()` (now in parser)
- Remove `_parse_import_line()` (now in parser)
- `_handle_import_iter()` uses `cmd.module`, `cmd.qualified`, `cmd.alias` directly
- Remove dead `_handle_eval`, `_handle_import`, `_handle_browse`, `_handle_info`, `_print_help` methods

### Updated `test_repl_parser.py`

- Replace `parse_line(s)` with `next(parse_lines([s]))`
- Rename `Eval` → `CodeInput`, `cmd.code` stays
- Add multiline tests using `parse_lines([...])` 
- `Browse.module_name`, `Info.name`, `Import.module/qualified/alias` — already correct in tests

## Why it works

- `parse_lines()` is a generator that pulls from the input iterator, so multiline `:{ ... :}` naturally consumes the next lines from the same iterator
- Driver becomes simpler: iterates `parse_lines(line_iter)` rather than managing multiline state itself
- Import parsing centralized — Tier 2 parse in parser, driver gets fully-parsed `Import`
- Test fixture: `list(parse_lines(["line1", "line2"]))` is trivial

## Files

| File | Action |
|------|--------|
| `systemf/src/systemf/elab3/repl_parser.py` | Rewrite |
| `systemf/src/systemf/elab3/repl_driver.py` | Update imports + dispatch |
| `systemf/tests/test_elab3/test_repl_parser.py` | Update to new API |
