# Change Plan: Shallow `_collect_pattern_vars` for Nested Patterns

**Previous plan:** `changes/2-add-literal-pattern-support-v2.md`

## Why a new plan

Plan v2 changed `SurfacePattern.vars` from `list[str]` to `list[SurfacePatternBase]` and stated that `_collect_pattern_vars` should "recurse on each element of `vars`". During implementation, review found that deep recursion changes the semantics of `_collect_pattern_vars` and breaks the assumption of existing callers (e.g. `checker.py`, `scope_pass.py`, `bidi_inference.py`) that the function returns a flat `list[str]` of variable names bound at the *current* pattern level. This plan keeps the return type `list[str]` and makes collection shallow.

## Facts

- `_collect_pattern_vars` is called in `checker.py`, `scope_pass.py`, `cons_pattern_pass.py`, and `bidi_inference.py`.
- All callers expect `list[str]` and use it to extend the scope context with bound variable names.
- The old AST represented constructor arguments as `list[str]` (e.g. `Pair a b` → `vars=["a", "b"]`). The new AST represents them as `list[SurfacePatternBase]` (e.g. `vars=[SurfacePattern("a"), SurfacePattern("b")]`).
- Deep recursion into nested constructor patterns (e.g. `Cons (Pair a b) zs`) would extract `a`, `b` from an inner `Pair`, which changes the binding order/semantics that the old code assumed.
- To keep old code working with minimal edits, `_collect_pattern_vars` should only look at **immediate children** that are bare variable patterns (`SurfacePattern` with empty `vars`).

## Design

### `_collect_pattern_vars` semantics

Return type stays `list[str]`.

For each pattern type:
- `SurfacePattern(constructor=c, vars=vars)`:
  - If `vars` is empty → variable pattern → return `[c]`
  - Otherwise → constructor pattern → scan immediate children in `vars`; for each child that is a `SurfacePattern` with empty `vars`, extract its `constructor`. **Do not recurse deeper.**
- `SurfacePatternTuple(elements=elements)`:
  - Scan immediate elements; for each that is a `SurfacePattern` with empty `vars`, extract its `constructor`. **No deep recursion.**
- `SurfacePatternCons(head=head, tail=tail)`:
  - Same shallow logic for `head` and `tail`.
- `SurfaceLitPattern()`:
  - Return `[]` (binds no variables).

### `_extract_pattern_var_names` in `bidi_inference.py`

Apply the same shallow logic so that type inference stays consistent with scope checking.

## Why It Works

- The return type `list[str]` is preserved, so no caller needs to change how it consumes the result.
- Only looking at immediate children matches the old behavior: in the old AST, `vars` was already a flat list of variable names for the current constructor level.
- Nested constructor patterns like `Cons (Pair a b) zs` are not yet deeply supported by the downstream pipeline anyway; keeping collection shallow avoids pretending they are.

## Files

- `systemf/src/systemf/surface/scoped/checker.py` — make `_collect_pattern_vars` shallow, return `list[str]`
- `systemf/src/systemf/surface/scoped/scope_pass.py` — same
- `systemf/src/systemf/surface/desugar/cons_pattern_pass.py` — same
- `systemf/src/systemf/surface/inference/bidi_inference.py` — make `_extract_pattern_var_names` shallow
