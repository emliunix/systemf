# Parser Cleanup: Remove Parser Class and Resolve Test Debt

**Change Plan Skill**: `.agents/skills/change-plan/SKILL.md`  
**References**: `changes/19-parser-architecture-refactor.md` (approved, partially implemented)  
**Status**: Pending review

---

## Problem

Change #19 refactored `top_decl_parser()` to use parsy combinators and changed `parse_program()` to return `tuple[imports, decls]`. During implementation, two categories of issues surfaced:

1. **`Parser` class duplicates `parse_program()` logic** — violates single source of truth
2. **Latent test debt surfaced by signature change** — pre-existing test bugs were blocked from execution

---

## Battle-Tested Migration Protocol

Based on prior API migration experience, the correct workflow is:

1. **Inventory all call sites before touching code** (`grep -rn` across entire repo)
2. **Categorize into migration patterns** (A, B, C — see below)
3. **Delete obsolete code first** (don't migrate what shouldn't exist)
4. **Automate mechanical changes** (bulk sed/ast replacements for simple patterns)
5. **One-shot verification** (run full test suite once, not iteratively)
6. **Fix only genuine bugs** (not latent pre-existing issues unless they block the change)

**Anti-patterns to avoid:**
- ❌ Run tests → fix first failure → run again → fix next failure (whack-a-mole)
- ❌ Migrate debug scripts that should be deleted
- ❌ Fix pre-existing test debt as one-offs instead of bulk categorizing

---

## Inventory

### `Parser.parse()` Callers → Pattern B

| File | Count | Notes |
|------|-------|-------|
| `src/systemf/eval/repl.py` | 3 | Production code |
| `tests/test_string.py` | 6 | Test |
| `tests/test_surface/test_inference.py` | 8 | Test |
| `tests/test_surface/test_parser/test_decl_docstrings.py` | 1 | Already unpacks tuple |

### `Parser.parse_expression()` Callers → Pattern C

| File | Count | Notes |
|------|-------|-------|
| `src/systemf/eval/repl.py` | 2 | Production code |
| `tests/test_string.py` | 1 | Test |

### `parse_program()` Callers → Pattern A

| File | Count | Status |
|------|-------|--------|
| `src/systemf/elab3/pipeline.py` | 1 | Untracked WIP — out of scope |
| `tests/test_eval/test_tool_calls.py` | 1 | **Not yet fixed** |
| `tests/test_llm_files.py` | 5 | **Not yet fixed** |
| `tests/test_surface/test_scoped_type_vars.py` | 2 | **Not yet fixed** |
| `tests/test_surface/test_scoped_type_vars_comprehensive.py` | 9 | **Not yet fixed** |
| `tests/test_surface/test_scoped_type_vars_integration.py` | 19 | **Not yet fixed** |
| `tests/test_surface/test_operator_desugar.py` | 1 | **Not yet fixed** |
| `tests/test_surface/test_parser/test_cons_regression.py` | 4 | Partially fixed |
| `tests/test_surface/test_parser/test_multiple_decls.py` | 34 | **Fixed** |

### Root-Level Debug Scripts (Delete, Don't Migrate)

| File | Lines | Parser Usage |
|------|-------|-------------|
| `systemf/test_nil.py` | 27 | `Parser(tokens).parse()` |
| `systemf/test_prelude_debug.py` | 27 | `Parser(tokens).parse()` |
| `systemf/test_constructors.py` | 80 | 4× `Parser(tokens).parse()` |
| `systemf/test_debug_nil.py` | 46 | `Parser(tokens).parse()` |
| `systemf/test_treverse.py` | 33 | `Parser(tokens).parse()` |

These are ad-hoc debug scripts, not pytest tests. They are not imported or run by CI. **Delete them.**

### Archived Tests (Out of Scope)

`tests/_archive/test_llm_integration.py` — 12 calls. Explicitly excluded.

---

## Migration Patterns

### Pattern A: `parse_program()` Tuple Unpacking

**Before:**
```python
decls = parse_program(source)
```

**After:**
```python
_, decls = parse_program(source)
```

**Mechanical fix:** `sed -i 's/decls = parse_program(/_, decls = parse_program(/g'`

### Pattern B: `Parser(tokens).parse()` → `parse_program()`

**Before:**
```python
tokens = lex(source)
decls = Parser(tokens).parse()
```

**After:**
```python
_, decls = parse_program(source)
```

**Mechanical fix:** Replace both lines with `_, decls = parse_program(source)`

### Pattern C: `Parser(tokens).parse_expression()` → `parse_expression()`

**Before:**
```python
tokens = Lexer(source, filename=fn).tokenize()
term = Parser(tokens).parse_expression()
```

**After:**
```python
term = parse_expression(source, filename=fn)
```

**Requires:** Add `filename` parameter to `parse_expression()` and `parse_type()`.

---

## Design

### 1. Remove Parser Class

Delete `class Parser` from `systemf/src/systemf/surface/parser/__init__.py` (lines 258-327).

### 2. Add filename Parameter to parse_expression/parse_type

```python
def parse_expression(source: str, filename: str | None = None):
    tokens = list(lex(source, filename=filename))
    return (expressions.expr_parser(AnyIndent()) << eof).parse(tokens)

def parse_type(source: str, filename: str | None = None):
    tokens = list(lex(source, filename=filename))
    return (type_parser() << eof).parse(tokens)
```

### 3. Apply Migration Patterns Systematically

**Pattern A files** (bulk sed):
- `tests/test_eval/test_tool_calls.py`
- `tests/test_llm_files.py`
- `tests/test_surface/test_scoped_type_vars.py`
- `tests/test_surface/test_scoped_type_vars_comprehensive.py`
- `tests/test_surface/test_scoped_type_vars_integration.py`
- `tests/test_surface/test_operator_desugar.py`

**Pattern B files** (manual — two-line replacement):
- `src/systemf/eval/repl.py`
- `tests/test_string.py`
- `tests/test_surface/test_inference.py`
- `tests/test_surface/test_parser/test_decl_docstrings.py` (remove Parser import only)

**Pattern C files** (manual — two-line replacement):
- `src/systemf/eval/repl.py`
- `tests/test_string.py`

### 4. Delete Root-Level Debug Scripts

Remove: `systemf/test_nil.py`, `test_prelude_debug.py`, `test_constructors.py`, `test_debug_nil.py`, `test_treverse.py`

### 5. Fix Pre-existing Test Bugs

`tests/test_surface/test_parser/test_cons_regression.py` — `.constructor` and `.vars` don't exist on `SurfacePattern`.

---

## Files

### Delete
- `systemf/test_nil.py`
- `systemf/test_prelude_debug.py`
- `systemf/test_constructors.py`
- `systemf/test_debug_nil.py`
- `systemf/test_treverse.py`

### Modify (remove Parser class)
- `systemf/src/systemf/surface/parser/__init__.py`

### Modify (Pattern A — bulk sed)
- `tests/test_eval/test_tool_calls.py`
- `tests/test_llm_files.py`
- `tests/test_surface/test_scoped_type_vars.py`
- `tests/test_surface/test_scoped_type_vars_comprehensive.py`
- `tests/test_surface/test_scoped_type_vars_integration.py`
- `tests/test_surface/test_operator_desugar.py`

### Modify (Pattern B/C — manual)
- `src/systemf/eval/repl.py`
- `tests/test_string.py`
- `tests/test_surface/test_inference.py`
- `tests/test_surface/test_parser/test_decl_docstrings.py`

### Modify (pre-existing bugs)
- `tests/test_surface/test_parser/test_cons_regression.py`

### Out of Scope
- `tests/_archive/`
- `systemf/src/systemf/elab3/pipeline.py` (untracked WIP)
- `systemf/demo.py` (not using Parser)

---

## Why It Works

- **Single source of truth**: Only `parse_program()` parses complete programs
- **No partial state**: Callers have source or call pipeline directly
- **Delete over migrate**: Debug scripts eliminated, not carried forward
- **Mechanical where possible**: Bulk sed for Pattern A, manual only for Patterns B/C where context matters
- **One-shot verification**: Run full suite once after all changes

---

## Verification

After all changes:
```bash
uv run pytest systemf/tests/test_surface/test_parser/ -q
uv run pytest systemf/tests/test_surface/test_scoped_type_vars* -q
uv run pytest systemf/tests/test_string.py -q
uv run pytest systemf/tests/test_surface/test_inference.py -q
uv run pytest systemf/tests/test_eval/test_tool_calls.py -q
uv run pytest systemf/tests/test_llm_files.py -q
```
