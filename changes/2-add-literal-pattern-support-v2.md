# Change Plan: Add Literal Pattern Support to Surface Parser (v2)

**Previous plan:** `changes/1-add-literal-pattern-support.md`

## Why a new plan

The previous plan chose Option A (reuse `SurfaceLit` in pattern positions). Review found this violates domain separation between expressions and patterns. This plan introduces a dedicated pattern type hierarchy instead.

## Facts

- The surface parser currently supports these pattern forms in `case` expressions:
  - Variable patterns: `x`
  - Constructor patterns: `Cons x xs`, `Pair (x, y) z`
  - Tuple patterns: `(x, y)`
  - Cons patterns: `x : xs`
- `SurfaceBranch.pattern` currently stores `SurfacePattern | SurfacePatternTuple | SurfacePatternCons | None`.
- `SurfacePattern` stores constructor/variable patterns as `constructor: str` and `vars: list[str]`, which flattens nested arguments to strings.
- `syntax.md` section 3.6 shows literal patterns in examples: `case x of 0 -> "zero" | n -> "non-zero"`.
- The parser's `pattern_base_parser()` only tries `IdentifierToken`; `NumberToken` and `StringToken` are not attempted, so literal patterns fail with "expected pattern".
- `elab3/ast.py` has a dedicated `LitPat(prim_type, value)` for literal patterns in the core AST.
- The scope checker (`scope_pass.py`, `checker.py`) uses `_collect_pattern_vars()` to extract bound variables from patterns. Literal patterns bind no variables.
- The cons-pattern desugaring pass (`cons_pattern_pass.py`) recursively walks patterns but has no case for literals.
- `equals_ignore_location` in `systemf/utils/ast_utils.py` is the project's standard structural equality helper.

## Design

### Pattern type hierarchy

Introduce a proper base class for all surface patterns:

```python
class SurfacePatternBase(SurfaceNode):
    """Base class for all surface patterns."""
    pass
```

All existing pattern types inherit from it:
- `SurfacePattern(SurfacePatternBase)`
- `SurfacePatternTuple(SurfacePatternBase)`
- `SurfacePatternCons(SurfacePatternBase)`

Add a new literal pattern type:

```python
@dataclass(frozen=True, kw_only=True)
class SurfaceLitPattern(SurfacePatternBase):
    """Literal pattern: 42, \"hello\"."""
    prim_type: str = ""
    value: object = None
```

### Fix `SurfacePattern.vars`

Change `SurfacePattern.vars` from `list[str]` to `list[SurfacePatternBase]`. This allows the AST to truthfully represent nested constructor arguments (e.g., `Cons (Pair x y) zs`) instead of flattening them to strings.

### Update `SurfaceBranch.pattern`

Change the type from the union `SurfacePattern | SurfacePatternTuple | SurfacePatternCons | None` to `SurfacePatternBase | None`.

### Update `_collect_pattern_vars`

In `scope_pass.py`, `checker.py`, and `cons_pattern_pass.py`:
- Change the parameter type to `SurfacePatternBase`
- Add a `SurfaceLitPattern()` case returning `[]`
- For `SurfacePattern(vars=vars)`, recurse on each element of `vars` instead of returning the list directly

### Parser changes

In `expressions.py`:
- `pattern_atom_parser()`: try `NumberToken` and `StringToken`, returning `SurfaceLitPattern`
- `pattern_base_parser()`: same literal token attempts at the top level; build `SurfacePattern` with `vars` containing actual pattern AST nodes
- `pattern_cons_parser()` and `pattern_parser()`: return `SurfacePatternBase`

### Tests

- `test_expressions.py`: add `test_case_with_int_literal_pattern` and `test_case_with_string_literal_pattern` using `equals_ignore_location`
- `test_multiple_decls.py`: `test_elab3_sample_program` uses the new `SurfaceLitPattern` and `equals_ignore_location`

## Why It Works

- A unified `SurfacePatternBase` hierarchy eliminates the union type soup in `SurfaceBranch.pattern` and makes the AST extensible.
- `SurfaceLitPattern` keeps patterns and expressions cleanly separated, matching the `elab3` `LitPat` design.
- `SurfacePattern.vars: list[SurfacePatternBase]` finally allows the AST to represent nested patterns truthfully instead of stringifying them.
- `_collect_pattern_vars` recursing on `vars` is correct because each element is now a proper pattern node.
- The parser changes are localized: we only add token matching in the two pattern atom/base parsers, following the existing `.optional()` style.

## Files

- `systemf/src/systemf/surface/types.py` — add `SurfacePatternBase`, `SurfaceLitPattern`; update `SurfacePattern.vars` and `SurfaceBranch.pattern`
- `systemf/src/systemf/surface/parser/expressions.py` — add literal token matching to pattern parsers, return `SurfacePatternBase`
- `systemf/src/systemf/surface/scoped/scope_pass.py` — update `_collect_pattern_vars` to use `SurfacePatternBase` and recurse
- `systemf/src/systemf/surface/scoped/checker.py` — same `_collect_pattern_vars` update
- `systemf/src/systemf/surface/desugar/cons_pattern_pass.py` — add `SurfaceLitPattern` handling and recurse on `vars`
- `systemf/tests/test_surface/test_parser/test_expressions.py` — add literal pattern tests
- `systemf/tests/test_surface/test_parser/test_multiple_decls.py` — add comprehensive sample program test
