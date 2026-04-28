# Add Literal Pattern Parser Support

**References**: `changes/1-add-literal-pattern-support.md` (older plan), `changes/19-parser-architecture-refactor.md`  
**Status**: COMPLETED

---

## Facts

The surface AST type `SurfaceLitPattern` exists in `systemf/surface/types.py` (line 592) but the parser never supported it. The pattern parser hierarchy (`pattern_parser` → `pattern_cons_parser` → `pattern_base_parser` → `pattern_atom_parser`) only handled:
- `IdentifierToken` (variables/constructors)
- `NumberToken`/`StringToken` (not handled — fell through to failure)
- Tuple patterns `(x, y)`
- Grouped patterns `(pattern)`
- Cons patterns `x : xs`

During change #19 implementation, `pattern_literal_parser()` was added to `expressions.py` to support parsing literal patterns (`0`, `"hello"`) in `case` expressions. This was necessary because the `elab3_syntax_sample` fixture uses literal patterns:

```haskell
case n of
  0 -> 1
  m -> m * factorial (m - 1)
```

The implementation added:
- `pattern_literal_parser()` function
- Literal matching in `pattern_atom_parser()` and `pattern_base_parser()`
- Return type updates for `pattern_cons_parser()` and `pattern_parser()` to include `SurfaceLitPattern`

However, this was **not documented** in any change plan.

---

## Design

### Already Implemented (undocumented)

The following changes are already in the working tree:

**`expressions.py`:**
- `pattern_literal_parser()` — matches `NumberToken` → `SurfaceLitPattern(prim_type="Int", value=int(...))`, `StringToken` → `SurfaceLitPattern(prim_type="String", value=...)`
- `pattern_atom_parser()` — tries `pattern_literal_parser()` before identifier fallback
- `pattern_base_parser()` — tries `pattern_literal_parser()` before identifier fallback
- Type annotations updated: `pattern_atom_parser()` → `P[SurfacePatternBase]`, `pattern_base_parser()` → `P[SurfacePatternBase]`, `pattern_cons_parser()` → `P[SurfacePatternBase]`, `pattern_parser()` → `P[SurfacePatternBase]`

### What Was Done

1. **Verified the implementation is correct** — all parser tests pass
2. **Added `TestLiteralPattern` class** in `tests/test_surface/test_parser/test_expressions.py` with tests for:
   - `case x of { 0 → 1 | 1 → 2 }` — multiple int literal branches
   - `case s of { "hello" → 0 | other → 1 }` — string literal pattern
   - `case xs of { Cons 0 rest → rest | Nil → Nil }` — constructor with literal argument
3. **All 55 tests pass** (52 existing + 3 new)

---

## Why It Works

- **Deterministic**: `NumberToken` and `StringToken` are disjoint from `IdentifierToken` — no ambiguity
- **Composable**: `SurfaceLitPattern` is a `SurfacePatternBase`, so it fits naturally into the pattern hierarchy
- **Non-breaking**: Only adds new parseable syntax; doesn't change existing behavior

---

## Files

### Already Modified
- `systemf/src/systemf/surface/parser/expressions.py` — `pattern_literal_parser()`, updates to `pattern_atom_parser()`/`pattern_base_parser()`

### Tests Added
- `tests/test_surface/test_parser/test_expressions.py` — Added `TestLiteralPattern` class with tests for:
  - `case x of { 0 -> 1 | 1 -> 2 }`
  - `case s of { "hello" -> 0 | other -> 1 }`
  - Constructor with literal arg: `Cons 0 xs`

---

## Verification

```bash
uv run pytest systemf/tests/test_surface/test_parser/test_expressions.py -q
```

Expected: 50+ passed (including new literal pattern tests).
