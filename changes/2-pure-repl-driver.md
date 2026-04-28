# Change Plan: Pure REPL Driver (v2)

## Requirements Summary

**Core principle**: REPLDriver must be a pure function: `Iterable[str] -> Iterable[str]`.

- **Input**: ONLY `Iterable[str]` — no `input()`, no optional fallback
- **Output**: Yields output strings via `Iterator[str]`
- **Interactive layer**: `repl_main.py` handles `input()` and passes lines to driver
- **Tier 1**: `repl_parser.py` — command name + raw string args
- **Tier 2**: `repl_driver.py` — parses content with surface parser where needed

## Design

### repl_parser.py (unchanged from v1)

Same as current: parses command name + raw string. No changes needed.

### repl_driver.py (complete rewrite)

```python
from collections.abc import Iterable, Iterator

class REPLDriver:
    def __init__(self, session):
        self.session = session
    
    def run(self, lines: Iterable[str]) -> Iterator[str]:
        """Pure driver: takes lines, yields output."""
        line_iter = iter(lines)
        
        while True:
            try:
                line = next(line_iter)
            except StopIteration:
                break
            
            stripped = line.strip()
            if not stripped:
                continue
            
            try:
                cmd = parse_line(stripped)
            except REPLParseError as e:
                yield f"*** {e}"
                continue
            
            match cmd:
                case Exit():
                    break
                case MultilineStart():
                    text = self._read_multiline(line_iter)
                    if text.strip():
                        yield from self._eval_iter(text)
                case Import(raw):
                    yield from self._import_iter(raw)
                case Browse(raw):
                    yield from self._browse_iter(raw)
                case Info(raw):
                    yield from self._info_iter(raw)
                case Help():
                    yield from self._help_iter()
                case Eval(code):
                    yield from self._eval_iter(code)
    
    def _read_multiline(self, line_iter: Iterator[str]) -> str:
        """Read until :} from the provided iterator."""
        lines = []
        for line in line_iter:
            if line.strip() == ":}":
                break
            lines.append(line)
        return "\n".join(lines)
    
    def _eval_iter(self, code: str) -> Iterator[str]:
        ...
    
    def _import_iter(self, raw: str) -> Iterator[str]:
        # Parse import line with surface parser (tier 2)
        ...
    
    def _browse_iter(self, raw: str) -> Iterator[str]:
        ...
    
    def _info_iter(self, raw: str) -> Iterator[str]:
        ...
    
    def _help_iter(self) -> Iterator[str]:
        ...
```

### repl_main.py (handles interactive input)

```python
def main() -> None:
    search_paths = sys.argv[1:] if len(sys.argv) > 1 else None
    ctx, session = make_session(search_paths)
    driver = REPLDriver(session)
    
    print("elab3 repl  (:browse <mod>  :info <name>  :import <mod>  :{ .. :}  :help  :quit)")
    
    # Read lines interactively and feed to driver
    def input_lines():
        while True:
            try:
                yield input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                yield ""
                break
    
    for output in driver.run(input_lines()):
        print(output)
```

## Key Decisions

1. **No `input()` in driver**: Driver is fully testable with string lists
2. **No `print()` in driver**: Driver yields strings, caller decides output
3. **`_read_multiline` takes iterator**: Consumes continuation lines from the same iterable
4. **Tier 2 in driver**: Import parsing, expression evaluation happen in driver, not parser

## Files

- `systemf/src/systemf/elab3/repl_driver.py` — rewrite
- `systemf/src/systemf/elab3/repl_main.py` — update to feed `input()` lines
- `systemf/src/systemf/elab3/repl_parser.py` — no changes
- `systemf/tests/test_elab3/test_repl_driver.py` — new tests using list inputs
