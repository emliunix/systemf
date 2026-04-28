# Change Plan: Add Literal Pattern Support to Surface Parser

## Facts

- The surface parser currently supports these pattern forms in `case` expressions:
  - Variable patterns: `x`
  - Constructor patterns: `Cons x xs`, `Pair (x, y) z`
  - Tuple patterns: `(x, y)`
  - Cons patterns: `x : xs`
- The `SurfaceBranch` AST node stores `pattern: SurfacePattern | SurfacePatternTuple | SurfacePatternCons | None`.
- `SurfacePattern` stores constructor/variable patterns as `constructor: str` and `vars: list[str]`, which flattens nested arguments to strings.
- `syntax.md` section 3.6 shows literal patterns in examples: `case x of 0 -> "zero" | n -> "non-zero"`.
- The parser's `pattern_base_parser()` only tries `IdentifierToken`; `NumberToken` and `StringToken` are not attempted, so literal patterns fail with "expected pattern".
- `elab3/ast.py` has a dedicated `LitPat(prim_type, value)` for literal patterns in the core AST.
- The scope checker (`scope_pass.py`, `checker.py`) uses `_collect_pattern_vars()` to extract bound variables from patterns. Literal patterns bind no variables.
- The cons-pattern desugaring pass (`cons_pattern_pass.py`) recursively walks patterns but has no case for literals.

## Design

### Option A: Reuse `SurfaceLit` in patterns
Add `SurfaceLit` as a valid pattern type in `SurfaceBranch.pattern` and the pattern parsers.

**Pros:** Minimal type additions. `SurfaceLit` already has `prim_type` and `value`.
**Cons:** Mixes expression AST nodes into pattern positions.

### Option B: Add `SurfaceLitPattern` wrapper
Create a dedicated `@dataclass(frozen=True, kw_only=True) class SurfaceLitPattern(SurfaceNode)` with `prim_type: str` and `value: object`.

**Pros:** Clean separation between expressions and patterns. Mirrors `elab3` `LitPat`.
**Cons:** One more dataclass. Requires a conversion step to `SurfaceLit` or `LitPat` later.

### Decision: Option A
Rationale: The surface AST is intentionally simpler than `elab3`. `SurfaceLit` is already a pure data container with no expression-specific behavior. Reusing it avoids type proliferation and matches the pragmatic style of the surface codebase (e.g., `SurfacePattern` already uses `list[str]` instead of a proper nested pattern type).

### Changes
1. **AST type (`systemf/src/systemf/surface/types.py`)**
   - Update `SurfaceBranch.pattern` annotation to include `SurfaceLit`.

2. **Pattern parsers (`systemf/src/systemf/surface/parser/expressions.py`)**
   - `pattern_atom_parser()`: try `NumberToken` and `StringToken` before falling back to `IdentifierToken`.
   - `pattern_base_parser()`: same literal token attempts at the top level.
   - `pattern_cons_parser()` and `pattern_parser()`: update return type annotations to include `SurfaceLit`.

3. **Scope checking (`systemf/src/systemf/surface/scoped/scope_pass.py`, `checker.py`)**
   - `_collect_pattern_vars()`: add `SurfaceLit()` case returning `[]`.

4. **Desugaring (`systemf/src/systemf/surface/desugar/cons_pattern_pass.py`)**
   - `_desugar_pattern()`: pass `SurfaceLit` through unchanged.
   - `_collect_pattern_vars()`: add `SurfaceLit()` case returning `[]`.

5. **Tests (`systemf/tests/test_surface/test_parser/test_expressions.py`)**
   - Add `test_case_with_int_literal_pattern`
   - Add `test_case_with_string_literal_pattern`

## Why It Works

- `SurfaceLit` is a frozen dataclass with no expression-specific methods, so using it in pattern positions is semantically harmless.
- Literal patterns bind no variables, so adding an empty `SurfaceLit` case to `_collect_pattern_vars` is correct.
- The cons-pattern desugar pass only needs to recognize that literals should not be transformed.
- The parser change is localized: we only add token matching in the two pattern atom/base parsers, following the existing `.optional()` style.

## Files

- `systemf/src/systemf/surface/types.py` — change `SurfaceBranch.pattern` type
- `systemf/src/systemf/surface/parser/expressions.py` — add literal token matching to pattern parsers
- `systemf/src/systemf/surface/scoped/scope_pass.py` — add `SurfaceLit` to `_collect_pattern_vars`
- `systemf/src/systemf/surface/scoped/checker.py` — add `SurfaceLit` to `_collect_pattern_vars`
- `systemf/src/systemf/surface/desugar/cons_pattern_pass.py` — add `SurfaceLit` handling
- `systemf/tests/test_surface/test_parser/test_expressions.py` — add literal pattern tests
