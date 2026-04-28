# System F Elaborator Refactor: File Change Manifest and Test Adaptation Plan

## Overview

This document tracks the major architectural refactor of the System F elaborator from a tightly-coupled architecture to a true multi-pass pipeline. The refactor replaces the monolithic `TypeElaborator` class with a modular pipeline of individual passes and a new `BidiInference` class.

---

## Part 1: File Change Manifest

### A. Files Created (New Architecture)

#### Result Type
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/result.py` | Result type for explicit error handling (Ok/Err monad) | 57 |

#### Desugaring Passes (Phase 0)
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/desugar/if_to_case_pass.py` | Transform if-then-else to case expressions | ~100 |
| `systemf/src/systemf/surface/desugar/operator_pass.py` | Transform operators to primitive operations | ~158 |
| `systemf/src/systemf/surface/desugar/multi_arg_lambda_pass.py` | Transform multi-arg lambdas to nested single-arg | ~80 |
| `systemf/src/systemf/surface/desugar/multi_var_type_abs_pass.py` | Transform multi-var type abstractions to nested | ~80 |
| `systemf/src/systemf/surface/desugar/implicit_type_abs_pass.py` | Add implicit type abstractions | ~100 |
| `systemf/src/systemf/surface/desugar/passes.py` | Composite pass orchestration | ~120 |

#### Scope Checking (Phase 1)
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/scoped/scope_pass.py` | Name resolution to de Bruijn indices | ~200 |
| `systemf/src/systemf/surface/scoped/context.py` | Scope context management | ~150 |
| `systemf/src/systemf/surface/scoped/errors.py` | Scope checking error types | ~80 |
| `systemf/src/systemf/surface/scoped/checker.py` | Scope checking utilities | ~100 |

#### Type Inference (Phase 2)
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/inference/bidi_inference.py` | Core bidirectional inference algorithm | 1,240 |
| `systemf/src/systemf/surface/inference/signature_collect_pass.py` | Collect signatures from declarations | ~150 |
| `systemf/src/systemf/surface/inference/data_decl_elab_pass.py` | Elaborate data declarations | ~200 |
| `systemf/src/systemf/surface/inference/prepare_contexts_pass.py` | Prepare type contexts | ~150 |
| `systemf/src/systemf/surface/inference/elab_bodies_pass.py` | Elaborate term bodies | ~200 |
| `systemf/src/systemf/surface/inference/build_decls_pass.py` | Build final core declarations | ~150 |
| `systemf/src/systemf/surface/inference/context.py` | Type context management | ~200 |
| `systemf/src/systemf/surface/inference/errors.py` | Type error types | ~100 |
| `systemf/src/systemf/surface/inference/unification.py` | Unification algorithm | ~300 |

#### LLM Pragma (Phase 3)
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/llm/pragma_pass.py` | LLM pragma processing (rewritten) | ~250 |

#### Pipeline Orchestration
| File | Purpose | Lines |
|------|---------|-------|
| `systemf/src/systemf/surface/pipeline.py` | Main pipeline orchestration (rewritten) | ~300 |
| `systemf/src/systemf/surface/pass_base.py` | Base class for pipeline passes | ~80 |

**Total New Files**: 21 files
**Total Lines Added**: ~4,000+

---

### B. Files Modified

| File | Changes | Lines Changed |
|------|---------|---------------|
| `systemf/src/systemf/surface/__init__.py` | Updated exports to include new API | ~169 |
| `systemf/src/systemf/surface/desugar/__init__.py` | New exports for desugar passes | ~30 |
| `systemf/src/systemf/surface/scoped/__init__.py` | New exports for scope checking | ~30 |
| `systemf/src/systemf/surface/inference/__init__.py` | Updated to export BidiInference and pass functions | ~57 |
| `systemf/src/systemf/surface/llm/__init__.py` | New exports for LLM pragma pass | ~19 |

**Total Modified Files**: 5 files

---

### C. Files Deleted

| File | Reason | Original Lines |
|------|--------|----------------|
| `systemf/src/systemf/surface/inference/elaborator.py` | Replaced by multi-pass architecture | 1,722 |
| `systemf/src/systemf/surface/desugar.py` | Replaced by modular desugar passes | ~200 |

**Total Deleted Files**: 2 files  
**Total Lines Removed**: ~1,922

---

## Part 2: Test Adaptation Plan

### API Migration Summary

#### OLD → NEW Mapping

| Old Component | New Component | Status |
|---------------|---------------|--------|
| `TypeElaborator` | `BidiInference` | Direct replacement |
| `TypeElaborator.infer()` | `BidiInference.infer()` | Compatible |
| `TypeElaborator.check()` | `BidiInference.check()` | Compatible |
| `TypeElaborator.infer_sigma()` | `BidiInference.infer_sigma()` | Compatible |
| `TypeElaborator.check_sigma()` | `BidiInference.check_sigma()` | Compatible |
| `desugar()` function | `desugar_term()` / `desugar_declaration()` | API change (returns Result) |
| `Desugarer` class | Removed | Use pass functions directly |
| `elaborate_term()` | `BidiInference.infer()` | May need wrapper |

---

### Tests Requiring Updates

#### Priority 1: Pipeline Integration Tests
**File**: `tests/test_pipeline.py`

**Status**: ✅ **Should work as-is**

The pipeline tests use the `ElaborationPipeline` class which has been updated to use the new architecture internally. No changes required.

```python
# Current usage (still valid):
from systemf.surface import ElaborationPipeline, elaborate_module
pipeline = ElaborationPipeline(module_name="test")
result = pipeline.run(declarations)
```

---

#### Priority 2: Core Type Inference Tests
**File**: `tests/test_surface/test_inference.py`

**Status**: ⚠️ **Requires Updates**

**Changes needed**:
```python
# OLD:
from systemf.surface.inference import (
    TypeElaborator,
    elaborate_term,
    TypeContext,
    TMeta,
    Substitution,
)

@pytest.fixture
def elab():
    return TypeElaborator()

# Usage:
core_term, ty = elab.infer(term, ctx)
```

```python
# NEW:
from systemf.surface.inference import (
    BidiInference,  # Changed from TypeElaborator
    TypeContext,
    TMeta,
    Substitution,
)

@pytest.fixture
def elab():
    return BidiInference()

# Usage remains the same:
core_term, ty = elab.infer(term, ctx)
```

**Count of usages**: 35+ test functions

---

#### Priority 3: Paper Examples Tests
**Files**:
- `tests/test_surface/test_putting2007_examples.py`
- `tests/test_surface/test_putting2007_gaps.py`

**Status**: ⚠️ **Requires Updates**

Both files use `TypeElaborator` fixture pattern:

```python
# OLD:
from systemf.surface.inference import TypeElaborator

@pytest.fixture
def elab():
    return TypeElaborator()
```

```python
# NEW:
from systemf.surface.inference import BidiInference

@pytest.fixture
def elab():
    return BidiInference()
```

**Impact**: 2 files, ~50 test functions total

---

#### Priority 4: Elaborator Rules Tests
**File**: `tests/test_elaborator_rules.py`

**Status**: ⚠️ **Requires Updates**

This file has the most usages of `TypeElaborator`:

**Count**: 35+ direct instantiations of `TypeElaborator()`

```python
# OLD:
from systemf.surface.inference import TypeElaborator

class TestElaborationRules:
    def test_var_rule(self):
        elab = TypeElaborator()
        # ... test code

    def test_abs_rule(self):
        elab = TypeElaborator()
        # ... test code
    
    # ... 33 more tests
```

```python
# NEW:
from systemf.surface.inference import BidiInference

class TestElaborationRules:
    def test_var_rule(self):
        elab = BidiInference()
        # ... test code (no other changes needed)

    def test_abs_rule(self):
        elab = BidiInference()
        # ... test code (no other changes needed)
```

**Note**: Consider extracting a fixture to reduce duplication:
```python
@pytest.fixture
def elab():
    return BidiInference()
```

---

#### Priority 5: Operator Desugar Tests
**File**: `tests/test_surface/test_operator_desugar.py`

**Status**: ⚠️ **Requires Updates**

This file uses the old desugar API:

```python
# OLD:
from systemf.surface.desugar import desugar, OPERATOR_TO_PRIM

# Uses:
OPERATOR_TO_PRIM["+"]  # Still works, but may need import change
result = desugar(term)  # Changed API
```

```python
# NEW:
from systemf.surface.desugar import (
    operator_to_prim_pass,  # If accessing OPERATOR_TO_PRIM
    desugar_term,
)
from systemf.surface.desugar.operator_pass import OPERATOR_TO_PRIM

# OPERATOR_TO_PRIM access:
from systemf.surface.desugar.operator_pass import OPERATOR_TO_PRIM

# Desugar usage (note Result type):
from systemf.surface.desugar import desugar_term

result = desugar_term(term)
if result.is_ok():
    desugared = result.unwrap()
else:
    error = result.error
```

**API Change Details**:
- Old: `desugar(term)` returned `SurfaceTerm` directly
- New: `desugar_term(term)` returns `Result[SurfaceTerm, DesugarError]`

**File changes needed**:
1. Update import: `desugar` → `desugar_term`
2. Handle Result type wrapping/unwrapping
3. Import `OPERATOR_TO_PRIM` from `operator_pass` module directly

---

#### Priority 6: Mutual Recursion Tests
**File**: `tests/test_elaborator/test_mutual_recursion.py`

**Status**: ⚠️ **May Require Updates**

Check for usage of old APIs. Likely uses `TypeElaborator` or pipeline components.

---

### Complete Test Migration Strategy

#### Phase 1: Create Compatibility Shim (Optional)

To ease migration, consider adding temporary aliases in `inference/__init__.py`:

```python
# systemf/src/systemf/surface/inference/__init__.py
# Temporary backward compatibility (remove after migration)
TypeElaborator = BidiInference  # type: ignore
```

This would allow tests to import `TypeElaborator` while actually using `BidiInference`, giving time to update tests gradually.

#### Phase 2: Update Tests in Priority Order

1. **test_pipeline.py** - Verify first (should work)
2. **test_inference.py** - Core inference tests
3. **test_elaborator_rules.py** - Rule coverage tests
4. **test_putting2007_*.py** - Paper examples
5. **test_operator_desugar.py** - Desugar tests
6. **test_mutual_recursion.py** - Check and update

#### Phase 3: Remove Compatibility Shim

Once all tests are updated, remove the `TypeElaborator` alias.

---

## Part 3: Detailed Migration Examples

### Example 1: Basic TypeElaborator Migration

```python
# BEFORE (test_inference.py):
from systemf.surface.inference import TypeElaborator, TypeContext

def test_inference():
    elab = TypeElaborator()
    ctx = TypeContext()
    core_term, ty = elab.infer(term, ctx)
    assert isinstance(ty, TypeConstructor)

# AFTER:
from systemf.surface.inference import BidiInference, TypeContext

def test_inference():
    elab = BidiInference()
    ctx = TypeContext()
    core_term, ty = elab.infer(term, ctx)
    assert isinstance(ty, TypeConstructor)
```

### Example 2: Result Type Handling

```python
# BEFORE (test_operator_desugar.py):
from systemf.surface.desugar import desugar

def test_desugar():
    result = desugar(term)
    assert isinstance(result, SurfaceTerm)

# AFTER:
from systemf.surface.desugar import desugar_term

def test_desugar():
    result = desugar_term(term)
    assert result.is_ok()
    desugared = result.unwrap()
    assert isinstance(desugared, SurfaceTerm)
```

### Example 3: Multiple Import Updates

```python
# BEFORE:
from systemf.surface.inference import (
    TypeElaborator,
    elaborate_term,
    TypeContext,
    TypeMismatchError,
)

# AFTER:
from systemf.surface.inference import (
    BidiInference,  # Changed
    TypeContext,
)
from systemf.surface.inference.errors import TypeMismatchError
# Note: elaborate_term may need replacement or wrapper
```

---

## Part 4: Potential Issues and Edge Cases

### Issue 1: Result Type Propagation

**Problem**: New desugar functions return `Result[T, E]` instead of raw values.

**Impact**: Tests using desugar must unwrap results.

**Solution**: Update tests to check `.is_ok()` and use `.unwrap()`.

### Issue 2: elaborate_term Function

**Problem**: The `elaborate_term()` function signature may have changed.

**Impact**: Tests calling `elaborate_term()` directly will fail.

**Solution**: Replace with `BidiInference().infer()` or check new signature.

### Issue 3: OPERATOR_TO_PRIM Export

**Problem**: `OPERATOR_TO_PRIM` was exported from `desugar` module, now in `operator_pass`.

**Impact**: Tests importing `OPERATOR_TO_PRIM` from old location will fail.

**Solution**: Update import to:
```python
from systemf.surface.desugar.operator_pass import OPERATOR_TO_PRIM
```

### Issue 4: Error Class Locations

**Problem**: Error classes may have moved to submodules.

**Impact**: Tests importing specific error types may fail.

**Solution**: Check `inference/errors.py` and update imports.

### Issue 5: TypeContext Changes

**Problem**: `TypeContext` API may have changed.

**Impact**: Tests setting up contexts may fail.

**Solution**: Review `TypeContext` class in `inference/context.py`.

### Issue 6: Scoped Term Types

**Problem**: Tests may still reference old scoped term types.

**Impact**: Type annotations and imports may be incorrect.

**Solution**: Check `surface/types.py` for current scoped term type names.

---

## Part 5: Verification Checklist

### Pre-Migration
- [ ] Read `systemf/src/systemf/surface/inference/bidi_inference.py` docstring
- [ ] Read `systemf/src/systemf/surface/desugar/passes.py` for new API
- [ ] Review `systemf/src/systemf/surface/pipeline.py` for pipeline changes

### Migration
- [ ] Add compatibility shim (optional)
- [ ] Update test_inference.py
- [ ] Update test_elaborator_rules.py
- [ ] Update test_putting2007_examples.py
- [ ] Update test_putting2007_gaps.py
- [ ] Update test_operator_desugar.py
- [ ] Update test_mutual_recursion.py (check needed)
- [ ] Run all tests and fix failures

### Post-Migration
- [ ] Remove compatibility shim
- [ ] Verify all tests pass
- [ ] Update documentation
- [ ] Archive this manifest

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| New Files Created | 21 |
| Files Modified | 5 |
| Files Deleted | 2 |
| Tests Needing Updates | 6-7 |
| Estimated Test Functions Affected | ~150+ |
| Lines of Code Changed (new) | ~4,000+ |
| Lines of Code Removed (old) | ~1,922 |

---

## References

- New Pipeline: `systemf/src/systemf/surface/pipeline.py`
- New Inference: `systemf/src/systemf/surface/inference/bidi_inference.py`
- New Desugar: `systemf/src/systemf/surface/desugar/passes.py`
- Result Type: `systemf/src/systemf/surface/result.py`
- Main Module: `systemf/src/systemf/surface/__init__.py`

---

*Document Created*: 2026-03-09  
*Refactor Phase*: Test Migration Planning  
*Status*: Ready for test updates
