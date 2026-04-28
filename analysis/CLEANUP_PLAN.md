# SystemF Cleanup Plan

## Objective

Remove all code that is not part of the elab3 + surface parser stack. Keep only:
1. `elab3/` - main implementation
2. `surface/parser/` + `surface/types.py` - parser and AST
3. `utils/` - shared utilities
4. `elab3_demo.py`, `demo.sf`, `builtins.sf` - demo files

## Dependency Analysis

### What elab3 imports from outside:
- `systemf.surface.parser` (parse_program, parse_expression, ParseError, lex, import_decl_parser)
- `systemf.surface.types` (SurfaceDeclaration, SurfaceImportDeclaration, SurfaceTermDeclaration, etc.)
- `systemf.utils.location` (Location)
- `systemf.utils.uniq` (Uniq)
- `systemf.utils` (capture_return, run_capture_return, unzip)

### What surface/parser imports:
- `systemf.surface.types` (AST nodes)
- `systemf.utils.location` (Location)
- Internal parser modules only

### What surface/types imports:
- `systemf.utils.location` (Location)

### What utils imports:
- Nothing external (self-contained)

## Keep List

### Source Code (`src/systemf/`)
```
utils/
  __init__.py
  location.py
  uniq.py
  ast_utils.py
  cons.py

surface/
  __init__.py
  types.py
  parser/
    __init__.py
    lexer.py
    helpers.py
    types.py
    expressions.py
    declarations.py
    type_parser.py

elab3/
  __init__.py
  builtins.py
  builtins_rts.py
  core_extra.py
  eval.py
  matchc.py
  name_gen.py
  pipeline.py
  reader_env.py
  rename.py
  rename_expr.py
  repl.py
  repl_driver.py
  repl_session.py
  scc.py
  tc_ctx.py
  typecheck.py
  typecheck_expr.py
  val_pp.py
  types/
    __init__.py
    ast.py
    core.py
    core_pp.py
    mod.py
    protocols.py
    tc.py
    ty.py
    tything.py
    val.py
    wrapper.py
    xpat.py

elab3_demo.py
```

### Test Code (`tests/`)
```
test_elab3/          (all elab3 tests)
test_surface/test_parser/  (parser tests only)
```

### Root Files
```
builtins.sf
demo.sf
pyproject.toml
README.md
```

## Remove List

### Source Code
```
core/                    (separate core language implementation)
elab2/                   (old elaborator)
elaborator/              (old elaborator)
eval/                    (old evaluator)
surface/desugar/         (desugaring passes)
surface/inference/       (type inference - separate from elab3)
surface/scoped/          (scoping passes)
surface/llm/             (LLM pragma passes)
surface/pipeline.py      (surface pipeline)
surface/pass_base.py     (pass infrastructure)
surface/result.py        (result types)
llm/                     (LLM metadata extraction)
```

### Test Code
```
test_core/               (core tests)
test_elab2/              (elab2 tests)
test_elaborator/         (elaborator tests)
test_eval/               (eval tests)
test_surface/            (keep only test_parser/)
  test_inference.py
  test_lexer.py
  test_operator_desugar.py
  test_putting2007_examples.py
  test_putting2007_gaps.py
  test_scope.py
  test_scoped_type_vars.py
  test_scoped_type_vars_comprehensive.py
  test_scoped_type_vars_integration.py
  test_unification.py
test_string.py
test_llm_files.py
test_pipeline.py
test_elab3/test_eval.py  (if it imports eval)
_archive/                (archived tests)
conftest.py              (if only for removed modules)
```

### Other Files
```
All docs/ except what's needed for README
All analysis/ except ELAB3_PROJECT_STATUS.md
```

## Execution Order

1. **Remove source directories** (least risky)
   - Remove `core/`, `elab2/`, `elaborator/`, `eval/`, `llm/`
   - Remove `surface/desugar/`, `surface/inference/`, `surface/scoped/`, `surface/llm/`
   - Remove `surface/pipeline.py`, `surface/pass_base.py`, `surface/result.py`

2. **Update `surface/__init__.py`**
   - Remove exports for removed modules
   - Keep only parser-related exports

3. **Remove test directories**
   - Remove `test_core/`, `test_elab2/`, `test_elaborator/`, `test_eval/`
   - Remove `test_surface/` except `test_parser/`
   - Remove `_archive/`, `test_string.py`, `test_llm_files.py`, `test_pipeline.py`

4. **Verify elab3 tests still pass**
   - Run `test_elab3/` suite
   - Run `test_surface/test_parser/` suite

5. **Update pyproject.toml**
   - Remove dependencies only needed by removed code
   - Update test paths if needed

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| elab3_demo imports removed modules | Check imports first, keep what's needed |
| Tests conftest.py imports removed modules | Update or remove conftest |
| Circular imports surface ↔ elab3 | None expected, they only import from surface.parser/types |
| pyproject.toml references removed paths | Update after cleanup |

## Verification

After cleanup, run:
```bash
cd systemf && uv run python -m systemf.elab3_demo
```

And verify parser tests pass:
```bash
cd systemf && uv run python -m pytest tests/test_surface/test_parser/ -v
```
