# Change Plan: Add SurfaceVarPattern and Flat Pattern Representation

**Previous plan:** `changes/2-add-literal-pattern-support-v2.md`, `changes/4-elab3-nested-patterns.md`

## Why a new plan

The current surface AST has two issues:

1. **Overloaded semantics:** `SurfacePattern` represents both constructors AND variables via `vars == []` check
2. **Hierarchical structure:** `SurfacePattern(constructor="Cons", vars=[...])` pre-determines constructor/argument structure at parse time

We need a design that:
- Defers constructor vs variable disambiguation to the rename phase (when we have name environment)
- Uses a flat structure where all identifiers are initially `SurfaceVarPattern`
- Allows the renamer to decide: single item = variable OR nullary constructor, multiple items = constructor pattern

## Facts

### Current Pattern Hierarchy

```
SurfacePatternBase
├── SurfacePattern          # Overloaded: constructor OR variable
├── SurfacePatternTuple     # (p1, p2, ..., pn)
├── SurfacePatternCons      # head : tail
└── SurfaceLitPattern       # 42, "hello"
```

### Current Design Issues

**Problem 1: Overloading**
```python
# Variable pattern
SurfacePattern(constructor="x", vars=[])

# Constructor pattern  
SurfacePattern(constructor="Cons", vars=[SurfacePattern("x"), SurfacePattern("y")])
```

**Problem 2: Early binding**
Parser decides constructor vs variable at parse time, but we need name environment to know if `Nothing` is a nullary constructor or a variable.

### New Design Approach

**Parser phase:** All identifiers → `SurfaceVarPattern`

```python
# x
SurfacePattern(patterns=[SurfaceVarPattern("x")])

# Cons x y
SurfacePattern(patterns=[SurfaceVarPattern("Cons"), SurfaceVarPattern("x"), SurfaceVarPattern("y")])
```

**Rename phase:** Disambiguate with name environment

```python
# Single item list
if len(patterns) == 1:
    name = patterns[0].name
    if name in constructors:  # Has name env info
        → ConPat(con=name, args=[])
    else:
        → VarPat(id=name)

# Multiple items  
else:
    con_name = patterns[0].name
    args = patterns[1:]
    → ConPat(con=con_name, args=args)
```

## Design

### Add SurfaceVarPattern

```python
@dataclass(frozen=True, kw_only=True)
class SurfaceVarPattern(SurfacePatternBase):
    """Variable pattern (or potential constructor name before rename): x."""
    name: str
```

### Change SurfacePattern Structure

**OLD:**
```python
@dataclass(frozen=True, kw_only=True)
class SurfacePattern(SurfacePatternBase):
    constructor: str                    # Con name or var name
    vars: list[SurfacePatternBase]      # Arguments (empty = variable)
```

**NEW:**
```python
@dataclass(frozen=True, kw_only=True)
class SurfacePattern(SurfacePatternBase):
    """Flat pattern list: [Con, arg1, arg2, ...] or [var].
    
    All identifiers are SurfaceVarPattern at parse time.
    Rename phase disambiguates:
    - [VarPat("x")] → single item: var or nullary con
    - [VarPat("Cons"), VarPat("x"), ...] → multi item: constructor pattern
    """
    patterns: list[SurfacePatternBase]   # Flat list, all items are patterns
```

### Update Parser

In `pattern_base_parser()`:
- Parse identifier and following arguments (if any)
- Return `SurfacePattern(patterns=[SurfaceVarPattern(name) for each identifier])`
- Do NOT try to distinguish constructor vs variable at parse time

Example parses:
- `x` → `SurfacePattern(patterns=[SurfaceVarPattern("x")])`
- `Cons x y` → `SurfacePattern(patterns=[SurfaceVarPattern("Cons"), SurfaceVarPattern("x"), SurfaceVarPattern("y")])`
- `Pair (x, y) z` → `SurfacePattern(patterns=[SurfaceVarPattern("Pair"), SurfacePatternTuple(...), SurfaceVarPattern("z")])`

### Update Rename Phase

The renamer will:
1. Check pattern length
2. If single item: look up in name environment
   - If constructor → `ConPat(con=name, args=[])`
   - Else → `VarPat(id=name)`
3. If multiple items: first is constructor, rest are arguments
   - `ConPat(con=patterns[0].name, args=patterns[1:])`

### Update Pattern Utilities

**Files to update:**
- `systemf/src/systemf/surface/scoped/scope_pass.py` — Update `_collect_pattern_vars()`
- `systemf/src/systemf/surface/scoped/checker.py` — Update `_collect_pattern_vars()`
- `systemf/src/systemf/surface/desugar/cons_pattern_pass.py` — Handle flat pattern structure
- `systemf/src/systemf/surface/inference/bidi_inference.py` — Update `_extract_pattern_var_names()`
- `systemf/src/systemf/surface/desugar/if_to_case_pass.py` — Update pattern construction

**New `_collect_pattern_vars` logic:**
```python
case SurfacePattern(patterns=patterns):
    if len(patterns) == 1:
        # Single item: either variable or nullary constructor
        # Return the name regardless, let type checker resolve
        return [patterns[0].name]
    else:
        # Constructor pattern: collect from arguments (not constructor name)
        result = []
        for pat in patterns[1:]:  # Skip constructor name at patterns[0]
            result.extend(_collect_pattern_vars(pat))
        return result

case SurfaceVarPattern(name=name):
    return [name]
```

### Update Tests

**Pattern construction changes:**

OLD:
```python
# Variable
SurfacePattern(constructor="x", vars=[])

# Constructor
SurfacePattern(constructor="Cons", vars=[SurfacePattern("x"), SurfacePattern("y")])
```

NEW:
```python
# Variable
SurfacePattern(patterns=[SurfaceVarPattern("x")])

# Constructor
SurfacePattern(patterns=[
    SurfaceVarPattern("Cons"),
    SurfaceVarPattern("x"),
    SurfaceVarPattern("y")
])
```

**Test files to update:**
- `tests/test_surface/test_parser/test_expressions.py`
- `tests/test_surface/test_parser/test_multiple_decls.py`
- `tests/test_surface/test_inference.py`
- `tests/test_surface/test_putting2007_examples.py`
- `tests/test_elaborator_rules.py`
- `tests/test_pipeline.py`

## Why It Works

1. **Deferred disambiguation:** Parser doesn't need to know what's a constructor
2. **Flat structure:** Simple list processing instead of tree traversal for renaming
3. **Clear semantics:** `SurfaceVarPattern` represents identifiers, `SurfacePattern` represents application-like patterns
4. **Matches rename phase capabilities:** The renamer has name environment to decide variable vs constructor
5. **Handles nullary constructors:** `Nothing` parses as `[VarPat("Nothing")]`, rename decides if it's `Nothing` constructor or a variable named Nothing

## Migration Strategy

**Breaking change** - all pattern construction sites need updates.

**Recommended approach:**
1. Update types.py (add `SurfaceVarPattern`, change `SurfacePattern`)
2. Update parser (return flat structure with all VarPatterns)
3. Update renamer (implement disambiguation logic)
4. Update all utility functions (`_collect_pattern_vars`, etc.)
5. Update all test files (change pattern construction)

Do as atomic commit since tests will fail at intermediate states.

## Files

### Parser Team (this agent)
- `systemf/src/systemf/surface/types.py` — Add `SurfaceVarPattern`, change `SurfacePattern.vars` → `patterns`
- `systemf/src/systemf/surface/parser/expressions.py` — Return flat pattern structure
- Test files — Update pattern construction to match new structure

### Rename Team (user)
- `systemf/src/systemf/elab3/rename.py` — Implement disambiguation logic

### Shared
- `systemf/src/systemf/surface/scoped/scope_pass.py` — Update `_collect_pattern_vars()`
- `systemf/src/systemf/surface/scoped/checker.py` — Update `_collect_pattern_vars()`
- `systemf/src/systemf/surface/desugar/cons_pattern_pass.py` — Handle new structure
- `systemf/src/systemf/surface/inference/bidi_inference.py` — Update pattern handling
- `systemf/src/systemf/surface/desugar/if_to_case_pass.py` — Update pattern construction

## Example Transformations

### Parse Examples

| Surface Syntax | Parsed AST (NEW) |
|----------------|------------------|
| `x` | `SurfacePattern(patterns=[SurfaceVarPattern("x")])` |
| `Cons x y` | `SurfacePattern(patterns=[SurfaceVarPattern("Cons"), SurfaceVarPattern("x"), SurfaceVarPattern("y")])` |
| `Nothing` | `SurfacePattern(patterns=[SurfaceVarPattern("Nothing")])` |
| `(a, b)` | `SurfacePatternTuple(elements=[SurfaceVarPattern("a"), SurfaceVarPattern("b")])` |
| `x : xs` | `SurfacePatternCons(head=SurfaceVarPattern("x"), tail=SurfaceVarPattern("xs"))` |
| `42` | `SurfaceLitPattern(prim_type="Int", value=42)` |

### Rename Transformations

| Parsed Pattern | Name Env | Renamed Result |
|----------------|----------|----------------|
| `[VarPat("x")]` | x not in constructors | `VarPat("x")` |
| `[VarPat("Nothing")]` | Nothing in constructors | `ConPat("Nothing", [])` |
| `[VarPat("Cons"), VarPat("x"), VarPat("y")]` | Cons in constructors | `ConPat("Cons", [VarPat("x"), VarPat("y")])` |

## Notes

- `True` and `False` in `if_to_case_pass.py` should be: `SurfacePattern(patterns=[SurfaceVarPattern("True")])`
- The rename phase will determine if single-item patterns are variables or nullary constructors
- Multi-item patterns are always constructor patterns with first item being constructor name
