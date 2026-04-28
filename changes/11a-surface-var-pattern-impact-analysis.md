# Complete Impact Analysis: SurfaceVarPattern Change

## Summary
- **Files affected:** 18 files
- **SurfacePattern constructor usages:** 60 occurrences
- **Pattern field accesses (.vars):** 20 occurrences
- **Pattern matching cases:** 15 occurrences

---

## Source Files (8 files)

### 1. types.py - Type Definition
**File:** `systemf/src/systemf/surface/types.py`
- Line 533: `class SurfacePattern(SurfacePatternBase):` - Definition
- Line 537: `vars: list[SurfacePatternBase]` - Field to change to `patterns`

**Changes needed:**
- Add `SurfaceVarPattern` class
- Change `SurfacePattern.vars` to `SurfacePattern.patterns`

---

### 2. parser/expressions.py - Parser
**File:** `systemf/src/systemf/surface/parser/expressions.py`
- Line 802: Returns `SurfacePattern(constructor=name_token.value, vars=[], location=name_token.location)`
- Line 845: Returns `SurfacePattern(constructor=name, vars=args, location=loc)`
- Lines 816-819, 892-895: Documentation/comments showing pattern structure
- Lines 861, 902: Local imports of `SurfacePatternTuple`, `SurfacePatternCons`

**Changes needed:**
- Return flat pattern structure: `SurfacePattern(patterns=[SurfaceVarPattern(name), ...])`
- Update docstrings
- All identifiers become `SurfaceVarPattern`

---

### 3. scoped/scope_pass.py - Scope Checking
**File:** `systemf/src/systemf/surface/scoped/scope_pass.py`
- Line 48: `case SurfacePattern(constructor=constructor, vars=vars):`
- Lines 56, 62: Cases for `SurfacePatternTuple`, `SurfacePatternCons`

**Changes needed:**
- Update pattern matching to handle flat structure
- Add `SurfaceVarPattern` case

---

### 4. scoped/checker.py - Type Checking
**File:** `systemf/src/systemf/surface/scoped/checker.py`
- Line 43: `case SurfacePattern(constructor=constructor, vars=vars):`
- Lines 51, 57: Cases for `SurfacePatternTuple`, `SurfacePatternCons`

**Changes needed:**
- Update pattern matching to handle flat structure
- Add `SurfaceVarPattern` case

---

### 5. desugar/cons_pattern_pass.py - Pattern Desugaring
**File:** `systemf/src/systemf/surface/desugar/cons_pattern_pass.py`
- Line 154: Comment showing transformation
- Line 163: `case SurfacePattern(vars=vars):`
- Line 165: Returns `SurfacePattern(constructor=..., vars=...)`
- Line 187: Returns `SurfacePattern(constructor="Cons", vars=vars, location=...)`
- Line 205: `case SurfacePattern(constructor=constructor, vars=vars):`
- Lines 171, 176, 214, 221: Other pattern cases

**Changes needed:**
- Update all `SurfacePattern` construction
- Change field access from `vars` to `patterns`
- Handle flat pattern structure

---

### 6. desugar/if_to_case_pass.py - If-to-Case Desugaring
**File:** `systemf/src/systemf/surface/desugar/if_to_case_pass.py`
- Line 62: `pattern=SurfacePattern(constructor="True", vars=[], location=loc)`
- Line 67: `pattern=SurfacePattern(constructor="False", vars=[], location=loc)`

**Changes needed:**
- Change to `SurfacePattern(patterns=[SurfaceVarPattern("True")])`
- Let rename phase decide if True/False are constructors or variables

---

### 7. inference/bidi_inference.py - Bidirectional Inference
**File:** `systemf/src/systemf/surface/inference/bidi_inference.py`
- Lines 90-92: Imports `SurfacePattern`, `SurfacePatternCons`, `SurfacePatternTuple`
- Line 96: `case SurfacePattern(constructor=constructor, vars=vars):`
- Lines 102, 104, 108, 112, 114: Checks `isinstance(var, SurfacePattern) and not var.vars`
- Lines 104, 110: Cases for `SurfacePatternTuple`, `SurfacePatternCons`

**Changes needed:**
- Update pattern matching
- Add `SurfaceVarPattern` case
- Change field access from `vars` to `patterns`

---

### 8. elab3/rename.py - Renaming (User's responsibility)
**File:** `systemf/src/systemf/elab3/rename.py`
- Line 22: Import of `SurfacePattern`
- Line 194: Function signature `def rename_pattern(self, pat: SurfacePatternBase)`
- Line 195: Helper `_con_pat(con: Name, pats: list[SurfacePatternBase])`
- Line 201: Helper `_rename_pat(pat: SurfacePatternBase)`
- Line 203: `case SurfacePattern(constructor=con, vars=pats):`
- Lines 206, 209: Cases for `SurfacePatternTuple`, `SurfacePatternCons`

**Changes needed (User):**
- Implement disambiguation logic:
  - Single item in patterns list → check name env for var vs nullary constructor
  - Multiple items → first is constructor, rest are arguments

---

## Test Files (10 files)

### 9. test_elaborator_rules.py
**File:** `tests/test_elaborator_rules.py`
- Line 30: Import `SurfacePattern`
- Line 240: `pattern=SurfacePattern(constructor="True", vars=[], location=DUMMY_LOC)`
- Line 245: `pattern=SurfacePattern(constructor="False", vars=[], location=DUMMY_LOC)`

**Usages:** 2

---

### 10. test_pipeline.py
**File:** `tests/test_pipeline.py`
- Line 30: Import `SurfacePattern`

**Usages:** 0 (just import, no construction)

---

### 11. test_surface/test_inference.py
**File:** `tests/test_surface/test_inference.py`
- Line 40: Import `SurfacePattern`
- Lines 604, 609, 860, 865: `pattern=SurfacePattern(constructor="True"/"False", vars=[], location=DUMMY_LOC)` (4 usages)
- Line 640-642: `pattern=SurfacePattern(constructor="Pair", vars=[SurfacePattern(constructor="a"), SurfacePattern(constructor="b")])` (1 usage + 2 nested)

**Usages:** 7

---

### 12. test_surface/test_parser/test_expressions.py
**File:** `tests/test_surface/test_parser/test_expressions.py`
- Line 27: Import `SurfacePattern`
- Lines 182, 194, 327: Local imports of `SurfacePatternTuple` (3)
- Lines 224, 240, 268, 280: Local imports of `SurfacePatternCons` (4)
- Line 304: `SurfaceBranch(pattern=SurfacePattern(constructor="m", vars=[]), ...)`
- Line 320: `SurfaceBranch(pattern=SurfacePattern(constructor="msg", vars=[]), ...)`

**Usages:** 2

---

### 13. test_surface/test_parser/test_multiple_decls.py
**File:** `tests/test_surface/test_parser/test_multiple_decls.py`
- Line 242: Import `SurfacePattern`
- Line 343: `pattern=SurfacePattern(constructor="Nothing", vars=[])`
- Lines 347-349: `pattern=SurfacePattern(constructor="Just", vars=[SurfacePattern(constructor="x")])`
- Line 394: `pattern=SurfacePattern(constructor="Nil", vars=[])`
- Lines 398-399: `pattern=SurfacePattern(constructor="Cons", vars=[SurfacePattern(constructor="z", vars=[]), SurfacePattern(constructor="zs", vars=[])])`
- Line 450: `pattern=SurfacePattern(constructor="m", vars=[])`
- Line 492: `pattern=SurfacePattern(constructor="other", vars=[])`

**Usages:** 7 + nested

---

### 14. test_surface/test_parser/test_cons_regression.py
**File:** `tests/test_surface/test_parser/test_cons_regression.py`
- Line 153: Local import `from systemf.surface.types import SurfacePattern`

**Usages:** 0 (just import)

---

### 15. test_surface/test_putting2007_examples.py
**File:** `tests/test_surface/test_putting2007_examples.py`
- Line 39: Import `SurfacePattern`
- Lines 348, 353, 391, 396, 425, 430, 484, 489, 536, 541, 584, 589, 655, 660: True/False patterns (14 usages)
- Lines 764-766: `pattern=SurfacePattern(constructor="Fork", vars=[SurfacePattern(constructor="v")])` (1 + nested)

**Usages:** 15

---

### 16. test_surface/test_putting2007_gaps.py
**File:** `tests/test_surface/test_putting2007_gaps.py`
- Line 39: Import `SurfacePattern`

**Usages:** 0 (just import)

---

### 17. test_surface/test_scope.py
**File:** `tests/test_surface/test_scope.py`
- Line 653-654: `pattern1 = SurfacePattern(constructor="True", vars=[], location=DUMMY_LOC)` (2 usages)
- Lines 685-687: `pattern = SurfacePattern(constructor="Fork", vars=[SurfacePattern(constructor="a"), SurfacePattern(constructor="b")])` (1 + 2 nested)

**Usages:** 3

---

### 18. surface/__init__.py
**File:** `systemf/src/systemf/surface/__init__.py`
- Likely exports SurfacePattern

**Changes needed:**
- Export `SurfaceVarPattern`

---

## Statistics

### By Category

| Category | Files | Constructor Usages | Pattern Cases | Field Accesses |
|----------|-------|-------------------|---------------|----------------|
| Source | 8 | 10 | 15 | 20 |
| Tests | 10 | 50 | 0 | 0 |
| **Total** | **18** | **60** | **15** | **20** |

### By File (Constructor Usages)

| File | Count |
|------|-------|
| test_putting2007_examples.py | 15 |
| cons_pattern_pass.py | 5 |
| test_multiple_decls.py | 7 |
| test_inference.py | 7 |
| parser/expressions.py | 2 |
| test_scope.py | 3 |
| test_elaborator_rules.py | 2 |
| test_expressions.py | 2 |
| if_to_case_pass.py | 2 |
| bidi_inference.py | 1 |
| rename.py | 1 |
| **Total** | **60** |

---

## Pattern Transformation Examples

### Before
```python
# Variable pattern
SurfacePattern(constructor="x", vars=[])

# Constructor pattern
SurfacePattern(constructor="Cons", vars=[
    SurfacePattern(constructor="x", vars=[]),
    SurfacePattern(constructor="y", vars=[])
])
```

### After
```python
# Variable pattern (single item)
SurfacePattern(patterns=[SurfaceVarPattern("x")])

# Constructor pattern (multiple items)
SurfacePattern(patterns=[
    SurfaceVarPattern("Cons"),
    SurfaceVarPattern("x"),
    SurfaceVarPattern("y")
])
```

---

## Files Missing from Original Plan

The original plan was missing these files identified in the complete audit:

1. `systemf/src/systemf/surface/__init__.py` - Export changes
2. `tests/test_surface/test_parser/test_cons_regression.py` - Import only
3. `tests/test_surface/test_putting2007_gaps.py` - Import only
4. `tests/test_pipeline.py` - Import only

---

## Breaking Change Impact

**Severe breaking change** - All 60 constructor usages across 18 files need updates.

**Recommendation:** Atomic commit with all changes. No intermediate state is viable since the AST structure changes fundamentally.
