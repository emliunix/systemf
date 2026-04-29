# SystemF Elab3 - Project Status

**Last Updated:** 2026-04-30
**Test Count:** 364 elab3 tests + 302 surface tests = 666 total

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
- **Test migration**: All elab2 tests migrated to elab3
- **SurfacePrimTypeDecl docstring support**: Parser supports docstrings attached to type args
- **LLM Agent Synthesizer**: Implemented under `bub_sf/bub_ext`
- **Surface unit/list syntax**: Added syntax-shaped surface nodes and parser support for `()`, `[]`, `[a, b]`, `() ->`, `[T]`, `() -> case`, and list/unit patterns
- **Pattern AST cleanup**: Parser now emits `SurfacePatternSeq` for flat pattern sequences and keeps singleton patterns atomic (`SurfaceVarPattern`, `SurfaceUnitPattern`, `SurfaceListPattern`, etc.)
- **Rename + e2e coverage for new syntax**: `rename_expr.py` updated for new surface nodes; `elab3_demo.py` covers unit/list literals, empty list syntax, nested list syntax, unit/list tuple syntax, and empty list patterns

## Next Steps

1. **Bub primitives for tape**: Add tape operations (append, read, query) as SystemF primitives so SF code can interact with bub's tape-based context model.
2. **More Built-in Types**: `Array`, `Map`, `IO`
3. **Error Handling**: Better typechecker/evaluator error messages
4. **Performance**: Profile evaluator for larger programs
5. **Documentation**: User-facing surface language syntax docs
6. **Ambiguous variable resolution not reported in source files** `#issue`: When a name resolves to multiple candidates (e.g., imported from multiple modules), the renamer currently accepts the first match silently. This is correct behavior for the REPL (where shadowing is allowed), but should be a hard error when loading source code files.
7. **`:info map` doesn't work with builtins imported** `#issue`: Even after importing builtins into the REPL environment, `:info map` fails to resolve or display information for builtin names. The `:info` command should consult the same imported/builtin namespace that expression lookup uses.
8. **Generalization produces unreadable skolem names** `#issue`: Skolem type variables are printed as `$a1234`, which is hard to recognize. Should pick a human-readable representative name (e.g., from the original bound variable) during generalization.
9. **Add e2e coverage for non-exhaustive pattern failures**: The `matchc.py` audit passed: fallible matches are threaded correctly and `typecheck_expr.py` supplies the runtime error handler. We still need an end-to-end test that exercises an actual non-exhaustive `case` or lambda pattern and checks for the `Non-exhaustive patterns` runtime error.
10. **Pretty-print `:info` output**: `:info <name>` currently includes the raw internal `Name(...)` representation before the type. It should use a user-facing pretty-printer so REPL introspection output matches the rest of the interface.

## Entry Points

- **Demo**: `systemf/src/systemf/elab3_demo.py`
- **Extension Demo**: `bub_sf/src/bub_sf/demo.py`
- **REPL**: `cd systemf && uv run python -m systemf.elab3.repl_main`
- **API**: `pipeline.execute(ctx, mod_name, file_path, code)`
