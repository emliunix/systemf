# Parser Architecture Refactor: Separate Import and Declaration Parsers

## Problem

`top_decl_parser()` currently handles both imports and non-import declarations in a single monolithic function with two duplicated `while` loops. This mixes concerns:

- Import ordering enforcement is tangled with declaration parsing
- Metadata accumulation (docstrings/pragmas) is duplicated in both phases
- `_ParserState` is mutated across both phases, creating implicit coupling
- The `saved_decl` / `saved_decl_type` / `saved_new_i` variables are a manual hand-off hack
- `parse_program()` returns a flat `list[SurfaceDeclaration]`, forcing downstream code to filter imports

## Architecture

Split into three layers:

```
parse_program (orchestrator)
  ├─ top_import_parser()  → list[SurfaceImportDeclaration]
  └─ top_decl_parser()    → list[RawDecl]
      └─ consolidate()    → list[SurfaceDeclaration]
```

### Layer 1: `top_import_parser()`

- Uses parsy combinators: `many()` + `alt()` + `>>`
- Skips docstrings/pragmas before imports (imports don't carry metadata)
- Stops naturally at first non-import token
- Returns `list[SurfaceImportDeclaration]`

### Layer 2: `top_decl_parser()`

- Uses parsy combinators: `@generate` + `many()` + `alt()`
- Collects metadata tokens into `RawDecl` but does NOT attach them
- Parses only non-import declarations
- Returns `list[RawDecl]`

### Layer 3: `consolidate()`

- Pure function, no parser state
- Walks `list[RawDecl]` and uses `dataclasses.replace()` to attach docstrings/pragmas
- Called by `parse_program()`, not by the parser itself

### Layer 4: Import Ordering Enforcement

After `top_decl_parser` finishes parsing, check the remaining token stream for `ImportToken`. If any import tokens remain, raise the existing error: `"import declarations must appear before other declarations"`. This preserves the behavior from change #18.

### Orchestrator: `parse_program()`

- Calls `top_import_parser().parse_partial(tokens)` → gets imports + remaining tokens
- Calls `top_decl_parser().parse_partial(remaining)` → gets raw declarations
- Calls `consolidate(raw_decls)` → gets final declarations
- Returns `tuple[list[SurfaceImportDeclaration], list[SurfaceDeclaration]]`

## Detailed Changes

### New: `RawDecl` type

```python
@dataclass
class RawDecl:
    docstrings: list[str]
    pragmas: dict[str, str]
    decl: SurfaceDeclaration
```

### New: `top_import_parser()`

```python
def top_import_parser() -> P[list[SurfaceImportDeclaration]]:
    skip_meta = many(alt(match_docstring(), match_pragma()))
    import_entry = skip_meta >> import_decl_parser()
    return import_entry.many()
```

### Refactor: `top_decl_parser()`

Replace the two-phase manual loop with:

```python
def top_decl_parser() -> P[list[RawDecl]]:
    @generate
    def entry():
        meta = yield many(alt(match_docstring(), match_pragma()))
        decl = yield alt(data_parser(), term_parser(), prim_type_parser(), prim_op_parser())
        
        docstrings = [t.content for t in meta if isinstance(t, DocstringToken)]
        pragmas = {t.key: t.value for t in meta if isinstance(t, PragmaToken)}
        return RawDecl(docstrings, pragmas, decl)
    
    return entry.many()
```

**Unknown token behavior**: The proposed `entry.many()` stops on unknown tokens (different from current behavior which skips them via `i += 1`). This is acceptable — unknown tokens at the top level indicate malformed input, and failing fast is better than silently skipping.

### New: `consolidate()`

```python
from dataclasses import replace

def consolidate(raw_decls: list[RawDecl]) -> list[SurfaceDeclaration]:
    result = []
    for rd in raw_decls:
        docstring = " ".join(rd.docstrings) if rd.docstrings else None
        pragmas = dict(rd.pragmas) if rd.pragmas else None
        result.append(replace(rd.decl, docstring=docstring, pragma=pragmas))
    return result
```

### New: `match_docstring()` and `match_pragma()`

```python
def match_docstring() -> P[DocstringToken]:
    @P
    def parser(tokens, i):
        if i < len(tokens) and isinstance(tokens[i], DocstringToken):
            return Result.success(i + 1, tokens[i])
        return Result.failure(i, "expected docstring")
    return parser

def match_pragma() -> P[PragmaToken]:
    @P
    def parser(tokens, i):
        if i < len(tokens) and isinstance(tokens[i], PragmaToken) and tokens[i].key:
            return Result.success(i + 1, tokens[i])
        return Result.failure(i, "expected pragma")
    return parser
```

### Refactor: `parse_program()`

```python
def parse_program(source: str, filename: str = "<stdin>") -> tuple[
    list[SurfaceImportDeclaration], 
    list[SurfaceDeclaration]
]:
    tokens = list(lex(source, filename))
    
    imports, rest = top_import_parser().parse_partial(tokens)
    raw_decls, remainder = top_decl_parser().parse_partial(rest)
    decls = consolidate(raw_decls)
    
    # Preserve import ordering error from change #18
    for token in remainder:
        if isinstance(token, ImportToken):
            loc = getattr(token, 'location', None)
            raise ParseError("import declarations must appear before other declarations", loc)
    
    return imports, decls
```

### Refactor: `Parser.parse()`

The `Parser` class in `__init__.py` currently wraps `top_decl_parser`. It should be updated to call `parse_program` instead, or return the tuple.

## Impact Analysis

### Files to Change

| File | Change |
|------|--------|
| `systemf/src/systemf/surface/parser/declarations.py` | Add `top_import_parser()`, refactor `top_decl_parser()`, add `match_docstring()` / `match_pragma()`, add `RawDecl` / `consolidate()`, update `__all__`. Remove `_ParserState` / `_attach_metadata` / `_try_parse_declaration` if fully unused. |
| `systemf/src/systemf/surface/parser/__init__.py` | Update `parse_program()` signature and implementation; update `Parser.parse()`; update `__all__` |

### Files with Callers to Update

| File | Call Site | Impact |
|------|-----------|--------|
| `tests/test_surface/test_parser/test_multiple_decls.py` | 30+ calls to `parse_program()` | Change `result = parse_program(...)` to `imports, decls = parse_program(...)` |
| `tests/test_surface/test_parser/test_declarations.py` | `decl_parser()` calls (wraps `top_decl_parser`) | Must update to call `consolidate()` before extracting first decl; ~8 tests affected |
| `tests/test_surface/test_parser/test_cons_regression.py` | `parse_program()` calls | Update destructuring |
| `tests/test_surface/test_scoped_type_vars*.py` | `parse_program()` calls | Update destructuring |
| `tests/test_surface/test_operator_desugar.py` | `parse_program()` calls | Update destructuring |
| `tests/test_surface/test_scoped_type_vars_integration.py` | `parse_program()` calls | Update destructuring |
| `tests/test_eval/test_tool_calls.py` | `parse_program()` calls | Update destructuring |
| `tests/test_llm_files.py` | `parse_program()` calls | Update destructuring |
| `systemf/src/systemf/elab3/pipeline.py` | `parse_program()` call | Update destructuring |
| `docs/_archive/` | References to `parse_program()` | Documentation only, can lag |

### Breaking Changes

- `parse_program()` return type changes from `list[SurfaceDeclaration]` to `tuple[list[SurfaceImportDeclaration], list[SurfaceDeclaration]]`
- `Parser.parse()` return type changes similarly
- `top_decl_parser()` return type changes from `list[SurfaceDeclaration]` to `list[RawDecl]`

### Backward Compatibility

No backward compatibility shim planned — all callers are in-repo tests and internal code. Update them in the same PR.

### Tests

- Existing `TestImportDeclaration` tests — no change (test `import_decl_parser()` directly)
- Existing `TestMultipleDeclarationsParsing` tests — update to destructure tuple
- Add new tests for `top_import_parser()` in isolation
- Add tests for `consolidate()` post-processing
- Verify import ordering still enforced (error on import after declaration)

## Why It Works

- **Separation of concerns**: Import parsing, declaration parsing, and metadata attachment are three distinct phases with clear boundaries
- **No implicit state**: `RawDecl` makes metadata explicit; no `_ParserState` mutation across phases
- **Parsy-native**: Uses `many()`, `alt()`, `>>` combinators instead of manual `while` loops
- **Composability**: `top_import_parser` and `top_decl_parser` are independent parsers that compose via `parse_partial`
- **Testability**: Each layer can be tested in isolation

## Open Questions

1. Should `Parser.parse()` return the tuple or just declarations? (A: Return tuple — caller can ignore imports if needed)
2. Should `match_docstring()` and `match_pragma()` be extracted as reusable token matchers? (A: Yes, they're needed by both parsers)
3. What happens to unknown tokens between imports and declarations? (A: `top_decl_parser` skips them, same as current behavior)
