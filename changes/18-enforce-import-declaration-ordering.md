# Enforce Import Declaration Ordering

## Facts

- `parse_program()` in `surface/parser/__init__.py` is the top-level entry point for parsing a complete module. It delegates to `top_decl_parser()` in `surface/parser/declarations.py`.
- `top_decl_parser()` currently parses declarations in a loop without enforcing ordering constraints. Imports can appear anywhere: before, between, or after other declarations.
- `import_decl_parser()` already correctly parses individual import declarations with qualified, alias, items, and hiding support.
- The `_try_parse_declaration()` helper dispatches `KeywordToken(keyword="import")` to `import_p`.
- Tests:
  - `test_declarations.py` tests `import_decl_parser()` in isolation — no ordering concerns.
  - `test_multiple_decls.py` tests `parse_program()` with the `elab3_syntax_sample` fixture, which already places imports at the top.
  - No existing test covers the "import after declaration" error case.
- The `ElaborationPipeline` (surface pipeline) passes `SurfaceImportDeclaration` through `_run_phase0_desugar` without processing. Import handling is elab3's responsibility (`Rename.do_imports()`).

## Design

### Parser Change

Restructure `top_decl_parser()` in `declarations.py` as two explicit phases:

**Phase 1**: Parse import declarations. Accumulate metadata (docstrings/pragmas) and attach to each import. When the first non-import declaration is encountered, save it and break.

**Phase 2**: Process the saved non-import declaration (metadata accumulated before it gets attached here), then continue parsing only non-import declarations. Any import token in phase 2 produces an error.

```python
# Phase 1: Parse import declarations
saved_decl = None
saved_decl_type = None
saved_new_i = 0

while i < len(tokens):
    # ... metadata accumulation ...
    can_start_decl, decl_result, decl_type, new_i = _try_parse_declaration(...)
    
    if decl_result is not None and decl_type == "import":
        updated_decl = _attach_metadata(decl_result, decl_type, state)
        state = state.with_declaration(updated_decl)
        i = new_i
    elif decl_result is not None:
        # First non-import declaration - save for phase 2
        saved_decl = decl_result
        saved_decl_type = decl_type
        saved_new_i = new_i
        break
    # ... error / skip ...

# Phase 2: Parse non-import declarations
if saved_decl is not None:
    updated_decl = _attach_metadata(saved_decl, saved_decl_type, state)
    state = state.with_declaration(updated_decl)
    i = saved_new_i

while i < len(tokens):
    # ... metadata accumulation ...
    can_start_decl, decl_result, decl_type, new_i = _try_parse_declaration(...)
    
    if decl_result is not None:
        if decl_type == "import":
            return Result.failure(i, "import declarations must appear before other declarations")
        # ... attach metadata, update state ...
    # ... error / skip ...
```

### Test Changes

Add test in `test_multiple_decls.py` (or a new test file) to verify:
1. Imports at top + declarations after → parses successfully.
2. Declaration first + import after → parse error with clear message.
3. Multiple imports scattered (e.g., import, data, import) → parse error.
4. Import-only module → parses successfully.
5. Docstring/pragma before import → parses successfully (metadata silently discarded; `SurfaceImportDeclaration` lacks docstring/pragma fields).

### Error Handling

The error message should be actionable: `"import declarations must appear before other declarations"`. The `_extract_parse_error()` in `__init__.py` will attach line/column info automatically.

**Error index behavior:** `Result.failure(i, ...)` uses the index of the `import` token, so the error report points to the offending import.

**Architectural note:** `SurfaceImportDeclaration` does not support docstrings or pragmas. Metadata accumulated before an import is silently discarded by `_attach_metadata`. This is existing behavior and not changed by this plan.

## Why It Works

- The enforcement happens at the `top_decl_parser` level, which is the correct abstraction — it's the only parser that sees the full sequence of declarations.
- Two explicit phases make the ordering rule self-enforcing: phase 1 consumes imports, phase 2 consumes non-imports. No flag needed.
- Existing tests that already place imports first (`elab3_syntax_sample`) will continue to pass unchanged.
- The change is localized to `top_decl_parser()` and doesn't affect `import_decl_parser()` or any downstream consumer.

## Files

| File | Change |
|------|--------|
| `systemf/src/systemf/surface/parser/declarations.py` | Restructure `top_decl_parser()` into two phases: import phase then non-import phase |
| `systemf/tests/test_surface/test_parser/test_multiple_decls.py` | Add tests for valid and invalid import ordering |
| `systemf/tests/test_surface/test_parser/test_declarations.py` | Verify existing import parser tests still pass (no changes expected) |
