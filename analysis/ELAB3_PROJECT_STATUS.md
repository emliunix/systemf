# SystemF Elab3 - Project Status

**Last Updated:** 2026-04-28
**Test Count:** 305 elab3 tests + 280 surface tests = 585 total

## Overview

Elab3 is a module system elaborator for SystemF with bidirectional type inference, Surface-to-Core compilation, and a CEK evaluator. Supports pluggable primitives via the `Synthesizer` protocol.

## Architecture

- **Pipeline** (`pipeline.py`): Parse → Rename → Typecheck
- **Types** (`types/`): Core AST, type representation, values, wrappers
- **Rename** (`rename.py`, `rename_expr.py`, `reader_env.py`): Name resolution, imports
- **Typecheck** (`typecheck.py`, `typecheck_expr.py`, `tc_ctx.py`): Bidirectional inference
- **Eval** (`eval.py`): CEK evaluator
- **Match** (`matchc.py`): Pattern compilation
- **REPL** (`repl.py`, `repl_session.py`, `repl_driver.py`, `repl_main.py`): Interactive environment

## Completed (Short Summary)

- **Codebase cleanup**: Removed elab2/, core/, eval/, llm/, desugar/, inference/, scoped/ dirs
- **SurfaceTypeForall**: Multi-arg `vars: list[str]` — parser, rename, tests updated
- **Pragma/docstring passing**: `pragma_pass.py` rewritten, 7 tests passing
- **Putting2007 rules**: 20/24 migrated (`test_putting2007_rules.py`)
- **Rename tests**: 20 tests (`test_elab3/test_rename.py`)
- **Pretty printer**: `pp_tything.py` with exact string tests (`test_elab3/test_pp_tything.py`, 13 tests)
- **Evaluator env**: Migrated to `PMap` for O(1) frame operations
- **Lookup optimization**: `_tythings_map` + `TyLookup` protocol
- **Synthesizer protocol**: Full implementation with `SyntRouter`, `PrimOpsSynth`, `bub_sf` demo
- **Core builders**: `CoreBuilderExtra` for polymorphic tuple construction
- **REPL refactoring**: Split `repl_driver.py` into `REPLDriver` class (I/O wrapper) and `repl_main.py` (entry point)
- **REPL commands**: Added `:browse <mod>`, `:info <name>`, `:import <mod>`, `:quit`, `:{ ... :}` with dedicated command parser

## Test Migration Status (elab2 → elab3)

| elab2 source | tests | elab3 target | status |
|---|---|---|---|
| `test_eval.py` | 49 | `test_eval.py` | **Done** |
| `test_unify.py` | 23 | `test_unify.py` | **Done** (+2 extras) |
| `test_types.py` | 9 | `test_types.py` | **Done** (+4 extras) |
| `test_tyck_examples_util_rules.py` | 24 | `test_putting2007_rules.py` | **Done** — 26 tests (all 24 + 2 extras) |
| `test_tyck.py` | 2 | `test_types.py` | **Done** — `test_quantify_replaces_meta_vars` migrated |
| `test_tyck_examples_terms.py` | 13 | `test_putting2007_terms.py` | **Done** — 15 tests using parse→rename→typecheck pipeline |

**Remaining:** 0 tests. All elab2 tests migrated.

## Next Steps

1. **SurfacePrimTypeDecl docstring support**: Enhance parser to support docstrings attached to type args. Change type arg params to `TyVar` and use a `TyVar` parser, or craft a `pre_docstring.optional() >> ident << post_docstring.optional()` parser (simpler approach).
2. **LLM Agent Synthesizer**: Implement `LLMSynth.get_primop()`
2. **More Built-in Types**: `Array`, `Map`, `IO`
3. **Error Handling**: Better typechecker/evaluator error messages
4. **Performance**: Profile evaluator for larger programs
5. **Documentation**: User-facing surface language syntax docs
## Entry Points

- **Demo**: `systemf/src/systemf/elab3_demo.py`
- **Extension Demo**: `bub_sf/src/bub_sf/demo.py`
- **REPL**: `cd systemf && uv run python -m systemf.elab3.repl_main`
- **API**: `pipeline.execute(ctx, mod_name, file_path, code)`
