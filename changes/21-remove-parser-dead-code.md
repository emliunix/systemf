# Remove Dead Code from declarations.py

**References**: `changes/19-parser-architecture-refactor.md`, `changes/20-parser-cleanup-and-test-debt.md`  
**Status**: Pending review

---

## Facts

After change #19 refactored `top_decl_parser()` to use parsy combinators with `RawDecl` and `consolidate()`, three functions/classes in `declarations.py` became **fully unreachable**:

### 1. `_ParserState` (lines 51–97)

An immutable accumulator dataclass used by the old manual-loop `top_decl_parser()`. It tracked:
- `declarations: list[SurfaceDeclaration]`
- `current_docstrings: list[str]`
- `current_pragmas: dict[str, str]`

Methods: `with_docstring()`, `with_pragma()`, `with_declaration()`, `get_docstring()`, `get_pragmas()`

**Why dead**: The new `top_decl_parser()` uses `@generate` + `RawDecl` + `consolidate()` instead. Metadata is accumulated in local variables within the `@generate` function, not in a state object.

### 2. `_try_parse_declaration()` (lines 587–634)

A manual dispatch table that tried each sub-parser based on token type:
- `KeywordToken("data")` → `data_p`
- `KeywordToken("prim_type")` → `prim_type_p`
- `KeywordToken("prim_op")` → `prim_op_p`
- `KeywordToken("import")` → `import_p`
- `IdentifierToken` → `term_p`

**Why dead**: The new `top_decl_parser()` uses `alt(data_parser(), term_parser(), prim_type_parser(), prim_op_parser())` from parsy, which handles dispatch natively.

### 3. `_attach_metadata()` (lines 636–690)

Attached accumulated docstrings/pragmas to declarations by type, using manual `match decl_type` and reconstructing each declaration type.

**Why dead**: The new `consolidate()` function uses `dataclasses.replace()` to attach metadata generically, without type-specific reconstruction.

---

## Design

Delete all three definitions from `systemf/src/systemf/surface/parser/declarations.py`.

**Scope**: Pure deletion. No new code. No behavior change.

---

## Why It Works

- **Verified unreachable**: `grep` confirms zero call sites for `_ParserState`, `_try_parse_declaration`, or `_attach_metadata` in `src/` or `tests/`.
- **No exports**: None of the three are in `__all__`.
- **Parser tests pass**: `240 passed` in current state with dead code present. Removing it won't change behavior.
- **Import cleanup**: `field` (line 16) is only used by `_ParserState` and should be removed as part of the same cleanup.

---

## Files

### To Modify
- `systemf/src/systemf/surface/parser/declarations.py` — Delete `_ParserState` (lines 51–97), `_try_parse_declaration` (lines 587–634), `_attach_metadata` (lines 636–690), and remove `field` from `dataclasses` import (line 16) since it's only used by `_ParserState`

---

## Verification

```bash
uv run pytest systemf/tests/test_surface/test_parser/ -q
```

Expected: 240 passed.
